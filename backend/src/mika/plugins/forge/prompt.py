"""Ce qu'elle dit de ses apps : ce qu'une app d'un projet trouve pour quelqu'un, et ce que ses apps ajoutent au prompt.

- **Ses trouvailles** (ADR 0105) : ce qu'une app d'un projet lui a signalé assez fort pour lui rester en tête et qui
  concerne quelqu'un (``ForgeState.news``), elle le lui dit, là où il est, sinon sur sa messagerie (la preuve
  ``_news``, ``news_for``) ; la section « app_news » en cite le texte, et l'énoncé qui la suit la marque dite par sa
  provenance (``_news_told``). Une initiative finie sans rien dire compte un essai (``_ended``) ; ce qui a été dit
  reste su (``said``, ``SAID_KEPT``). Ces réducteurs tiennent aussi le début et la fin d'une lecture de file
  (``sifting``) et d'un essai qui prouvait (ADR 0161).
- **La section « apps »** : la ligne de chacune de ses apps qui en apportent une (``context``), appelées ensemble,
  chacune au niveau de ce qu'elle concerne ; une section citée, en zone volatile, coupée en premier.

Ces contributions s'inscrivent sur ``FORGE`` à l'import du module, que le paquet fait en fin de fichier, en premier.
La file de signaux (``signals.py``), que ce module importe entre ses deux parties pour ``told_to``, s'inscrit ainsi
entre les trouvailles et la section « apps », comme dans l'ancien fichier unique : la console montre cet ordre
(Système › Contributions). Ce module lit du paquet l'état et les aides partagées.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from mika.contracts import agency as agency_c
from mika.contracts import attention as attention_c
from mika.contracts import forge as c
from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import DAY
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.guards import floor
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.plugins.forge import (
    FORGE,
    App,
    ForgeParams,
    ForgeState,
    News,
    concerns,
    has_secrets,
    params,
    rules_of,
    sifting_app,
    trusted,
)
from mika.vocab.days import ago_words
from mika.vocab.episodes import CONVERSATIONAL, WORKING, Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity, hearable

# ── Ce que ses apps trouvent pour quelqu'un : le lui dire (ADR 0105) ──────


NEWS_PROVENANCE = "forge-news:"
#: ce qu'elle garde en mémoire de ce qu'elle a déjà dit de chaque app (les plus récentes)
SAID_KEPT = 3
#: les initiatives ouvertes gardées au plus (un épisode jamais réglé ne les fait pas grossir)
OPENINGS_KEPT = 32


def news_for(s: ForgeState, person: str | None, now: int, p: ForgeParams, threshold: float) -> list[tuple[str, News]]:
    """Ses trouvailles d'apps à dire à cette personne : récentes, assez fortes pour lui être restées en tête, pas
    encore dites, pas trop essayées — de la plus ancienne à la plus récente."""
    if not person:
        return []
    return sorted(((k, n) for k, n in s.news.items()
                   if k in s.apps and person in n.about and not n.told and n.attempts < p.news_attempts
                   and now - n.at <= p.news_within_us and n.pertinence >= threshold), key=lambda kn: kn[1].at)


@FORGE.reducer(rt.EPISODE_STARTED, reads=[identity_c.PERSON])
def _started(s: ForgeState, e, cx) -> ForgeState:
    """Une lecture de file part : le lot qu'elle lira (les premiers de la file, autant que l'app le déclare) et un
    appel de plus au quota du jour. Une initiative pour dire une trouvaille part : on note laquelle."""
    d = e.data
    app_name = sifting_app(d.target) if d.kind == Kind.TASK else ""
    if app_name:
        app = s.apps.get(app_name)
        if app is None:
            return s
        batch = tuple(q.seq for q in app.queue[:rules_of(app).per_call])
        calls = (*(t for t in app.calls_at if e.at - t < DAY), e.at)
        sifting = s.sifting.set(e.correlation, (app_name, batch, e.at))
        if len(sifting) > OPENINGS_KEPT:
            sifting = FrozenDict(sorted(sifting.items())[-OPENINGS_KEPT:])
        return replace(s, apps=s.apps.set(app_name, replace(app, calls_at=calls)), sifting=sifting)
    if d.kind != Kind.INITIATIVE or not {c.APP_NEWS, c.APP_ALERT} & set(str(d.reason).split(",")):
        return s
    person = cx.facts.get(identity_c.PERSON(d.target)) or d.target if d.target else ""
    apps = tuple(k for k, n in s.news.items() if person in n.about and not n.told)
    openings = s.openings.set(e.correlation, (e.at, apps))
    if len(openings) > OPENINGS_KEPT:
        openings = FrozenDict(sorted(openings.items())[-OPENINGS_KEPT:])
    return replace(s, openings=openings)


@FORGE.reducer(rt.UTTERANCE)
def _news_told(s: ForgeState, e, cx) -> ForgeState:
    """Elle l'a dit : les trouvailles que son prompt lui montrait (``forge-news:<app>:<signal>``) sont dites — en
    répondant comme de son initiative."""
    d = e.data
    s = replace(s, openings=s.openings.delete(e.correlation)) if e.correlation in s.openings else s
    if not d.visible:
        return s
    shown = {x[len(NEWS_PROVENANCE):] for x in d.provenance if x.startswith(NEWS_PROVENANCE)}
    news, said = s.news, s.said
    for ref in shown:
        app, _, seq = ref.rpartition(":")
        n = news.get(app)
        if n is not None and str(n.seq) == seq and not n.told:
            news = news.set(app, replace(n, told=True))
            said = said.set(app, (*said.get(app, ()), (n.summary_ref, e.at, n.level))[-SAID_KEPT:])
    return replace(s, news=news, said=said) if news is not s.news else s


@FORGE.reducer(rt.EPISODE_ENDED, reads=[agency_c.RENOUNCED])
def _ended(s: ForgeState, e, cx) -> ForgeState:
    """Une lecture de file finie sans verdict : si c'était un vrai essai (une panne, un silence), le lot lu quitte la
    file — une file ne se relit pas sans fin aux frais du quota ; devancée ou interrompue, il y reste. Une initiative
    pour dire une trouvaille finie sans rien dire : un essai (``agency.tried``)."""
    renounced = cx.facts.get(agency_c.RENOUNCED(e.data.target)) if e.data.target else 0
    # un essai qui prouvait, dans une exécution finie sans le créditer : rien n'est consommé (ADR 0161)
    for name, app in s.apps.items():
        if app.trial_in and app.trial_in == e.correlation:
            s = replace(s, apps=s.apps.set(name, replace(app, trial_in="", trial_version=0)))
    sift = s.sifting.get(e.correlation)
    if sift is not None:
        s = replace(s, sifting=s.sifting.delete(e.correlation))
        app_name, batch, started = sift
        app = s.apps.get(app_name)
        if app is not None and agency_c.tried(e.data.outcome, started, 0):
            s = replace(s, apps=s.apps.set(app_name, replace(app, queue=tuple(q for q in app.queue
                                                                              if q.seq not in set(batch)))))
    opening = s.openings.get(e.correlation)
    if opening is None:
        return s
    s = replace(s, openings=s.openings.delete(e.correlation))
    started, apps = opening
    if not agency_c.tried(e.data.outcome, started, renounced):
        return s
    news = s.news
    for app in apps:
        n = news.get(app)
        if n is not None and not n.told:
            news = news.set(app, replace(n, attempts=n.attempts + 1))
    return replace(s, news=news)


def _address(frame: Frame, person: str) -> str | None:
    """Où la joindre : là où elle est, sinon une adresse qui la joint (sa messagerie)."""
    return identity_c.reach_now(frame, person)


@FORGE.propose(kinds=[Kind.INITIATIVE], reasons={c.APP_NEWS: (0.0, 10.0), c.APP_ALERT: (0.0, 10.0)},
               reads=[attention_c.SIGNAL_THOUGHT_FROM, identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY,
                      presence_c.PRESENT])
def _news(s: ForgeState, frame: Frame) -> list[Candidate]:
    """Ce qu'une app d'un projet vient de lui signaler et qui concerne quelqu'un : elle le lui dit, là où elle est,
    sinon sur sa messagerie (ADR 0105 — elle croyait n'avoir « aucun moyen de le prévenir », et sa pensée attendait
    d'insister). Elle prévient (``agency.INFORMS``) ; ce qu'elle a jugé urgent ouvre le dialogue même avec qui ne lui
    répond plus (``c.APP_ALERT``), le reste attend qu'il ait répondu."""
    p = params(frame.env.params_of("forge", frame.root))
    threshold = frame.get(attention_c.SIGNAL_THOUGHT_FROM)
    threshold = 0.6 if threshold is None else threshold
    people = sorted({person for n in s.news.values() for person in n.about})
    out = []
    for person in people:
        found = news_for(s, person, frame.now, p, threshold)
        address = _address(frame, person) if found else None
        if address is None:
            continue
        apps = ", ".join(f"« {s.apps[k].title} »" for k, _ in found)
        who = identity_c.keeper_name(frame, person, quoted=True)
        urgent = any(n.urgent for _, n in found)
        brief = phrase("forge.news.alert_brief", apps=apps, who=who) if urgent else \
            phrase("forge.news.brief", apps=apps, who=who)
        out.append(Candidate(Kind.INITIATIVE, address, c.APP_ALERT if urgent else c.APP_NEWS, p.news_evidence,
                             resources=frozenset({floor(address)}), args=FrozenDict({"brief:forge": brief})))
    return out


@FORGE.enricher("news", episodes=[*CONVERSATIONAL], deadline_ms=1000)
async def _news_texts(s: ForgeState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    store = ports.get("store")
    ep = frame.episode
    if store is None or ep is None or not ep.target or not s.news:
        return None
    refs = [n.summary_ref for n in s.news.values() if n.summary_ref and not n.told]
    return {"texts": store.content(refs)} if refs else None


@FORGE.section("app_news", zone=Zone.VOLATILE, episodes=[*CONVERSATIONAL], trim_rank=80,
               title=phrase("forge.news.title"), untrusted=True)
def _news_section(s: ForgeState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce que ses apps viennent de trouver pour la personne à qui elle parle (de son initiative ou en répondant), pas
    encore dit (le titre le dit) : le texte du signal, cité — rien d'autre, ni consigne ni mot à elle dans la
    citation. L'énoncé qui suit le dit (sa provenance la marque dite)."""
    ep, aud = frame.episode, frame.audience
    if ep is None or aud is None or not ep.target:
        return None
    person = frame.get(identity_c.PERSON(ep.target)) or ep.target
    if ep.kind == Kind.INITIATIVE and agency_c.checking_in(ep.attrs.get("reasons") or (),
                                                           frame.get(attention_c.AWAITING(person)).initiatives):
        return None  # elle relance qui ne lui répond pas : elle prend de ses nouvelles, la trouvaille attend
    p = params(frame.env.params_of("forge", frame.root))
    threshold = frame.get(attention_c.SIGNAL_THOUGHT_FROM)
    found = news_for(s, person, frame.now, p, 0.6 if threshold is None else threshold)
    texts = (enrich.get("news") or {}).get("texts") or {}
    lines, refs, level = [], [], 0
    for app, n in found:
        text = texts.get(n.summary_ref)
        if not text or not hearable(n.about, n.level, person, aud.level, aud.witness_level, aud.private_ok):
            continue
        lines.append(phrase("forge.news.line", text=text, ago=ago_words(frame.now - n.at)))
        refs.append(f"{NEWS_PROVENANCE}{app}:{n.seq}")
        level = max(level, n.level if any(a != person for a in n.about) else 0)
    if not lines:
        return None
    return SectionBody("\n".join(lines), level=level, provenance=tuple(refs))


# à qui elle dirait ce qu'une app trouve : la file de signaux, importée ici, entre les trouvailles et la section
# « apps », s'inscrit à la place qu'elle avait dans l'ancien fichier unique
from mika.plugins.forge.signals import told_to  # noqa: E402

# ── Ce que ses apps lui disent, en conversation ───────────────────────────


@FORGE.enricher("apps", episodes=[*CONVERSATIONAL, *WORKING], deadline_ms=3000)
async def _contexts(s: ForgeState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """La ligne de chacune de ses apps, appelées ensemble (une app lente ne fait plus perdre les autres), chacune
    au niveau de ce qu'elle concerne (son projet, ADR 0104). Une app sans projet, ou qui lit ses secrets, parle de
    la vie de qui s'occupe d'elle (son agenda, sa banque) : au moins le personnel — et une app que l'interlocuteur
    ne peut pas entendre n'est même pas appelée."""
    port = ports.get("forge")
    live = [(k, a) for k, a in sorted(s.apps.items()) if a.enabled and not a.broken and a.context][:4]
    if port is None or not live:
        return None
    ep, aud = frame.episode, frame.audience
    person = (frame.get(identity_c.PERSON(ep.target)) or ep.target) if ep is not None and ep.target else None
    heard: list[tuple[str, App, int]] = []
    for name, app in live:
        about, level = told_to(frame, app)
        if not concerns(frame, app)[0] or (trusted(app) and has_secrets(ports, port.info(name))):
            level = max(level, int(Sensitivity.PERSONAL))
        if aud is None or not hearable(about, level, person, aud.level, aud.witness_level, aud.private_ok):
            continue
        heard.append((name, app, level if any(a != person for a in about) else 0))
    if not heard:
        return None
    p = params(frame.env.params_of("forge", frame.root))
    got = await asyncio.gather(*(port.call(name, "context", timeout_s=p.context_timeout_s, secrets=trusted(app))
                                 for name, app, _ in heard))
    lines = {app.title: str(r.value)[: p.context_chars] for (_, app, _), r in zip(heard, got, strict=True)
             if r.ok and r.value}
    level = max((lvl for _, app, lvl in heard if app.title in lines), default=0)
    return {"lines": lines, "level": level} if lines else None


@FORGE.section("apps", zone=Zone.VOLATILE, episodes=[*CONVERSATIONAL, *WORKING], trim_rank=0,
               title=phrase("forge.section.title"), untrusted=True)
def _section(s: ForgeState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("apps") or {}
    texts = got.get("lines") or {}
    lines = [phrase("forge.section.line", app=title, text=text) for title, text in sorted(texts.items())]
    return SectionBody("\n".join(lines), level=int(got.get("level") or 0)) if lines else None
