"""Les vues d'inspection de l'affect, du corps, des besoins, de l'initiative
et des buts ; leurs vitaux et leurs séries.

Ce qu'un opérateur doit pouvoir lire, par ses intentions :

- sur un noyau neuf, chaque vue se rend sans erreur et dit qu'il n'y a rien ;
  une courbe sans mesure le dit, lisiblement ; les vitaux disent « au repos »,
  une énergie en pourcentage, « éveillée », une envie ;
- chaque série mesure un nombre dans ses bornes ; une courbe montre ce que
  l'échantillonneur a mesuré, sur la période choisie ;
- après un échange en colère, la posture envers cette personne se lit en
  colère (hostilité, chaleur négative), l'humeur de la barre de vitaux aussi,
  et la valence baisse ; après un échange chaleureux, elle se réchauffe ;
- sur la fiche d'une personne, l'onglet d'affect ne parle que d'elle ;
- la nuit, le rythme dit qu'elle dort, quand elle se réveillera, et que ses
  initiatives ordinaires sont retenues ;
- une initiative restée sans réponse se lit comme telle, puis comme répondue ;
- une exploration ouverte et un pas rapporté se lisent dans la liste et dans
  le détail (verdict, outils, épisodes liés) ; un titre oublié se lit
  « (oublié) » ; un numéro inconnu donne une note, pas une exception.
"""

from __future__ import annotations

import asyncio

from mika.contracts import goals as goals_c
from mika.inspector import render
from mika.kernel.clock import DAY, HOUR, MINUTE, US, local
from mika.kernel.inspect import (
    Badge,
    Block,
    Chart,
    Disclosure,
    Fields,
    Grid,
    Meter,
    Note,
    Prose,
    Ref,
    Row,
    Section,
    Stats,
    Swatch,
    Table,
    Text,
    Timeline,
    When,
)
from mika.ports.llm import LLMResponse
from mika.runtime.effects import with_content
from mika.runtime.inspection import Inspection, find, run_view
from mika.sim.clock import SimClock, run_virtual
from mika.sim.llm.persona import PersonaSimLLM
from tests.fixtures.mika import PARIS, at_paris, befriend, boot, build, connect, said

VIEWS = {("affect", "humeur"): "Humeur", ("affect", "postures"): "Postures", ("body", "rythme"): "Rythme",
         ("needs", "needs"): "Besoins", ("agency", "initiatives"): "Initiatives", ("goals", "vivants"): "Buts vivants",
         ("goals", "clos"): "Clos", ("goals", "resume"): "Résumé",
         ("goals", "politique"): "Cadre et réglages", ("goals", "decisions"): "Décisions",
         ("projects", "tous"): "Ses projets", ("projects", "toutes_executions"): "Exécutions",
         ("projects", "toutes_decisions"): "Décisions techniques", ("projects", "apercu"): "Vue d'ensemble"}
SERIES = {"affect.valence": (-1.0, 1.0), "affect.eveil": (-1.0, 1.0), "body.energie": (0.0, 1.0),
          "body.pression": (0.0, 1.0), "needs.social": (0.0, 1.0), "needs.expression": (0.0, 1.0),
          "needs.curiosite": (0.0, 1.0)}
#: les émotions de la famille de la colère (ce qu'un échange en colère installe)
ANGER = {"angry", "frustrated", "disgusted"}


def _num(text: str) -> float:
    """Un nombre affiché à la française (« −0,31 », « +0,12 ») relu."""
    return float(text.replace("\u2212", "-").replace("+", "").replace(",", ".").replace("\u202f", ""))


def when(t: int) -> str:
    return local(t, PARIS).strftime("%d/%m %H:%M")


def show(kernel, owner: str, name: str, *, subject: str = "", inspection: Inspection | None = None,
         **params: str) -> list[Block]:
    spec = find(kernel, owner, name)
    assert spec is not None, f"vue absente : {owner}/{name}"
    if inspection is not None:
        blocks = inspection.run(spec, params, when=when, subject=subject)
    else:
        blocks = run_view(kernel, spec, params, when=when, subject=subject)
    failed = [b.text for b in walk(blocks) if isinstance(b, Note) and b.text.startswith("Cette vue a échoué")]
    assert not failed, failed
    return blocks


def walk(blocks) -> list:
    """Tous les blocs, y compris ceux imbriqués (sections, grilles, détails de lignes)."""
    out = []
    for b in blocks:
        out.append(b)
        if isinstance(b, (Section, Disclosure, Grid)):
            out += walk(b.items)
        elif isinstance(b, Table):
            out += walk([x for r in b.rows if isinstance(r, Row) for x in r.detail])
    return out


def _cell(v) -> str:
    if isinstance(v, (Ref, Swatch, Text, Badge)):
        return v.text
    if isinstance(v, Meter):
        return v.text or f"{v.ratio:.0%}"
    if isinstance(v, When):
        return when(v.at)
    return "" if v is None else str(v)


def _cells(row) -> tuple:
    return row.cells if isinstance(row, Row) else tuple(row)


def flat(blocks: list[Block]) -> str:
    out = []
    for b in walk(blocks):
        if isinstance(b, Table):
            out += [b.title, *(c if isinstance(c, str) else c.label for c in b.columns),
                    *(_cell(v) for row in b.rows for v in _cells(row))]
            if not b.rows:
                out.append(b.empty)
        elif isinstance(b, Fields):
            out += [b.title, *(f"{k} : {_cell(v)}" for k, v in b.pairs)]
        elif isinstance(b, Stats):
            out += [b.title, *(f"{s.label} : {_cell(s.value)} ({s.sub})" for s in b.items)]
        elif isinstance(b, Timeline):
            out += [b.title, *(f"{e.title} · {e.text} · {e.meta}" for e in b.entries)]
            if not b.entries:
                out.append(b.empty)
        elif isinstance(b, Chart):
            out.append(b.title)
            if not any(s.points for s in b.series):
                out.append(b.empty)
        elif isinstance(b, (Note, Prose)):
            out.append(b.text)
    return "\n".join(out)


def field(blocks: list[Block], name: str):
    for b in walk(blocks):
        if isinstance(b, Fields):
            for k, v in b.pairs:
                if k == name:
                    return v
    raise KeyError(name)


def stat(blocks: list[Block], label: str, title: str | None = None):
    for b in walk(blocks):
        if isinstance(b, Stats) and (title is None or b.title == title):
            for s in b.items:
                if s.label == label:
                    return s
    raise KeyError(label)


def table(blocks: list[Block], title: str) -> Table:
    return next(b for b in walk(blocks) if isinstance(b, Table) and b.title == title)


def timeline(blocks: list[Block], title: str) -> Timeline:
    return next(b for b in walk(blocks) if isinstance(b, Timeline) and b.title == title)


def chart(blocks: list[Block]) -> Chart:
    return next(b for b in walk(blocks) if isinstance(b, Chart))


def column(t: Table, name: str) -> list:
    labels = [c if isinstance(c, str) else c.label for c in t.columns]
    i = labels.index(name)
    return [_cells(row)[i] for row in t.rows]


class Script:
    """Le modèle factice répond avec la balise qu'on lui dicte."""

    def __init__(self) -> None:
        self.tag = "[EMOTION:happy:0.5]"

    def __call__(self, req):
        if req.role in ("extract", "profile", "compact", "validate", "interpret", "plan"):
            return LLMResponse("{}")
        if req.role == "murmur":
            return LLMResponse("tiens, et si je lui écrivais")
        if req.role == "narrative":
            return LLMResponse("Je suis quelqu'un qui aime les petites choses du quotidien.")
        return LLMResponse(f"d'accord {self.tag}")


def live(tmp_path, scenario, *, start=at_paris(2026, 9, 28, 14, 0)):
    script = Script()
    kernel, clock, _llm, _out = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel, script)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def vitals(kernel) -> dict:
    return {spec.key: v for spec, v in Inspection(kernel).vitals()}


def measure(kernel) -> dict[str, float]:
    frame = kernel.mind.frame()
    return {key: kernel.registry.series[key].fn(frame.state(kernel.registry.series[key].owner), frame)
            for key in SERIES}


# ── Un noyau neuf ─────────────────────────────────────────────────────────


def test_every_view_reads_a_fresh_kernel(tmp_path):
    async def scenario(kernel, script):
        titles = {(o, n): find(kernel, o, n).title for o, n in VIEWS}
        return titles, {key: show(kernel, *key) for key in VIEWS}, {
            "inconnu": show(kernel, "goals", "resume", subject="999"),
            "illisible": show(kernel, "goals", "resume", subject="douze"),
            "sorte": show(kernel, "goals", "vivants", sorte="bidule"),
            "vivants": show(kernel, "goals", "vivants", sorte="exploration"),
            "projet": show(kernel, "projects", "apercu", subject="999"),
            "periode": show(kernel, "affect", "humeur", periode="un siècle"),
        }

    titles, fresh, odd = live(tmp_path, scenario)
    assert titles == VIEWS
    mood = fresh[("affect", "humeur")]
    assert stat(mood, "ressentie").value == "au repos"
    assert stat(mood, "dernière balise").value == "aucune"
    assert _cell(stat(mood, "son fond").value)  # une émotion nommée, en couleur
    assert isinstance(stat(mood, "débordement").value, Meter)
    assert "comme d'habitude" in flat(mood)
    assert "elle n'a encore rien déclaré" in flat(mood)
    assert "personne ne l'a encore touchée" in flat(fresh[("affect", "postures")])
    body = fresh[("body", "rythme")]
    assert stat(body, "sommeil").value == "éveillée" and field(body, "phase du jour") == "après-midi"
    assert str(field(body, "prochaine transition")).startswith("s'endormir — ")
    assert isinstance(stat(body, "prochaine transition").value, When)
    assert field(body, "initiatives et travail ordinaires") == "libres"
    assert _cell(stat(body, "énergie").value).endswith(" %")
    assert "aucune transition encore" in flat(body)
    needs = fresh[("needs", "needs")]
    assert column(table(needs, "Ses besoins"), "besoin") == ["compagnie", "s'exprimer", "apprendre"]
    assert all(isinstance(m, Meter) and 0 <= m.ratio <= 1 for m in column(table(needs, "Ses besoins"), "tension"))
    agency = fresh[("agency", "initiatives")]
    assert _cell(stat(agency, "aujourd'hui").value) == "0 / 5" and stat(agency, "ignorées d'affilée").value == 0
    assert "elle n'a encore rien dit d'elle-même" in flat(agency)
    # sans échantillonneur, chaque courbe dit qu'elle n'a pas encore de mesure — lisiblement
    for key in (("affect", "humeur"), ("body", "rythme"), ("needs", "needs")):
        c = chart(fresh[key])
        assert not any(s.points for s in c.series) and "pas encore de mesure" in c.empty
    assert chart(mood).y == (-1.0, 1.0) and chart(mood).zero == 0.0
    shown = render.block(chart(mood), render.Env(when=when, now=0), {})  # la page dit l'absence, sans graphe vide
    assert shown["has"] is False and shown["svg"] == "" and "pas encore de mesure" in shown["empty"]
    assert [s.label for s in chart(needs).series] == ["compagnie", "s'exprimer", "apprendre"]
    assert chart(needs).y == (0.0, 1.0) and chart(body).y == (0.0, 1.0)
    assert "aucun but en cours" in flat(fresh[("goals", "vivants")])
    assert field(fresh[("goals", "vivants")], "vivants") == 0 and "aucun but clos" in flat(fresh[("goals", "clos")])
    assert [b.tone for b in fresh[("goals", "resume")]] == ["muted"]  # hors d'une fiche : une consigne, pas une erreur
    # des paramètres invalides donnent une note, jamais une exception
    assert "Aucun but « 999 »" in flat(odd["inconnu"]) and odd["inconnu"][0].tone == "warn"
    assert "Aucun but « douze »" in flat(odd["illisible"])
    assert "« bidule » inconnu" in flat(odd["sorte"]) and "aucun but en cours" in flat(odd["sorte"])
    assert "aucun but avec ces filtres" in flat(odd["vivants"])
    # les projets : une liste vide qui dit comment commencer, une fiche inconnue qui le dit
    assert "aucun projet" in flat(fresh[("projects", "tous")]) and "Créer un projet" in flat(fresh[("projects", "tous")])
    assert "aucune exécution encore" in flat(fresh[("projects", "toutes_executions")])
    assert "Aucun projet « 999 »" in flat(odd["projet"]) and odd["projet"][0].tone == "warn"
    assert "Période" in odd["periode"][0].text and odd["periode"][0].tone == "warn"
    assert chart(odd["periode"]).until - chart(odd["periode"]).since == DAY  # retombe sur 24 h


def test_the_vitals_and_series_of_a_fresh_kernel(tmp_path):
    async def scenario(kernel, script):
        return vitals(kernel), measure(kernel), {k: s.label for k, s in kernel.registry.series.items()}

    got, measured, labels = live(tmp_path, scenario)
    assert set(labels) >= set(SERIES)
    assert got["affect.humeur"].text == "au repos" and got["affect.humeur"].swatch is None
    energy = got["body.energie"]
    assert energy.text.endswith(" %") and 0.0 <= energy.ratio <= 1.0
    assert energy.text == f"{round(energy.ratio * 100)} %" and energy.tone == ""  # un après-midi : pas fatiguée
    assert got["body.sommeil"].text == "éveillée"
    envie = got["needs.envie"]
    assert envie.text in ("compagnie", "s'exprimer", "apprendre") and 0.0 <= envie.ratio <= 1.0
    for key, (lo, hi) in SERIES.items():
        assert isinstance(measured[key], float), key
        assert lo <= measured[key] <= hi, (key, measured[key])
    assert labels["affect.valence"] == "Valence" and labels["affect.eveil"] == "Éveil"
    assert labels["body.pression"] == "Pression de sommeil" and labels["needs.curiosite"] == "Apprendre"


def test_a_chart_shows_what_the_sampler_measured_over_the_chosen_period(tmp_path):
    asked: list[tuple[str, int, int]] = []

    def sampler(key, since, until, points):
        asked.append((key, since, until))
        return [(since + HOUR, 0.25), (until - HOUR, -0.5)]

    async def scenario(kernel, script):
        inspection = Inspection(kernel, sampler=sampler)
        now = kernel.mind.clock.now()
        return now, show(kernel, "affect", "humeur", inspection=inspection), \
            show(kernel, "affect", "humeur", inspection=inspection, periode="7 jours"), \
            show(kernel, "needs", "needs", inspection=inspection), show(kernel, "body", "rythme", inspection=inspection)

    now, day, week, needs, body = live(tmp_path, scenario)
    assert [v for _, v in chart(day).series[0].points] == [0.25, -0.5]
    drawn = render.block(chart(day), render.Env(when=when, now=now), {})
    assert drawn["has"] and "<svg" in drawn["svg"] and len(drawn["table"]["rows"]) == 2
    assert chart(day).until == now and chart(day).since == now - DAY
    assert chart(week).since == now - 7 * DAY  # le libellé tapé à la main est compris
    assert {k for k, _, _ in asked} == {"affect.valence", "needs.social", "needs.expression", "needs.curiosite",
                                        "body.energie", "body.pression"}
    assert all(s.points for s in chart(needs).series) and len(chart(body).series) == 2


# ── L'affect : une colère, puis de la chaleur ─────────────────────────────


async def turn(kernel, script, handle, emotion, intensity, text="…"):
    script.tag = f"[EMOTION:{emotion}:{intensity}]"
    await (await kernel.perceive(said(handle, text))).reply
    await asyncio.sleep(90)


def _row(t: Table, who: str) -> dict:
    row = next(r for r in t.rows if who in _cell(_cells(r)[0]))
    labels = [c if isinstance(c, str) else c.label for c in t.columns]
    return dict(zip(labels, _cells(row), strict=True)) | {"_row": row}


def test_the_stance_toward_someone_reads_anger_then_warmth(tmp_path):
    async def scenario(kernel, script):
        fresh = measure(kernel)
        await befriend(kernel, "user_1", "friend")
        await connect(kernel, "user_1", "Alice")
        for _ in range(6):
            await turn(kernel, script, "user_1", "angry", 0.8, "tu m'énerves")
        angry = show(kernel, "affect", "postures"), show(kernel, "affect", "humeur"), vitals(kernel), measure(kernel)
        await asyncio.sleep(2 * HOUR / US)
        for _ in range(10):
            await turn(kernel, script, "user_1", "love", 0.8, "pardon, je t'adore")
        return fresh, angry, (show(kernel, "affect", "postures"), show(kernel, "affect", "humeur"), measure(kernel))

    fresh, (angry, angry_mood, angry_vitals, angry_measure), (warm, warm_mood, warm_measure) = live(tmp_path, scenario)
    a = _row(table(angry, "Postures envers chacun"), "Alice")
    w = _row(table(warm, "Postures envers chacun"), "Alice")
    assert a["ressentie envers elle"].key in ANGER and a["dernière balise"].key == "angry"
    assert isinstance(a["hostilité"], Meter) and _num(a["hostilité"].text) > 0.05
    assert _num(a["chaleur (−1…1)"].text) < 0 and a["chaleur (−1…1)"].tone == "danger"
    # la ligne mène à la fiche de la personne, et son détail dit ce qu'elle se dit
    assert a["_row"].href == Ref.subject("person", "user_1", a["personne"].text, "affect")
    assert "en colère" in flat([a["_row"].detail[0]])
    assert isinstance(a["quand"], When)
    assert w["ressentie envers elle"].key not in ANGER and w["dernière balise"].key == "love"
    assert _num(w["chaleur (−1…1)"].text) > _num(a["chaleur (−1…1)"].text)
    assert _num(w["hostilité"].text) < _num(a["hostilité"].text)
    # l'humeur générale : la vue et la barre de vitaux se lisent en colère, la valence a baissé
    assert stat(angry_mood, "dernière balise").value.key == "angry"
    assert stat(angry_mood, "ressentie").value.key in ANGER
    mood_vital = angry_vitals["affect.humeur"]
    assert mood_vital.swatch is not None and mood_vital.swatch.key in ANGER
    assert mood_vital.swatch.palette == "emotion" and 0.0 < mood_vital.ratio <= 1.0
    assert angry_measure["affect.valence"] < fresh["affect.valence"]
    assert warm_measure["affect.valence"] > angry_measure["affect.valence"]
    assert "Alice" in stat(warm_mood, "dernière balise").sub and "user_1" not in stat(warm_mood, "dernière balise").sub
    declared = table(warm_mood, "Dernières balises")
    assert column(declared, "émotion déclarée")[0].key == "love"
    assert isinstance(column(declared, "à qui")[0], Ref) and column(declared, "à qui")[0].key == "person/user_1"


# ── Sur la fiche d'une personne ───────────────────────────────────────────


def test_the_person_tab_speaks_only_of_that_person(tmp_path):
    async def scenario(kernel, script):
        await befriend(kernel, "user_1", "friend")
        await befriend(kernel, "user_2", "friend")
        await connect(kernel, "user_1", "Alice")
        await connect(kernel, "user_2", "Bruno")
        for _ in range(4):
            await turn(kernel, script, "user_1", "angry", 0.8, "tu m'énerves")
            await turn(kernel, script, "user_2", "love", 0.8, "je t'adore")
        return {key: show(kernel, "affect", "affect", subject=key) for key in ("user_1", "user_2", "user_9", "")}

    tabs = live(tmp_path, scenario)
    alice, bruno, stranger, nobody = tabs["user_1"], tabs["user_2"], tabs["user_9"], tabs[""]
    alice_tags = timeline(alice, "Ses dernières balises envers elle").entries
    bruno_tags = timeline(bruno, "Ses dernières balises envers elle").entries
    # chacun ne voit que ce qui lui a été déclaré (une salutation d'elle-même comprise)
    # par où, jamais la clé de l'adresse (les réponses d'Alice, toutes en colère, ne sont pas celles de Bruno)
    assert all(e.meta.endswith("· sur le web") and "user_" not in e.meta for e in (*alice_tags, *bruno_tags))
    alice_replies = [e.title for e in alice_tags if e.meta.startswith("en répondant")]
    bruno_replies = [e.title for e in bruno_tags if e.meta.startswith("en répondant")]
    assert len(alice_replies) == 4 and all("en colère" in t for t in alice_replies)
    assert len(bruno_replies) == 4 and all("amoureuse" in t for t in bruno_replies)
    assert stat(alice, "ressentie").value.key in ANGER and stat(alice, "dernière balise").value.key == "angry"
    assert _num(stat(alice, "chaleur").value.text) < 0 < _num(stat(bruno, "chaleur").value.text)
    assert stat(bruno, "dernière balise").value.key == "love"
    assert "Aucune posture" in flat(stranger) and "elle ne lui a encore rien déclaré" in flat(stranger)
    assert nobody[0].text == "Cette vue se lit sur la fiche d'une personne."


# ── Le corps : la nuit ────────────────────────────────────────────────────


def test_at_night_the_rhythm_says_she_sleeps_and_when_she_will_wake(tmp_path):
    async def scenario(kernel, script):
        await asyncio.sleep((at_paris(2026, 9, 29, 2, 0) - kernel.mind.clock.now()) / US)
        return show(kernel, "body", "rythme"), vitals(kernel)

    night, got = live(tmp_path, scenario, start=at_paris(2026, 9, 28, 21, 0))
    assert stat(night, "sommeil").value.startswith("sommeil")
    assert field(night, "phase du jour") == "nuit"
    assert str(field(night, "prochaine transition")).startswith("se réveiller — 29/09 0")
    assert stat(night, "prochaine transition").sub == "se réveiller"
    assert when(stat(night, "prochaine transition").value.at).startswith("29/09 0")
    assert field(night, "initiatives et travail ordinaires") == "retenues : elle dort"
    transitions = timeline(night, "Dernières transitions").entries
    assert transitions[0].title == "s'endort" and transitions[0].href.kind == "event"
    fell = when(transitions[0].at)
    assert fell.startswith("28/09 2") or fell.startswith("29/09 0")  # vers 23 h
    assert got["body.sommeil"].text.startswith("sommeil") and got["body.sommeil"].tone == "info"
    assert got["body.energie"].tone == "warn"  # 2 h du matin : elle est fatiguée


# ── L'initiative : sans réponse, puis répondue ────────────────────────────


def test_an_unanswered_initiative_reads_as_such_then_as_answered(tmp_path):
    async def scenario(kernel, script):
        await befriend(kernel, "user_1", "close")
        await connect(kernel, "user_1", "Alice")
        await (await kernel.perceive(said("user_1", "coucou"))).reply
        for _ in range(60):  # elle finit par lui écrire d'elle-même
            await asyncio.sleep(10 * MINUTE / US)
            if timeline(show(kernel, "agency", "initiatives"), "Ce qu'elle a dit d'elle-même").entries:
                break
        await asyncio.sleep(30 * MINUTE / US)
        before = show(kernel, "agency", "initiatives")
        await (await kernel.perceive(said("user_1", "oh pardon, je viens de voir ton message !"))).reply
        return before, show(kernel, "agency", "initiatives")

    before, after = live(tmp_path, scenario, start=at_paris(2026, 9, 28, 9, 0))
    spoken = timeline(before, "Ce qu'elle a dit d'elle-même").entries
    assert spoken and spoken[0].title == "à Alice" and spoken[0].meta == "sans réponse pour l'instant"
    assert spoken[0].tone == "warn" and spoken[0].href.key == "person/user_1"
    assert stat(before, "ignorées d'affilée").value != 0 and stat(before, "ignorées d'affilée").tone == "warn"
    answered = timeline(after, "Ce qu'elle a dit d'elle-même").entries[0]
    assert answered.meta.startswith("répondue — ") and answered.tone == "ok"
    used = stat(after, "aujourd'hui").value
    assert isinstance(used, Meter) and used.text.endswith(" / 5") and 0 < used.ratio <= 1


# ── Les buts : une exploration, un pas ────────────────────────────────────


def test_an_exploration_and_its_step_read_in_the_list_and_the_detail(tmp_path):
    clock = SimClock(at_paris(2026, 9, 28, 14, 0))
    llm = PersonaSimLLM(clock, seed=1, abstain_rate=0.0, latency=2.0)
    kernel, clock, _, _out = build(tmp_path, None, clock=clock, llm=llm)

    def reported():
        mind = kernel.mind
        return [with_content(mind, mind.decode(e)) for e in mind.store.read(types={goals_c.STEP_REPORTED.name})]

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await (await kernel.perceive(said("user_1", "j'ai peur, je stresse pour mon examen de demain"))).reply
            opened = None
            for _ in range(2 * 3600):  # à la seconde : le but ouvert, avant que son pas ne le close
                goals = kernel.mind.frame().state("goals").goals
                if any(g.status == goals_c.ACTIVE for g in goals.values()):
                    opened = show(kernel, "goals", "vivants")
                    break
                await asyncio.sleep(1)
            for _ in range(6 * 60):
                if reported():
                    break
                await asyncio.sleep(MINUTE / US)
            step = reported()[0]
            await kernel.lanes.join()
            gid = str(step.data.goal)
            detail = [*show(kernel, "goals", "resume", subject=gid), *show(kernel, "goals", "seances", subject=gid),
                      *show(kernel, "goals", "episodes", subject=gid)]
            after = {
                "vivants": show(kernel, "goals", "vivants"),
                "exploration": show(kernel, "goals", "clos", sorte="exploration"),
                "rappel": show(kernel, "goals", "clos", sorte="rappel")}
            await kernel.forget("user_1")
            forgotten = [*show(kernel, "goals", "resume", subject=f"#{gid}"),
                         *show(kernel, "goals", "seances", subject=gid)]
            return step, opened, detail, after, forgotten
        finally:
            await kernel.stop()

    step, opened, detail, after, forgotten = run_virtual(clock, main)
    gid = step.data.goal
    # ouvert : dans la liste des buts vivants, avec son envie à l'instant
    assert opened is not None
    goals = table(opened, "Buts vivants")
    row = dict(zip([c.label for c in goals.columns], _cells(goals.rows[0]), strict=True))
    link = row["but"]
    assert isinstance(link, Ref) and link.kind == "subject" and link.key == f"goal/{gid}"  # la fiche du but
    assert goals.rows[0].href == link
    # son titre à elle (ce qu'Adrien lui a dit est gardé à part, cité au travail)
    assert row["titre"] == "Repenser à ce que « Adrien » m'a confié" and row["autorité"] == "à elle"
    assert row["sorte"] == "exploration"
    assert _cell(row["statut"]) == "en cours"
    assert isinstance(row["envie"], Meter) and 0.5 <= row["envie"].ratio <= 1  # l'envie de départ, à peine usée
    assert field(opened, "vivants") == 1
    # le détail : ses champs, ses pas, ses épisodes
    assert field(detail, "sorte") == "exploration" and "Adrien" in field(detail, "titre")
    assert _cell(field(detail, "personne concernée")) == "Adrien"  # son nom, pas sa clé
    opening = field(detail, "ouvert")
    assert isinstance(opening, Ref) and opening.kind == "event" and opening.key == str(gid)
    steps = table(detail, "Ses séances")
    first = dict(zip([c.label for c in steps.columns], _cells(steps.rows[-1]), strict=True))
    verdict = {"continue": "continuer", "done": "fini", "blocked": "bloquée", "wait": "attendre"}[step.data.verdict]
    assert _cell(first["verdict"]).startswith(verdict)
    assert _cell(first["résumé"]) == step.data.summary.text
    assert set(step.data.tools) == set(first["outils utilisés"].split(", ")) and step.data.tools == ("goal_reflect",)
    assert first[""] == Ref("episode", step.correlation, "épisode")
    episodes = table(detail, "Ses épisodes")
    assert "séance de travail" in column(episodes, "épisode")
    assert step.correlation in [r.key for r in column(episodes, "Prompt")]
    assert all(isinstance(r, Ref) and r.kind == "episode" for r in column(episodes, "Prompt"))
    assert _cell(field(detail, "statut")) == "abouti"
    # les filtres : par sorte (code ou libellé)
    assert not table(after["vivants"], "Buts vivants").rows
    closed = table(after["exploration"], "Buts clos")
    assert len(closed.rows) == 1 and _cell(column(closed, "issue")[0]) == "abouti"
    assert not table(after["rappel"], "Buts clos").rows
    # oublié : ce qui la concernait se lit « (oublié) », la vue tient
    assert field(forgotten, "titre") == "(oublié)" and field(forgotten, "résultat") == "(oublié)"
    assert field(detail, "titre") != "(oublié)"
    # le résumé du pas pouvait citer ses mots : l'oubli l'atteint aussi
    summaries = column(table(forgotten, "Ses séances"), "résumé")
    assert summaries and all(_cell(s) == "(oublié)" for s in summaries)
    assert "examen" not in flat(forgotten)


def test_the_views_never_run_an_episode(tmp_path):
    """Lire n'écrit rien : le journal ne bouge pas quand on regarde."""
    async def scenario(kernel, script):
        await (await kernel.perceive(said("user_1", "coucou"))).reply
        head = kernel.mind.head
        for key in VIEWS:
            show(kernel, *key)
        show(kernel, "goals", "resume", subject="1")
        return head, kernel.mind.head

    head, after = live(tmp_path, scenario)
    assert head == after
