"""Assembler, pour une fenêtre que la mémoire du noyau consolide, ce que Claude Code a lu hors ligne.

La consolidation du moteur (rôle ``extract``) montre une conversation ainsi
(``mika.faculties.memory.extraction.render``)::

    Conversation privée avec Julie Martin [P1].
    Les messages :
    [#812] 14:05 Julie Martin [P1] : t'es où ?
    [#815] 14:06 Mika : j'arrive

et attend l'outil ``record_memories``. On sait ce que chaque ``seq`` du journal porte de
l'archive (le pilote le note en déroulant le script). On rend donc les éléments annotés
**dont le dernier message d'ancrage tombe dans la fenêtre** : un élément à cheval sur deux
fenêtres sort une seule fois, dans la seconde. Les numéros de l'archive deviennent des
``seq``, les personnes des jetons (``[P1]``) ou des noms. Les plafonds du moteur sont
respectés (les plus importants d'abord).
"""

from __future__ import annotations

import calendar
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: ce que ``mika.faculties.memory.extraction.parse`` garde au plus par appel
CAPS = {"souvenirs": 12, "croyances": 20, "promesses": 6, "evenements": 8}
_SEQ = re.compile(r"^\[#(\d+)\]", re.M)
#: « Conversation privée avec Julie Martin [P1]. » / « Un salon de groupe (…) : A [P1], B [P2]. »
_HEADER = re.compile(r"^(?:Conversation privée avec |Un salon de groupe[^:]*: )(.+?)\.?$", re.M)
_TOKENED = re.compile(r"^\s*(.+?) \[P(\d+)\]\s*$")
#: « [#812] 14:06 Julie Martin [P1] : … »
_LINE = re.compile(r"^\[#\d+\] \d{1,2}:\d{2} (.+?) \[P(\d+)\]", re.M)


@dataclass
class ArchiveItems:
    """Les éléments annotés, rangés par le message d'archive qui les clôt."""

    by_anchor: dict[int, list[tuple[str, dict[str, Any]]]] = field(default_factory=lambda: defaultdict(list))

    def add_session(self, annotation: Mapping[str, Any], session_messages: Sequence[int]) -> None:
        """``session_messages`` : les messages **rejoués** de la séance, dans l'ordre du temps. Un élément est rangé
        sous le dernier de ses ancres ; sans ancre, sous le dernier message rejoué (jamais un média seul, un
        message système ou supprimé : ils n'ont pas de ``seq``, et l'élément serait perdu)."""
        order = {m: i for i, m in enumerate(session_messages)}
        last = session_messages[-1] if session_messages else None
        for kind in ("souvenirs", "croyances", "promesses", "evenements"):
            for item in annotation.get(kind, []) or []:
                anchors = [m for m in item.get("messages", []) if m in order]
                anchor = max(anchors, key=order.__getitem__) if anchors else last
                if anchor is not None:
                    self.by_anchor[anchor].append((kind, dict(item)))


def tokens_of(request_text: str) -> dict[str, str]:
    """Nom affiché → jeton (« Julie Martin » → « P1 ») d'après la conversation montrée."""
    out: dict[str, str] = {}
    for header in _HEADER.findall(request_text):
        for part in header.split(", "):
            m = _TOKENED.match(part)
            if m:
                out[m.group(1).strip()] = f"P{m.group(2)}"
    for name, n in _LINE.findall(request_text):
        out.setdefault(name.strip(), f"P{n}")
    return out


def window_seqs(request_text: str) -> list[int]:
    return [int(x) for x in _SEQ.findall(request_text.split("Les messages :", 1)[-1])]


def assemble_extraction(request_text: str, archive_of_seq: Mapping[int, Sequence[int]], items: ArchiveItems,
                        display_name: Mapping[str, str]) -> dict[str, Any]:
    """L'argument de ``record_memories`` pour cette fenêtre.

    ``archive_of_seq`` : ``seq`` du journal → messages d'archive qu'il porte.
    ``display_name`` : ``p12`` → le nom sous lequel la personne a été présentée au noyau.
    """
    tokens = tokens_of(request_text)
    seqs = window_seqs(request_text)
    seq_of_archive = {a: seq for seq in seqs for a in archive_of_seq.get(seq, ())}
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in CAPS}
    for archive_id, _seq in sorted(seq_of_archive.items(), key=lambda kv: kv[1]):
        for kind, item in items.by_anchor.get(archive_id, ()):
            translated = _translate(kind, item, seq_of_archive, tokens, display_name)
            if translated is not None:
                out[kind].append(translated)
    result: dict[str, Any] = {}
    for kind, cap in CAPS.items():
        ranked = sorted(out[kind], key=lambda x: -int(x.get("importance", 2)))[:cap]
        result[kind] = ranked
    result.update({"promesses_tenues": [], "confidentiel": [], "situations_finies": []})
    return result


def _person(ref: str, tokens: Mapping[str, str], display_name: Mapping[str, str]) -> str:
    """« p12 » → « [P1] » si la personne est dans la conversation, sinon son nom ; un prénom reste un prénom ;
    un « p99 » inconnu ne devient rien (jamais un numéro dans sa mémoire)."""
    if re.fullmatch(r"p\d+", ref) and ref not in display_name:
        return ""
    name = display_name.get(ref, ref)
    token = tokens.get(name)
    return f"{name} [{token}]" if token else name


def _translate(kind: str, item: dict[str, Any], seq_of_archive: Mapping[int, int], tokens: Mapping[str, str],
               display_name: Mapping[str, str]) -> dict[str, Any] | None:
    out = dict(item)
    out["messages"] = sorted({seq_of_archive[m] for m in item.get("messages", []) if m in seq_of_archive})
    if kind == "promesses":
        out["envers"] = _person(str(item.get("envers", "")), tokens, display_name)
    else:
        out["personnes"] = [x for p in item.get("personnes", []) if (x := _person(str(p), tokens, display_name))]
    if kind == "evenements":
        when = event_date(str(item.get("quand", "")))
        if when is None:
            return None
        out["quand"], precise = when
        if not precise:
            out["a_feter"] = False  # on ne souhaite pas une fête à une date devinée
    return out


def event_date(raw: str) -> tuple[str, bool] | None:
    """La date d'un événement au format du moteur (AAAA-MM-JJ[THH:MM]) ; un mois seul devient son dernier jour
    (une prise de nouvelles vient alors forcément après). ``(date, précise)`` ou ``None``."""
    raw = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?", raw):
        return raw, True
    m = re.fullmatch(r"(\d{4})-(\d{2})", raw)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}", False
    return None
