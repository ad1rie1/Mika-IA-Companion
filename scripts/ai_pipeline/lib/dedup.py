"""Repère les doublons d'une issue d'audit avant sa création.

Comparaison du titre (normalisé) et des fichiers concernés avec les issues
existantes. Le titre seul ne suffit pas : mesuré sur 212 issues d'audit
passées, au-dessus de 0,6 de ressemblance presque toutes les paires touchent
le même fichier, en dessous c'est surtout du bruit. D'où trois verdicts :

    skip    titre très proche d'une issue OUVERTE : on ne la recrée pas
    flag    titre proche d'une issue ouverte ET un fichier en commun :
            créée, mais à trancher par un humain
    closed  proche d'une issue FERMÉE : créée, avec un renvoi (régression,
            ou correction incomplète ?)
    new     rien de proche

Usage (une ligne TSV en sortie : verdict, numéro, score, titre trouvé) :
    python3 dedup.py POOL.json --title "…" --files "a.py, b.py" [--skip 0.8] [--flag 0.6]

POOL.json : la liste JSON rendue par
    gh issue list --json number,title,state,body
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata

STOP_WORDS = frozenset(
    "le la les un une des de du d l a au aux en et ou sur dans par pour avec "
    "sans qui que quand ne pas plus est sont se son sa ses ce cet cette il "
    "elle on n s y".split()
)

# Rang des verdicts : le plus fort l'emporte, puis le meilleur score.
RANK = {"skip": 3, "flag": 2, "closed": 1, "new": 0}

_PREFIX = re.compile(r"^\s*\[AI\]\[[^\]]*\]\s*", re.IGNORECASE)
_FILES_IN_BODY = re.compile(r"Fichiers concern[ée]s\*\*\s*:\s*`([^`]*)`")


def tokens(title: str) -> list[str]:
    """Titre sans préfixe [AI][profil], en minuscules, sans accents ni ponctuation."""
    title = _PREFIX.sub("", title or "")
    title = unicodedata.normalize("NFKD", title.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9_ ]+", " ", title).split()


def similarity(a: str, b: str) -> float:
    """Ressemblance de deux titres, entre 0 et 1.

    Le plus grand de deux scores : la similarité de séquence (reformulation
    proche) et le recouvrement des mots porteurs (mêmes mots, autre ordre).
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    ratio = difflib.SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    ca = {w for w in ta if w not in STOP_WORDS and len(w) > 2}
    cb = {w for w in tb if w not in STOP_WORDS and len(w) > 2}
    jaccard = len(ca & cb) / len(ca | cb) if ca | cb else 0.0
    return max(ratio, jaccard)


def file_names(files: str) -> set[str]:
    """Noms de fichiers (sans dossier) d'une liste « a.py, b/c.py »."""
    return {f.strip().rstrip("/").split("/")[-1] for f in (files or "").split(",") if f.strip()}


def files_of(issue: dict) -> set[str]:
    match = _FILES_IN_BODY.search(issue.get("body") or "")
    return file_names(match.group(1)) if match else set()


def verdict(title: str, files: str, pool: list[dict], skip: float = 0.8, flag: float = 0.6):
    """(verdict, issue la plus proche ou None, score)."""
    mine = file_names(files)
    best = ("new", None, 0.0)
    for issue in pool:
        score = similarity(title, issue.get("title", ""))
        if score < flag:
            continue
        shared = bool(mine & files_of(issue))
        is_open = (issue.get("state") or "").upper() == "OPEN"
        if is_open and score >= skip:
            found = "skip"
        elif is_open and shared:
            found = "flag"
        elif not is_open and (score >= skip or shared):
            found = "closed"
        else:
            continue
        if (RANK[found], score) > (RANK[best[0]], best[2]):
            best = (found, issue, score)
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pool")
    parser.add_argument("--title", required=True)
    parser.add_argument("--files", default="")
    parser.add_argument("--skip", type=float, default=0.8)
    parser.add_argument("--flag", type=float, default=0.6)
    args = parser.parse_args()

    with open(args.pool, encoding="utf-8") as fh:
        pool = json.load(fh)
    found, issue, score = verdict(args.title, args.files, pool, args.skip, args.flag)
    number = issue["number"] if issue else ""
    other = (issue.get("title") or "").replace("\t", " ") if issue else ""
    print(f"{found}\t{number}\t{score:.2f}\t{other}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
