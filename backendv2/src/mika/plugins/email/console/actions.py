"""Ce qu'un opérateur fait depuis le courrier : écrire, répondre, relever,
ranger. Un mail écrit ici part **tout de suite** de sa boîte (c'est
l'opérateur qui décide : pas d'accord à demander) et **elle le sait** :
``email.sent`` est un signal que son attention remarque, sa boîte le lui
montre deux jours, et une réponse à ce mail lui est présentée comme telle."""

from __future__ import annotations

import dataclasses
import email.utils
from typing import Annotated, Any

from pydantic import BaseModel, Field, ValidationError

from mika.contracts import email as c
from mika.kernel import forms
from mika.kernel.events import Content
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import Ref
from mika.kernel.operate import Done, Refused
from mika.plugins.email import BUNDLE, EMAIL, POLL_ASKED, READ, EmailState, keeper_name
from mika.plugins.email.console.common import SECTION, can_send, clip, mail_key, ready, resolve, unread
from mika.plugins.email.console.mail import _server
from mika.ports.mail import addresses
from mika.ports.preprocess import inert
from mika.vocab.privacy import Sensitivity

NOT_READY = "Aucune boîte ne peut envoyer : elle n'est pas configurée (Configuration › Plugins › Boîtes aux lettres)."


class WriteArgs(BaseModel):
    account: Annotated[str | None, Knob(label="Depuis", widget="select", advanced=False,
                                        help="La boîte d'où il part (vide : la première qui peut envoyer).")] = None
    to: Annotated[str, Knob(label="À", help="Une adresse, ou « Nom <adresse> » ; plusieurs, séparées par des "
                                            "virgules.", advanced=False)] = Field(min_length=3, max_length=300)
    cc: Annotated[str, Knob(label="Copie", advanced=False)] = Field(default="", max_length=300)
    subject: Annotated[str, Knob(label="Objet", advanced=False)] = Field(min_length=1, max_length=200)
    body: Annotated[str, Knob(label="Message", widget="textarea", advanced=False,
                              help="Sans signature : celle de la boîte est ajoutée.")] = \
        Field(min_length=1, max_length=20_000)


class ReplyArgs(BaseModel):
    to: Annotated[str, Knob(label="À", advanced=False)] = Field(min_length=3, max_length=300)
    cc: Annotated[str, Knob(label="Copie", advanced=False)] = Field(default="", max_length=300)
    subject: Annotated[str, Knob(label="Objet", advanced=False)] = Field(min_length=1, max_length=200)
    body: Annotated[str, Knob(label="Message", widget="textarea", advanced=False,
                              help="Sans signature : celle de la boîte est ajoutée.")] = \
        Field(min_length=1, max_length=20_000)
    quote: Annotated[bool, Knob(label="Citer le mail auquel tu réponds", advanced=False)] = True
    #: le mail auquel on répond : posé par la fiche, jamais tapé
    reply_to: Annotated[str, Knob(label="En réponse à", widget="hidden")] = Field(default="", max_length=500)


class NoArgs(BaseModel):
    pass


class ForwardArgs(BaseModel):
    original: Annotated[str, Knob(label="Message original", widget="hidden")] = Field(min_length=1, max_length=500)
    to: Annotated[str, Knob(label="À", advanced=False)] = Field(min_length=3, max_length=300)
    cc: Annotated[str, Knob(label="Copie", advanced=False)] = Field(default="", max_length=300)
    subject: Annotated[str, Knob(label="Objet", advanced=False)] = Field(min_length=1, max_length=200)
    body: Annotated[str, Knob(label="Message d'accompagnement", widget="textarea", advanced=False,
                              help="Le message original complet est ajouté après ton texte.")] = Field(default="", max_length=20_000)
    attachments: Annotated[bool, Knob(label="Joindre les pièces jointes du message original", advanced=False)] = True


class FolderArgs(BaseModel):
    compte: Annotated[str, Knob(label="Boîte", widget="hidden")] = Field(default="", max_length=40)
    dossier: Annotated[str, Knob(label="Dossier", widget="hidden")] = Field(default="INBOX", max_length=300)


class TidyArgs(BaseModel):
    mail: Annotated[str, Knob(label="Mail", widget="hidden")] = Field(min_length=1, max_length=500)
    geste: Annotated[str, Knob(label="Geste", widget="hidden")] = Field(min_length=1, max_length=40)


def _check(to: str, cc: str) -> None:
    bad = {"to": "une adresse, comme nom@exemple.fr"} if not addresses(to) else {}
    if cc and not addresses(cc):
        bad["cc"] = "des adresses, séparées par des virgules"
    if bad:
        raise Refused("Adresse invalide.", bad)


async def _send(frame: Frame, ctx: Any, args: Any, *, account: str = "", reply_to: str = "",
                quote: bool = False, original: str = "") -> Done:
    port = ctx.ports.get("mail")
    if not can_send(port):
        raise Refused(NOT_READY)
    _check(args.to, args.cc)
    try:
        if original:
            mail_id = await port.forward(original, args.to, args.subject, args.body, cc=args.cc,
                                         by=ctx.by, attachments=args.attachments)
        else:
            mail_id = await port.send(args.to, args.subject, args.body, reply_to, by=ctx.by, account=account,
                                     cc=args.cc, quote=quote)
    except (OSError, RuntimeError, ValueError) as exc:  # une erreur SMTP est une OSError
        raise Refused(f"L'envoi a échoué : {exc}"[:300]) from None
    gone = port.sent_mail(mail_id)
    who = keeper_name(frame, ctx.by)
    summary = (f"{who[:1].upper()}{who[1:]} a envoyé un mail depuis ta boîte, à {inert(args.to, 200)} : "
               f"« {inert(args.subject, 200)} »")
    first = email.utils.parseaddr(args.to)[1].lower()
    draft = c.SENT.draft(source="email", kind=c.SENT_KIND, summary=Content.of(summary[:400],
                         level=int(Sensitivity.PERSONAL)), pertinence=0.5, sensitivity=int(Sensitivity.PERSONAL),
                         bundle=BUNDLE, mail=mail_id, to=args.to[:200], address=first, by=ctx.by,
                         in_reply_to=reply_to, account=gone.account if gone is not None else account,
                         about=tuple(h for h in (c.address_handle(first),) if h), dedupe_key=f"sent:{mail_id}")
    return Done(drafts=(draft,), message=f"Envoyé à {args.to}. Elle le sait.",
                go=Ref.subject("mail", mail_key(mail_id), clip(args.subject)))


def _write_fields(s: EmailState, frame: Frame, key: str, fixed: Any, ports: Any = None) -> list[Any]:
    port = ports.get("mail") if ports is not None else None
    choices = tuple((a.key, f"{a.name} <{a.address}>") for a in (port.accounts() if port is not None else ())
                    if a.can_send)
    return [dataclasses.replace(f, choices=choices, nullable=False, required=True, default=choices[0][0] if choices else None) if f.path == "account" else f
            for f in forms.describe(WriteArgs)]


@EMAIL.action("ecrire", title="Écrire un mail", args=WriteArgs, emits=[c.SENT], section=SECTION, order=10,
              fields=_write_fields, description="Il part de sa boîte tout de suite ; elle le saura.",
              confirm="Envoyer ce mail depuis sa boîte ?")
async def _write(s: EmailState, frame: Frame, args: Any, ctx: Any) -> Done:
    try:
        model = WriteArgs.model_validate(forms.nest({k: v for k, v in dict(args).items()
                                                     if k in WriteArgs.model_fields}))
    except ValidationError as exc:
        raise Refused("Le formulaire a des erreurs.", forms.errors_fr(exc)) from None
    return await _send(frame, ctx, model, account=model.account or "")


@EMAIL.action("repondre", title="Répondre", args=ReplyArgs, emits=[c.SENT],
              description="La réponse part de sa boîte tout de suite ; elle le saura.",
              confirm="Envoyer cette réponse depuis sa boîte ?")
async def _reply(s: EmailState, frame: Frame, args: ReplyArgs, ctx: Any) -> Done:
    return await _send(frame, ctx, args, reply_to=args.reply_to, quote=args.quote and bool(args.reply_to))


@EMAIL.action("transferer", title="Transférer", args=ForwardArgs, emits=[c.SENT],
              description="Envoie le message complet depuis son compte d'origine, avec ses pièces jointes si choisies.",
              confirm="Transférer ce message aux destinataires indiqués ?")
async def _forward(s: EmailState, frame: Frame, args: ForwardArgs, ctx: Any) -> Done:
    return await _send(frame, ctx, args, original=args.original)


@EMAIL.action("relever", title="Relever maintenant", args=NoArgs, emits=[POLL_ASKED], section=SECTION, order=20,
              description="Sans attendre la prochaine relève (même si elle dort).")
def _poll(s: EmailState, frame: Frame, args: NoArgs, ctx: Any) -> Done:
    if not ready(ctx.ports.get("mail")):
        raise Refused("Aucune boîte n'est prête à relever : la boîte n'est pas configurée (Configuration › Plugins › Boîtes aux lettres).")
    return Done(drafts=(POLL_ASKED.draft(by=ctx.by),), message="Relève demandée : les nouveaux mails arrivent "
                "dans quelques secondes.")


def _unread_keys(s: EmailState) -> list[str]:
    return [k for k, m in s.mails.items() if not m.read]


@EMAIL.action("tout_lu", title="Marquer comme lus les mails qu'elle a remarqués", args=NoArgs, emits=[READ],
              section=SECTION, order=30,
              description="Les mails qu'elle a remarqués et pas encore lus (au plus les 100 derniers) quittent « tes "
                          "mails non lus » et sont marqués lus sur le serveur, en une fois. Les autres mails non lus "
                          "de la boîte restent tels quels.",
              confirm="Marquer comme lus, ici et sur le serveur, les mails qu'elle a remarqués et pas encore lus ?",
              available=lambda s, frame, key: bool(_unread_keys(s)))
async def _all_read(s: EmailState, frame: Frame, args: NoArgs, ctx: Any) -> Done:
    """Ceux qu'elle a remarqués sans les lire : sur le serveur **par lot** (une session par compte et par
    dossier, pas une par mail), et pour elle."""
    keys = _unread_keys(s)
    port = ctx.ports.get("mail")
    failed = 0
    if port is not None:
        try:
            failed = await port.mark_seen(keys)
        except (OSError, RuntimeError, ValueError):
            failed = len(keys)
    note = f" ({failed} n'ont pas pu être marqués sur le serveur)" if failed else ""
    return Done(drafts=tuple(READ.draft(mail=k, by=ctx.by, how="lu") for k in keys),
                message=f"{len(keys)} mail(s) qu'elle avait remarqué(s) marqué(s) comme lu(s){note}.")


@EMAIL.action("relire", title="Relire ce dossier", args=FolderArgs, emits=[],
              description="Va chercher ce qui est arrivé dans ce dossier. S'il fait partie des dossiers qu'elle "
                          "relève, elle remarquera quand même les nouveaux mails à sa prochaine relève.")
async def _reread(s: EmailState, frame: Frame, args: FolderArgs, ctx: Any) -> Done:
    port = ctx.ports.get("mail")
    info = port.account(args.compte) if port is not None else None
    if info is None or not info.ready:
        raise Refused("Ce compte n'est pas prêt à relever.")
    try:
        n = await port.sync_folder(args.compte, args.dossier, 50)
    except (OSError, RuntimeError, ValueError) as exc:
        raise Refused(f"Le serveur a refusé : {exc}"[:300]) from None
    return Done(message=f"{n} nouveau(x) mail(s) dans « {args.dossier} »." if n else "Rien de nouveau.")


GESTURES = ("lu", "non_lu", "suivre", "ne_plus_suivre", "archiver", "corbeille")


@EMAIL.action("historique", title="Charger des messages plus anciens", args=FolderArgs, emits=[],
              description="Charge jusqu'à 50 messages antérieurs aux messages déjà synchronisés dans ce dossier.")
async def _older(s: EmailState, frame: Frame, args: FolderArgs, ctx: Any) -> Done:
    port = ctx.ports.get("mail")
    info = port.account(args.compte) if port is not None else None
    if info is None or not info.ready:
        raise Refused("Ce compte n'est pas prêt à relever.")
    try:
        n = await port.older(args.compte, args.dossier, 50)
    except (OSError, RuntimeError, ValueError):
        raise Refused("L'historique n'a pas pu être chargé. Actualise le dossier et vérifie la connexion du compte.") from None
    return Done(message=f"{n} message(s) ancien(s) ajouté(s)." if n else "Tout l'historique disponible de ce dossier est chargé.",
                go=Ref("local", "/inspecteur/courrier/reception", "Retour au dossier",
                       (("compte", args.compte), ("dossier", args.dossier))))


@EMAIL.action("ranger", title="Ranger", args=TidyArgs, emits=[READ],
              description="Un geste rapide sur un mail de la liste (sur le serveur).")
async def _tidy(s: EmailState, frame: Frame, args: TidyArgs, ctx: Any) -> Done:
    if args.geste not in GESTURES:
        raise Refused("Geste inconnu.")
    port = ctx.ports.get("mail")
    ref = resolve(s, port, args.mail) if port is not None else None
    if ref is None:
        raise Refused("Ce mail n'est plus dans la boîte.")
    m = port.cached_one(ref)
    if args.geste == "lu" and m is not None and not unread(m, s.mails.get(ref)):
        return Done(message="Déjà lu.", tone="info")
    done = await _server(dataclasses.replace(ctx, subject=ref), s, args.geste)
    return dataclasses.replace(done, go=Ref("local", f"/inspecteur/{SECTION}/reception", "",
                                            tuple((k, v) for k, v in (("compte", m.account if m else ""),
                                                                      ("dossier", m.folder if m else "")) if v)))
