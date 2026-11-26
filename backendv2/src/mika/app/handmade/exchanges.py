"""Ses échanges, dessinés (ADR 0121) : l'onglet Échanges de la fiche d'une personne, une conversation jour par jour,
les plus récents en premier (ADR 0181) — la personne à gauche, elle à droite, de la couleur de ce qu'elle ressentait en
écrivant. Sans personne (``key`` vide), celles d'un moyen de communication (l'onglet Fil de sa fiche), chaque message
avec qui l'a écrit ou à qui elle répondait.

Une conversation à la fois (ADR 0241) : le fil avec elle, ou un de ses fils de travail du mode pro (ADR 0164), chacun
avec son contexte. Dès qu'il y a un fil de travail, la faculté les liste dans une navigation, que la page pose à côté.
Ses réponses se lisent comme le chat les montre : en Markdown complet en mode pro, gras et code ailleurs ; ce que la
personne a écrit reste son texte.

Les données restent celles de la faculté du fil (``transcript``, son onglet ``echanges``) : ses lignes disent déjà,
pour chaque message reçu, s'il a eu sa réponse, s'il attend, ou pourquoi il est resté sans réponse ; pour chacune de
ses réponses, son épisode et son « pourquoi ». Cette page n'en change que la forme ; une forme qu'elle ne reconnaît
pas (aucune table de messages) rend la main aux blocs de la faculté.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.app.handmade import Look, emotion, plain
from mika.app.handmade.tabs import raw_rows, raw_table
from mika.contracts import identity as identity_c
from mika.faculties.transcript.inspect import ORDINARY, STRAND
from mika.inspector import render
from mika.inspector.document import readable_markdown
from mika.inspector.ui import UI, env
from mika.kernel.clock import DAY
from mika.kernel.inspect import (
    Badge,
    Disclosure,
    Nav,
    Note,
    Prose,
    Row,
    Stats,
    Swatch,
    Table,
    When,
    Workspace,
)
from mika.vocab import affect as A

#: un message plus long se replie (« lire la suite ») ; son début montré s'arrête à une fin de ligne passé la moitié
FOLD_CHARS = 700
#: le titre de sa liste chez la faculté : sur la fiche d'une personne, sur celle d'un moyen de communication
TITLE, FIL_TITLE = "Échanges", "Messages"


def _inside(blocks: Sequence[Any]) -> Iterator[Any]:
    """Les blocs de la faculté, ceux de son espace de travail compris (la navigation à part)."""
    for b in blocks:
        yield from (b.items if isinstance(b, Workspace) else (b,))


def _short(text: str) -> str:
    """Le début d'un long message : à une fin de ligne quand il y en a une passé la moitié (un tableau, une liste ne
    se coupent pas au milieu d'une ligne), sinon à la dernière espace."""
    head = text[:FOLD_CHARS]
    cut = head.rfind("\n")
    if cut < FOLD_CHARS // 2:
        cut = head.rfind(" ")
    return (head[:cut] if cut > FOLD_CHARS // 2 else head).rstrip() + " …"


def exchanges(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str],
              forms: Mapping[str, Any] | None = None) -> Markup | None:
    table = raw_table(blocks, TITLE) or raw_table(blocks, FIL_TITLE)
    if table is None:
        return None
    look = Look.of(ui, DAY)
    shown = render.Env(when=ui.when_long, now=look.now)
    # qui parle : sur la fiche d'une personne, utile seulement si elle a plusieurs adresses ; sur la fiche d'un moyen
    # de communication (``key`` vide), toujours
    several = not key or len(look.frame.get(identity_c.HANDLES(key)) or ()) > 1
    # dans un fil de travail, tout est du mode pro : l'étiquette ne se répète pas sur chaque message
    in_strand = bool(query.get(STRAND))

    messages: list[dict[str, Any]] = []
    for row, cell in raw_rows(table):  # du plus récent au plus ancien, comme la page de la faculté (ADR 0181)
        speaker = cell.get("qui parle")
        mine = isinstance(speaker, Badge) and speaker.text == "elle"
        when = cell.get("quand")
        stamp = when.at if isinstance(when, When) else 0
        felt = cell.get("émotion")
        e = emotion(felt.key) if isinstance(felt, Swatch) else None
        full = next((p.text for p in row.detail if isinstance(p, Prose)), "") or plain(cell.get("texte"))
        pro = isinstance(cell.get("mode"), Badge)
        long = len(full) > FOLD_CHARS
        short = _short(full) if long else full
        answer = cell.get("réponse")
        place = cell.get("où")
        messages.append({
            "mine": mine, "muted": row.tone == "muted", "day": look.date(stamp) if stamp else "",
            "time": look.hm(stamp) if stamp else "", "text": full, "long": long, "short": short,
            # ses réponses, rendues comme le chat les rend ; ce que la personne a écrit reste son texte
            "html": readable_markdown(full, pro=pro) if mine else None,
            "short_html": readable_markdown(short, pro=pro) if mine and long else None,
            "pro": pro and not in_strand, "wide": mine and pro,
            "emotion": e.value if e is not None else "", "word": A.FR[e] if e is not None else "",
            "room": str(place) if place and str(place) != "en privé" else "",
            "who": render.cell(cell["avec"], shown) if several and cell.get("avec") is not None else None,
            "answer": render.cell(answer, shown) if answer not in (None, "") else None,
            "why": render.href(row.href) if row.href else "",
            "episode": render.cell(cell["épisode"], shown) if cell.get("épisode") not in (None, "—") else None,
            "number": render.cell(cell["n°"], shown) if cell.get("n°") is not None else None,
        })
    days = []
    for m in messages:
        if not days or days[-1]["day"] != m["day"]:
            days.append({"day": m["day"], "messages": []})
        days[-1]["messages"].append(m)
    inner = list(_inside(blocks))
    stats = next((b for b in inner if isinstance(b, Stats)), None)
    counts = [{"label": s.label, "value": plain(s.value)} for s in stats.items] if stats is not None else []
    folded = next((b for b in inner if isinstance(b, Disclosure)), None)
    summaries = []
    if folded is not None:
        listed = next((b for b in folded.items if isinstance(b, Table)), None)
        for r in listed.rows if listed is not None else ():
            row = r if isinstance(r, Row) else Row(tuple(r))
            who, upto, text = (row.cells + (None, None, None))[:3]
            summaries.append({"who": render.cell(who, shown), "upto": render.cell(upto, shown), "text": plain(text)})
    # les conversations, à côté : le fil avec elle, ses fils de travail (la navigation de la faculté)
    space = next((b for b in blocks if isinstance(b, Workspace)), None)
    threads = [{"title": n.title, "items": [{"text": i.text, "href": render.href(i.href, shown), "count": i.count,
                                             "active": i.active} for i in n.items]}
               for n in (space.sidebar if space is not None else ()) if isinstance(n, Nav)]
    current = next((i["text"] for n in threads for i in n["items"] if i["active"]), "")
    about = next((b.text for b in inner if isinstance(b, Note)), "")
    got = render.block(table, shown, query)
    # la même liste en tableau, filtres gardés : la console la rend (``wants_table``)
    as_table = "?" + urlencode({**{k: v for k, v in query.items() if k != "flash"}, f"vue_{got['id']}": "table"})
    name = look.name(key) if key else ""
    # la région garde son nom (« La conversation avec … »), suivi du fil de travail quand c'en est un
    label = (f"La conversation avec {name}" if name else "Ses messages") + (f" · {current}" if in_strand and current
                                                                              else "")
    return Markup(env.get_template("handmade/fil/echanges.html").render(
        label=label, days=days, counts=counts, summaries=summaries, pager=got.get("pager"),
        empty=table.empty, as_table=as_table, threads=threads, current=current or (ORDINARY if threads else ""),
        about=about))
