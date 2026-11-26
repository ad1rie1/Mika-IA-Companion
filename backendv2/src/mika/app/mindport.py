"""Le port d'entrée, implémenté sur le noyau : ce que voient les adaptateurs.

``KernelPort`` tient ce qui n'est à aucun domaine. Ce qui est à un domaine — ce que signale un appareil, la position
d'une personne et les bulles de ses messages, un réveil par API, le travail en cours d'une propriétaire — est sa
part (ADR 0310 : ``PortPart``, ``app/domains/<nom>/port.py``) : ``KernelPort`` mêle leurs méthodes aux siennes, et
le panneau d'une personne prend ce que chacune dit du travail en cours (``PortPart.work``). Les parts sont lues à
l'import de ce module, qui en fait une classe : aucune ne l'importe.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from typing import Any

from sqlalchemy import select

from mika.app.domains import DOMAINS, part
from mika.contracts import attachments as attachments_c
from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.contracts import world as w
from mika.contracts.entry import (
    Admission,
    Efforts,
    HistoryRow,
    SharedDownload,
    SharedMeta,
    StrandItem,
)
from mika.contracts.runtime import PerceptionReceived
from mika.faculties import attachments, shares, transcript
from mika.faculties.attention import prompt as attention_prompt
from mika.faculties.identity import describe
from mika.faculties.self import night
from mika.faculties.self.faculty import lived_date
from mika.faculties.social.sections import profile_parts, refs_of
from mika.faculties.world import commands as world_commands
from mika.kernel import forms
from mika.kernel.events import Event, Origin
from mika.kernel.frame import Audience, Frame
from mika.kernel.guards import Superseded
from mika.kernel.state import Root
from mika.ports.shares import MAX_SHARE_BYTES, valid_id
from mika.runtime import decisions, health, operations
from mika.runtime.bootstrap import Kernel, ReadOnlyStore
from mika.vocab.circadian import day_fr
from mika.vocab.episodes import PRO


def _row(r: dict) -> HistoryRow:
    """Un message tel que la personne le relit (G-6) : ce qu'elle a tapé, et ses pièces jointes par leur nom — pas
    ce que les préprocesseurs en ont tiré (le contenu d'un PDF, cité sous la note ``kernel.prompt.UNTRUSTED_NOTE``),
    qui est pour son prompt. Un message plus ancien, sans séparation connue, garde son texte perçu et n'annonce
    aucune pièce jointe (son texte les décrit déjà)."""
    text, typed = r["text"] or "", r.get("typed")
    attachments = "[]"
    if typed is not None:
        text = text[:max(0, int(typed))]
        attachments = r["attachments"] or "[]"
    elif r["role"] == "assistant":
        # ce qu'elle a envoyé avec ce message : des identifiants, que l'écran fait décrire (``shared``)
        attachments = r["attachments"] or "[]"
    return HistoryRow(
        id=r["id"], at=r["at"], role=r["role"], text=text, source=r["source"] or "",
        emotion=r["emotion"], emotion_intensity=r["emotion_intensity"], attachments=attachments,
        verdict=r.get("verdict") or "", verdict_note=r.get("verdict_note") or "",
        mode=r.get("mode") or "", tools=(r.get("tools") or "") if r.get("mode") else "",
        strand=r.get("strand") or "",
    )


def journal_title(day: str, today: date) -> str:
    """Le titre du journal montré : celui d'hier (le cas ordinaire — il s'écrit la nuit), d'avant-hier, ou d'un
    jour daté. Jamais « d'aujourd'hui » : la journée en cours n'est pas encore écrite."""
    try:
        gap = (today - date.fromisoformat(day)).days
    except ValueError:
        return "Son journal"
    if gap == 1:
        return "Son journal d'hier"
    if gap == 2:
        return "Son journal d'avant-hier"
    return f"Son journal du {day_fr(date.fromisoformat(day))}"


#: ce que les écrans du monde ne reçoivent jamais, même quand le monde le réduit : ce qu'elle remarque et la prose
#: ne regardent qu'elle ; de ses répliques, le monde ne retient que l'heure (rien ne change à l'écran, et un
#: rattrapage qui en croiserait une rendrait un instantané pour rien)
_WORLD_UNSHOWN = frozenset({w.NOTICED.name, w.DESCRIBED.name, rt.UTTERANCE.name})
#: ce que les écrans du monde reçoivent sans que le monde le réduise : les gestes, les présences, les demandes
_WORLD_SHOWN = frozenset(t.name for t in w.ALL) - _WORLD_UNSHOWN
#: ce qu'un client lit quand l'état a bougé entre la décision et l'écriture
_STALE = "Le monde a changé entre-temps : relis-le, puis recommence."


#: la part de chaque domaine qui en a une (ADR 0310, ``PortPart``), dans l'ordre des fiches
PORTS = tuple(part(d.port, "PORT") for d in DOMAINS if d.port is not None)
#: leurs méthodes, que ``KernelPort`` mêle aux siennes
MIXED: tuple[type, ...] = tuple(p.methods for p in PORTS if p.methods is not None)
#: ce que chacune ajoute à ce que le panneau d'une personne dit, pour une propriétaire, du travail en cours
WORKS = tuple(p.work for p in PORTS if p.work is not None)


class KernelPort(*MIXED):
    """Le port d'entrée (``contracts/entry.py::MindPort``) : ses méthodes, et celles des parts des domaines
    (``MIXED``)."""

    def __init__(self, kernel: Kernel) -> None:
        self.kernel = kernel
        self._store = ReadOnlyStore(kernel.deps.store)
        self._world_types: tuple[Any, frozenset[str]] | None = None
        self._life = ""

    def life(self) -> str:
        """L'empreinte de sa vie : un condensé de l'identifiant du premier événement du journal (sa genèse). Une
        sauvegarde restaurée la garde ; un autre dossier de données (``--data``) en a une autre."""
        if not self._life:
            rows = self.kernel.deps.store.read(after=0)
            try:
                first = next(iter(rows), None)
            finally:
                close = getattr(rows, "close", None)
                if close is not None:
                    close()
            if first is not None:
                self._life = hashlib.sha256(f"mika:{first.id}".encode()).hexdigest()[:16]
        return self._life

    async def perceive(self, p: PerceptionReceived, *, dedupe_key: str | None = None) -> Admission:
        got = await self.kernel.perceive(p, dedupe_key=dedupe_key)
        if got.overloaded:
            return Admission("overloaded")
        return Admission("accepted", got.seq, duplicate=bool(got.commit and got.commit.deduped), reply=got.reply,
                         held=got.held and not self._awaits_typing(got.seq, p))

    def _awaits_typing(self, seq: int | None, p: PerceptionReceived) -> bool:
        """La réponse attend seulement que la personne ait fini d'écrire (``composition._reply_wait``), pas son
        réveil : rien à dire à l'écran — son message suivant, ou la fin de sa saisie, la fera partir."""
        if seq is None or p.room is not None:
            return False
        frame = self.kernel.mind.frame()
        return frame.get(body_c.REPLY_WAIT(seq)) != 0 and frame.get(presence_c.COMPOSING(p.handle)) is not None

    async def connected(self, c: presence_c.Connected) -> None:
        await self.kernel.mind.append([presence_c.CONNECTED.draft(c)], emitter="presence",
                                      correlation=f"ws:{c.connection}", origin=Origin.EXTERNAL)

    async def disconnected(self, handle: str, connection: str) -> None:
        await self.kernel.mind.append([presence_c.DISCONNECTED.draft(handle=handle, connection=connection)],
                                      emitter="presence", correlation=f"ws:{connection}", origin=Origin.EXTERNAL)

    async def read(self, handle: str, up_to: int) -> None:
        """« Lu jusqu'ici » : une fois par valeur et par adresse (une même valeur redite à chaque connexion
        n'écrit rien de plus)."""
        await self.kernel.mind.append([presence_c.READ.draft(handle=handle, up_to=up_to,
                                                             dedupe_key=f"lu:{handle}:{up_to}")],
                                      emitter="presence", correlation=f"lu:{handle}", origin=Origin.EXTERNAL)

    async def composing(self, handle: str, connection: str, on: bool) -> None:
        """En train d'écrire, ou plus : le début et la fin d'une saisie (l'adaptateur en borne le débit)."""
        await self.kernel.mind.append([presence_c.COMPOSE.draft(handle=handle, connection=connection, on=on)],
                                      emitter="presence", correlation=f"ws:{connection}", origin=Origin.EXTERNAL)

    def frame(self) -> Frame:
        return self.kernel.mind.frame()

    def recent(self, handle: str, limit: int) -> list[HistoryRow]:
        return [_row(r) for r in transcript.recent(self._store, handle, limit)]

    def after(self, handle: str, after_id: int, limit: int) -> tuple[list[HistoryRow], bool]:
        rows, truncated = transcript.after(self._store, handle, after_id, limit)
        return [_row(r) for r in rows], truncated

    def strands(self, handle: str) -> list[StrandItem]:
        return [StrandItem(**item) for item in transcript.strands_of(self._store, handle)]

    def strand_history(self, handle: str, strand: str, before: int | None, limit: int) -> tuple[list[HistoryRow],
                                                                                                 bool]:
        rows, more = transcript.strand_history(self._store, handle, strand, before, limit)
        return [_row(r) for r in rows], more

    async def set_strand(self, handle: str, strand: str, *, title: str, description: str, archived: bool) -> str:
        """Un fil de travail réglé depuis le chat (ADR 0164) : le chemin des actions de la console
        (``transcript.regler_fil``, validé et audité), au nom de celle à qui il est. ``ok``, ``invalid`` ou
        ``failed``."""
        form = {"strand": [strand], operations.FIXED_FIELD: ["strand"],
                forms.RENDERED: ["title", "description", "archived"], "title": [title], "description": [description]}
        if archived:
            form["archived"] = ["1"]
        outcome = await operations.perform(self.kernel, "transcript.regler_fil", form, by=handle, via=operations.SPACE)
        if outcome.ok:
            return "ok"
        return "failed" if outcome.retry else "invalid"

    def efforts(self, handle: str) -> Efforts:
        """Ce que la personne a forcé (sa conversation, ses fils), et ce que « auto » vaut en ce moment : l'effort
        du rôle qui lui répond, et de celui du mode pro (ADR 0287)."""
        forced = dict(transcript.efforts_of(self._store, handle))
        runner = self.kernel.runner
        reply = runner.policies.get(self.kernel.deps.reply_kind)
        pro = runner.modes.get(PRO)
        return Efforts(conversation=forced.pop("", ""), strands=forced,
                       auto=self._role_effort(reply.role if reply is not None else None),
                       auto_pro=self._role_effort(pro.role if pro is not None else None))

    def _role_effort(self, role: str | None) -> str:
        """L'effort auquel part un appel de ce rôle qui n'en demande pas (ADR 0285) ; « » : le défaut du modèle, ou
        aucun modèle."""
        gateway = self.kernel.deps.gateway
        return gateway.effort_of(str(role))[0] if gateway is not None and role else ""

    async def set_effort(self, handle: str, strand: str, effort: str) -> str:
        """L'effort de réflexion forcé depuis le chat (ADR 0287) : le chemin des actions de la console
        (``transcript.regler_effort``, validé et audité), au nom de celle qui règle. ``ok``, ``invalid`` ou
        ``failed``."""
        form = {"strand": [strand], operations.FIXED_FIELD: ["strand"], forms.RENDERED: ["effort"],
                "effort": [effort or "auto"]}
        outcome = await operations.perform(self.kernel, "transcript.regler_effort", form, by=handle,
                                           via=operations.SPACE)
        if outcome.ok:
            return "ok"
        return "failed" if outcome.retry else "invalid"

    def ready(self) -> bool:
        return self.kernel.started

    # ── les pièces jointes qu'on lui envoie (ADR 0106) ──
    async def keep_attachments(self, handle: str, blobs: Sequence[bytes]) -> list[str | None]:
        """Les octets d'abord, sous la clé de la pièce (l'adresse et la personne derrière pour sujets : l'oubli de
        l'une les efface) ; le message qui suit les désigne."""
        store = self.kernel.ports.get(attachments.PORT)
        if store is None:
            return [None for _ in blobs]
        person = self.kernel.mind.frame().get(identity_c.PERSON(handle))
        out: list[str | None] = []
        for data in blobs:
            if not data or len(data) > MAX_SHARE_BYTES:
                out.append(None)
                continue
            file = attachments.file_id(handle, data)
            try:
                await store.put(file, data, subjects=tuple(k for k in (handle, person) if k))
            except (OSError, ValueError):
                out.append(None)
                continue
            out.append(file)
        return out

    # ── les fichiers qu'elle envoie (ADR 0062) ──
    def shared(self, ids: Sequence[str]) -> list[SharedMeta]:
        return [SharedMeta(id=r.id, name=r.name, kind=r.kind, mime=r.mime, size=r.size, available=not r.gone)
                for r in shares.rows(self._store, [i for i in ids if valid_id(i)])]

    def pieces(self, files: Sequence[str]) -> list[SharedMeta]:
        """Les pièces reçues que cette liste désigne (les clés d'une ligne du fil de la personne qui les a
        envoyées) : ce qu'un écran montre de sa propre copie (ADR 0215) — lue de près, ou seulement gardée au bord, en
        attendant sa lecture (ADR 0312 : sa taille n'est pas encore connue, 0)."""
        found = {r.id: r for r in attachments.rows(self._store, files)}
        state = self.kernel.mind.root.slices.get(attachments_c.OWNER)
        out: list[SharedMeta] = []
        for file in dict.fromkeys(f for f in files if isinstance(f, str)):
            r = found.get(file)
            if r is not None:
                out.append(SharedMeta(id=r.id, name=r.name, kind=r.kind, mime=r.mime, size=r.size,
                                      available=not r.gone))
            elif (p := attachments.waiting(state, file)) is not None:
                out.append(SharedMeta(id=p.file, name=p.name, kind=p.kind, mime=p.mime, size=0))
        return out

    async def _own_piece(self, file: str, handle: str) -> SharedDownload | None:
        """Une pièce que cette adresse a envoyée elle-même (ADR 0215) : à elle seule, et ses octets relus doivent être
        ceux qui ont été lus (leur empreinte). L'ADR 0106 (« elle ne renvoie jamais une pièce reçue ») vise les
        outils de Mika ; ici, c'est la personne qui reprend sa propre copie."""
        r = attachments.row(self._store, file)
        if r is None:
            return await self._waiting_piece(file, handle)
        if r.handle != handle:
            return None
        if r.gone:
            return SharedDownload(r.name, r.mime, gone=True)
        store = self.kernel.ports.get(attachments.PORT)
        data = await store.read(file, MAX_SHARE_BYTES) if store is not None else None
        if data is None or hashlib.sha256(data).hexdigest() != r.digest:
            return SharedDownload(r.name, r.mime, gone=True)
        return SharedDownload(r.name, r.mime, data)

    async def _waiting_piece(self, file: str, handle: str) -> SharedDownload | None:
        """Une pièce que cette adresse a envoyée, gardée au bord mais pas encore lue de près (ADR 0312) : elle la
        reprend sans attendre. Sans empreinte gardée, ses octets doivent redonner sa clé, faite de cette adresse et de
        leur empreinte (``attachments.file_id``)."""
        p = attachments.waiting(self.kernel.mind.root.slices.get(attachments_c.OWNER), file, handle)
        if p is None:
            return None
        store = self.kernel.ports.get(attachments.PORT)
        data = await store.read(file, MAX_SHARE_BYTES) if store is not None else None
        if data is None or attachments.file_id(handle, data) != file:
            return SharedDownload(p.name, p.mime, gone=True)
        return SharedDownload(p.name, p.mime, data)

    async def shared_file(self, file: str, *, handle: str) -> SharedDownload | None:
        """Un fichier parti avec un message du fil que cette adresse peut relire (``THREAD`` : la sienne, celles de
        sa personne dont la liaison est confirmée), ou une pièce qu'elle a envoyée (ADR 0215) ; ses octets relus
        doivent être ceux qui sont partis (leur empreinte)."""
        if not valid_id(file):
            return None
        r = shares.row(self._store, file)
        if r is None:
            return await self._own_piece(file, handle)
        if not r.sent:
            return None
        if r.person not in self.kernel.mind.frame().get(identity_c.THREAD(handle)):
            return None
        if r.gone:
            return SharedDownload(r.name, r.mime, gone=True)
        store = self.kernel.ports.get(shares.PORT)
        data = await store.read(file, MAX_SHARE_BYTES) if store is not None else None
        if data is None or hashlib.sha256(data).hexdigest() != r.digest:
            return SharedDownload(r.name, r.mime, gone=True)
        return SharedDownload(r.name, r.mime, data)

    def health(self) -> dict[str, Any]:
        return health.report(self.kernel).public()

    def _inner_life(self, frame: Any, handle: str, disclosure: Any) -> dict[str, Any]:
        """Ses pensées (celles que cette personne peut entendre) et son récit."""
        out: dict[str, Any] = {}
        audience = Audience(persons=(handle,), channel="web", public=False, level=int(disclosure.level),
                            witness_level=int(disclosure.witness_level), private_ok=disclosure.own_file,
                            untied_level=int(disclosure.untied_level))
        person = frame.get(identity_c.PERSON(handle))
        thoughts = [t for t in frame.get(attention_c.THOUGHTS)
                    if attention_prompt.admissible(t, person, audience, frame)][:3]
        texts = self._store.content([t.text_ref for t in thoughts if t.text_ref])

        def name_of(key: str) -> str:
            return frame.get(identity_c.IDENTITY(key)).name

        # les mots d'un message privé ne se citent qu'à qui les a écrits (attention)
        out["ruminations"] = [{"summary": attention_prompt.shown(t, texts[t.text_ref], person, name_of,
                                                                name=attention_prompt.named(t, person, audience)),
                               "intensity": round(t.intensity, 2), "emotion": t.emotion}
                              for t in thoughts if texts.get(t.text_ref)]
        yesterday, dream = frame.get(self_c.YESTERDAY), frame.get(self_c.DREAM_RESIDUE)
        # la même version que celle qu'elle a en tête devant cette personne (ADR 0043) : l'intime à qui en est le
        # seul concerné, en privé ; sinon la partageable ; sinon rien
        ref = night.journal_ref(yesterday, person, audience, frame) if yesterday is not None else ""
        if yesterday is not None and ref:
            text = self._store.content([ref]).get(ref)
            if text:
                # le journal d'une journée passée (il s'écrit la nuit) : son titre le dit, le panneau ne l'invente pas
                out["today_journal"] = {"date": yesterday.day, "title": journal_title(yesterday.day,
                                                                                      lived_date(frame)),
                                        "narrative": text, "dominant_emotion": yesterday.dominant,
                                        "persons_interacted": []}
        if dream is not None and night.dream_hearable(dream, person, audience, frame):
            text = self._store.content([dream.text_ref]).get(dream.text_ref)
            if text:
                out["last_dream"] = {"content": text, "dream_type": dream.kind, "vividness": dream.vividness,
                                     "emotion": dream.emotion or "dreamy", "night_of": dream.night,
                                     "recalled": dream.recalled}
        me = frame.state("self")
        ref = me.narrative_ref if not me.narrative_masked else ""  # un souvenir repris est devenu secret (ADR 0082)
        narrative = self._store.content([ref]).get(ref) if ref else None
        if narrative:
            out["self_narrative"] = {"content": narrative}
        return out

    async def resolve_effect(self, proposal: int, approved: bool, *, by: str, note: str = "",
                             seen: str = "") -> str:
        """Approuver ou refuser un effet en attente (``runtime/decisions.py``) : ``approved``,
        ``rejected``, ``unknown`` (inconnu ou déjà décidé), ``changed`` (ce qui partirait a
        changé depuis qu'on l'a lu) ou ``blocked`` (ça ne peut pas partir tel quel)."""
        got = await decisions.decide(self.kernel.mind, self.kernel.ports, proposal, approved, by=by, note=note,
                                     seen=seen)
        return got.status

    async def approval_cards(self, handle: str) -> list[dict[str, Any]]:
        """Les cartes d'accord de cette adresse (ADR 0064) : les effets en attente dont elle seule décide, dans le
        chat (``_decider``) — chacun avec exactement ce qui partirait et son empreinte (celle que la réponse
        renvoie), et l'instant où la carte ne vaudra plus."""
        frame = self.kernel.mind.frame()
        effects = frame.state("runtime").effects
        cards: list[dict[str, Any]] = []
        for view in frame.get(rt.PENDING_EFFECTS):
            pending = effects.get(view.proposal)
            args = rt.proposal_args(pending.args_json) if pending is not None else {}
            if not handle or args.get(rt.DECIDER) != handle:
                continue
            shown = await decisions.preview(self.kernel.mind, self.kernel.ports, pending.capability,
                                            pending.args_json)
            summary = self.kernel.mind.store.content([view.summary_ref]).get(view.summary_ref, "") \
                if view.summary_ref else ""
            expires = rt.arg_int(args, rt.EXPIRES)
            cards.append({"id": view.proposal, "title": summary[:400] or "Une demande d'accord",
                          "text": shown.text[:4000] if shown is not None else summary[:400],
                          "digest": shown.digest if shown is not None else "",
                          "blocked": shown.blocked if shown is not None else "",
                          "expires_at": expires // 1000 if expires else None,
                          # ce qu'elle veut faire, et le brouillon qu'elle a écrit : un client qui relit ses
                          # brouillons là où ils partiront y mène plutôt que de les décider ici (ADR 0191)
                          "capability": pending.capability, "draft": str(args.get("draft") or "")[:100]})
        return cards

    async def judge(self, handle: str, seq: int, verdict: str, comment: str) -> str:
        """Une de ses réponses jugée depuis le chat par une opératrice (ADR 0113) : le chemin des actions de la
        console (``transcript.juger``, validé et audité). ``ok``, ``invalid`` (pas une de ses réponses, un avis
        inconnu) ou ``failed``."""
        # un formulaire tel que la console l'envoie : les champs rendus (``_champs``), la clé cachée en valeur fixe
        form = {"seq": [str(seq)], operations.FIXED_FIELD: ["seq"], forms.RENDERED: ["verdict", "comment"],
                "verdict": [verdict or "retire"], "comment": [comment]}
        outcome = await operations.perform(self.kernel, "transcript.juger", form, by=handle, via=operations.SPACE)
        if outcome.ok:
            return "ok"
        return "failed" if outcome.retry else "invalid"

    async def decide_card(self, handle: str, proposal: int, approved: bool, seen: str) -> str:
        """Une carte décidée dans le chat : seulement par l'adresse à qui elle est adressée, tant qu'elle vaut,
        telle qu'elle était montrée (``seen``). ``approved``, ``rejected``, ``unknown``, ``changed``, ``blocked``,
        ``expired`` ou ``forbidden`` (pas à toi de décider)."""
        frame = self.kernel.mind.frame()
        pending = frame.state("runtime").effects.get(proposal)
        if pending is None:
            return decisions.UNKNOWN
        args = rt.proposal_args(pending.args_json)
        if not handle or args.get(rt.DECIDER) != handle:
            return "forbidden"
        expires = rt.arg_int(args, rt.EXPIRES)
        if approved and expires and self.kernel.mind.clock.now() > expires:
            return "expired"
        if approved and not seen:
            return decisions.CHANGED  # accepter sans dire ce qu'on a lu : jamais
        return await self.resolve_effect(proposal, approved, by=handle, seen=seen,
                                         note="" if approved else "refusé dans la conversation")

    def person_panel(self, handle: str) -> dict[str, Any] | None:
        frame = self.kernel.mind.frame()
        view = frame.get(identity_c.IDENTITY(handle))
        if not view.known:
            return None
        claims = [{"id": 0, "name": view.claim, "kind": "self_declared", "evidence": "", "created_at": ""}] \
            if view.claim else []
        out: dict[str, Any] = {"identity": {
            "known_as": view.name, "certainty": round(view.claim_certainty if view.claim else view.certainty, 2),
            "level": " ".join(describe(view, public=False)), "trust": view.trust.value, "pending_claims": claims,
        }}
        disclosure = frame.get(identity_c.DISCLOSURE((handle, view.channel or "web", False)))
        out.update(self._inner_life(frame, handle, disclosure))
        if frame.get(identity_c.SPEAKS_AS_OWNER(handle)):  # les droits tiennent à l'adresse qui parle
            for work in WORKS:  # ce que chaque domaine dit du travail en cours (ses projets : ``PortPart.work``)
                out.update(work(self, frame))
        if not disclosure.own_file:
            return out  # sa fiche est fermée : rien de ce qu'elle sait de la personne
        person = frame.get(identity_c.PERSON(handle))
        profile = frame.state("social").profiles.get(person)
        contact = frame.get(social_c.CONTACT(person))
        shown = profile is not None and not profile.masked  # devenue secrète, une source le fait taire (ADR 0082)
        parts = profile_parts(profile, self._store.content(refs_of(profile))) if shown else (None, "", (), ())
        out["person_profile"] = {
            "name": view.name, "summary": parts[0] or "", "closeness": frame.get(social_c.CLOSENESS(person)),
            "preferred_tone": parts[1], "topics_of_interest": list(parts[2]), "sensitive_topics": list(parts[3]),
            "interaction_count": contact.inbound,
        }
        promises = frame.get(memory_c.PROMISES_TO(person))
        if promises:
            ids = [pr.id for pr in promises]
            v = memory_c.KNOWLEDGE
            rows = self._store.query_mind(select(v.c.text).where(v.c.id.in_(ids)).order_by(v.c.id))
            out["pending_commitments"] = [r[0] for r in rows]
        return out

    # ── le monde (ADR 0050, 0051) ──
    def world_view(self) -> tuple[w.WorldDef, w.WorldState]:
        frame = self.kernel.mind.frame()
        return frame.get(w.DEFINITION), frame.get(w.STATE)

    async def world_command(self, command: Any, *, actor: str, handle: str | None, operator: bool,
                            session: str | None = None) -> w.CommandResult:
        """Une seule racine pour décider et pour écrire : la faculté rend son verdict sur ``frame``, et l'écriture
        se fait sur la même base, sous sa garde — si le monde a bougé entre-temps, rien n'est écrit (``stale``)."""
        frame = self.kernel.mind.frame()
        verdict = world_commands.handle(frame, command, actor=actor, handle=handle, operator=operator)
        if not verdict.ok:
            return w.CommandResult(status=w.CommandStatus.REFUSED, code=verdict.code, message=verdict.message[:300])
        if not verdict.drafts:
            return w.CommandResult(status=w.CommandStatus.ACCEPTED)  # un progrès, un chargement : rien à écrire
        # la clé du noyau d'abord (une fin d'action : ``fin:<intent>``, que l'échéance partage) ; sinon celle de
        # la commande, par brouillon (deux brouillons d'un même type sous une même clé n'en feraient qu'un)
        drafts = [d if d.dedupe_key is not None or session is None
                  else replace(d, dedupe_key=f"{session}:{command.cmd}:{i}") for i, d in enumerate(verdict.drafts)]
        try:
            commit = await self.kernel.mind.append(drafts, emitter=w.OWNER, correlation=f"monde:{actor}",
                                                   origin=Origin.EXTERNAL, basis=frame.root, guard=verdict.guard)
        except Superseded:
            return w.CommandResult(status=w.CommandStatus.REFUSED, code=w.Refusal.STALE, message=_STALE)
        return w.CommandResult(status=w.CommandStatus.ACCEPTED, seq=commit.seqs[-1] if commit.seqs else None)

    def _screen_types(self) -> frozenset[str]:
        """Les types qui changent ce que montrent les écrans du monde : ceux que la faculté ``world`` réduit (lus
        dans la composition, pas recopiés : un réflexe de plus s'y ajoute seul) et ceux qu'elle diffuse."""
        registry = self.kernel.mind.registry
        if self._world_types is None or self._world_types[0] is not registry:
            reduced = {name for name, specs in registry.reducers_by_type.items()
                       if any(spec.owner == w.OWNER for spec in specs)}
            self._world_types = (registry, (frozenset(reduced) | _WORLD_SHOWN) - _WORLD_UNSHOWN)
        return self._world_types[1]

    def world_events(self, after: int, *, limit: int) -> list[Event[Any]] | None:
        mind = self.kernel.mind
        events: list[Event[Any]] = []
        rows = mind.store.read(after=max(0, after), types=self._screen_types(), upto=mind.head)
        try:
            for stored in rows:
                if len(events) >= limit:
                    return None
                events.append(mind.decode(stored))
        finally:
            close = getattr(rows, "close", None)
            if close is not None:
                close()
        return events

    def world_update(self, events: Sequence[Event[Any]], root: Root
                     ) -> tuple[list[Event[Any]], w.WorldDef, w.WorldState] | None:
        """Ce qu'un lot commité change pour les écrans du monde (``None`` : rien), avec le monde après le lot —
        branché sur ``Mind.subscribe`` par le serveur."""
        types = self._screen_types()
        relevant = [e for e in events if e.type.name in types]
        if not relevant:
            return None
        view = self.kernel.mind.view(root)
        return relevant, view.get(w.DEFINITION), view.get(w.STATE)
