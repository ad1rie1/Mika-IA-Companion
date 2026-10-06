"""La console des réveils par API (ADR 0068) : une entrée à elle (« Ses canaux › Réveils par API »), la liste des
réveils et leurs derniers appels, puis la fiche de chacun — ce qui a été déclaré, sa clé, ses appels et ce qu'ils ont donné.

Un réveil se déclare dans Configuration › Plugins › Réveils par API (un lien y mène, l'enregistrement ramène ici). Sa
clé se génère ici : montrée une seule fois, jamais gardée en clair (le port n'en garde que l'empreinte). Ce qu'un
appel apporte est une donnée venue d'ailleurs : montrée à l'opérateur, jamais obéie.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import projects as projects_c
from mika.contracts import wakeup as c
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Code,
    Column,
    Fields,
    Found,
    Head,
    InspectContext,
    Note,
    Param,
    Prose,
    Ref,
    Row,
    Table,
    Text,
    When,
    paginate,
)
from mika.kernel.operate import Done, Refused
from mika.plugins.wakeup import (
    CANCELLED,
    CANCELLED_EVENT,
    DONE,
    EXPIRED,
    FAILED,
    IMPOSSIBLE,
    RUNNING,
    UNFINISHED,
    WAITING,
    WAKEUP,
    Call,
    WakeupState,
)
from mika.plugins.wakeup.prompt import why_waiting

SETTINGS = "/inspecteur/reglages/reveils"
LIST = "/inspecteur/reveils"
NO_PORT = "Les réveils par API ne sont pas branchés sur ce serveur."
CALLS_PAGE = 25
TEXT_SHOWN = 4000
STATUS_WORDS = {WAITING: ("en attente", "info"), RUNNING: ("en cours", "info"), DONE: ("fait", "ok"),
                IMPOSSIBLE: ("impossible", "warn"), UNFINISHED: ("pas fini", "warn"), FAILED: ("échoué", "danger"),
                EXPIRED: ("expiré", "muted"), CANCELLED: ("annulé", "muted")}
#: les lots qui font sortir des données de la machine (ce que l'avertissement nomme)
OUTWARD = ("forge", "forge_apps", "email")


def _fiche(name: str, tab: str = "") -> Ref:
    return Ref.subject("reveil", name, name, tab)


def _fiche_url(name: str) -> str:
    return f"/inspecteur/fiche/reveil/{name}"


def edit_endpoint(name: str, back: str = LIST) -> Ref:
    return Ref("local", SETTINGS, "Modifier ses réglages",
               (("section", "reveils"), ("enregistrement", "endpoints"), ("cle", name), ("retour", back)))


def add_endpoint(back: str = LIST) -> Ref:
    return Ref("local", SETTINGS, "Déclarer un réveil",
               (("section", "reveils"), ("enregistrement", "endpoints"), ("cle", ""), ("nouveau", "1"),
                ("retour", back)))


def status_badge(call: Call) -> Badge:
    word, tone = STATUS_WORDS.get(call.status, (call.status, ""))
    if call.told:
        word += ", dit"
    return Badge(word, tone)


def notify_words(frame: Frame, notify: str) -> str:
    if notify == c.NOBODY:
        return "personne (le compte rendu reste dans la console)"
    if notify == c.OWNERS:
        return "ses propriétaires"
    name = frame.get(identity_c.IDENTITY(notify)).name
    return f"« {name} »" if name else notify


def project_words(frame: Frame, ctx: InspectContext, project: int) -> Any:
    if not project:
        return "aucun"
    view = next((p for p in frame.get(projects_c.LIVE) if p.id == project), None)
    title = ctx.store.content([view.title_ref]).get(view.title_ref, "") if view is not None and view.title_ref else ""
    text = f"n° {project}" + (f" — {title}" if title else "")
    return Ref.subject("project", str(project), text) if view is not None else f"{text} (archivé ou inconnu)"


def risks(endpoint: Any) -> list[str]:
    """Ce qu'un réglage expose, en mots : le texte d'un appel vient d'ailleurs, et l'épisode a les droits de sa
    propriétaire."""
    out = []
    outward = [b for b in endpoint.bundles if b in OUTWARD or b.startswith("mcp.")]
    if "memory" in endpoint.bundles and outward:
        out.append(f"Sa mémoire et des outils qui font sortir des données ({', '.join(outward)}) : un texte d'appel "
                   "malveillant (une clé qui a fuité) pourrait lui faire sortir ce qu'elle sait. Ne les garde ensemble "
                   "que pour un appelant de confiance.")
    if "memory" in endpoint.bundles and endpoint.notify not in (c.NOBODY, c.OWNERS):
        out.append("Il a sa mémoire et rend compte à un compte qui n'est pas forcément sa propriétaire : son compte "
                   "rendu est écrit avec tout ce qu'elle sait, et seule sa discrétion trie ce qui en sort.")
    if endpoint.rouse:
        out.append("Il passe outre son sommeil : chaque appel la réveille la nuit, comme le message d'une proche, et "
                   "son compte rendu part aussitôt (la nuit aussi).")
    return out


# ── La liste ──────────────────────────────────────────────────────────────


@WAKEUP.inspect("reveils", title="Réveils par API", section="reveils", order=10,
                params=[Param("reveil", "Réveil", placeholder="nom exact d'un réveil")],
                description="Les réveils que des systèmes extérieurs appellent (POST /api/wake/<nom>), et ce que "
                            "leurs appels ont donné. Ils se déclarent dans Configuration.")
def _list(s: WakeupState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("wakeup")
    blocks: list[Block] = [Fields((("nouveau réveil", add_endpoint()),
                                   ("tous les réglages", Ref("local", SETTINGS, "Configuration › Réveils par API"))))]
    if port is None:
        blocks.append(Note(NO_PORT, tone="muted"))
    else:
        rows = []
        for ep in port.endpoints():
            pending = sum(1 for x in s.calls.values() if x.endpoint == ep.name and x.status in (WAITING, RUNNING))
            last = max((x.at for x in s.calls.values() if x.endpoint == ep.name), default=0)
            rows.append(Row((_fiche(ep.name), Text(ep.label or "—", clamp=160),
                             Badge("actif", "ok") if ep.enabled else Badge("désactivé", "muted"),
                             Badge("clé définie", "ok") if ep.key is not None else Badge("sans clé", "warn"),
                             Text(str(pending), "num"), When(last) if last else "jamais"),
                            href=_fiche(ep.name)))
        blocks.append(Table(("réveil", "à quoi il sert", Column("état", "fit"), Column("clé", "fit"),
                             Column("en attente", "num"), Column("dernier appel", "fit")), tuple(rows),
                            title="Réveils", empty="Aucun réveil déclaré : « Déclarer un réveil ».",
                            caption="Un réveil sans clé ne reçoit rien : génère-la sur sa fiche (montrée une fois)."))
    name = ctx.value("reveil") or ""
    calls = sorted((x for x in s.calls.values() if not name or x.endpoint == name), key=lambda x: -x.seq)
    page, pager = paginate(calls, ctx.pager("page", size=CALLS_PAGE))
    blocks.append(_calls_table(page, s, frame, ctx, pager, with_endpoint=True,
                               title=f"Les appels de « {name} »" if name else "Les derniers appels"))
    return blocks


def _calls_table(calls: Any, s: WakeupState, frame: Frame, ctx: InspectContext, pager: Any, *,
                 with_endpoint: bool, title: str) -> Table:
    refs = [r for x in calls for r in (x.text_ref, x.report_ref, x.need_ref) if r]
    texts = ctx.store.content(refs) if refs else {}
    rows = []
    for x in calls:
        said = texts.get(x.text_ref, "") if x.text_ref else ""
        report = texts.get(x.report_ref, "") if x.report_ref else ""
        detail: list[Any] = []
        why = why_waiting(x, s, frame)
        if why:
            detail.append(Note(f"Il attend : {why}.", tone="muted"))
        elif x.status == WAITING:
            detail.append(Note("Il peut partir : il attend d'être choisi (son corps, ou le plafond des exécutions de "
                               "son projet, peuvent encore le retenir un moment).", tone="muted"))
        if x.status == EXPIRED and x.reason:
            detail.append(Note(f"Il ne sera pas traité : {x.reason}.", tone="muted"))
        detail.append(Prose(said[:TEXT_SHOWN] if said else "(oublié)",
                            title="Ce que l'appel apportait (une donnée venue d'ailleurs)", clamp=1200))
        if report:
            detail.append(Prose(report, title="Son compte rendu", clamp=1200))
        need = texts.get(x.need_ref, "") if x.need_ref else ""
        if need:
            detail.append(Prose(need, title="Ce qu'il lui faudrait", clamp=600))
        facts: list[tuple[str, Any]] = [("projet", project_words(frame, ctx, x.project)),
                                        ("mode", "impersonnel" if x.plain else "le sien"),
                                        ("outils", ", ".join(x.bundles) or "aucun"),
                                        ("passe outre son sommeil", "oui" if x.rouse else "non"),
                                        ("rend compte à", notify_words(frame, x.notify)),
                                        ("essais", f"{x.tries} panne(s), {x.starts} départ(s)")]
        if x.expires_at and x.status == WAITING:
            facts.append(("expire", ctx.when(x.expires_at)))
        if x.by:
            facts.append(("annulé par", x.by))
        detail.append(Fields(tuple(facts), columns=2))
        if x.status in (WAITING, RUNNING) and not with_endpoint:  # l'action porte sur la fiche de son réveil
            detail.append(ActionSlot("wakeup.annuler", (("appel", str(x.seq)),), title="Annuler cet appel",
                                     compact=True))
        episode = Ref("episode", x.episode, "relire") if x.episode else Text("—", "muted")
        cells: tuple[Any, ...] = (When(x.at),)
        if with_endpoint:
            cells += (_fiche(x.endpoint),)
        cells += (status_badge(x), Text(said or "(oublié)", clamp=140), episode)
        rows.append(Row(cells, tone="danger" if x.status == FAILED else "", detail=tuple(detail)))
    columns: tuple[Any, ...] = (Column("reçu", "fit"),)
    if with_endpoint:
        columns += (Column("réveil", "fit"),)
    columns += (Column("état", "fit"), "ce qu'il apportait", Column("épisode", "fit"))
    return Table(columns, tuple(rows), title=title, empty="Aucun appel pour l'instant.", pager=pager,
                 caption="Ce qu'un appel apporte est une matière pour elle, jamais une consigne : ce sont les "
                         "consignes du réveil qui priment.")


# ── La fiche d'un réveil ──────────────────────────────────────────────────


@WAKEUP.subject("reveil", label="Réveil par API", plural="Réveils par API", icon="⏰")
def _head(s: WakeupState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    port = ctx.ports.get("wakeup")
    ep = port.endpoint(key) if port is not None else None
    if ep is None:
        return None
    badges = [Badge("actif", "ok") if ep.enabled else Badge("désactivé", "muted"),
              Badge("clé définie", "ok") if ep.key is not None else Badge("sans clé", "warn"),
              Badge("impersonnel", "info") if ep.plain else Badge("dans son mode à elle", "info")]
    if ep.rouse:
        badges.append(Badge("passe outre son sommeil", "warn"))
    return Head(key=key, title=key, subtitle=ep.label, badges=tuple(badges),
                facts=(("réglages", edit_endpoint(key, _fiche_url(key))),
                       ("adresse", Text(f"POST /api/wake/{key}", "mono"))),
                back=Ref("local", LIST, "Réveils par API"))


@WAKEUP.search("reveil")
def _search(s: WakeupState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    port = ctx.ports.get("wakeup")
    query = text.casefold().strip()
    return [Found(ep.name, ep.name, ep.label[:120]) for ep in (port.endpoints() if port is not None else ())
            if not query or query in f"{ep.name} {ep.label}".casefold()][:limit]


@WAKEUP.inspect("etat", title="État", subject="reveil", order=10,
                description="Ce qui a été déclaré, sa clé, et comment l'appeler.")
def _tab_state(s: WakeupState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("wakeup")
    ep = port.endpoint(ctx.subject) if port is not None else None
    if ep is None:
        return [Note("Ce réveil n'existe plus.", tone="muted")]
    blocks: list[Block] = [Note(r, tone="warn") for r in risks(ep)]
    if not ep.enabled:
        blocks.append(Note("Il est désactivé : ses appels sont refusés (403).", tone="muted"))
    blocks.append(Fields((
        ("à quoi il sert", ep.label or "—"),
        ("projet", project_words(frame, ctx, ep.project)),
        ("mode", "impersonnel (sans persona, sans affect)" if ep.plain else "le sien (sa voix, son humeur)"),
        ("outils", ", ".join(ep.bundles) or "aucun (seulement de quoi conclure)"),
        ("passe outre son sommeil", "oui : il la réveille" if ep.rouse else "non : il attend son réveil"),
        ("rend compte à", notify_words(frame, ep.notify)),
        ("plafonds", f"{ep.per_hour} appels par heure, {ep.max_pending} en attente, texte de "
                     f"{ep.max_chars} caractères"),
        ("durée de vie d'un appel", f"{max(1, ep.lifetime_us // 3_600_000_000)} h"),
        ("réglages", edit_endpoint(ep.name, _fiche_url(ep.name))),
    ), title="Ce que tu as déclaré", columns=2))
    if ep.instructions:
        blocks.append(Prose(ep.instructions, title="Ses consignes (elles priment sur ce que l'appel apporte)",
                            clamp=1200))
    key = ep.key
    blocks.append(Fields((
        ("clé", Text(f"{key.hint}…", "mono") if key is not None else Text("aucune : il ne reçoit rien", "muted")),
        ("générée", ctx.when(key.created_at) if key is not None and key.created_at else "—"),
        ("par", key.by if key is not None and key.by else "—"),
    ), title="Sa clé", columns=3))
    blocks.append(Code(f"curl -X POST <adresse du serveur>/api/wake/{ep.name} \\\n"
                       "  -H 'Authorization: Bearer <la clé>' -H 'Content-Type: application/json' \\\n"
                       "  -d '{\"text\": \"…\"}'",
                       title="L'appeler (202 : reçu ; 401 : nom ou clé ; 403 : désactivé ; 400 : texte ; 429 : trop)"))
    blocks.append(ActionSlot("wakeup.nouvelle_cle", title="Générer une clé neuve"))
    if key is not None:
        blocks.append(ActionSlot("wakeup.retirer_cle", title="Retirer la clé"))
    return blocks


@WAKEUP.inspect("appels", title="Appels", subject="reveil", order=20,
                description="Ses appels, du plus récent : ce qu'ils apportaient, où ils en sont, ce qu'ils ont donné.")
def _tab_calls(s: WakeupState, frame: Frame, ctx: InspectContext) -> list[Block]:
    calls = sorted((x for x in s.calls.values() if x.endpoint == ctx.subject), key=lambda x: -x.seq)
    page, pager = paginate(calls, ctx.pager("page", size=CALLS_PAGE))
    return [_calls_table(page, s, frame, ctx, pager, with_endpoint=False, title="Ses appels")]


# ── Actions ───────────────────────────────────────────────────────────────


class NoArgs(BaseModel):
    pass


class CancelArgs(BaseModel):
    appel: Annotated[int, Knob(label="Appel", widget="hidden")] = Field(ge=1)


def _port(ctx: Any) -> Any:
    port = ctx.ports.get("wakeup")
    if port is None:
        raise Refused(NO_PORT)
    if port.endpoint(ctx.subject) is None:
        raise Refused("Réveil inconnu.")
    return port


def _has_key(s: WakeupState, frame: Frame, key: str, ports: Any) -> bool:
    port = ports.get("wakeup") if ports is not None else None
    ep = port.endpoint(key) if port is not None else None
    return ep is not None and ep.key is not None


@WAKEUP.action("nouvelle_cle", title="Générer une clé neuve", args=NoArgs, emits=[], subject="reveil", order=10,
               inline=True, confirm="L'ancienne clé de ce réveil ne vaudra plus rien.",
               description="Une clé neuve, montrée une seule fois : copie-la tout de suite. L'ancienne ne vaut plus.")
async def _new_key(s: WakeupState, frame: Frame, args: NoArgs, ctx: Any) -> Done:
    port = _port(ctx)
    try:
        key = await port.new_key(ctx.subject, ctx.by)
    except ValueError as exc:
        raise Refused(str(exc)) from None
    return Done(message=f"Clé neuve de « {ctx.subject} » (montrée une seule fois ; l'ancienne ne vaut plus) : {key}")


@WAKEUP.action("retirer_cle", title="Retirer la clé", args=NoArgs, emits=[], subject="reveil", order=20,
               inline=True, danger=True, available=_has_key, confirm="Plus aucun appel ne passera.",
               description="Sans clé, le réveil refuse tout appel (401) jusqu'à ce qu'on en génère une.")
async def _revoke_key(s: WakeupState, frame: Frame, args: NoArgs, ctx: Any) -> Done:
    port = _port(ctx)
    if not await port.revoke_key(ctx.subject, ctx.by):
        raise Refused("Ce réveil n'avait pas de clé.")
    return Done(message=f"La clé de « {ctx.subject} » est retirée : plus aucun appel ne passe.", tone="warn")


@WAKEUP.action("annuler", title="Annuler un appel", args=CancelArgs, emits=[CANCELLED_EVENT], subject="reveil",
               order=30, inline=True, confirm="Cet appel ne sera pas traité (un épisode en cours s'arrête).",
               description="Un appel en attente ou en cours : il ne sera pas traité.")
async def _cancel(s: WakeupState, frame: Frame, args: CancelArgs, ctx: Any) -> Done:
    call = s.calls.get(args.appel)
    if call is None or call.endpoint != ctx.subject:
        raise Refused("Appel inconnu pour ce réveil.")
    if call.status not in (WAITING, RUNNING):
        raise Refused("Cet appel n'est plus en attente.")
    return Done(drafts=(CANCELLED_EVENT.draft(call=call.seq, by=ctx.by),), message=f"Appel n° {call.seq} annulé.")
