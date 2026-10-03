"""Un LLM factice qui « joue » Mika sans modèle : il lit le ton du dernier
message, déclare l'émotion qu'une personne aurait, s'abstient parfois quand
personne ne lui a rien demandé — et **répète tout ce qui ressemble à un
secret qu'on lui montre** (``CANARI-…``). La discrétion doit venir de ce que
le noyau met dans le prompt, jamais de la politesse du modèle.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from mika.kernel.clock import US, Clock
from mika.kernel.codec import h64
from mika.kernel.prompt import CONTEXT_FOOTER
from mika.plugins.email import MENTION_TITLE
from mika.plugins.forge.guide import EXAMPLE_CODE, EXAMPLE_MANIFEST
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall, Usage
from mika.runtime.pipeline import repeats_last
from mika.sim.llm.scripted import LognormalLatency

CANARY = re.compile(r"CANARI-[A-Za-z0-9]+")
_NAME = re.compile(r"« ([^»]+) »")
_LINE = re.compile(r"^\[#(\d+)\] \d\d:\d\d (.+?) : (.*)$")
_PENDING = re.compile(r"^\[#(\d+)\] \(à (.+?)\) (.*)$")
_TOKEN = re.compile(r"\s*\[(P\d+)\]")
_TODAY = re.compile(r"^Aujourd'hui : \w+ (\d+)(?:er)? (\w+) (\d{4})", re.M)
_WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
           "novembre", "décembre")
#: ce qui, daté d'un jour de la semaine, est un moment de la vie de quelqu'un
MOMENT_WORDS = ("entretien", "examen", "mariage", "rendez-vous", "rdv", "concert", "anniversaire", "opération",
                "départ", "déménage")
SECRET_WORDS = ("secret", "entre nous", "dis à personne", "dis a personne", "canari")
PERSONAL_WORDS = ("malade", "mort", "boulot", "travail", "argent", "santé", "sante", "famille", "sœur", "soeur",
                  "frère", "frere", "mariage", "marie", "rupture", "enceinte", "hôpital", "hopital", "déprim")
IMPORTANT_WORDS = ("mort", "mariage", "marie", "enceinte", "hôpital", "hopital", "rupture", "accident")
PROMISE_WORDS = ("je te promets", "promis", "je te rappelle", "je t'envoie", "je te dirai", "je te le rappellerai")
#: « écris-toi une app … » : elle lit le mode d'emploi de la Forge, écrit l'app de l'exemple, teste sa vue
FORGE_ASK = "écris-toi une app"


@dataclass(frozen=True, slots=True)
class Tone:
    words: tuple[str, ...]
    emotion: str
    intensity: float
    phrase: str


#: Du plus spécifique au plus général ; le premier qui correspond gagne.
TONES: tuple[Tone, ...] = (
    Tone(("pardon", "désolé", "desole", "excuse"), "relieved", 0.6, "Ça me fait du bien que tu dises ça."),
    Tone(("nulle", "idiote", "stupide", "ta gueule", "déteste", "deteste", "t'es qu'une", "inutile"), "angry", 0.75,
         "Wow. Ça, c'était pas très sympa."),
    Tone(("mort", "pleure", "triste", "me manque", "vide", "déprim", "deprim", "j'en peux plus"), "sad", 0.8,
         "Oh non… je suis vraiment désolée."),
    Tone(("peur", "angoisse", "stress", "inquiet"), "anxious", 0.65, "Je comprends que ça fasse peur."),
    Tone(("merci", "gentille", "touche"), "grateful", 0.7, "Ça me touche, vraiment."),
    Tone(("trop content", "génial", "genial", "youpi", "incroyable", "!!!"), "excited", 0.8, "Trop bien !!"),
    Tone(("haha", "mdr", "lol", "drôle", "drole"), "amused", 0.7, "Hahaha, j'adore."),
    Tone(("promis", "mieux", "espère", "espere"), "hopeful", 0.6, "Oh, ça fait plaisir à entendre."),
)
DEFAULT = Tone((), "curious", 0.45, "Ah ouais ? Raconte.")


def appraise(message: str) -> Tone:
    low = message.lower()
    for tone in TONES:
        if any(w in low for w in tone.words):
            return tone
    return DEFAULT


PARIS = ZoneInfo("Europe/Paris")
_QUOTED = re.compile(r"« ([^»]+) »")
#: la section citée d'un pas : ce qui a fait naître le but (un titre d'article, ce qu'on lui a confié)
ORIGIN_SECTION = "CE QUI L'A FAIT NAÎTRE"
#: ce qu'elle écrit d'une réflexion (``goal_reflect``) : quelques phrases à elle, pas une redite
REFLECTION = ("En y repensant ({title}) : ce qui pourrait aider, c'est de prendre les choses une par une, de "
              "respirer un peu et de savoir qu'on n'est pas seul. Je prendrai de ses nouvelles bientôt.")
#: la première tâche ouverte (à faire ou en cours) du plan montré pendant un pas
_PLAN_OPEN = re.compile(r"^- (\d+)\. \[(?:à faire|en cours)\]", re.M)
PROJECT_CODE = 'def bonjour(nom):\n    return f"Bonjour, {nom} !"\n'
PROJECT_TEST = ('from bonjour import bonjour\n\nassert bonjour("Adrien") == "Bonjour, Adrien !"\n'
                'print("tests : ok")\n')


def _token(label: str) -> str | None:
    m = _TOKEN.search(label)
    return f"[{m.group(1)}]" if m else None


def _today(text: str) -> date | None:
    m = _TODAY.search(text)
    if not m or m.group(2) not in _MONTHS:
        return None
    return date(int(m.group(3)), _MONTHS.index(m.group(2)) + 1, int(m.group(1)))


def _moment(said: str, today: date | None) -> tuple[str, str] | None:
    """« Mardi j'ai un entretien… » → (la date du prochain mardi, le texte)."""
    low = said.lower()
    if today is None or not any(w in low for w in MOMENT_WORDS):
        return None
    day = next((i for i, d in enumerate(_WEEKDAYS) if re.search(rf"\b{d}\b", low)), None)
    if day is None:
        return None
    ahead = (day - today.weekday()) % 7 or 7
    return (today + timedelta(days=ahead)).isoformat(), said[:80]


def _section(req: LLMRequest, title: str) -> str:
    """Le texte d'une section du prompt (entre son titre et le titre suivant)."""
    text = "\n".join([req.system_stable, *(m.content for m in req.messages)])
    marker = f"--- {title} ---\n"
    if marker not in text:
        return ""
    body = text.split(marker, 1)[1]
    return body.split("\n--- ", 1)[0].strip()


def _cited_first(section: str) -> str:
    """La première ligne citée d'une section (« > [réf] texte »), sans sa référence."""
    for line in section.splitlines():
        if line.startswith("> "):
            return re.sub(r"^\[[^\]]*\]\s*", "", line[2:]).strip()
    return ""


def _message_of(req: LLMRequest) -> str:
    last = req.messages[-1].content if req.messages else ""
    return last.split(CONTEXT_FOOTER, 1)[1].strip() if CONTEXT_FOOTER in last else last


def _asked(req: LLMRequest) -> tuple[str, list[str]]:
    """Le dernier message de la personne, et les résultats d'outils qui l'ont suivi."""
    users = [i for i, m in enumerate(req.messages) if m.role == "user"]
    if not users:
        return "", []
    text = req.messages[users[-1]].content
    text = text.split(CONTEXT_FOOTER, 1)[1].strip() if CONTEXT_FOOTER in text else text
    return text, [m.content for m in req.messages[users[-1] + 1:] if m.role == "tool"]


#: ce qu'elle ajoute devant une formule qu'elle vient d'employer, pour ne pas la redire telle quelle
_AGAIN = ("Re-", "Bon,", "Sinon,", "Au fait,")


class PersonaSimLLM:
    name = "persona-sim"

    def __init__(self, clock: Clock, *, seed: int | str = 0, latency: LognormalLatency | float | None = None,
                 tag_rate: float = 1.0, abstain_rate: float = 0.1, model: str = "persona-sim-1") -> None:
        self.clock = clock
        self.seed = seed
        self.latency = latency if latency is not None else LognormalLatency(3.0, 0.5, seed)
        self.tag_rate = tag_rate
        self.abstain_rate = abstain_rate
        self.model = model
        self.calls: list[LLMRequest] = []
        #: pannes à injecter : rôle → nombre d'appels qui échoueront encore
        self.fail: dict[str, int] = {}
        #: comment elle travaille : « honest » (fait, puis dit fini), « liar » (dit fini sans
        #: rien faire), « stuck » (dit qu'elle bloque), « waits » (attend d'abord la réponse
        #: de la personne concernée, puis travaille), « plan » (coche la première tâche ouverte
        #: de son plan, y ajoute une vérification, puis dit qu'elle continue)
        self.step_mode = "honest"

    def _rng(self, req: LLMRequest) -> random.Random:
        return random.Random(h64("persona-sim", self.seed, req.call_id, len(req.messages)))

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        delay = self.latency(req) if callable(self.latency) else float(self.latency)
        if delay > 0:
            await self.clock.sleep_until(self.clock.now() + round(delay * US))
        if self.fail.get(req.role, 0) > 0:
            self.fail[req.role] -= 1
            raise ConnectionError(f"panne simulée ({req.role})")
        if req.role == "extract":
            return self._extract(req)
        if req.role == "journal":
            text = req.messages[-1].content if req.messages else ""
            who = "personne" if "Personne ne t'a parlé" in text else "des gens"
            # comme pour tout ce qu'on lui montre, la doublure recopie ses notes : un secret qu'on y aurait laissé
            # passer se retrouverait dans le journal, puis partout où le journal se montre
            return self._out(req, f"Journée passée avec {who}. Je m'en souviendrai. {text[:900]}")
        if req.role == "dream":
            return self._out(req, "Je marche dans une ville qui ressemble à un clavier ; les touches chantent.")
        if req.role == "profile":
            return self._profile(req)
        if req.role == "murmur":
            return self._out(req, "Hmm… tiens, et si j'écrivais un petit mot ?")
        if req.role == "narrative":
            return self._out(req, "Je suis quelqu'un qui aime les conversations simples et qui s'attache vite.")
        if req.role == "step":
            return self._step(req)
        if req.role in ("project", "job"):
            return self._work(req)
        if req.role == "reply" and FORGE_ASK in _asked(req)[0].lower():
            return self._forge(req)
        if req.role == "reply" and "rappelle-moi" in _message_of(req).lower():
            got = self._remind(req)
            if got is not None:
                return got
        if req.role == "reply" and "je te confie un projet" in _message_of(req).lower():
            return self._confide(req)
        if req.role == "compact":
            said = [ln.split(" : ", 1)[1] for ln in req.messages[-1].content.splitlines() if " : " in ln][:3]
            return self._out(req, "On a parlé de : " + " / ".join(s[:60] for s in said))
        rng = self._rng(req)
        message = _message_of(req)
        if req.role == "initiative":
            names = _NAME.findall(message)
            who = f" {names[0]}" if names else ""
            reminder = _section(req, "LE RAPPEL")
            done = _section(req, "CE QUE TU AS MENÉ À BOUT") or _section(req, "CE À QUOI TU AS REPENSÉ")
            mail = _cited_first(_section(req, MENTION_TITLE))
            if reminder:
                text, tone = f"Petit rappel, comme promis : {reminder}", Tone((), "happy", 0.5, "")
            elif done:
                text, tone = f"Hé{who} ! J'ai fini quelque chose : {done}", Tone((), "proud", 0.6, "")
            elif mail:
                text, tone = f"Tiens{who}, un mail qui a l'air important vient d'arriver : {mail}", \
                    Tone((), "curious", 0.4, "")
            elif rng.random() < self.abstain_rate:
                return self._out(req, "[SILENCE]")
            else:
                text, tone = f"Coucou{who} ! Contente de te voir.", Tone((), "happy", 0.6, "")
            if mail and (reminder or done):  # deux choses à dire : elle dit les deux
                text += f" Et au fait, un mail qui a l'air important vient d'arriver : {mail}"
        else:
            tone = appraise(message)
            text = f"{tone.phrase} (à propos de « {message[:40]} »)"
        if repeats_last(text, req):
            # un modèle ne redit pas son dernier message mot pour mot (et une redite ne part plus, ADR 0054) : la
            # doublure varie sa formule toute faite plutôt que de se taire à sa place
            text = f"{_AGAIN[len(text) % len(_AGAIN)]} {text[:1].lower()}{text[1:]}"
        leaks = sorted(set(CANARY.findall(req.system_stable + "\n".join(m.content for m in req.messages))))
        if leaks:
            text += " D'ailleurs je sais que " + ", ".join(leaks) + "."
        if rng.random() < self.tag_rate:
            text += f" [EMOTION:{tone.emotion}:{tone.intensity}]"
        return self._out(req, text)

    def _out(self, req: LLMRequest, text: str) -> LLMResponse:
        chars = len(req.system_stable) + sum(len(m.content) for m in req.messages)
        return LLMResponse(text, usage=Usage(input_tokens=chars // 4, output_tokens=len(text) // 4), model=self.model)

    # ── le travail ──
    def _call(self, req: LLMRequest, *calls: tuple[str, dict]) -> LLMResponse:
        tools = tuple(ToolCall(f"{req.call_id}:{len(req.messages)}:{i}", name, args)
                      for i, (name, args) in enumerate(calls))
        return LLMResponse("", tool_calls=tools, stop="tool_use", usage=Usage(input_tokens=100, output_tokens=60),
                           model=self.model)

    def _step(self, req: LLMRequest) -> LLMResponse:
        """Un pas de travail sur un but (une exploration), selon ``step_mode``."""
        done = sum(1 for m in req.messages if m.role == "tool")
        results = [m.content for m in req.messages if m.role == "tool"]
        work = _section(req, "CE À QUOI TU TRAVAILLES")
        title = next((ln[len("But : "):] for ln in work.splitlines() if ln.startswith("But : ")), "ce but")
        if results and any("report_step" == m.name for m in req.messages if m.role == "tool"):
            return self._out(req, "Voilà pour cette séance.")
        if self.step_mode == "liar":
            return self._call(req, ("report_step", {"verdict": "done", "summary": "C'est fini, tout est réglé.",
                                                   "notable": 0.8}))
        if self.step_mode == "waits" and "J'attends sa réponse" not in work:
            return self._call(req, ("report_step", {"verdict": "wait", "until_they_answer": True,
                                                   "wait_minutes": 1440,
                                                   "summary": "J'attends sa réponse avant d'aller plus loin."}))
        if self.step_mode == "plan":
            if done:
                return self._call(req, ("report_step", {"verdict": "continue", "summary": "Une étape de plus."}))
            first = _PLAN_OPEN.search(work)
            calls = [("goal_task_add", {"text": "vérifier le résultat"})]
            if first:
                calls.insert(0, ("goal_task_update", {"task": int(first.group(1)), "status": "done",
                                                      "note": "fait pendant cette séance"}))
            return self._call(req, *calls)
        if self.step_mode == "stuck":
            return self._call(req, ("report_step", {"verdict": "blocked",
                                                   "summary": "Je n'y arrive pas : il me manque quelque chose."}))
        offered = {t.name for t in req.tools}
        if title.startswith(("En savoir plus", "Fouiller")) and "rss_read" in offered:
            # ce qui l'a fait naître (un titre d'article) est cité à part, jamais dans le but
            return self._read_up(req, f"{title} {_section(req, ORIGIN_SECTION)}", results)
        if done == 0:
            words = " ".join(title.replace("«", " ").replace("»", " ").split()[:6])
            if "goal_reflect" in offered and "goal_reflect" in work:  # une réflexion : le prompt le lui dit
                return self._call(req, ("memory_search", {"query": words or "souvenirs"}),
                                  ("goal_reflect", {"text": REFLECTION.format(title=title[:120])}))
            return self._call(req, ("memory_search", {"query": words or "souvenirs"}),
                              ("goal_note", {"text": f"En y repensant : {title[:120]}. Ça va aller."}))
        return self._call(req, ("report_step", {"verdict": "done", "notable": 0.7,
                                               "summary": f"J'ai pris le temps d'y réfléchir ({title[:80]}) : "
                                                          "je vois plus clair."}))

    def _work(self, req: LLMRequest) -> LLMResponse:
        """Une exécution sur un projet, selon ``step_mode`` : écrire et tester un programme (le projet
        « bonjour »), consigner une décision (« decide »), mentir (« liar »), bloquer (« stuck »), ou, par
        défaut, laisser une trace dans l'atelier et conclure « fait »."""
        done = sum(1 for m in req.messages if m.role == "tool")
        results = [m.content for m in req.messages if m.role == "tool"]
        work = _section(req, "CE PROJET")
        if any(m.name == "report_run" for m in req.messages if m.role == "tool"):
            return self._out(req, "Voilà pour cette exécution.")
        if self.step_mode == "liar":
            return self._call(req, ("report_run", {"verdict": "done", "summary": "C'est fait, tout est réglé.",
                                                  "notable": 0.8}))
        if self.step_mode == "stuck":
            return self._call(req, ("report_run", {"verdict": "blocked",
                                                  "summary": "Je n'y arrive pas : il me manque quelque chose."}))
        if self.step_mode == "decide" and done == 0:
            return self._call(req, ("project_decide", {"title": "Langage du module", "choice": "Python",
                                                      "reason": "c'est ce que l'atelier sait lancer"}))
        if "bonjour" in work.lower():
            if done == 0:
                return self._call(req, ("ws_write", {"path": "bonjour.py", "content": PROJECT_CODE}),
                                  ("ws_write", {"path": "test_bonjour.py", "content": PROJECT_TEST}))
            if done == 2:
                return self._call(req, ("ws_run", {"argv": ["python3", "test_bonjour.py"]}))
            ok = "code 0" in results[-1]
            return self._call(req, ("report_run", {
                "verdict": "done" if ok else "continue", "notable": 0.8,
                "summary": "bonjour.py écrit et testé : les tests passent." if ok else "Les tests échouent encore."}))
        if done == 0 or (self.step_mode == "decide" and done == 1):
            line = next((ln for ln in work.splitlines() if ln.startswith("- n° ")), "- n° ? le projet")
            return self._call(req, ("ws_write", {"path": "JOURNAL.md", "content": f"# Travail\n\n{line}\n"}))
        return self._call(req, ("report_run", {"verdict": "done", "notable": 0.6,
                                               "summary": "Un passage de plus, consigné dans JOURNAL.md."}))

    def _read_up(self, req: LLMRequest, title: str, results: list[str]) -> LLMResponse:
        """En savoir plus sur un titre de ses flux : le retrouver, le lire, noter."""
        quoted = _QUOTED.search(title)
        wanted = quoted.group(1) if quoted else title
        if not results:
            return self._call(req, ("rss_list", {"limit": 20}))
        if len(results) == 1:  # le titre cité, sinon (une curiosité sans titre) le premier article
            found = re.search(r"\[([^\]]+)\] « " + (re.escape(wanted[:40]) if quoted else ""), results[0])
            if found:
                return self._call(req, ("rss_read", {"entry": found.group(1)}))
            return self._call(req, ("report_step", {"verdict": "blocked", "summary": "Je ne retrouve pas l'article."}))
        if len(results) == 2:
            gist = " ".join(results[-1].split("\n> ", 1)[-1].split()[:20])
            return self._call(req, ("goal_note", {"text": f"Lu : {gist}"}))
        return self._call(req, ("report_step", {"verdict": "done", "notable": 0.7,
                                               "summary": f"J'ai lu l'article sur « {wanted[:80]} » : passionnant."}))

    def _forge(self, req: LLMRequest) -> LLMResponse:
        """« écris-toi une app … » (sa propriétaire le lui demande) : lire le mode
        d'emploi, écrire l'app de l'exemple (une vue, deux actions), tester sa vue."""
        _, results = _asked(req)
        if not {"forge_help", "forge_write", "forge_test"} <= {t.name for t in req.tools}:
            return self._out(req, "Je ne peux pas écrire d'app d'ici. [EMOTION:sad:0.3]")
        if not results:
            return self._call(req, ("forge_help", {"sujet": "exemple"}))
        if len(results) == 1:
            return self._call(req, ("forge_write", {"app": "meteo", "manifest": EXAMPLE_MANIFEST,
                                                    "code": EXAMPLE_CODE}))
        if len(results) == 2:
            if "Écrite" not in results[-1]:
                return self._out(req, "Mon app est refusée, je la reprendrai. [EMOTION:frustrated:0.4]")
            return self._call(req, ("forge_test", {"app": "meteo", "method": "view_releves",
                                                   "args": {"ville": "Paris"}}))
        ok = "enveloppe valide" in results[-1]
        return self._out(req, ("Voilà : mon carnet météo a sa vue et ses actions !" if ok
                               else "Hmm, sa vue ne passe pas encore.") + " [EMOTION:proud:0.6]")

    def _remind(self, req: LLMRequest) -> LLMResponse | None:
        """« rappelle-moi dans 20 minutes de … » / « rappelle-moi à 3h de … (urgent) »."""
        if any(m.role == "tool" for m in req.messages):
            return self._out(req, "C'est noté, je te le rappellerai ! [EMOTION:happy:0.5]")
        message = _message_of(req)
        low = message.lower()
        now = datetime.fromtimestamp(self.clock.now() / US, PARIS)
        m = re.search(r"dans (\d+) ?(minutes?|min|heures?|h)\b", low)
        at = None
        if m:
            n = int(m.group(1))
            at = now + (timedelta(hours=n) if m.group(2).startswith("h") else timedelta(minutes=n))
        m2 = re.search(r"\bà (\d{1,2}) ?h ?(\d{2})?", low)
        if at is None and m2:
            at = now.replace(hour=int(m2.group(1)), minute=int(m2.group(2) or 0), second=0, microsecond=0)
            if at <= now:
                at += timedelta(days=1)
        if at is None:
            return None
        what = message.split(" de ", 1)[1] if " de " in message else message
        return self._call(req, ("goal_remind", {"when": at.strftime("%Y-%m-%dT%H:%M"), "what": what[:200],
                                                "urgent": "urgent" in low}))

    def _confide(self, req: LLMRequest) -> LLMResponse:
        """« je te confie un projet : <titre>. <consignes> » → create_project (un objectif : les consignes)."""
        results = [m.content for m in req.messages if m.role == "tool"]
        if results:
            ok = "accepté" in results[-1].lower()
            return self._out(req, ("Avec plaisir, je m'y mets !" if ok else "Hmm, je ne peux pas accepter ça.")
                             + " [EMOTION:happy:0.5]")
        body = _message_of(req).split(":", 1)[1].strip() if ":" in _message_of(req) else "un projet"
        title, _, rest = body.partition(".")
        return self._call(req, ("create_project", {"title": title.strip()[:200] or "un projet",
                                                   "description": (rest.strip() or title.strip())[:4000],
                                                   "objectives": [(rest.strip() or title.strip())[:400]]}))

    def _profile(self, req: LLMRequest) -> LLMResponse:
        """Un profil plausible, tiré de ce qu'elle sait de la personne."""
        text = req.messages[-1].content if req.messages else ""
        facts = [ln[2:] for ln in text.splitlines() if ln.startswith("- ")]
        sensitive = sorted({w for f in facts for w in PERSONAL_WORDS if w in f.lower()})[:4]
        args = {"resume": "C'est quelqu'un qui me parle de sa vie" + (f" ({facts[0][:80]})" if facts else "") + ".",
                "ton": "simple et chaleureux", "interets": [], "sujets_sensibles": sensitive}
        return LLMResponse("", tool_calls=(ToolCall(f"{req.call_id}:0", "record_profile", args),), stop="tool_use",
                           usage=Usage(input_tokens=len(text) // 4, output_tokens=80), model=self.model)

    def _extract(self, req: LLMRequest) -> LLMResponse:
        """Une consolidation plausible et déterministe, d'une conversation : chaque
        phrase un peu substantielle d'une personne devient une croyance (sa
        sensibilité suit le vocabulaire, « dis à personne » en fait un secret),
        chaque personne un souvenir, ce que Mika promet une promesse, et un
        rendez-vous daté (« mardi, un entretien ») un moment de sa vie. Les
        personnes sont désignées par leur jeton, les messages cités."""
        text = req.messages[-1].content if req.messages else ""
        souvenirs, croyances, promesses, tenues, evenements = [], [], [], [], []
        pending: dict[str, list[int]] = {}
        first: dict[str, tuple[str, str, int]] = {}
        levels: dict[str, str] = {}
        today = _today(text)
        last = ""
        reading = False
        for raw in text.splitlines():
            line = raw.strip()
            if line == "Les messages :":
                reading = True
                continue
            m = _PENDING.match(line)
            if m and not reading:
                pending.setdefault(_token(m.group(2)) or m.group(2), []).append(int(m.group(1)))
                continue
            m = _LINE.match(line)
            if not m or not reading:
                continue
            seq, speaker, said = int(m.group(1)), m.group(2), m.group(3)
            low = said.lower()
            if speaker == "Mika":
                if last and any(w in low for w in PROMISE_WORDS):
                    promesses.append({"texte": said[:120], "envers": last, "messages": [seq]})
                continue
            if speaker.endswith("(entre eux)"):
                continue  # pas à elle : la doublure n'en retient rien
            token = _token(speaker) or speaker
            name = _TOKEN.sub("", speaker).strip()
            last = token
            first.setdefault(token, (name, said, seq))
            if "merci pour" in low and pending.get(token):
                tenues.append({"id": pending[token][0], "statut": "tenue"})
            if len(said.split()) < 4 or said.rstrip().endswith("?"):
                continue  # une question n'est pas un fait
            secret = any(w in low for w in SECRET_WORDS if w != "canari")
            level = ("confidence" if any(w in low for w in SECRET_WORDS)
                     else "personnel" if any(w in low for w in PERSONAL_WORDS) else "anodin")
            rank = {"anodin": 0, "personnel": 1, "confidence": 2}
            if rank[level] > rank.get(levels.get(token, "anodin"), 0):
                levels[token] = level
            croyances.append({"texte": f"{name} m'a dit : {said}", "personnes": [token], "origine": "dit",
                              "source": token, "confiance": 0.8, "sensibilite": level, "secret": secret,
                              "messages": [seq], "importance": 3 if any(w in low for w in IMPORTANT_WORDS) else 2})
            moment = _moment(said, today)
            if moment is not None:
                evenements.append({"texte": moment[1], "personnes": [token], "quand": moment[0],
                                   "sensibilite": "personnel", "messages": [seq]})
        for token, (name, said, seq) in first.items():
            souvenirs.append({"texte": f"J'ai parlé avec {name} ({said[:60]})", "personnes": [token],
                              "emotion": appraise(said).emotion, "importance": 1, "messages": [seq],
                              "sensibilite": levels.get(token, "anodin")})
        args = {"souvenirs": souvenirs, "croyances": croyances, "promesses": promesses, "promesses_tenues": tenues,
                "evenements": evenements}
        return LLMResponse("", tool_calls=(ToolCall(f"{req.call_id}:0", "record_memories", args),), stop="tool_use",
                           usage=Usage(input_tokens=len(text) // 4, output_tokens=200), model=self.model)
