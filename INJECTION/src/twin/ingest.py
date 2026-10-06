"""Ingérer ``brut/`` : chaque fichier va au lecteur le plus sûr de lui, puis dans le corpus.

Relancer est sans danger : un fichier inchangé (même empreinte, même lecteur, même
version) est sauté ; un fichier modifié remplace ce qu'il avait apporté ; des exports
qui se chevauchent ne créent pas de doublons (empreinte des messages). Ce que personne
ne reconnaît est listé dans ``travail/inconnus.txt`` pour ``/jumeau-nouveau-format``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from twin.corpus import Corpus, SourceStats, file_sha256
from twin.readers import ReadContext, Reader, all_readers, pick

#: fichiers jamais lus (systèmes, médias : leur contenu n'est pas du texte)
SKIP_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".mp4", ".mov", ".avi", ".mp3", ".m4a", ".ogg",
                 ".opus", ".wav", ".pdf", ".zip", ".7z", ".rar", ".exe", ".dll", ".db-wal", ".db-shm", ".ds_store",
                 ".ini", ".xsl", ".css", ".js", ".ico", ".lnk", ".tmp"}
SKIP_NAMES = {"LISEZMOI.md", ".gitkeep", "Thumbs.db", "desktop.ini"}
#: au-delà, un lecteur qui charge tout le fichier en mémoire le refuse (ceux qui lisent en flux — ``streams`` —
#: le prennent) : un fichier de plusieurs Go ne fait pas tomber l'ingestion entière
MAX_WHOLE_FILE = 256 * 1024 * 1024


@dataclass
class IngestReport:
    read: dict[str, int] = field(default_factory=dict)  # lecteur → fichiers lus
    skipped_unchanged: int = 0
    skipped_media: int = 0
    unknown: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    locked: list[str] = field(default_factory=list)  # modifiées depuis, mais déjà lues : laissées telles quelles
    messages: int = 0
    documents: int = 0
    duplicates: int = 0
    warnings: list[str] = field(default_factory=list)


def walk(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and not any(part.startswith(".") for part in
                                                                        p.relative_to(root).parts))


def ingest(corpus: Corpus, root: Path, ctx: ReadContext, *, readers: list[Reader] | None = None,
           only: set[str] | None = None, progress: Callable[[str], None] | None = None,
           now: Callable[[], datetime] | None = None) -> IngestReport:
    readers = readers or all_readers()
    if only:
        readers = [r for r in readers if r.name in only]
    report = IngestReport()
    clock = now or (lambda: datetime.now().astimezone())
    for path in walk(root):
        if path.name in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIXES or path.name.startswith("~$"):
            report.skipped_media += 1  # ~$… : le fichier verrou d'un document Word ouvert
            continue
        reader, score = pick(path, readers)
        rel = str(path.relative_to(root))
        if reader is None or score == 0:
            report.unknown.append(rel)
            continue
        sha = file_sha256(path)
        if corpus.source_unchanged(rel, sha, reader.name, reader.version):
            report.skipped_unchanged += 1
            continue
        if corpus.source_read(rel):
            # déjà lue par Claude Code : la relire effacerait ses messages, leurs séances et ce qui y renvoie
            report.locked.append(rel)
            continue
        size = path.stat().st_size
        if size > MAX_WHOLE_FILE and not getattr(reader, "streams", False):
            report.failed.append((rel, f"{size // 2**20} Mo : trop gros pour le lecteur {reader.name}, qui lit d'un "
                                       f"bloc (au plus {MAX_WHOLE_FILE // 2**20} Mo) — le découper"))
            continue
        if progress:
            progress(f"{reader.name:>9} · {rel}")
        stats = SourceStats()
        ctx.warnings = stats.warnings
        try:
            with corpus.transaction():
                source = corpus.begin_source(rel, sha, reader.name, reader.version, size,
                                             clock().isoformat(timespec="seconds"))
                corpus.add_items(source, reader.read(path, ctx), stats)
                corpus.end_source(source, stats)
        except Exception as exc:  # noqa: BLE001 — un fichier, quel qu'il soit, n'arrête jamais l'ingestion des autres
            report.failed.append((rel, f"{type(exc).__name__}: {str(exc)[:300]}"))
            continue
        report.read[reader.name] = report.read.get(reader.name, 0) + 1
        report.messages += stats.messages
        report.documents += stats.documents
        report.duplicates += stats.duplicates
        report.warnings += [f"{rel} : {w}" for w in stats.warnings]
    corpus.rebuild_search()
    return report
