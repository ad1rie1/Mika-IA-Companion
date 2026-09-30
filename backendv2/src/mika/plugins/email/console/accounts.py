"""Ses comptes : l'état de chaque boîte, ses dossiers, et **comment elle y écrit**
(le texte exact qu'elle lit avant d'écrire). Les réglages eux-mêmes (serveurs,
mot de passe, voix) se modifient dans Réglages › Sens › Courrier : un lien y
mène, et l'enregistrement ramène ici."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Column,
    Fields,
    Found,
    Head,
    InspectContext,
    Note,
    Prose,
    Ref,
    Row,
    Table,
    Text,
    When,
)
from mika.kernel.operate import Done, Refused
from mika.plugins.email import EMAIL, POLL_ASKED, EmailState
from mika.plugins.email.console.common import (
    NO_PORT,
    SECTION,
    VOICE_LABEL,
    add_account,
    box_link,
    edit_account,
    fold,
)
from mika.plugins.email.voice import voice_text
from mika.ports.mail import AccountInfo


def _state(info: AccountInfo, error: str) -> Badge:
    if not info.enabled:
        return Badge("inactif", "muted")
    if not info.ready:
        return Badge("incomplet", "warn")
    if error:
        return Badge("erreur", "danger")
    return Badge("prêt", "ok")


def _fiche(key: str) -> str:
    return f"/inspecteur/fiche/compte/{key}"


@EMAIL.inspect("comptes", title="Comptes", section=SECTION, order=50,
               description="Ses boîtes aux lettres : leur état, leurs dossiers, comment elle y écrit.")
def _accounts(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mail")
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    rows = []
    for a in port.accounts():
        status = port.status(a.key)
        inbox = next((f for f in port.folders(a.key) if f.role == "inbox"), None)
        rows.append(Row((Text(a.name), Text(a.key, "mono"), Text(a.address or "—", "mono"),
                         Badge(VOICE_LABEL.get(a.voice, a.voice), "info"), Text(", ".join(a.folders), "muted"),
                         _state(a, status.error), When(status.last_poll) if status.last_poll else "jamais",
                         Text(str(inbox.unseen), "num") if inbox is not None else "—",
                         Badge("oui", "ok") if a.autodraft else "non"),
                        href=Ref.subject("compte", a.key, a.name),
                        tone="danger" if status.error else ("warn" if not a.ready and a.enabled else ""),
                        detail=((Note(f"Dernière erreur : {status.error}", tone="danger"),) if status.error else ())
                        + (Fields((("fiche", Ref.subject("compte", a.key, "état, dossiers, tester la connexion")),
                                   ("réglages", edit_account(a.key)))),)))
    blocks: list[Block] = [Fields((("nouvelle boîte", add_account()),
                                   ("tous les réglages", Ref("local", "/inspecteur/reglages/sens",
                                                             "Réglages › Sens › Courrier"))))]
    blocks.append(Table(("nom", Column("clé", "fit"), "adresse", Column("elle écrit", "fit"), "relevés",
                         Column("état", "fit"), Column("dernier relevé", "fit"), Column("non lus", "num"),
                         Column("réponses préparées", "fit")), tuple(rows), title=f"Comptes ({len(rows)})",
                        empty="aucune boîte : ajoute un compte",
                        caption="Un clic ouvre la fiche du compte (état, dossiers, sa voix)."))
    return blocks


@EMAIL.subject("compte", label="Compte", plural="Comptes", icon="✉")
def _head(s: EmailState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    port = ctx.ports.get("mail")
    info = port.account(key) if port is not None else None
    if info is None:
        return None
    status = port.status(key)
    badges = [_state(info, status.error), Badge(f"elle y écrit {VOICE_LABEL.get(info.voice, info.voice)}", "info")]
    if info.autodraft:
        badges.append(Badge("prépare des réponses d'elle-même", "info"))
    facts: list[tuple[str, Any]] = [("réglages", edit_account(key, _fiche(key))),
                                    ("dernier relevé", ctx.when(status.last_poll) if status.last_poll else "jamais")]
    return Head(key=key, title=info.name, subtitle=info.address, badges=tuple(badges), facts=tuple(facts))


@EMAIL.search("compte")
def _search(s: EmailState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    port = ctx.ports.get("mail")
    query = fold(text)
    return [Found(a.key, a.name, a.address) for a in (port.accounts() if port is not None else ())
            if not query or query in fold(f"{a.key} {a.name} {a.address}")][:limit]


@EMAIL.inspect("etat", title="État", subject="compte", order=10)
def _tab_state(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mail")
    info = port.account(ctx.subject) if port is not None else None
    if info is None:
        return [Note("Ce compte n'existe plus.", tone="muted")]
    status = port.status(info.key)
    blocks: list[Block] = []
    if status.error:
        blocks.append(Note(f"Dernière erreur ({ctx.when(status.error_at)}) : {status.error}", tone="danger"))
    if not info.ready:
        blocks.append(Note("Il manque de quoi relever (serveur IMAP, utilisateur) ou le compte est inactif.",
                           tone="warn"))
    blocks.append(Fields(info.details or (("réglages", "—"),), title="Réglages (sans secret)", columns=2))
    rows = tuple(Row((Text(f.label), Text(f.name, "mono"), Badge("relevé", "info") if f.polled else "",
                      Text(str(f.unseen), "num"), Text(str(f.total), "num"),
                      When(f.last_sync) if f.last_sync else "jamais"),
                     href=box_link(f.label, account=info.key, folder=f.name)) for f in port.folders(info.key))
    blocks.append(Table(("dossier", "nom sur le serveur", Column("", "fit"), Column("non lus", "num"),
                         Column("dans le cache", "num"), Column("relu", "fit")), rows, title="Dossiers",
                        empty="la liste des dossiers n'est pas encore connue : « Actualiser les dossiers »",
                        caption="Elle ne remarque que ce qui arrive dans les dossiers relevés."))
    blocks.append(ActionSlot("email.ecrire", (("account", info.key), ("_bouton", "Écrire depuis cette boîte")),
                             title="Écrire depuis cette boîte"))
    return blocks


@EMAIL.inspect("voix", title="Sa voix", subject="compte", order=20)
def _tab_voice(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mail")
    info = port.account(ctx.subject) if port is not None else None
    if info is None:
        return [Note("Ce compte n'existe plus.", tone="muted")]
    pairs: list[tuple[str, Any]] = [
        ("elle y écrit", VOICE_LABEL.get(info.voice, info.voice)),
        ("ton nom", info.display_name or "—"),
        ("son nom d'expéditrice", info.sender_name or "Mika"),
        ("réponses préparées d'elle-même", "oui" if info.autodraft else "non"),
        ("jamais pour", ", ".join(info.autodraft_skip) or "—"),
        ("modifier", edit_account(info.key, _fiche(info.key) + "?onglet=voix")),
    ]
    blocks: list[Block] = [Fields(tuple(pairs), title="Sa voix dans cette boîte", columns=2),
                           Prose(voice_text(info), title="Ce qu'elle lit avant d'écrire depuis cette boîte")]
    blocks.append(Prose(info.signature, title="Signature (ajoutée sous chaque envoi)") if info.signature.strip()
                  else Note("Pas de signature.", tone="muted"))
    if info.voice == "proprietaire" and not info.display_name.strip():
        blocks.append(Note("Elle écrit à ta place, mais « Ton nom » est vide : l'expéditeur et la signature ne "
                           "diront pas qui tu es.", tone="warn"))
    return blocks


# ── Actions ───────────────────────────────────────────────────────────────


class AccountArgs(BaseModel):
    pass


def _key(ctx: Any, fallback: str = "") -> str:
    return ctx.subject or fallback


@EMAIL.action("tester", title="Tester la connexion", args=AccountArgs, emits=[], subject="compte", order=10,
              description="Se connecte (lecture puis envoi) et relit la liste des dossiers.")
async def _test(s: EmailState, frame: Frame, args: AccountArgs, ctx: Any) -> Done:
    port = ctx.ports.get("mail")
    if port is None or port.account(ctx.subject) is None:
        raise Refused("Compte inconnu.")
    ok, said = await port.test(ctx.subject)
    return Done(message=said, tone="ok" if ok else "danger")


@EMAIL.action("dossiers", title="Actualiser les dossiers", args=AccountArgs, emits=[], subject="compte", order=20)
async def _folders(s: EmailState, frame: Frame, args: AccountArgs, ctx: Any) -> Done:
    port = ctx.ports.get("mail")
    if port is None or port.account(ctx.subject) is None:
        raise Refused("Compte inconnu.")
    try:
        found = await port.refresh_folders(ctx.subject)
    except (OSError, RuntimeError, ValueError) as exc:
        raise Refused(f"Le serveur a refusé : {exc}"[:300]) from None
    return Done(message=f"{len(found)} dossier(s).")


@EMAIL.action("relever_compte", title="Relever maintenant", args=AccountArgs, emits=[POLL_ASKED], subject="compte",
              order=30, description="Sans attendre la prochaine relève (même si elle dort).")
def _poll(s: EmailState, frame: Frame, args: AccountArgs, ctx: Any) -> Done:
    port = ctx.ports.get("mail")
    info = port.account(ctx.subject) if port is not None else None
    if info is None or not info.ready:
        raise Refused("Ce compte n'est pas prêt à relever.")
    return Done(drafts=(POLL_ASKED.draft(by=ctx.by),), message="Relève demandée : les nouveaux mails arrivent dans "
                "quelques secondes.")

