"""Ce qu'elle lit devient ce qu'elle sait, et la nuit confronte ses témoins (ADR 0085).

Avant, ce qu'elle lisait seule (un article de ses flux, une page consultée en travaillant) ne devenait jamais un
savoir : seules les conversations étaient relues. Deux croyances sur une même personne, dites par deux témoins
différents, restaient côte à côte sans jamais se rencontrer — la même chose dite deux fois, ou deux versions qui se
contredisent. Maintenant, la nuit relit ses lectures en un appel au plus ; le modèle propose, le code juge, avec les
règles du socle (ADR 0080, 0081). Chaque cible échoue sur l'arbre d'avant.
"""

from __future__ import annotations

from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

from mika.contracts import memory as mc
from mika.contracts import rss as rss_c
from mika.contracts import runtime as rt
from mika.faculties.memory.faculty import MemoryParams, MemoryState, _reread
from mika.faculties.memory.projections import READINGS_TABLE, TESTIMONIES_TABLE, Readings, Told
from mika.faculties.memory.recall import items_by_id, verdict_of
from mika.faculties.memory.reread import Reread, _learned, _learned_section
from mika.kernel.clock import DAY, HOUR, local_date_of_night
from mika.kernel.events import Content
from mika.kernel.frame import Audience
from mika.kernel.prompt import PromptBudgetError
from mika.plugins.mcp import ExternalArgs, _call
from mika.ports.vectors import VectorItem
from mika.vocab.episodes import Kind
from mika.vocab.privacy import Sensitivity
from tests.unit.test_audit_regressions import event
from tests.unit.test_knowledge_coherence import FRAME, Frame, Store, ask, index

UTC = ZoneInfo("UTC")
NOW = FRAME.now  # jeudi 8 octobre 2026, midi
ALICE, BOB, CAROL = "user_2", "user_3", "user_4"
FEED = "rss:Science"
ASLEEP = NOW - 11 * HOUR  # endormie à 1 h : la nuit du 7
NIGHT = local_date_of_night(ASLEEP, UTC, 5).isoformat()
FRIEND = Audience(persons=(CAROL,), public=False, level=int(Sensitivity.PERSONAL),
                  witness_level=int(Sensitivity.PERSONAL), private_ok=True)


class Asleep(Frame):
    def __init__(self, p: MemoryParams | None = None, **kw):
        super().__init__(**kw)
        if p is not None:
            self.env = NS(tz_of=lambda *_: UTC, params_of=lambda *_: p)

    def get(self, key):
        return ASLEEP if key.name == "body.asleep_since" else super().get(key)


class LLM:
    """Un modèle qui répond toujours la même relecture ; ``fails`` : il tombe en panne."""

    def __init__(self, args: dict | None = None, *, fails: bool = False):
        self.args, self.fails, self.calls = args or {}, fails, []

    async def call(self, request):
        self.calls.append(request)
        if self.fails:
            raise TimeoutError("panne")
        return NS(tool_calls=(NS(name="record_readings", args=self.args),), text="", model="haiku")


def store() -> Store:
    db = Store()
    Readings().create(db, "")
    Told().create(db, "")
    return db


def read(db: Store, seq: int, title: str, excerpt: str, *, source: str = FEED, asked_by: str = "") -> None:
    """Elle a lu un article (``rss.read``), dans la journée ; ``asked_by`` : pour quelqu'un, en conversation."""
    db.texts[f"{seq}.title"], db.texts[f"{seq}.excerpt"] = title, excerpt
    d = rss_c.READ.draft(source=source, ref=f"article-{seq}", title=Content(ref=f"{seq}.title", text=title),
                         excerpt=Content(ref=f"{seq}.excerpt", text=excerpt), depth="article", asked_by=asked_by)
    Readings().apply(db, [event(d, seq, NOW - 20 * HOUR)], "")


def believe(db: Store, seq: int, text: str, *, at: int = NOW - 10 * DAY, **kw):
    kw.setdefault("sensitivity", int(Sensitivity.ANODYNE))
    return db.put(mc.BELIEVED.draft(text=Content.of(text, level=kw["sensitivity"]), **kw), seq, at)


async def night(db: Store, llm: LLM, *, vectors=None, p: MemoryParams | None = None, process: Reread | None = None,
                state: MemoryState | None = None) -> list:
    out: list = []

    async def emit(*drafts):
        out.extend(drafts)

    ctx = NS(frame=Asleep(p), state=state or MemoryState(sorted_night=NIGHT), ports={"store": db, "vectors": vectors},
             llm=llm, run_id="nuit", emit=emit)
    await (process or Reread()).run(ctx)
    return out


def of(out: list, et) -> list:
    return [d.data for d in out if d.type.name == et.name]


WEBB = "Le James Webb a trouvé de la vapeur d'eau sur l'exoplanète K2-18b"


# ── Ce qu'elle lit seule devient ce qu'elle sait ────────────────────────────


async def test_what_she_reads_alone_becomes_knowledge():
    db = store()
    read(db, 7, "Le James Webb trouve de l'eau sur K2-18b",
         "Le télescope James Webb a détecté de la vapeur d'eau sur l'exoplanète K2-18b. Une éclipse totale de "
         "Soleil sera visible en Espagne le 12 août 2027, a rappelé l'agence spatiale.")
    llm = LLM({"croyances": [{"texte": WEBB, "lecture": 1},
                             {"texte": "Le prix du pain a doublé en un an", "lecture": 1}],  # pas dans la lecture
               "moments": [{"texte": "L'éclipse totale de Soleil en Espagne", "lecture": 1, "quand": "2027-08-12",
                            "date_officielle": True}]})
    out = await night(db, llm)
    assert len(llm.calls) == 1
    (b,) = of(out, mc.BELIEVED)  # ce qu'aucune lecture ne dit ne naît pas d'une lecture
    assert (b.text.text, b.origin, b.told_by, b.about, b.sensitivity, b.sources) == \
        (WEBB, mc.READ, (FEED,), (), int(Sensitivity.ANODYNE), (7,))
    assert b.confidence <= 0.7  # au plus comme un témoin qui rapporte
    (ev,) = of(out, mc.EVENT_NOTED)
    assert (ev.scope, ev.about, ev.told_by, ev.official) == ("world", (), (FEED,), True)  # le monde, vu venir
    (done,) = of(out, mc.REREAD)
    assert (done.night, done.upto, done.readings, done.model) == (NIGHT, 7, 1, "haiku")
    db.conn.close()


async def test_relecture_is_bounded():
    db = store()
    llm = LLM()
    out = await night(db, llm)
    assert llm.calls == [] and [(d.night, d.upto) for d in of(out, mc.REREAD)] == [(NIGHT, 0)]  # rien à relire
    for seq in range(1, 6):
        read(db, seq, f"Article {seq} sur les comètes", f"La comète numéro {seq} passera bientôt.")
    llm = LLM({"croyances": [{"texte": f"La comète numéro {n} passera bientôt", "lecture": n} for n in range(1, 6)]})
    out = await night(db, llm, p=MemoryParams(reread_max_readings=3, reread_max_items=2))
    assert len(llm.calls) == 1 and llm.calls[0].messages[0].content.count("comète numéro") == 3  # les trois premières
    assert len(of(out, mc.BELIEVED)) == 2 and of(out, mc.REREAD)[0].upto == 3  # le reste attend la nuit suivante
    assert await night(db, llm, state=MemoryState(sorted_night=NIGHT, reread_night=NIGHT)) == []  # une par nuit
    failing, process = LLM(fails=True), Reread()
    assert await night(db, failing, process=process) == [] and len(failing.calls) == 1
    assert await night(db, failing, process=process) == [] and len(failing.calls) == 1  # une panne : la nuit suivante
    db.conn.close()


async def test_relecture_is_bounded_in_size_too():
    """Trente pages lues en entier dépassaient le contexte du modèle, et le même lot revenait échouer chaque nuit :
    chaque extrait se coupe, le lot s'arrête à sa taille — au moins une lecture —, le reste attend (ADR 0127)."""
    db = store()
    for seq in range(1, 5):
        read(db, seq, f"Page {seq}", f"comète{seq} " * 400)  # ~ 3 200 caractères chacune
    llm = LLM()
    out = await night(db, llm, p=MemoryParams(reread_excerpt_chars=500, reread_max_chars=1_200))
    prompt = llm.calls[0].messages[0].content
    assert prompt.count("comète1") < 100 and "comète2" in prompt and "comète3" not in prompt  # deux lectures coupées
    assert of(out, mc.REREAD)[0].upto == 2
    db.conn.close()


class TooLong(LLM):
    """Un modèle dont le contexte ne tient pas plus de ``fits`` lectures."""

    def __init__(self, fits: int):
        super().__init__()
        self.fits = fits

    async def call(self, request):
        self.calls.append(request)
        if request.messages[0].content.count("Article ") > self.fits:
            raise PromptBudgetError("requête trop longue pour le contexte du fournisseur")
        return NS(tool_calls=(NS(name="record_readings", args={}),), text="", model="haiku")


async def test_a_batch_too_long_for_the_model_is_retried_half_as_long_the_same_night():
    db = store()
    for seq in range(1, 9):
        read(db, seq, f"Article {seq}", "court")
    llm, process = TooLong(fits=2), Reread()
    for _ in range(3):  # 8 → 4 → 2 : chaque refus divise le lot, sans attendre la nuit suivante
        out = await night(db, llm, process=process)
        if out:
            break
    assert [m.messages[0].content.count("Article ") for m in llm.calls] == [8, 4, 2]
    assert of(out, mc.REREAD)[0].upto == 2 and process.limit == 0
    db.conn.close()


async def test_same_fact_read_adds_a_testimony():
    db = store()
    believe(db, 3, WEBB, told_by=(ALICE,), heard_by=(ALICE,), source=ALICE)
    read(db, 7, "Le James Webb trouve de l'eau sur K2-18b", "De la vapeur d'eau sur l'exoplanète K2-18b.")
    out = await night(db, LLM({"croyances": [{"texte": WEBB, "lecture": 1}]}))
    assert of(out, mc.BELIEVED) == []
    (att,) = of(out, mc.ATTESTED)
    assert (att.item, att.told_by, att.origin) == (3, (FEED,), mc.READ)  # un témoin de plus, pas une ligne de plus
    db.put(mc.ATTESTED.draft(**att.model_dump()), 8, NOW)
    assert db.query_mind(f"SELECT COUNT(*) FROM {TESTIMONIES_TABLE} WHERE item=3")[0][0] == 2
    db.conn.close()


async def test_a_weaker_reading_makes_her_doubt():
    db = store()
    seen = "La boulangerie de la rue Lepic ferme le lundi"
    believe(db, 3, seen, told_by=(ALICE,), heard_by=(ALICE,), source=ALICE, first_hand=True)  # elle y était
    believe(db, 4, "La ligne 14 du métro ferme à 23 h", told_by=(FEED,), origin=mc.READ, source=FEED)
    vectors = await index(db, [VectorItem(3, mc.BELIEF, seen), VectorItem(4, mc.BELIEF, "La ligne 14 du métro ferme")])
    read(db, 7, "Boulangerie de la rue Lepic : ouverte le lundi", "La boulangerie de la rue Lepic ouvre le lundi.")
    read(db, 8, "Métro : la ligne 14 ferme désormais à minuit", "La ligne 14 du métro fermera à minuit.")
    out = await night(db, LLM({"croyances": [
        {"texte": "La boulangerie de la rue Lepic est ouverte le lundi", "lecture": 1, "remplace": 3},
        {"texte": "La ligne 14 du métro ferme à minuit", "lecture": 2, "remplace": 4}]}), vectors=vectors)
    lepic, metro = of(out, mc.BELIEVED)
    assert (lepic.contests, lepic.replaces) == (3, None)  # un article ne remplace pas ce qu'Alice a vu : elle doute
    assert (metro.replaces, metro.contests) == (4, None)  # le même journal qui se corrige, oui
    db.conn.close()


async def test_her_opinions_are_hers():
    db = store()
    mine = "Je trouve que le nucléaire est trop risqué"
    believe(db, 4, mine, origin=mc.OBSERVED, about_self=True, durable=True, knowledge_kind="opinion")
    vectors = await index(db, [VectorItem(4, mc.BELIEF, mine)])
    read(db, 7, "Le nucléaire, une énergie sûre ?", "Le nucléaire est l'énergie la moins risquée par kWh produit.")
    read(db, 8, "Réforme des retraites : le débat", "La réforme des retraites repousse l'âge légal à 64 ans.")
    out = await night(db, LLM({"avis": [
        {"texte": "Finalement, le nucléaire me paraît moins risqué que je le croyais", "remplace": 4, "lectures": [1]},
        {"texte": "Je trouve la réforme des retraites injuste", "lectures": [2]},  # la politique aussi : ses avis
        {"texte": "Je pense que les comètes sont fascinantes"}]}), vectors=vectors)
    first, second = of(out, mc.BELIEVED)  # au plus deux par nuit
    assert all((b.about_self, b.durable, b.knowledge_kind, b.origin, b.about) ==
               (True, True, "opinion", mc.OBSERVED, ()) for b in (first, second))
    assert first.replaces == 4 and first.sources == (7,)  # elle change d'avis (et le ressent, ADR 0081)
    assert second.text.text == "Je trouve la réforme des retraites injuste" and second.sources == (8,)
    db.conn.close()


# ── Ce qu'elle consulte en travaillant ──────────────────────────────────────


class Port:
    async def call(self, server, remote, data):
        return NS(ok=True, text="La comète C/2026 A1 passera au plus près de la Terre le 3 novembre.")


def _search() -> NS:
    """L'outil « search » d'un serveur : il lit."""
    return NS(server="web", remote="search", max_result_chars=4000, nature="lecture")


async def _consult(kind: str, reads_world: bool = True, target: str | None = None) -> list:
    out: list = []

    async def emit(*drafts):
        out.extend(drafts)

    ctx = NS(ports={"mcp": Port()}, frame=NS(episode=NS(kind=kind, target=target)), emit=emit)
    # ce qu'elle garde, la ligne d'accès qui a laissé passer l'appel le dit : public, ou un souvenir
    result = await _call(_search(), ExternalArgs(q="comète"), ctx, "public" if reads_world else "perso")
    assert result.ok and (result.floor, result.unkept) == (0, False)
    return out


async def test_what_she_reads_working_or_for_someone_is_kept():
    (page,) = await _consult(Kind.STEP)
    assert (page.type.name, page.data.source, page.data.depth, page.data.asked_by) == \
        ("mcp.consulted", "mcp:web", "page", "")
    assert "3 novembre" in page.data.excerpt.text and "comète" in page.data.title.text
    # en conversation, lu pour quelqu'un (ADR 0110) : ce qu'elle a lu est gardé à son nom (son sujet : l'oubli de la
    # personne l'efface), jamais ce qu'il cherchait
    for kind in (Kind.REPLY, Kind.INITIATIVE):
        (page,) = await _consult(kind, target=ALICE)
        assert page.data.asked_by == ALICE and "3 novembre" in page.data.excerpt.text
        assert "comète" not in page.data.title.text
    assert page.type.subject_fields == {"asked_by"}
    assert await _consult(Kind.REPLY) == []  # personne en face : rien à garder pour quelqu'un
    assert await _consult(Kind.STEP, reads_world=False) == []  # un serveur que l'opérateur n'a pas dit public
    from mika.adapters.mcp.config import McpServer
    # un courrier, un agenda : jamais public par défaut — un service branché garde « rien » tant qu'aucune ligne
    # d'accès ne dit autre chose (ADR 0131)
    assert McpServer.model_fields["default_keep"].default == "rien"


async def test_what_she_reads_for_someone_comes_back_without_a_rule():
    """Ce qu'une lecture du monde lui rend en conversation est la même donnée citée qu'au travail : comment le
    raconter a une seule maison, ses outils dans son prompt (``runtime.tools.acting``) — la réponse de l'outil n'y
    ajoute pas de consigne (ADR 0154). La sonde du 2026-10-14 (« c'est la page de flash info de RTL […] je n'ai lu
    que le début de la page ») est à surveiller au banc."""
    async def result(kind: str, target: str | None) -> str:
        async def emit(*drafts):
            pass
        ctx = NS(ports={"mcp": Port()}, frame=NS(episode=NS(kind=kind, target=target)), emit=emit)
        return (await _call(_search(), ExternalArgs(q="comète"), ctx, "public")).content

    told = await result(Kind.REPLY, ALICE)
    assert "3 novembre" in told and told == await result(Kind.STEP, None)


async def test_the_night_keeps_only_the_news_of_what_she_read_for_someone():
    """Lu pour Alice en conversation : la nuit est prévenue (n'en garder que les nouvelles et les faits publics), ce
    qu'elle en garde est du monde (aucune personne, la source pour témoin), entendu par Alice — à qui elle l'a dit sur
    le moment, et qu'elle ne lui raconte donc pas comme une nouvelle ; à Carol, si."""
    db = store()
    read(db, 7, "search", "Le volcan Grimsvötn est entré en éruption ce matin en Islande.", source="mcp:web",
         asked_by=ALICE)
    volcano = "Le volcan Grimsvötn est entré en éruption en Islande le 7 octobre 2026"
    llm = LLM({"croyances": [{"texte": volcano, "lecture": 1}]})
    out = await night(db, llm)
    assert "[1] web — « search » (lu pour quelqu'un)" in llm.calls[0].messages[0].content
    assert "lu pour quelqu'un" in llm.calls[0].system_stable  # ce qu'elle peut en garder
    assert "Tu es Mika (persona full)." in llm.calls[0].system_stable  # ses avis se forment à son portrait (0153)
    (b,) = of(out, mc.BELIEVED)
    assert (b.about, b.told_by, b.heard_by, b.origin) == ((), ("mcp:web",), (ALICE,), mc.READ)
    (believed,) = [d for d in out if d.type.name == mc.BELIEVED.name]
    Told().apply(db, [event(believed, 20, NOW - 2 * HOUR)], "")
    db.put(believed, 20, NOW - 2 * HOUR)

    async def section(person: str) -> str | None:
        frame = Frame(FRIEND)
        frame.episode = NS(target=person, kind=Kind.INITIATIVE, attrs={})
        got = await _learned(MemoryState(), frame, {"store": db})
        body = _learned_section(MemoryState(), frame, {"learned": got})
        return body.content if body is not None else None

    assert await section(ALICE) is None  # elle le lui a dit en le lisant
    assert volcano in await section(CAROL)
    db.conn.close()


# ── « J'ai lu que… », une fois par personne ─────────────────────────────────


async def test_she_says_jai_lu_que_once_per_person():
    db = store()
    believe(db, 12, WEBB, at=NOW - 6 * HOUR, told_by=(FEED,), origin=mc.READ, source=FEED, confidence=0.7)
    believe(db, 13, "Le chat de Bob s'appelle Pixel", at=NOW - 6 * HOUR, told_by=(BOB,), source=BOB)  # pas lu
    believe(db, 14, "La Lune s'éloigne de la Terre", at=NOW - 9 * DAY, told_by=(FEED,), origin=mc.READ, source=FEED)

    async def section(person: str, kind: str = Kind.INITIATIVE) -> str | None:
        frame = Frame(FRIEND)
        frame.episode = NS(target=person, kind=kind, attrs={"reply_to": 10000} if kind == Kind.REPLY else {})
        got = await _learned(MemoryState(), frame, {"store": db})
        body = _learned_section(MemoryState(), frame, {"learned": got})
        return body.content if body is not None else None

    body = await section(CAROL)
    assert f"- {WEBB} (lu dans « Science »" in body  # ce qu'elle a lu, et où
    assert "Pixel" not in body and "Lune" not in body  # pas ce qu'on lui a dit ; plus ce qu'elle a lu il y a 9 jours
    ask(db, "salut !")
    # en réponse aussi, ce qu'elle a lu est là : en parler ou non, c'est elle qui en juge (ADR 0153 — un « tu » dans
    # le message ne le décide plus)
    shown = await section(CAROL, Kind.REPLY)
    assert WEBB in shown and "Tu peux en parler" not in shown
    said = NS(type=NS(name=rt.UTTERANCE.name), data=NS(visible=True, target=CAROL, provenance=("memory:12",)), at=NOW)
    Told().apply(db, [said], "")  # elle l'a raconté à Carol
    assert await section(CAROL) is None
    assert WEBB in await section(BOB)  # pas encore à Bob
    db.conn.close()


async def test_relecture_replays_without_calls():
    db = store()
    read(db, 7, "Le James Webb trouve de l'eau sur K2-18b", "De la vapeur d'eau sur l'exoplanète K2-18b.")
    out = await night(db, LLM({"croyances": [{"texte": WEBB, "lecture": 1}]}))
    (done,) = [d for d in out if d.type.name == mc.REREAD.name]
    after = _reread(MemoryState(sorted_night=NIGHT), event(done, 9, NOW), None)
    Readings().apply(db, [event(done, 9, NOW)], "")
    assert db.query_mind(f"SELECT COUNT(*) FROM {READINGS_TABLE}")[0][0] == 0  # relues, elles s'effacent
    llm = LLM({"croyances": [{"texte": WEBB, "lecture": 1}]})
    assert await night(db, llm, state=after) == [] and llm.calls == []  # le journal suffit : aucun appel au rejeu
    db.conn.close()


# ── La nuit confronte deux témoins ──────────────────────────────────────────


async def test_the_night_confronts_two_tellers():
    p = MemoryParams(recall_floor=0.0)
    for teller, verdict in ((BOB, "contests"), (CAROL, "supersedes")):
        db = store()
        believe(db, 20, "Carol a quitté son travail chez Ubisoft", about=(CAROL,), told_by=(ALICE,),
                heard_by=(ALICE,), source=ALICE, sensitivity=int(Sensitivity.PERSONAL))
        believe(db, 30, "Carol travaille toujours chez Ubisoft", at=NOW - DAY, about=(CAROL,), told_by=(teller,),
                heard_by=(teller,), source=teller, sensitivity=int(Sensitivity.PERSONAL),
                first_hand=teller == CAROL)
        vectors = await index(db, [VectorItem(20, mc.BELIEF, "Carol a quitté son travail chez Ubisoft", (CAROL,)),
                                   VectorItem(30, mc.BELIEF, "Carol travaille toujours chez Ubisoft", (CAROL,))])
        llm = LLM({"liens": [{"paire": 1, "relation": "contredit"}]})
        out = await night(db, llm, vectors=vectors, p=p)
        assert "Carol travaille toujours chez Ubisoft" in llm.calls[0].messages[0].content  # rien à lire, une paire
        (conf,) = of(out, mc.CONFRONTED)
        if verdict == "contests":
            assert (conf.contests, conf.supersedes) == (((20, 30),), ())  # Bob contre Alice : elle doute
        else:
            assert (conf.supersedes, conf.contests) == (((30, 20),), ())  # Carol, d'elle-même : c'est elle qui sait
            db.put(mc.CONFRONTED.draft(**conf.model_dump()), 40, NOW)
            assert items_by_id(db, [20])[20].status == "superseded"
        db.conn.close()


async def test_a_joined_rumor_stays_closed():
    db = store()
    believe(db, 20, "Alice attend un bébé", about=(ALICE,), told_by=(ALICE,), heard_by=(ALICE,), source=ALICE,
            secret=True, first_hand=True, sensitivity=int(Sensitivity.CONFIDENCE))
    believe(db, 30, "Alice est enceinte, elle attend un bébé", at=NOW - DAY, about=(ALICE,), told_by=(BOB,),
            heard_by=(BOB, CAROL), source=BOB, sensitivity=int(Sensitivity.PERSONAL))
    vectors = await index(db, [VectorItem(20, mc.BELIEF, "Alice attend un bébé", (ALICE,)),
                               VectorItem(30, mc.BELIEF, "Alice est enceinte, elle attend un bébé", (ALICE,))])
    read(db, 7, "Natalité : moins de bébés en France", "Les naissances reculent ; on attend moins de bébés.")
    out = await night(db, LLM({"liens": [{"paire": 1, "relation": "meme"}],
                               "croyances": [{"texte": "Alice attend un bébé", "lecture": 1}]}),
                      vectors=vectors, p=MemoryParams(recall_floor=0.0))
    assert of(out, mc.BELIEVED) == []  # ce qu'on lui a montré d'une paire ne renaît pas en « lu » : pas de blanchiment
    (joined,) = of(out, mc.JOINED)
    assert joined.pairs == ((20, 30),) and joined.mute
    db.put(mc.JOINED.draft(**joined.model_dump()), 40, NOW)
    item = items_by_id(db, [20])[20]
    assert all(t.secret for t in item.testimonies)  # Alice a demandé le silence : la rumeur de Bob se ferme avec
    assert not verdict_of(Frame(FRIEND), item, CAROL, FRIEND, {}, db).ok  # même devant Carol, qui l'avait entendue
    # et devant Bob : son témoignage (ses mots, « elle attend un bébé ») ne laisse pas redire ceux d'Alice — la sonde
    # réelle du 2026-10-10 l'a vu, la gardée disant « Alice est enceinte… Mika a promis de garder le secret »
    bob = Audience(persons=(BOB,), public=False, level=int(Sensitivity.PERSONAL),
                   witness_level=int(Sensitivity.PERSONAL), private_ok=True)
    assert not verdict_of(Frame(bob), item, BOB, bob, {}, db).ok
    db.conn.close()
