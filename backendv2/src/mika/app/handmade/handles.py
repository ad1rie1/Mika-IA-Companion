"""La fiche d'un moyen de communication, dessinée (ADR 0121) : son en-tête, et son premier onglet, « En bref ».

Par où la personne lui écrit (le canal, ce qu'il prouve, son compte, si elle peut lui écrire d'elle-même), qui écrit
d'ici (pour qui il parle, ses droits de propriétaire, ses autres moyens de communication), ce que ça ouvre (en privé, en
public, une ligne par sorte de chose) et le verdict pas à pas, replié. Le verdict est celui de la faculté ``identity``
(ses faits ``IDENTITY`` et ``DISCLOSURE``), lu par ses propres fonctions : rien n'est recalculé autrement. Son fil se
dessine en bulles, comme les Échanges ; ses onglets « Verdict » et « Ses autres moyens de communication », qu'elle
résume, passent sous
« Le détail ».
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade import Look
from mika.app.handmade.person.echanges import exchanges
from mika.contracts import identity as identity_c
from mika.contracts import transcript as transcript_c
from mika.faculties.identity.faculty import handles_of, known_as, view_of
from mika.faculties.identity.inspect import (
    LEVEL_FR,
    LEVEL_TONE,
    TRUST_FR,
    TRUST_SHORT,
    TRUST_TONE,
    VIA_FR,
    disclosures,
    handle_label,
    kind_of,
    owner_here,
    reach_fr,
    stance,
    verdict_steps,
    view_certainty,
    why_file,
    why_level,
)
from mika.inspector import render
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import UI, Overview, env
from mika.kernel.clock import DAY
from mika.kernel.inspect import Pager
from mika.vocab import privacy
from mika.vocab.people import is_identifiable
from mika.vocab.privacy import ChannelTrust

KIND = "handle"
#: par où, en mots : (court, pour la tuile ; long, pour la fiche)
CHANNELS = {privacy.MOBILE: ("le téléphone", "l'application Android, sur son téléphone"),
            privacy.WEB: ("le chat web", "le chat, dans un navigateur"),
            privacy.EXTERNAL: ("un compte extérieur", "un canal extérieur, sans compte chez elle")}
#: ce qu'elle peut dire, une ligne par sorte de chose : (libellé, champ de ``Disclosure``, une aide)
OPENS = (("Sur les autres", "level", "ce qu'elle sait des autres, en général"),
         ("Sur ce qui concerne la personne", "witness_level", "ce qui la regarde, ou dont elle a été témoin"),
         ("Sur quelqu'un qu'elle connaît", "tied_level", "une personne avec qui elle a un lien"),
         ("La vie de quelqu'un, sans lien", "untied_level", "dite nommément à qui n'a aucun lien avec lui"),
         ("Sans nommer personne", "veiled_level", "à qui n'a aucun lien connu avec la personne"))


def _channel(channel: str) -> tuple[str, str]:
    return CHANNELS.get(channel, (channel or "inconnu", channel or "un canal inconnu"))


def _read(ui: UI, key: str) -> tuple[Look, Any, Any, Any] | None:
    look = Look.of(ui, DAY)
    try:
        s = look.frame.state("identity")
    except KeyError:
        return None
    h = s.handles.get(key)
    return None if h is None else (look, s, h, view_of(s, key, look.frame.now))


class HandleOverview(Overview):
    """« En bref » : le premier onglet de la fiche d'un moyen de communication ; « Verdict » et ses autres moyens,
    qu'il résume, passent au bout de la barre ; son fil est dessiné en bulles."""

    slug = "ensemble"
    title = "En bref"
    description = "Par où cette personne lui écrit, ce que ce canal prouve, qui écrit d'ici et ce que ça ouvre."
    styles = ("handmade/identites.css",)
    folded = ("verdict", "autres")
    tabs = ("fil",)

    def head(self, ui: UI, key: str) -> Markup | None:
        got = _read(ui, key)
        if got is None:
            return None
        look, s, h, view = got
        frame = look.frame
        if view.bound:
            said = f"lié par {VIA_FR.get(h.via, h.via or '?')}"
        elif view.name:
            said = "relié à personne d'autre"
        else:
            said = "rien ne dit encore qui écrit d'ici"
        tags = [(TRUST_SHORT[h.trust], TRUST_TONE[h.trust]),
                (f"certitude {view_certainty(view)}",
                 "ok" if view.certainty >= privacy.POLICY.private_threshold else "")]
        if view.claim:
            tags.append((f"se présente comme « {view.claim} »", "warn"))
        if frame.get(identity_c.SPEAKS_AS_OWNER(key)):
            tags.append(("droits de propriétaire", "info"))
        elif frame.get(identity_c.IS_OWNER(view.person)):
            tags.append(("propriétaire, sans ses droits ici", "warn"))
        if view.bound and view.via == identity_c.VIA_CORROBORATED:
            tags.append(("liaison à confirmer", "warn"))
        if not is_identifiable(key):
            tags.append(("jetable", ""))
        return Markup(env.get_template("handmade/identites/adresse_tete.html").render(
            title=handle_label(s, key), channel=_channel(h.channel)[1], kind=kind_of(h), tags=tags,
            person={"name": known_as(s, view.person), "href": look.href(view.person)} if view.person else None,
            said=said))

    def render(self, ui: UI, key: str) -> Markup | None:
        got = _read(ui, key)
        if got is None:
            return None
        look, s, h, view = got
        frame = look.frame
        last = frame.get(transcript_c.LAST_FROM(key))
        short, long = _channel(h.channel)
        alerts = []
        if view.claim:
            alerts.append({"tone": "warn", "text": f"Elle se présente comme « {view.claim} » : rien ne le confirme "
                                                   "encore.", "href": fiche_url(KIND, key, "revendication"),
                           "link": "Ce qui manque pour le croire"})
        if view.bound and view.via == identity_c.VIA_CORROBORATED:
            alerts.append({"tone": "warn", "text": "Lié par recoupement : le fil de ses autres moyens de "
                                                   "communication lui reste fermé tant qu'un opérateur n'a pas "
                                                   "confirmé la liaison."})
        private, public = disclosures(frame, key, h)
        closeness, warmth = stance(frame, key, view.person)
        audiences = []
        for label, d, flag in (("En privé", private, False), ("En public", public, True)):
            seen_public = flag or h.trust is ChannelTrust.PUBLIC
            opened, _, why = why_file(view.certainty, h.trust, public=seen_public).partition(" : ")
            audiences.append({"label": label, "file": opened, "file_why": why, "why": why_level(
                view.certainty, h.trust, closeness=closeness, warmth=warmth, public=seen_public),
                "levels": [{"text": LEVEL_FR.get(getattr(d, field), "?"),
                            "tone": LEVEL_TONE.get(getattr(d, field), "")} for _, field, _ in OPENS]})
        others = [{"label": handle_label(s, k), "href": fiche_url(KIND, k),
                   "trust": TRUST_SHORT[s.handles[k].trust], "tone": TRUST_TONE[s.handles[k].trust]}
                  for k in handles_of(s, view.person) if k != key and k in s.handles]
        return Markup(env.get_template("handmade/identites/adresse.html").render(
            alerts=alerts, channel_short=short, channel_long=long, channel_key=h.channel or "—",
            trust_short=TRUST_SHORT[h.trust], trust_long=TRUST_FR.get(h.trust, str(h.trust)),
            trust_tone=TRUST_TONE[h.trust], certainty=view_certainty(view),
            certainty_tone="ok" if view.certainty >= privacy.POLICY.private_threshold else "",
            account="compte opérateur" if h.operator else "compte" if h.authenticated else "aucun compte",
            reach=reach_fr(h), reach_yes=h.push, reach_how=reach_fr(h).removeprefix("oui (").rstrip(")")
            if h.push else "seulement quand la personne lui écrit", first=f"{ui.when(h.first_seen)} ({look.ago(h.first_seen)})" if h.first_seen else "—",
            last=f"{ui.when(last)} ({look.ago(last)})" if last else "jamais", last_short=look.ago(last) if last else
            "jamais", key=key, person={"name": known_as(s, view.person), "href": look.href(view.person)}
            if view.person else None, bound=view.bound, via=VIA_FR.get(h.via, h.via or ""),
            owner=owner_here(s, frame, key, h, view.person), known_since=ui.when(view.first_seen)
            if view.first_seen else "—", others=others, jetable=not is_identifiable(key),
            opens=[{"label": label, "hint": hint} for label, _, hint in OPENS], audiences=audiences,
            opens_pager=render._pager(Pager(size=len(OPENS) + 1, total=len(OPENS) + 1), {}),
            steps=verdict_steps(h, view.certainty), verdict_tab=fiche_url(KIND, key, "verdict")))

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Sequence[Any], query: Mapping[str, str],
                   forms: Mapping[str, Any] | None = None) -> Any:
        return exchanges(ui, "", blocks, query) if tab == "fil" else None
