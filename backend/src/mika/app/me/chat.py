"""Les fichiers du chat (ADR 0312) : tout ce que la personne et Mika se sont envoyé dans sa conversation — ses pièces,
qui sont à elle (ADR 0215), et les fichiers que Mika lui a envoyés (ADR 0062) —, à chercher et à reprendre page par
page, pas seulement dans les messages chargés à l'écran.

Le fil est celui que le chat relit (``transcript.with_files``, la règle de ``strand_history``) : le fil avec elle, ou
un fil de travail en mode pro. Ce qui se télécharge est ce que ``GET /files/<id>`` rend à ce compte : sa pièce une
fois gardée, ou un fichier de Mika parti vers une adresse dont il peut relire le fil ; le reste se dit, avec sa raison,
sans adresse. Le contrat : ``docs/protocole-moi.md`` § 14.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from starlette.routing import Route

from mika.adapters.web.protocol import FILES_PATH, sanitize_filename
from mika.app.me.api import Call, Denied, MeApiBase
from mika.app.me.common import millis
from mika.contracts import attachments as attachments_c
from mika.contracts import identity as identity_c
from mika.faculties import attachments, shares, transcript
from mika.kernel.text import fold
from mika.ports.shares import valid_id

__all__ = ["REASONS", "SORTES", "ChatFile", "page_of", "routes", "sorte_of"]

#: les sortes que l'écran trie, dans l'ordre de ses filtres
SORTES = ("image", "pdf", "texte", "tableau", "autre")
#: qui l'a envoyé
FROM = ("toi", "mika")
#: une page, par défaut et au plus
PER_PAGE, PER_MAX = 12, 60
#: les messages qui portent quelque chose (un fichier, une petite bulle d'elle) relus au plus, du plus récent au plus
#: ancien : au-delà, les plus anciens ne se listent pas
SCANNED = 5000
#: pourquoi un fichier ne se télécharge pas : retiré (trop vieux, la place, une opératrice), ses octets perdus ou
#: introuvables, jamais gardé. Une pièce gardée au bord se télécharge sans attendre d'être lue de près.
REASONS = ("retention", "budget", "operator", "missing", "unkept")

_TABLE_MIMES = frozenset({"text/csv", "text/tab-separated-values"})
_TABLE_EXTS = frozenset({"csv", "tsv"})
_TEXT_MIMES = frozenset({"application/json", "application/xml", "application/x-yaml", "application/yaml"})
_TEXT_EXTS = frozenset({"txt", "md", "markdown", "log", "json", "yaml", "yml", "xml", "ini", "toml"})


def sorte_of(name: str, mime: str, kind: str = "") -> str:
    """La sorte d'un fichier pour l'écran, par sa sorte gardée, sa sorte MIME, puis son extension : ``image``, ``pdf``,
    ``texte``, ``tableau`` (CSV), ``autre``."""
    base = mime.split(";", 1)[0].strip().lower()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if kind == "image" or base.startswith("image/"):
        return "image"
    if base == "application/pdf" or ext == "pdf":
        return "pdf"
    if base in _TABLE_MIMES or ext in _TABLE_EXTS:
        return "tableau"
    if base.startswith("text/") or base in _TEXT_MIMES or ext in _TEXT_EXTS:
        return "texte"
    return "autre"


@dataclass(frozen=True, slots=True)
class ChatFile:
    """Un fichier de la conversation, tel que l'écran le montre. ``key`` : sa clé dans la liste, son message et sa
    place (la même pièce renvoyée a le même ``id`` dans deux messages) ; ``index`` : sa place dans son message, à partir
    de 0."""

    key: str
    id: str
    name: str
    mime: str
    size: int
    sorte: str
    sender: str
    at: int
    message: int
    index: int
    available: bool
    reason: str

    def item(self) -> dict[str, Any]:
        out: dict[str, Any] = {"key": self.key, "id": self.id, "name": self.name, "mime": self.mime, "size": self.size,
                               "sorte": self.sorte, "from": self.sender, "at": self.at, "message": self.message,
                               "index": self.index, "available": self.available}
        if self.available:
            out["url"] = f"{FILES_PATH}{self.id}"
        else:
            out["reason"] = self.reason
        return out


def _items(raw: Any) -> list[dict[str, Any]]:
    """Les entrées d'une colonne ``attachments`` (un JSON) ; illisible : aucune."""
    try:
        got = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [a for a in got if isinstance(a, dict)] if isinstance(got, list) else []


@dataclass(frozen=True, slots=True)
class _Waiting:
    """Une pièce gardée au bord, pas encore lue de près : elle se télécharge déjà."""

    name: str
    mime: str
    handle: str
    size: int = 0
    expired_at: int | None = None
    reason: str | None = None
    stored: bool = True


def _gone_reason(reason: str | None) -> str:
    return reason if reason in ("retention", "budget", "operator") else "missing"


def files_of(store: Any, frame: Any, handle: str, strand: str, message: int | None = None) -> list[ChatFile]:
    """Tous les fichiers d'un fil de cette adresse, du plus récent au plus ancien (dans un message, dans son ordre) ;
    ``message`` : ceux de ce seul message."""
    lines = transcript.with_files(store, handle, strand, SCANNED, message)
    keys: list[str] = []
    ids: list[str] = []
    for line in lines:
        for a in _items(line["attachments"]):
            key = a.get("file") if line["role"] == "user" else a.get("id")
            if isinstance(key, str) and valid_id(key):
                (keys if line["role"] == "user" else ids).append(key)
    mine: dict[str, Any] = {r.id: r for r in attachments.rows(store, keys)}
    # une pièce gardée au bord, pas encore lue de près, se reprend déjà (sa taille n'est pas encore connue)
    state = frame.root.slices.get(attachments_c.OWNER)
    for key in keys:
        if key not in mine and (p := attachments.waiting(state, key, handle)) is not None:
            mine[key] = _Waiting(name=p.name, mime=p.mime, handle=p.handle)
    hers = {r.id: r for r in shares.rows(store, ids)}
    # la règle de ``GET /files/<id>`` : un fichier parti vers une adresse dont ce compte relit le fil
    readable = set(frame.get(identity_c.THREAD(handle)) or ())
    out: list[ChatFile] = []
    for line in lines:
        seq, at = int(line["id"]), millis(int(line["at"]))
        if line["role"] == "user":
            for i, a in enumerate(_items(line["attachments"])):
                out.append(_piece(a, i, seq, at, mine, handle))
        else:
            for i, a in enumerate(_items(line["attachments"])):
                got = _hers(a, i, seq, at, hers, readable)
                if got is not None:
                    out.append(got)
    return out


def _piece(a: dict[str, Any], i: int, seq: int, at: int, mine: dict[str, Any], handle: str) -> ChatFile:
    """Une pièce de la personne : à elle seule ; gardée, lue, retirée, ou jamais gardée."""
    key = a.get("file") if isinstance(a.get("file"), str) and valid_id(a["file"]) else ""
    r = mine.get(key) if key else None
    if r is not None and r.handle != handle:
        r = None  # une pièce d'une autre adresse ne se rend pas, ni ne se décrit (le même 404 que /files)
    # le nom de ce message : la même pièce renvoyée sous un autre nom garde, ici, celui qu'on lui a donné
    name = sanitize_filename(a.get("name") or (r.name if r is not None else ""))
    mime = str(r.mime if r is not None else a.get("mime") or "")[:100]
    kind = str(a.get("kind") or "")
    if not key:
        reason, ok = "unkept", False
    elif r is None:
        reason, ok = "missing", False  # retirée avant d'être lue, ou oubliée
    elif r.expired_at is not None:
        reason, ok = _gone_reason(r.reason), False
    elif not r.stored:
        reason, ok = "unkept", False
    else:
        reason, ok = "", True
    return ChatFile(key=f"{seq}-{i}", id=key, name=name, mime=mime, size=int(r.size) if r is not None else 0,
                    sorte=sorte_of(name, mime, kind), sender="toi", at=at, message=seq, index=i, available=ok,
                    reason=reason)


def _hers(a: dict[str, Any], i: int, seq: int, at: int, hers: dict[str, Any],
          readable: set[str]) -> ChatFile | None:
    """Un fichier qu'elle a envoyé : inconnu (oublié), rien ; retiré, ou parti vers une adresse dont ce compte ne relit
    plus le fil, sans adresse."""
    key = a.get("id")
    r = hers.get(key) if isinstance(key, str) else None
    if r is None:
        return None
    name = sanitize_filename(r.name)
    if r.gone:
        reason, ok = _gone_reason(r.reason), False
    elif not r.sent or r.person not in readable:
        reason, ok = "missing", False
    else:
        reason, ok = "", True
    return ChatFile(key=f"{seq}-{i}", id=r.id, name=name, mime=str(r.mime or "")[:100], size=int(r.size),
                    sorte=sorte_of(name, r.mime or "", r.kind), sender="mika", at=at, message=seq, index=i,
                    available=ok, reason=reason)


def _matches(f: ChatFile, words: Sequence[str]) -> bool:
    name = fold(f.name)
    return all(w in name for w in words)


def page_of(files: Iterable[ChatFile], *, q: str = "", sorte: str = "", sender: str = "", page: int = 1,
            per: int = PER_PAGE) -> dict[str, Any]:
    """Une page de ces fichiers : ceux dont le nom contient chaque mot de ``q`` (sans casse ni accents), de cette
    sorte, de cet envoyeur. ``counts`` compte chaque sorte parmi ceux que ``q`` et l'envoyeur gardent (``""`` : toutes)
    ; ``unavailable``, ceux de la sélection qui ne se téléchargent plus."""
    words = [w for w in fold(q).split() if w]
    kept = [f for f in files if (not sender or f.sender == sender) and _matches(f, words)]
    counts = {s: 0 for s in ("", *SORTES)}
    for f in kept:
        counts[""] += 1
        counts[f.sorte] += 1
    chosen = [f for f in kept if not sorte or f.sorte == sorte]
    pages = max(1, -(-len(chosen) // per))
    page = max(1, min(page, pages))
    start = (page - 1) * per
    return {"items": [f.item() for f in chosen[start:start + per]], "total": len(chosen), "page": page,
            "pages": pages, "per": per, "counts": counts,
            "unavailable": sum(1 for f in chosen if not f.available)}


async def chat_files(req: Call) -> dict[str, Any]:
    """``GET /api/moi/chat/fichiers`` : une page des fichiers de la conversation, ou ceux d'un message (``message``)."""
    sorte, sender = req.arg("sorte", limit=20), req.arg("de", limit=10)
    if sorte and sorte not in SORTES:
        raise Denied(400, "« sorte » : image, pdf, texte, tableau ou autre.", {"sorte": "inconnue"})
    if sender and sender not in FROM:
        raise Denied(400, "« de » : toi ou mika.", {"de": "inconnu"})
    strand = req.arg("fil", limit=64)
    message = req.arg("message", limit=20)
    if message:
        if not (message.isascii() and message.isdigit()):
            raise Denied(400, "« message » : un numéro.", {"message": "un numéro"})
        return {"items": [f.item() for f in files_of(req.port("store"), req.frame, req.me.handle, strand, int(message))]}
    files = files_of(req.port("store"), req.frame, req.me.handle, strand)
    return page_of(files, q=req.arg("q", limit=200), sorte=sorte, sender=sender,
                   page=req.number("page", 1, 1, 100_000), per=req.number("par", PER_PAGE, 1, PER_MAX))


def routes(api: MeApiBase) -> list[Route]:
    return [api.route("/chat/fichiers", chat_files)]
