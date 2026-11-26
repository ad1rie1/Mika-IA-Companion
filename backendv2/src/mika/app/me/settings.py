"""Paramètres, pour qui est connecté (ADR 0187) : son compte (son nom, son mot de passe), et comment part ce que Mika
prépare depuis chacun de ses comptes (ADR 0207). Ses boîtes aux lettres et ses comptes Teams se règlent dans leur
domaine (ADR 0310 : ``app/domains/mail/account_settings.py``, ``app/domains/teams/account_settings.py``), avec les aides
d'ici, qui leur sont communes : à qui est ce qu'elle branche, une clé neuve, les valeurs envoyées, ce qui se
rejournalise, la règle d'un compte en mots.

Ce qu'une personne branche est à elle (ADR 0185, 0186) : à son nom (``personne:<clé>``), ou « à toi » si elle est une
de ses propriétaires — jamais à quelqu'un d'autre ; le partager est une délégation (ADR 0188), pas un changement de
propriétaire. Une ressource qui n'est pas à elle n'existe pas ici. Les secrets ne repartent jamais : un mot de passe
laissé vide reste celui qui est gardé. Ce qui se dérive d'une boîte ou d'un compte (à qui, actif, la règle de son
canal) est rejournalisé aussitôt (``reconfigure``), comme depuis la console. À qui est un compte, c'est son canal qui
le dit (``app/me/accounts.py``).
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from typing import Any

from starlette.routing import Route

from mika.app.domains import AccountsPart
from mika.app.me import accounts as channels
from mika.app.me import rights as rights_me
from mika.app.me.api import Call, Denied, MeApiBase, either
from mika.app.me.common import settings_of
from mika.contracts import self_ as self_c
from mika.kernel.text import fold
from mika.runtime.operations import audit
from mika.vocab.access import PERSON, REPLIES, SOURCE_WORDS, SOURCE_WORDS_OTHER, Canal, canal_key
from mika.vocab.canals import CanalRule, Canals, CanalTable

#: ce que la propriétaire d'un compte règle de la règle de son canal (ADR 0207), ligne par ligne et par défaut :
#: préparer d'elle-même, comment ça part — qui, quand et les lignes elles-mêmes restent à la console
RULE_FIELDS = ("prepare", "reply")
#: comment ça part : seule, ton accord, brouillon (le courrier n'en a pas : ton accord), non
REPLY_CODES = tuple(code for code, _words in REPLIES)


def owner_for(call: Call) -> str:
    """À qui est ce qu'elle branche : « à toi » pour une de ses propriétaires, sinon à son nom."""
    return "" if call.me.owner else PERSON + call.me.person


async def rejournal(call: Call) -> None:
    if call.api.reconfigure is not None:
        await call.api.reconfigure()


def fresh_key(text: str, taken: set[str], rule: re.Pattern[str]) -> str:
    """Une clé neuve (minuscules, chiffres, - ou _) tirée d'un nom ou d'une adresse, suivie d'un suffixe tiré au
    hasard et libre parmi ``taken`` : une clé ne sert jamais deux fois, car le courrier gardé, ses pièces et ce
    qu'elle en sait restent rangés sous la clé d'une boîte retirée (une boîte neuve ne les rouvre pas). ``rule`` : la
    règle des clés de qui l'appelle (``ports.mail.ACCOUNT_KEY``, ``ports.teams.ACCOUNT_KEY``)."""
    base = re.sub(r"[^a-z0-9_-]+", "-", fold(text.split("@", 1)[0])).strip("-_")[:30]
    base = base if base and rule.fullmatch(base) else "boite"
    while True:
        key = f"{base}-{secrets.token_hex(3)}"
        if key not in taken:
            return key


def posted_values(call: Call, allowed: tuple[str, ...]) -> dict[str, Any]:
    raw = call.data.get("values")
    if not isinstance(raw, dict):
        raise Denied(400, "« values » : un objet.")
    unknown = sorted(set(raw) - set(allowed))
    if unknown:
        raise Denied(400, f"« {unknown[0]} » ne se règle pas ici.")
    return dict(raw)


# ── son compte ──


async def account_name(call: Call) -> dict[str, Any]:
    name = " ".join(call.arg("name", limit=120).split())
    if not name:
        raise Denied(400, "Un nom.", {"name": "valeur requise"})
    problem = await call.api.accounts.update(call.me.account.id, full_name=name)
    if problem:
        raise Denied(400, problem)
    await audit(call.kernel, "moi.nom", by=call.me.handle, subject_kind="compte", subject=call.me.account.username)
    return {"ok": True, "message": "C'est ton nom, maintenant : elle t'appellera ainsi."}


async def account_password(call: Call) -> dict[str, Any]:
    """Changer son mot de passe : l'ancien d'abord. Toutes ses sessions se ferment, et les jetons obtenus par
    l'ancien mot de passe tombent : on se reconnecte."""
    me, throttle = call.me, call.api.password_tries
    tries = f"compte:{me.account.id}"
    if throttle.blocked(tries):
        raise Denied(429, "Trop d'essais : attends une minute avant de réessayer.")
    throttle.fail(tries)  # compté d'avance : des essais lancés ensemble ne passent pas tous avant le premier échec
    if await call.api.accounts.verify(me.account.username, call.arg("current", limit=200)) is None:
        raise Denied(400, "Ce n'est pas ton mot de passe actuel.", {"current": "mot de passe incorrect"})
    throttle.forgive(tries)
    problem = await call.api.accounts.update(me.account.id, password=call.arg("password", limit=200))
    if problem:
        raise Denied(400, problem, {"password": problem})
    await audit(call.kernel, "moi.mot_de_passe", by=me.handle, subject_kind="compte", subject=me.account.username)
    return {"ok": True, "message": "Mot de passe changé : reconnecte-toi.", "relogin": True}


# ── comment part ce qu'elle prépare (ADR 0207) ──


def _canal_table(canals: Canals, canal: str) -> tuple[CanalTable, bool, bool]:
    """Le tableau qui vaut pour un de ses comptes (``courrier:<clé>``, ``teams:<clé>``), tel que le courrier et Teams
    le lisent (``mail_verdict``, ``teams_verdict``) : le sien s'il est réglé, sinon celui de tout son canal, sinon le
    minimum vital ; s'il est à lui (``set``) ; s'il est celui de tout son canal, réglé dans la console (``common``)."""
    kind, key = canal_key(canal)
    table, used = canals.table_of(Canal(kind, key))
    return table, used == canal, used == kind and kind in canals.tables


def _version(table: CanalTable) -> str:
    """L'empreinte d'un tableau : ce qu'on règle d'ici vaut pour le tableau qu'on a lu, pas pour un autre."""
    said = json.dumps(table.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(said.encode()).hexdigest()[:16]


def rules_json(call: Call, canal: str) -> dict[str, Any]:
    """La règle d'un de ses comptes, en mots comme dans la matrice (``app/me/rights.py``) : ses lignes (qui, quand,
    préparer d'elle-même, comment ça part), sa ligne par défaut, et son empreinte (``version``)."""
    table, own, common = _canal_table(settings_of(call).canals(), canal)
    frame = call.frame
    name, her = rights_me.person_name(frame), self_c.name_of(frame.get(self_c.PERSONA))
    sources = SOURCE_WORDS if call.me.owner else SOURCE_WORDS_OTHER
    return {"canal": canal, "set": own, "common": common, "version": _version(table),
            "lines": [rights_me.rule_json(a, name, her, sources) for a in table.lines],
            "default": rights_me.rule_json(table.default, name, her, sources)}


def _ruled(found: AccountsPart, canal: str, line: CanalRule, sent: Any, n: int) -> CanalRule:
    """Une ligne de la règle, avec ce que sa propriétaire en règle d'ici : préparer d'elle-même, comment ça part. Un
    canal sans brouillon que tu envoies toi-même (``AccountsPart.no_drafts`` : le courrier, que la console grise) : une
    ligne ne le devient pas d'ici."""
    where = f"Ligne {n}" if n else "La ligne par défaut"
    if not isinstance(sent, dict) or set(sent) - set(RULE_FIELDS):
        raise Denied(400, f"{where} : « prepare » et « reply » seulement.")
    prepare, reply = sent.get("prepare", line.prepare), sent.get("reply", line.reply)
    if not isinstance(prepare, bool) or reply not in REPLY_CODES:
        raise Denied(400, f"{where} : « prepare » vrai ou faux ; « reply » seule, accord, brouillon ou non.")
    if found.no_drafts and reply == "brouillon" and line.reply != "brouillon":
        raise Denied(400, f"{where} : {found.no_drafts}")
    return line.model_copy(update={"prepare": prepare, "reply": reply, "canal": (canal,)})


async def rules_save(call: Call) -> dict[str, Any]:
    """Comment part ce qu'elle prépare depuis un de ses comptes (ADR 0207) : pour chaque ligne de sa règle et pour la
    ligne par défaut, préparer d'elle-même et comment ça part. Le reste (qui, quand, ses lignes) reste à la console ;
    la règle lue (``version``) doit être celle d'aujourd'hui (409 sinon). Enregistrée, la règle est celle du compte :
    celle de tout le canal, réglée dans la console, ne vaut plus pour lui. Un compte est à elle selon son canal
    (``AccountsPart.owned``), qui dit aussi s'il a des brouillons (``no_drafts``) et le geste qui le règle (``audit``,
    ``subject_kind``)."""
    canal = call.arg("canal", limit=60)
    kind, key = canal_key(canal)
    found = channels.parts().get(kind)
    if found is None or not key:
        yours = either(f"{p.canal}:<{p.yours}>" for p in channels.parts().values())
        raise Denied(400, f"« canal » : {yours}.")
    found.owned(call, key)
    lines, default = call.data.get("lines"), call.data.get("default")
    if not isinstance(lines, list) or not isinstance(default, dict):
        raise Denied(400, "« lines » : une entrée par ligne de la règle ; « default » : sa ligne par défaut.")
    settings = settings_of(call)
    async with settings.writing:  # relue puis réécrite d'un seul tenant, avec ce qui en dérive (``reconfigure``)
        table, _own, _common = _canal_table(settings.canals(), canal)
        if call.arg("version", limit=64) != _version(table) or len(lines) != len(table.lines):
            raise Denied(409, "Cette règle vient d'être réglée ailleurs : rouvre-la, puis recommence.")
        rows = tuple(_ruled(found, canal, line, sent, n)
                     for n, (line, sent) in enumerate(zip(table.lines, lines, strict=True), start=1))
        await settings.save_canal(canal, CanalTable(lines=rows, default=_ruled(found, canal, table.default, default, 0)))
        await rejournal(call)
    # la règle est un réglage du compte : son geste est celui qui le règle, que son canal dit
    await audit(call.kernel, found.audit, by=call.me.handle, subject_kind=found.subject_kind, subject=key)
    return {"ok": True, "message": "Règle d'envoi enregistrée."}


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    return [r("/account/name", account_name, write=True), r("/account/password", account_password, write=True),
            r("/rules", rules_save, write=True)]
