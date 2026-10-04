"""Ses outils pour envoyer un fichier à la personne à qui elle parle (ADR 0062).

Offerts seulement en tête-à-tête, à quelqu'un qui a un compte (authentifié), jamais dans un salon : un fichier
part avec son message, vers l'application de la personne. Trois appels au plus par épisode, un quota par jour et
par personne ; le résultat lui dit d'annoncer en une phrase ce qu'elle envoie, sans le recopier.

- ``share_text`` : un texte qu'elle écrit maintenant (une liste, une note, du code, un tableau) ;
- ``project_files`` : ce qu'elle peut envoyer de ses projets (les numéros ne se disent jamais en conversation) ;
- ``share_project_file`` : un fichier de l'atelier d'un projet — seulement si la personne en a les droits (elle
  parle en propriétaire, ou c'est elle qui l'a confié) et peut entendre ce dont il parle.

Le fichier a un identifiant **déterministe** (la portée de ses écritures, l'appel, la personne) : une réponse
supplantée puis recomposée qui refait le même appel retombe sur le même fichier, sans doublon.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import projects as projects_c
from mika.contracts import shares as c
from mika.faculties.shares.faculty import MIB, PORT, SHARES, params_of
from mika.kernel.codec import digest
from mika.kernel.events import Content
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Audience, Frame
from mika.kernel.guards import Superseded
from mika.kernel.inspect import num_fr
from mika.ports.workshop import OutsideWorkshop
from mika.vocab.episodes import CONVERSATIONAL, is_work_target
from mika.vocab.privacy import ChannelTrust, Sensitivity, hearable

BUNDLE = "shares"
SHARE_TEXT, PROJECT_FILES, SHARE_PROJECT_FILE = "share_text", "project_files", "share_project_file"
SENDING = frozenset({SHARE_TEXT, SHARE_PROJECT_FILE})
#: au plus tant de fichiers par épisode (les deux outils ensemble)
PER_EPISODE = 3
#: un texte qu'elle écrit, une fois encodé
TEXT_MAX_BYTES = 512 * 1024
NAME_MAX = 80
#: une arborescence montrée : au plus tant d'entrées
TREE_SHOWN = 60

#: ce qu'un texte écrit peut être (l'extension dit la sorte ; sans extension : du texte brut)
TEXT_TYPES = {
    ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv", ".tsv": "text/tab-separated-values",
    ".json": "application/json", ".yaml": "application/yaml", ".yml": "application/yaml",
    ".toml": "application/toml", ".ini": "text/plain", ".log": "text/plain", ".py": "text/x-python",
    ".js": "text/javascript", ".ts": "text/x-typescript", ".kt": "text/x-kotlin", ".java": "text/x-java",
    ".c": "text/x-c", ".h": "text/x-c", ".cpp": "text/x-c++", ".rs": "text/x-rust", ".go": "text/x-go",
    ".sh": "application/x-sh", ".sql": "application/sql", ".css": "text/css", ".ics": "text/calendar",
    ".vcf": "text/vcard", ".srt": "application/x-subrip",
}
#: la sorte d'un fichier de projet, par une table fixe (jamais deviné par le contenu ni par le système) ; une
#: extension inconnue : ``application/octet-stream``
PROJECT_TYPES = {
    **TEXT_TYPES, ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif", ".pdf": "application/pdf", ".svg": "image/svg+xml", ".html": "text/html",
    ".htm": "text/html", ".xml": "application/xml", ".zip": "application/zip", ".mp3": "audio/mpeg",
    ".wav": "audio/wav", ".ogg": "audio/ogg", ".mp4": "video/mp4",
}
OCTETS = "application/octet-stream"
#: ce qui se montre comme une image (une vignette dans l'application)
IMAGES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})

_FORBIDDEN = re.compile(r'[<>:"/\\|?*]')
_EXTENSION = re.compile(r"^[a-z0-9]{1,8}$")

NOT_HERE = ("Tu ne peux envoyer un fichier qu'en tête-à-tête, à quelqu'un qui a un compte : ici, garde-le pour ton "
            "message.")
NO_STORE = "Tu ne peux pas envoyer de fichier ici (rien pour les garder)."
NO_PROJECT = "Ce projet n'est pas à partager avec cette personne."
SUGGEST = "choisis .md, .txt, .csv, .json…"

SHARES.bundle(BUNDLE, "envoyer un fichier à la personne : un texte que tu écris (liste, note, code, tableau) ou un "
                      "fichier d'un de tes projets")


def offered(audience: Any) -> bool:
    """Seulement en tête-à-tête, à quelqu'un qui a un compte : jamais dans un salon, jamais à un inconnu."""
    return bool(getattr(audience, "persons", ())) and not audience.public \
        and audience.trust == ChannelTrust.AUTHENTICATED.value


def clean_name(raw: Any) -> str:
    """Un nom de fichier sans danger : normalisé (NFC), sans dossier, sans caractère de contrôle ni ``<>:"/\\|?*``,
    sans point ni espace aux bords."""
    text = unicodedata.normalize("NFC", str(raw or ""))
    text = re.split(r"[/\\]", text)[-1]
    text = "".join(ch for ch in text if unicodedata.category(ch) not in ("Cc", "Cf", "Cs"))
    text = _FORBIDDEN.sub("", text)
    return " ".join(text.split()).strip(" .")


def _fit(stem: str, ext: str) -> str:
    """``stem.ext`` en ``NAME_MAX`` caractères au plus : le début du nom se coupe, jamais l'extension."""
    room = NAME_MAX - len(ext) - 1
    return f"{(stem[:room].rstrip(' .') or 'fichier')}.{ext}"


def text_name(raw: Any) -> tuple[str, str] | None:
    """(nom, sorte) d'un texte écrit ; ``None`` pour une extension qui n'est pas du texte. Sans extension : ``.txt``."""
    name = clean_name(raw) or "fichier"
    stem, dot, ext = name.rpartition(".")
    ext = ext.lower()
    if not dot or not stem or not _EXTENSION.fullmatch(ext):
        return _fit(name, "txt"), TEXT_TYPES[".txt"]
    mime = TEXT_TYPES.get(f".{ext}")
    return (_fit(stem, ext), mime) if mime else None


def project_name(path: str) -> tuple[str, str, str]:
    """(nom, sorte, genre) d'un fichier de l'atelier, par son extension (table fixe)."""
    name = clean_name(path) or "fichier"
    stem, dot, ext = name.rpartition(".")
    ext = ext.lower()
    if dot and stem and _EXTENSION.fullmatch(ext):
        name = _fit(stem, ext)
        mime = PROJECT_TYPES.get(f".{ext}", OCTETS)
    else:
        name = name[:NAME_MAX]
        mime = OCTETS
    return name, mime, c.IMAGE if mime in IMAGES else c.FILE


def size_words(n: int) -> str:
    return f"{n} o" if n < 1024 else f"{num_fr(n / 1024, 1)} Ko" if n < MIB else f"{num_fr(n / MIB, 1)} Mo"


# ── Ce qui est permis ─────────────────────────────────────────────────────


def _recipient(ctx: Any) -> tuple[str, str] | ToolResult:
    """(adresse, personne) à qui ira le fichier — ou le refus, dit."""
    ep, aud = ctx.frame.episode, ctx.frame.audience
    target = ep.target if ep is not None else None
    if not target or is_work_target(target) or aud is None or not offered(aud) or target not in aud.persons:
        return ToolResult(ok=False, content=NOT_HERE)
    return target, ctx.frame.get(identity_c.PERSON(target))


def _budget(ctx: Any, target: str) -> ToolResult | None:
    """Le plafond de l'épisode, puis celui du jour (par personne)."""
    done = sum(1 for name, ok in ctx.calls if name in SENDING and ok)
    if done >= PER_EPISODE:
        return ToolResult(ok=False, content=f"Tu as déjà préparé {done} fichiers pour ce message : c'est assez.")
    per_day = params_of(ctx.frame).per_day
    today = ctx.frame.get(c.SENT_TODAY(target))
    if today >= per_day:
        return ToolResult(ok=False, content=(
            f"Tu lui as déjà envoyé {today} fichier(s) aujourd'hui : garde la suite pour ton message, ou pour plus "
            "tard." if per_day else "Tu n'envoies pas de fichier en ce moment : garde-le pour ton message."))
    return None


def may_share(v: projects_c.ProjectView, person: str, aud: Audience) -> bool:
    """Un projet dont elle peut envoyer les fichiers à qui l'écoute : vivant, la personne en a les droits (elle parle
    en propriétaire, ou c'est elle qui l'a confié) et peut entendre ce dont il parle (ce qui s'écrit dans un projet
    est au moins personnel)."""
    if v.status not in (projects_c.ACTIVE, projects_c.PAUSED):
        return False
    confided = v.authority == projects_c.USER and v.owner is not None and v.owner == person
    if not (aud.owner or confided):
        return False
    return hearable(v.about, v.written, person, aud.level, aud.witness_level, aud.private_ok,
                    tied_level=aud.tied_level, ties=aud.ties)


def _visible(frame: Frame, person: str) -> list[projects_c.ProjectView]:
    aud = frame.audience
    if aud is None:
        return []
    return [v for v in frame.get(projects_c.LIVE) if may_share(v, person, aud)]


def _file_id(ctx: Any, target: str) -> str:
    """Le même appel, dans la même portée (le tour d'une réponse, recomposée ou non), vers la même personne : le
    même fichier."""
    return digest(("partage", ctx.dedupe_scope or ctx.episode_id, ctx.call_key or ctx.call_id, target))


async def _send(ctx: Any, target: str, person: str, *, name: str, mime: str, data: bytes, kind: str, origin: str,
                level: int, project: int | None = None, path: str | None = None,
                about: tuple[str, ...] = ()) -> ToolResult:
    """Les octets d'abord (hors du journal), puis l'événement ; une écriture supplantée efface ce qu'elle a posé."""
    store = ctx.ports.get(PORT)
    if store is None:
        return ToolResult(ok=False, content=NO_STORE)
    file = _file_id(ctx, target)
    concerned = tuple(dict.fromkeys(a for a in (*about, person) if a and a != target))
    await store.put(file, data, subjects=(target, *concerned))
    draft = c.SHARED.draft(
        file=file, target=target, name=Content.of(name, level=level), mime=mime, size=len(data),
        digest=hashlib.sha256(data).hexdigest(), kind=kind, origin=origin, project=project,
        path=Content.of(path, level=level) if path else None, about=concerned,
        dedupe_key=f"partage:{file}")
    try:
        await ctx.emit(draft)
    except Superseded:
        # rien n'a été écrit (un même fichier déjà journalisé aurait été dédoublonné avant la garde) : ses octets
        # ne restent pas orphelins
        await store.delete((file,))
        return ToolResult(ok=False, content="La conversation a bougé entre-temps : ce fichier n'est pas parti.")
    return ToolResult(content=f"Prêt à partir avec ton message : « {name} » ({size_words(len(data))}). Dis en une "
                              "phrase ce que tu envoies ; ne recopie pas le contenu.", attach=(file,))


# ── Écrire un texte et l'envoyer ──────────────────────────────────────────


class TextArgs(BaseModel):
    name: str = Field(description="Le nom du fichier, avec son extension : courses.md, notes.txt, budget.csv, "
                                  "script.py… (sans extension : un .txt)")
    content: str = Field(description="Tout le contenu du fichier, en texte.")


@SHARES.tool(SHARE_TEXT, description="Envoyer à la personne un fichier texte que tu écris maintenant (une liste, une "
             "note, du code, un tableau) : il part avec ton message, en pièce jointe. Seulement quand un fichier lui "
             "sert vraiment (quelque chose à garder ou à ouvrir ailleurs, trop long pour un message) : une réponse "
             "ordinaire reste dans ton message. Dis en une phrase ce que tu envoies.",
             args=TextArgs, bundle=BUNDLE, episodes=CONVERSATIONAL, max_calls_per_episode=PER_EPISODE, when=offered)
async def share_text(args: TextArgs, ctx: Any) -> Any:
    who = _recipient(ctx)
    if isinstance(who, ToolResult):
        return who
    target, person = who
    named = text_name(args.name)
    if named is None:
        return ToolResult(ok=False, content=f"Ce n'est pas un nom de fichier texte : {SUGGEST}")
    name, mime = named
    p = params_of(ctx.frame)
    content = args.content
    if not content.strip():
        return ToolResult(ok=False, content="Un fichier vide n'a rien à envoyer.")
    if "\x00" in content:
        return ToolResult(ok=False, content="Ce contenu n'est pas du texte.")
    if len(content) > p.text_max_chars:
        return ToolResult(ok=False, content=f"Trop long pour un fichier : {p.text_max_chars} caractères au plus.")
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError:
        return ToolResult(ok=False, content="Ce contenu n'est pas du texte lisible.")
    if len(data) > TEXT_MAX_BYTES:
        return ToolResult(ok=False, content=f"Trop lourd pour un fichier : {TEXT_MAX_BYTES // 1024} Kio au plus.")
    refused = _budget(ctx, target)
    if refused is not None:
        return refused
    return await _send(ctx, target, person, name=name, mime=mime, data=data, kind=c.FILE, origin=c.WRITTEN,
                       level=int(Sensitivity.PERSONAL))


# ── Ses projets ───────────────────────────────────────────────────────────


class FilesArgs(BaseModel):
    project: int = Field(0, description="Le numéro du projet (0 : la liste de tes projets dont tu peux envoyer "
                                        "des fichiers).")
    path: str = Field("", description="Un dossier du projet (vide : tout le projet).")


def _titles(ctx: Any, views: list[projects_c.ProjectView]) -> dict[str, str]:
    store = ctx.ports.get("store")
    refs = [v.title_ref for v in views if v.title_ref]
    return store.content(refs) if store is not None and refs else {}


def _entries(tree: list[str]) -> list[str]:
    return [line for line in tree if not line.startswith("[")]


@SHARES.tool(PROJECT_FILES, description="Voir ce que tu peux envoyer de tes projets à la personne : sans numéro, "
             "tes projets (avec leur numéro) ; avec un numéro (et un dossier), leurs fichiers.",
             args=FilesArgs, bundle=BUNDLE, episodes=CONVERSATIONAL, max_calls_per_episode=4, when=offered)
async def project_files(args: FilesArgs, ctx: Any) -> Any:
    who = _recipient(ctx)
    if isinstance(who, ToolResult):
        return who
    _target, person = who
    atelier = ctx.ports.get("workshop")
    if atelier is None:
        return ToolResult(ok=False, content="Les ateliers de tes projets ne sont pas disponibles ici.")
    visible = _visible(ctx.frame, person)
    titles = _titles(ctx, visible)
    if not args.project:
        if not visible:
            return ToolResult(content="Aucun de tes projets n'a de fichier à lui envoyer.")
        lines = []
        for v in visible:
            count = 0
            if atelier.exists(v.id):
                try:
                    count = len(_entries(await atelier.tree(v.id)))
                except (OutsideWorkshop, OSError, ValueError):
                    count = 0
            lines.append(f"- n° {v.id} « {titles.get(v.title_ref, '…')} » — {count} fichier(s)")
        return ToolResult(content="Ses projets dont tu peux lui envoyer des fichiers :\n" + "\n".join(lines))
    v = next((x for x in visible if x.id == args.project), None)
    if v is None:
        return ToolResult(ok=False, content=NO_PROJECT)
    if not atelier.exists(v.id):
        return ToolResult(content=f"Le projet « {titles.get(v.title_ref, '…')} » n'a encore aucun fichier.")
    try:
        tree = _entries(await atelier.tree(v.id, args.path.strip() or "."))
    except (OutsideWorkshop, FileNotFoundError, OSError, ValueError) as exc:
        return ToolResult(ok=False, content=f"Ce dossier ne se lit pas : {exc}")
    shown = tree[:TREE_SHOWN]
    more = f"\n[… et {len(tree) - len(shown)} de plus : ouvre un sous-dossier]" if len(tree) > len(shown) else ""
    body = "\n".join(f"- {line}" for line in shown) or "(dossier vide)"
    return ToolResult(content=f"Projet n° {v.id} « {titles.get(v.title_ref, '…')} » :\n{body}{more}")


class ProjectFileArgs(BaseModel):
    project: int = Field(description="Le numéro du projet (vu avec project_files).")
    path: str = Field(description="Le chemin du fichier dans le projet (vu avec project_files).")


@SHARES.tool(SHARE_PROJECT_FILE, description="Envoyer à la personne un fichier de l'atelier d'un de tes projets (son "
             "numéro et son chemin, vus avec project_files) : il part avec ton message, en pièce jointe. Dis en une "
             "phrase ce que tu envoies.",
             args=ProjectFileArgs, bundle=BUNDLE, episodes=CONVERSATIONAL, max_calls_per_episode=PER_EPISODE,
             when=offered)
async def share_project_file(args: ProjectFileArgs, ctx: Any) -> Any:
    who = _recipient(ctx)
    if isinstance(who, ToolResult):
        return who
    target, person = who
    atelier = ctx.ports.get("workshop")
    v = next((x for x in _visible(ctx.frame, person) if x.id == args.project), None)
    if v is None:
        return ToolResult(ok=False, content=NO_PROJECT)
    path = args.path.strip().strip("/")
    parts = [x for x in path.split("/") if x]
    if not parts or any(x == ".." for x in parts):
        return ToolResult(ok=False, content="Donne le chemin d'un fichier du projet (vu avec project_files).")
    if any(x.startswith(".") for x in parts):
        return ToolResult(ok=False, content="Un fichier caché de l'atelier ne s'envoie pas.")
    if atelier is None or not atelier.exists(v.id):
        return ToolResult(ok=False, content="Ce fichier n'est pas dans l'atelier du projet.")
    limit = params_of(ctx.frame).project_max_mb * MIB
    try:
        data = await atelier.read_bytes(v.id, path, limit + 1)
    except (OutsideWorkshop, FileNotFoundError, IsADirectoryError, OSError, ValueError):
        return ToolResult(ok=False, content="Ce fichier n'est pas dans l'atelier du projet.")
    if len(data) > limit:
        return ToolResult(ok=False, content=f"Trop gros pour être envoyé : {limit // MIB} Mio au plus.")
    if not data:
        return ToolResult(ok=False, content="Ce fichier est vide : rien à envoyer.")
    refused = _budget(ctx, target)
    if refused is not None:
        return refused
    name, mime, kind = project_name(parts[-1])
    return await _send(ctx, target, person, name=name, mime=mime, data=data, kind=kind, origin=c.PROJECT,
                       level=v.written, project=v.id, path="/".join(parts), about=v.about)
