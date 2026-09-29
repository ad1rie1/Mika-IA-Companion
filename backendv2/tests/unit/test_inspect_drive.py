"""Les vues d'inspection de l'affect, du corps, de l'initiative et des buts.

Ce qu'un opérateur doit pouvoir lire, par ses intentions :

- sur un noyau neuf, chaque vue se rend sans erreur et dit qu'il n'y a rien ;
- après un échange en colère, la posture envers cette personne se lit en
  colère (hostilité, chaleur négative) ; après un échange chaleureux, elle se
  réchauffe ;
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
from mika.kernel.clock import HOUR, MINUTE, US, local
from mika.kernel.inspect import Block, Fields, Note, Prose, Ref, Table
from mika.ports.llm import LLMResponse
from mika.runtime.effects import with_content
from mika.runtime.inspection import find, run_view
from mika.sim.clock import SimClock, run_virtual
from mika.sim.llm.persona import PersonaSimLLM
from tests.fixtures.mika import PARIS, at_paris, befriend, boot, build, connect, said

VIEWS = {("affect", "humeur"): "Humeur", ("affect", "postures"): "Postures", ("body", "rythme"): "Rythme",
         ("agency", "initiatives"): "Initiatives", ("goals", "buts"): "Buts", ("goals", "but"): "But"}


def when(t: int) -> str:
    return local(t, PARIS).strftime("%d/%m %H:%M")


def show(kernel, owner: str, name: str, **params: str) -> list[Block]:
    spec = find(kernel, owner, name)
    assert spec is not None, f"vue absente : {owner}/{name}"
    blocks = run_view(kernel, spec, params, when=when)
    failed = [b.text for b in blocks if isinstance(b, Note) and b.text.startswith("Cette vue a échoué")]
    assert not failed, failed
    return blocks


def _cell(v) -> str:
    return v.text if isinstance(v, Ref) else "" if v is None else str(v)


def flat(blocks: list[Block]) -> str:
    out = []
    for b in blocks:
        if isinstance(b, Table):
            out += [b.title, *b.columns, *(_cell(v) for row in b.rows for v in row)]
            if not b.rows:
                out.append(b.empty)
        elif isinstance(b, Fields):
            out += [b.title, *(f"{k} : {_cell(v)}" for k, v in b.pairs)]
        elif isinstance(b, (Note, Prose)):
            out.append(b.text)
    return "\n".join(out)


def field(blocks: list[Block], name: str):
    for b in blocks:
        if isinstance(b, Fields):
            for k, v in b.pairs:
                if k == name:
                    return v
    raise KeyError(name)


def table(blocks: list[Block], title: str) -> Table:
    return next(b for b in blocks if isinstance(b, Table) and b.title == title)


def column(t: Table, name: str) -> list:
    i = t.columns.index(name)
    return [row[i] for row in t.rows]


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


# ── Un noyau neuf ─────────────────────────────────────────────────────────


def test_every_view_reads_a_fresh_kernel(tmp_path):
    async def scenario(kernel, script):
        titles = {(o, n): find(kernel, o, n).title for o, n in VIEWS}
        return titles, {key: show(kernel, *key) for key in VIEWS}, {
            "inconnu": show(kernel, "goals", "but", goal="999"),
            "illisible": show(kernel, "goals", "but", goal="douze"),
            "statut": show(kernel, "goals", "buts", status="bidule"),
            "vivants": show(kernel, "goals", "buts", status="vivants"),
        }

    titles, fresh, odd = live(tmp_path, scenario)
    assert titles == VIEWS
    mood = fresh[("affect", "humeur")]
    assert field(mood, "ressentie (écart au repos)") == "au repos"
    assert field(mood, "dernière balise déclarée") == "aucune"
    assert "comme d'habitude" in flat(mood)
    assert "personne ne l'a encore touchée" in flat(fresh[("affect", "postures")])
    body = fresh[("body", "rythme")]
    assert field(body, "sommeil") == "éveillée" and field(body, "phase du jour") == "après-midi"
    assert str(field(body, "prochaine transition")).startswith("s'endormir — ")
    assert field(body, "initiatives et travail ordinaires") == "libres"
    agency = fresh[("agency", "initiatives")]
    assert field(agency, "aujourd'hui") == "0 / 5" and field(agency, "ignorées d'affilée") == "0"
    assert "elle n'a encore rien dit d'elle-même" in flat(agency)
    assert "aucun but" in flat(fresh[("goals", "buts")]) and field(fresh[("goals", "buts")], "vivants") == 0
    assert [b.tone for b in fresh[("goals", "but")]] == ["mut"]  # sans numéro : une consigne, pas une erreur
    # des paramètres invalides donnent une note, jamais une exception
    assert "Aucun but n°999" in flat(odd["inconnu"]) and odd["inconnu"][0].tone == "ko"
    assert "n'est pas un numéro" in flat(odd["illisible"])
    assert "Statut inconnu" in flat(odd["statut"]) and "aucun but" in flat(odd["statut"])
    assert "aucun but avec ce statut" in flat(odd["vivants"])


# ── L'affect : une colère, puis de la chaleur ─────────────────────────────


async def turn(kernel, script, handle, emotion, intensity, text="…"):
    script.tag = f"[EMOTION:{emotion}:{intensity}]"
    await (await kernel.perceive(said(handle, text))).reply
    await asyncio.sleep(90)


def _row(t: Table, who: str) -> dict:
    row = next(r for r in t.rows if who in _cell(r[0]))
    return dict(zip(t.columns, row, strict=True))


def test_the_stance_toward_someone_reads_anger_then_warmth(tmp_path):
    async def scenario(kernel, script):
        await befriend(kernel, "user_1", "friend")
        await connect(kernel, "user_1", "Alice")
        for _ in range(6):
            await turn(kernel, script, "user_1", "angry", 0.8, "tu m'énerves")
        angry = show(kernel, "affect", "postures"), show(kernel, "affect", "humeur")
        await asyncio.sleep(2 * HOUR / US)
        for _ in range(10):
            await turn(kernel, script, "user_1", "love", 0.8, "pardon, je t'adore")
        return angry, (show(kernel, "affect", "postures"), show(kernel, "affect", "humeur"))

    (angry, angry_mood), (warm, warm_mood) = live(tmp_path, scenario)
    a = _row(table(angry, "Postures envers chacun"), "Alice")
    w = _row(table(warm, "Postures envers chacun"), "Alice")
    assert "en colère" in a["ressentie envers elle"] and "en colère" in a["dernière balise"]
    assert float(a["hostilité"]) > 0.05 and float(a["chaleur (−1…1)"]) < 0
    assert "en colère" in a["ce qu'elle se dit"]
    assert "en colère" not in w["ressentie envers elle"] and "amoureuse" in w["dernière balise"]
    assert float(w["chaleur (−1…1)"]) > float(a["chaleur (−1…1)"])
    assert float(w["hostilité"]) < float(a["hostilité"])
    assert "en colère" in field(angry_mood, "dernière balise déclarée")
    assert "« Alice »" in field(warm_mood, "dernière balise déclarée")
    assert "amoureuse" in column(table(warm_mood, "Dernières balises"), "émotion déclarée")[0]


# ── Le corps : la nuit ────────────────────────────────────────────────────


def test_at_night_the_rhythm_says_she_sleeps_and_when_she_will_wake(tmp_path):
    async def scenario(kernel, script):
        await asyncio.sleep((at_paris(2026, 9, 29, 2, 0) - kernel.mind.clock.now()) / US)
        return show(kernel, "body", "rythme")

    night = live(tmp_path, scenario, start=at_paris(2026, 9, 28, 21, 0))
    assert field(night, "sommeil").startswith("sommeil")
    assert field(night, "phase du jour") == "nuit"
    assert str(field(night, "prochaine transition")).startswith("se réveiller — 29/09 0")
    assert field(night, "initiatives et travail ordinaires") == "retenues : elle dort"
    assert column(table(night, "Dernières transitions"), "transition")[0] == "s'endort"
    fell = column(table(night, "Dernières transitions"), "quand")[0]
    assert fell.startswith("28/09 2") or fell.startswith("29/09 0")  # vers 23 h


# ── L'initiative : sans réponse, puis répondue ────────────────────────────


def test_an_unanswered_initiative_reads_as_such_then_as_answered(tmp_path):
    async def scenario(kernel, script):
        await befriend(kernel, "user_1", "close")
        await connect(kernel, "user_1", "Alice")
        await (await kernel.perceive(said("user_1", "coucou"))).reply
        for _ in range(60):  # elle finit par lui écrire d'elle-même
            await asyncio.sleep(10 * MINUTE / US)
            spoken = table(show(kernel, "agency", "initiatives"), "Ce qu'elle a dit d'elle-même")
            if spoken.rows:
                break
        await asyncio.sleep(30 * MINUTE / US)
        before = show(kernel, "agency", "initiatives")
        await (await kernel.perceive(said("user_1", "oh pardon, je viens de voir ton message !"))).reply
        return before, show(kernel, "agency", "initiatives")

    before, after = live(tmp_path, scenario, start=at_paris(2026, 9, 28, 9, 0))
    spoken = table(before, "Ce qu'elle a dit d'elle-même")
    assert spoken.rows and "« Alice »" in spoken.rows[0][1] and spoken.rows[0][3] == "pas encore"
    assert field(before, "ignorées d'affilée") != "0"
    assert table(after, "Ce qu'elle a dit d'elle-même").rows[0][3].startswith("oui, ")


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
                    opened = show(kernel, "goals", "buts", status="vivants")
                    break
                await asyncio.sleep(1)
            for _ in range(6 * 60):
                if reported():
                    break
                await asyncio.sleep(MINUTE / US)
            step = reported()[0]
            await kernel.lanes.join()
            gid = str(step.data.goal)
            detail = show(kernel, "goals", "but", goal=gid)
            after = {s: show(kernel, "goals", "buts", status=s) for s in ("vivants", "abouti", "done")}
            await kernel.forget("user_1")
            return step, opened, detail, after, show(kernel, "goals", "but", goal=f"#{gid}")
        finally:
            await kernel.stop()

    step, opened, detail, after, forgotten = run_virtual(clock, main)
    gid = step.data.goal
    # ouvert : dans la liste des buts vivants, avec son envie à l'instant
    assert opened is not None
    goals = table(opened, "Buts")
    row = dict(zip(goals.columns, goals.rows[0], strict=True))
    link = row["but"]
    assert isinstance(link, Ref) and link.kind == "view" and link.key == "goals/but"
    assert link.params == (("goal", str(gid)),)
    assert "examen" in row["titre"] and row["autorité"] == "à elle" and row["sorte"] == "exploration"
    assert row["statut"] == "en cours" and row["outils"] == "goals, memory"
    assert 50 <= int(row["envie"].rstrip("%")) <= 100  # l'envie de départ, à peine usée
    assert field(opened, "vivants") == 1
    # le détail : ses champs, ses pas, ses épisodes
    assert field(detail, "sorte") == "exploration" and "examen" in field(detail, "titre")
    assert field(detail, "personne concernée") == "« Adrien » (user_1)"
    opening = field(detail, "ouvert le")
    assert isinstance(opening, Ref) and opening.kind == "event" and opening.key == str(gid)
    steps = table(detail, "Ses pas")
    first = dict(zip(steps.columns, steps.rows[-1], strict=True))
    verdict = {"continue": "continuer", "done": "fini", "blocked": "bloquée", "wait": "attendre"}[step.data.verdict]
    assert first["verdict"].startswith(verdict)
    assert first["résumé"] == step.data.summary.text
    assert set(step.data.tools) == set(first["outils utilisés"].split(", ")) and "memory_search" in step.data.tools
    assert first[""] == Ref("episode", step.correlation, "épisode")
    episodes = table(detail, "Ses épisodes")
    assert "pas de travail" in column(episodes, "épisode")
    assert step.correlation in [r.key for r in column(episodes, "")]
    assert all(isinstance(r, Ref) and r.kind == "episode" for r in column(episodes, ""))
    assert field(detail, "statut") == "abouti"
    # les filtres : par code ou par libellé
    assert not table(after["vivants"], "Buts").rows
    assert [r[0] for r in table(after["abouti"], "Buts").rows] == [r[0] for r in table(after["done"], "Buts").rows]
    assert len(table(after["abouti"], "Buts").rows) == 1
    # oublié : ce qui la concernait se lit « (oublié) », la vue tient
    assert field(forgotten, "titre") == "(oublié)" and field(forgotten, "résultat") == "(oublié)"
    assert field(detail, "titre") != "(oublié)"
    # le résumé du pas pouvait citer ses mots : l'oubli l'atteint aussi
    summaries = column(table(forgotten, "Ses pas"), "résumé")
    assert summaries and all(s == "(oublié)" for s in summaries)
    assert "examen" not in flat(forgotten)


def test_the_views_never_run_an_episode(tmp_path):
    """Lire n'écrit rien : le journal ne bouge pas quand on regarde."""
    async def scenario(kernel, script):
        await (await kernel.perceive(said("user_1", "coucou"))).reply
        head = kernel.mind.head
        for key in VIEWS:
            show(kernel, *key)
        show(kernel, "goals", "but", goal="1")
        return head, kernel.mind.head

    head, after = live(tmp_path, scenario)
    assert head == after

