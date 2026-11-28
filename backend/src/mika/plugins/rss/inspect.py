"""Ce que la console montre de ses flux (Connexions › Ses sens › Flux RSS) : ce qui paraît, ce qui la touche,
ce qu'elle laisse passer — l'état des abonnements, ce qu'elle a remarqué et ce qui lui a fait penser à ses amies.

Lecture seule : le cache des flux (par son port) et le journal ; les jetons des adresses ne sont jamais montrés.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from mika.contracts import identity as identity_c
from mika.contracts import rss as c
from mika.kernel.clock import MINUTE, instant
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    FORGOTTEN,
    Badge,
    Block,
    Chart,
    Column,
    Disclosure,
    Fields,
    InspectContext,
    Meter,
    Note,
    Pager,
    Param,
    Prose,
    Ref,
    Row,
    Series,
    Stat,
    Stats,
    Table,
    Text,
    When,
    num_fr,
    paginate,
)
from mika.kernel.state import FrozenDict
from mika.plugins.rss import KEEP, RSS, RssParams, RssState, interest_words, params
from mika.ports.feeds import feed_name, tokenless
from mika.vocab.interests import pertinence
from mika.vocab.words import fold

#: la console ne relit pas plus que ceci du cache des flux (filtres, pages)
PAGE = 25
#: le graphe : tant de jours, et jamais plus de titres relus que ceci
DAYS = 14
CHART_MAX = 1_000
BATCH = 250


def _clip(text: str, n: int = 120) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _web(link: str) -> bool:
    """Un lien d'article montrable : http(s), un hôte, sans identifiants ni caractères de contrôle."""
    if not link or len(link) > 2_000 or not link.isprintable() or "\\" in link:
        return False
    parts = urlsplit(link)
    return parts.scheme in ("http", "https") and bool(parts.hostname) and not parts.username and not parts.password


def _matches(wanted: str, feed: str) -> bool:
    return not wanted or fold(wanted) in fold(feed)


def _feeds_note(port: Any, p: RssParams) -> Note:
    if port is None:
        return Note("Flux non configurés : aucun lecteur de flux n'est branché.", tone="muted")
    if not port.configured():
        return Note("Aucun flux n'est suivi : ajoute leurs adresses dans Connexions › Ses sens › Flux suivis, "
                    "en haut à droite.", tone="muted")
    return Note(f"Relevés toutes les {p.poll_every_us // MINUTE} min quand elle est éveillée ; elle ne remarque "
                f"que ce qui touche ses centres d'intérêt ({p.noticed_per_poll} titres au plus par relevé, "
                f"à partir d'une pertinence de {num_fr(p.notice_from, 2)}).", tone="ok")


def _days(frame: Frame) -> list[tuple[date, int]]:
    """Les ``DAYS`` derniers jours (le plus ancien d'abord) et leur minuit, à son heure à elle."""
    tz = frame.env.tz_of(frame.root)
    today = frame.local().date()
    out = []
    for back in range(DAYS - 1, -1, -1):
        d = today - timedelta(days=back)
        out.append((d, instant(datetime(d.year, d.month, d.day, tzinfo=tz))))
    return out


def _since(ctx: InspectContext, since: int, cap: int) -> tuple[list[Any], bool]:
    """Les titres remarqués depuis cet instant (du plus récent au plus ancien), bornés ;
    et si la borne a coupé."""
    out: list[Any] = []
    before = None
    while True:
        want = min(BATCH, cap - len(out))
        if want <= 0:
            return out, True
        batch = ctx.events([c.NOTICED], want, before=before)
        for e in batch:
            if e.at < since:
                return out, False
            out.append(e)
        if len(batch) < want:
            return out, False
        before = batch[-1].seq


def _chart(frame: Frame, days: list[tuple[date, int]], noticed: list[Any], cut: bool, feed: str) -> Chart:
    per_day = Counter(frame.local(e.at).date() for e in noticed)
    points = tuple((at, float(per_day.get(d, 0))) for d, at in days) if noticed else ()
    title = f"Titres remarqués par jour ({DAYS} jours)" + (f" — flux « {_clip(feed, 60)} »" if feed else "")
    if cut:
        title += f" — seuls les {CHART_MAX} derniers sont comptés"
    return Chart((Series("titres remarqués", points, slot=1),), kind="bars", title=title,
                 empty=f"aucun titre remarqué ces {DAYS} derniers jours")


def _health(port: Any) -> list[dict[str, Any]]:
    """La santé de chaque flux suivi (ce que le dernier relevé a donné) ; un port sans santé : ses flux, sans
    état connu."""
    health = getattr(port, "health", None)
    if callable(health):
        return list(health())
    return [{"title": title, "url": url, "attempted_at": 0, "ok_at": 0, "error": "", "failures": 0, "items": 0,
             "added": 0, "kept": 0} for title, url in port.followed()]


def _state(h: dict[str, Any]) -> Badge:
    if h["error"] and h["failures"]:
        return Badge(f"en erreur ({h['failures']} d'affilée)", "danger")
    if h["error"]:
        return Badge("répond, mais illisible", "warn")
    if not h["attempted_at"]:
        return Badge("pas encore relevé", "muted")
    return Badge("va bien", "ok")


def _followed(port: Any, s: RssState, health: list[dict[str, Any]]) -> Table:
    by_feed = port.feed_counts()
    noticed = Counter(v.feed for v in s.noticed.values())
    rows = []
    for h in health:  # tous : la console les montre par pages
        title = str(h["title"])
        name = _clip(title, 80)
        detail = (Fields((("adresse", Text(str(h["url"]) or "—", kind="mono")),
                          ("dernière tentative", When(h["attempted_at"]) if h["attempted_at"] else "jamais"),
                          ("dernier succès", When(h["ok_at"]) if h["ok_at"] else "jamais"),
                          ("erreur", Text(str(h["error"]) or "aucune", kind="muted" if not h["error"] else "text")),
                          ("articles lus au dernier relevé", h["items"]), ("nouveaux au dernier relevé", h["added"]),
                          ("gardés dans le cache", h["kept"])), title="Son dernier relevé"),)
        rows.append(Row((
            Ref.view("rss", "flux", name, flux=title[:200]) if title else Text("(titre inconnu)", kind="muted"),
            _state(h), When(h["ok_at"]) if h["ok_at"] else Text("jamais", kind="muted"),
            Text(_clip(str(h["error"]), 90) or "—", kind="muted"), h["items"], h["added"],
            by_feed.get(title, 0), noticed.get(title, 0)),
            tone="danger" if h["error"] and h["failures"] else "", detail=detail))
    return Table(("flux", "état", Column("dernier succès", "fit"), "erreur", Column("lus", "num"),
                  Column("nouveaux", "num"), Column("relevés", "num"), Column("remarqués", "num")), tuple(rows),
                 title=f"Flux suivis ({len(rows)})", empty="aucun flux suivi",
                 caption="« lus » et « nouveaux » : au dernier relevé. Cliquer un flux filtre la page sur lui. Les "
                         "jetons des adresses ne sont jamais montrés.")


def _entries(s: RssState, ctx: InspectContext, port: Any, words: frozenset[str]) -> Table:
    feed, query = ctx.value("flux") or "", fold(ctx.value("q") or "")
    request = ctx.pager(size=PAGE)
    result = port.entries_page(feed, query, request.number, request.size)
    pager = Pager(number=result.number, size=result.size, total=result.total)
    rows = []
    for e in result.items:
        seen = s.noticed.get(e.id)
        title = _clip(e.title) or "(sans titre)"
        score = seen.pertinence if seen else pertinence(e.title, e.summary, words)
        rows.append(Row((
            Ref.url(e.link, title) if _web(e.link) else Text(title), Text(_clip(feed_name(e.feed), 60)),
            When(e.published) if e.published else None,
            Badge("remarqué", "ok") if seen else Badge("laissé passer", "muted"),
            Meter(score, num_fr(score, 2)) if seen else Meter(score, f"{num_fr(score, 2)} (estimée)", tone="muted"),
        ), detail=(Prose(e.summary, title="Résumé de l'article", reading=True),) if e.summary else ()))
    return Table(("titre", "flux", Column("paru", "fit"), Column("remarqué", "fit"), Column("pertinence", "fit", detail=True)),
                 tuple(rows), title="Derniers articles relevés", pager=pager,
                 empty="aucun article ne correspond à ces filtres" if feed or query else "rien de relevé pour l'instant",
                 caption="Ouvre un titre pour lire l'article à sa source, ou déplie son résumé.")


def _noticed(s: RssState, ctx: InspectContext, feed: str) -> Table:
    noticed, pager = paginate(sorted((v for v in s.noticed.values() if _matches(feed, v.feed)), key=lambda v: -v.seq),
                              ctx.pager("page_remarques", size=PAGE))
    texts = ctx.store.content([v.summary_ref for v in noticed if v.summary_ref])
    return Table(
        (Column("remarqué", "fit"), "flux", "ce qu'elle a remarqué", Column("pertinence", "fit"),
         Column("journal", "fit")),
        tuple((When(v.at), Text(_clip(feed_name(v.feed), 60)), Text(tokenless(texts.get(v.summary_ref, FORGOTTEN)), clamp=300),
               Meter(v.pertinence, num_fr(v.pertinence, 2)), Ref("event", str(v.seq), f"#{v.seq}")) for v in noticed),
        title="Ce qu'elle a remarqué", empty="elle n'a encore remarqué aucun titre" if not feed else
        "rien de remarqué dans ce flux", pager=pager,
        caption=f"Elle garde les {KEEP} derniers titres remarqués, du plus récent au plus ancien.")


def _person(frame: Frame, key: str) -> Any:
    """Un lien vers la fiche d'une personne qu'elle connaît ; sinon sa clé."""
    who = frame.get(identity_c.IDENTITY(key))
    return Ref.subject("person", key, who.name or key) if who.known else Text(who.name or key, kind="muted")


def _thoughts(s: RssState, frame: Frame, ctx: InspectContext, feed: str) -> Table:
    found = sorted(((k, who, v) for k, by in s.thought_of.items() for who, v in by.items() if _matches(feed, v.feed)),
                   key=lambda r: (-r[2].seq, r[1]))
    page, pager = paginate(found, ctx.pager("page_amies", size=PAGE))
    texts = ctx.store.content([v.summary_ref for _k, _who, v in page if v.summary_ref])
    return Table(
        (Column("quand", "fit"), "pensé à", "le titre", Column("pertinence", "fit"), Column("dit", "fit"),
         Column("journal", "fit")),
        tuple((When(v.at), _person(frame, who), Text(tokenless(texts.get(v.summary_ref, FORGOTTEN)), clamp=300),
               Meter(v.pertinence, num_fr(v.pertinence, 2)),
               Badge("dit", "ok") if who in s.told.get(k, FrozenDict()) else Badge("pas encore", "muted"),
               Ref("event", str(v.seq), f"#{v.seq}")) for k, who, v in page),
        title="Ce qui lui a fait penser à ses amies", pager=pager,
        empty="aucun titre ne lui a fait penser à quelqu'un" if not feed else "rien de ce flux",
        caption="Un titre qui touche ce qu'une amie ou une proche lui a dit aimer (sa fiche) : il passe en tête de ses "
                "flux quand elle lui écrit d'elle-même, en privé — jamais devant une autre. « Dit » : elle le lui a "
                "montré. Oublier la personne efface sa copie du titre.")


@RSS.inspect("flux", title="Flux RSS", section="sens", order=20,
             description="Ses flux : ce qui paraît, ce qui la touche, ce qu'elle laisse passer.",
             params=[Param("flux", "Flux", placeholder="titre d'un flux"),
                     Param("q", "Recherche", placeholder="titre ou résumé")])
def _inspect(s: RssState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("feeds")
    p = params(frame.env.params_of("rss", frame.root))
    words, _by_interest = interest_words(frame, ctx.store)
    feed = ctx.value("flux") or ""
    days = _days(frame)
    window, cut = _since(ctx, days[0][1], CHART_MAX)
    window = [e for e in window if _matches(feed, e.data.feed)]
    today = days[-1][1]
    health = _health(port) if port is not None else []
    broken = sum(1 for h in health if h["error"] and h["failures"])
    last = max((v.at for v in s.noticed.values() if _matches(feed, v.feed)), default=0)
    passed = port.entry_count(feed, tuple(s.noticed)) if port is not None else 0
    stats = Stats((
        Stat("flux suivis", len(health) if port is not None else "—",
             sub=f"{broken} en erreur" if broken else "tous répondent" if health else "",
             tone="danger" if broken else ""),
        Stat("laissés passer", passed,
             sub="relevés sans la toucher, sur l'horizon du cache (il oublie les vieux articles ; elle ne "
                 "marque pas ses lectures)"),
        Stat("remarqués aujourd'hui", sum(1 for e in window if e.at >= today)),
        Stat("dernier titre remarqué", When(last) if last else "jamais"),
    ))
    # ses réglages (les flux suivis) : derrière la roue de Ses sens, en haut à droite (ADR 0206)
    blocks: list[Block] = [_feeds_note(port, p), stats]
    if port is not None:
        blocks.append(_entries(s, ctx, port, words))
        blocks.append(Disclosure("État des abonnements", (_followed(port, s, health),), open=bool(broken)))
    blocks.append(Disclosure("Activité et articles remarqués", (_chart(frame, days, window, cut, feed),
                                                               _noticed(s, ctx, feed))))
    blocks.append(Disclosure("Ce qui lui a fait penser à ses amies", (_thoughts(s, frame, ctx, feed),)))
    blocks.append(Disclosure("Ce qui la touche", (Fields((
        ("titres remarqués (gardés)", len(s.noticed)),
        ("les mots qui la touchent", Text(_clip(", ".join(sorted(words)), 600) or "—")),
    )),)))
    return blocks
