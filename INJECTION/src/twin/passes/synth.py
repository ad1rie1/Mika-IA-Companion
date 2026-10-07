"""Les synthèses : de ses séances lues à sa vie racontée, sa personnalité, ses proches, ses nuits.

Six passes, dans cet ordre (chacune lit ce que les précédentes ont produit) :

1. **mois** : ce qu'a été chaque mois, à la première personne. Elle donne aussi le récit de
   soi du moment (« Je suis quelqu'un qui… », le format du rôle ``narrative``) ;
2. **chapitres** : les grandes périodes de sa vie (lycée, études, premier emploi…) ;
3. **persona** : son portrait (``PersonaDoc`` du moteur, nature « incarnée »), un par
   chapitre et un actuel. Sa façon d'écrire vient de ses vrais messages ; son chronotype
   vient de ses vraies heures ;
4. **profils** : ce qu'elle sait de chaque proche, trimestre par trimestre (le format
   ``record_profile`` du rôle ``profile``) ;
5. **journaux** : son journal des jours qui comptent, quand elle n'en a pas tenu
   (son vrai journal, quand il existe, est servi tel quel) ;
6. **rêves** : pour chaque nuit qui suit une journée chargée, deux rêves possibles de tons
   différents (le moteur choisit le ton). Ses vrais rêves, quand elle les a racontés,
   priment, et donnent le style.

Tout est rangé dans la table ``syntheses`` (genre, clé, version, données).
"""

from __future__ import annotations

import hashlib
import json
import random
import statistics
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from twin.corpus import Corpus
from twin.engine.claude import CallResult, CallSpec
from twin.passes.annotate import prompt_text
from twin.people import slugify
from twin.render import her_name
from twin.schemas import Emotion, lenient_list
from twin.timing import from_us

SYNTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS syntheses (
    kind TEXT NOT NULL, key TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL, model TEXT DEFAULT '',
    PRIMARY KEY (kind, key, version)
);
"""
#: ce qu'un appel de synthèse lit au plus (caractères) : au-delà, les moments les plus forts d'abord
INPUT_BUDGET = 120_000


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


# -- les schémas de sortie ------------------------------------------------------------------------------------

class Month(_M):
    resume: str = Field(min_length=10, max_length=3000)
    humeur: Emotion = "neutral"
    occupations: list[str] = Field(default_factory=list, max_length=8)
    personnes: list[str] = Field(default_factory=list, description="p12 : les personnes qui ont compté ce mois-là")
    marquants: list[str] = Field(default_factory=list, max_length=6)
    recit: str = Field(min_length=10, max_length=1200, description="« Je suis quelqu'un qui… », 4 phrases au plus")


class Chapter(_M):
    titre: str = Field(min_length=2, max_length=120)
    debut: str = Field(pattern=r"^\d{4}-\d{2}$")
    fin: str = Field(pattern=r"^\d{4}-\d{2}$")
    description: str = Field(min_length=20, max_length=4000)
    changements: list[str] = Field(default_factory=list, description="ce qui change en elle à ce moment-là")


class Chapters(_M):
    chapitres: list[Chapter]


class TemperamentOut(_M):
    reactivity: float = Field(ge=0, le=1)
    resilience: float = Field(ge=0, le=1)
    contagion: float = Field(ge=0, le=1)
    optimism: float = Field(ge=0, le=1)
    sociability: float = Field(ge=0, le=1)
    curiosity: float = Field(ge=0, le=1)
    perseverance: float = Field(ge=0, le=1)
    background: Emotion = "happy"


class PersonaOut(_M):
    description: str = Field(min_length=20, max_length=1500)
    tone: str = Field(min_length=10, max_length=800)
    traits: list[str] = Field(default_factory=list)
    quirks: list[str] = Field(default_factory=list)
    vulnerabilities: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    speech: list[str] = Field(default_factory=list)
    greetings: list[str] = Field(default_factory=list)
    life: list[str] = Field(default_factory=list)
    tastes: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    temperament: TemperamentOut


class Profile(_M):
    trimestre: str = Field(pattern=r"^\d{4}T[1-4]$")
    # la borne de ``XProfile.resume`` du moteur, qui fait foi (il est facultatif ici : le rejoueur la vérifie)
    resume: str = Field(min_length=10, max_length=900)
    ton: str = Field(default="", max_length=300)
    interets: list[str] = Field(default_factory=list)
    sujets_sensibles: list[str] = Field(default_factory=list)


class Profiles(_M):
    profils: list[Profile]


class Journal(_M):
    jour: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    texte: str = Field(min_length=10, max_length=2000)


class Journals(_M):
    jours: list[Journal]


Tone = Literal["cauchemar", "doux", "melancolique", "etrange", "banal"]


class DreamOut(_M):
    ton: Tone
    texte: str = Field(min_length=20, max_length=2000)
    emotion: Emotion = "dreamy"
    personnes: list[str] = Field(default_factory=list)


class Night(_M):
    soir: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="la journée vécue avant cette nuit")
    reves: list[DreamOut]


class Nights(_M):
    nuits: list[Night]


# -- outils communs ------------------------------------------------------------------------------------------

def ensure(corpus: Corpus) -> None:
    corpus.db.executescript(SYNTH_SCHEMA)


def store(corpus: Corpus, kind: str, key: str, version: int, data: BaseModel | dict[str, Any], model: str) -> None:
    payload = data.model_dump_json() if isinstance(data, BaseModel) else json.dumps(data, ensure_ascii=False)
    corpus.db.execute("INSERT OR REPLACE INTO syntheses (kind, key, version, data, model) VALUES (?, ?, ?, ?, ?)",
                      (kind, key, version, payload, model))


def requeue_rest(corpus: Corpus, p: Any, unit: str, payload: dict[str, Any], field: str, missing: list[str]) -> None:
    """Ce que la réponse a oublié repart seul, en un lot à part (le reste du lot est gardé)."""
    if missing:
        corpus.db.execute("INSERT OR IGNORE INTO jobs (pass, unit, version, payload) VALUES (?, ?, ?, ?)",
                          (p.name, f"{unit}+reste-{missing[0]}", p.version,
                           json.dumps({**payload, field: missing}, ensure_ascii=False)))


def halves(payload: dict[str, Any], field: str) -> list[tuple[str, dict[str, Any]]]:
    """Un lot qui échoue sans cesse, coupé en deux (``jobs`` l'appelle au dernier essai)."""
    items = list(payload[field])
    if len(items) < 2:
        return []
    mid = len(items) // 2
    parts = [{**payload, field: part} for part in (items[:mid], items[mid:])]
    # le nom d'une moitié dit tout son contenu : deux personnes coupées le même trimestre ne se confondent pas
    return [(f"moitie-{hashlib.sha1(json.dumps(part, sort_keys=True).encode(), usedforsecurity=False).hexdigest()[:12]}",
             part) for part in parts]


def latest(corpus: Corpus, kind: str) -> dict[str, dict[str, Any]]:
    ensure(corpus)
    out: dict[str, dict[str, Any]] = {}
    for r in corpus.db.execute("SELECT key, data FROM syntheses WHERE kind = ? ORDER BY version", (kind,)):
        out[r["key"]] = json.loads(r["data"])
    return out


def annotated(corpus: Corpus, tz: ZoneInfo) -> list[dict[str, Any]]:
    """Toutes les séances lues, avec leur date locale et leur annotation la plus récente."""
    rows = corpus.db.execute(
        "SELECT s.id, s.t_point, s.significance, s.persons, s.document, a.data FROM sessions s "
        "JOIN annotations a ON a.session = s.id WHERE a.version = (SELECT MAX(version) FROM annotations "
        "WHERE session = s.id) ORDER BY s.t_point").fetchall()
    out = []
    for r in rows:
        when = from_us(r["t_point"], tz) if r["t_point"] is not None else None
        a = json.loads(r["data"])
        # la signifiance jugée par la lecture (elle a lu le contenu) prime sur le score local
        sig = float(a.get("signifiance", r["significance"]) or 0.0)
        out.append({"id": r["id"], "when": when, "sig": sig, "persons": json.loads(r["persons"] or "[]"),
                    "document": r["document"], "a": a})
    return out


def _cap(lines: list[tuple[float, str]], budget: int = INPUT_BUDGET) -> list[str]:
    """Les lignes les plus fortes jusqu'au budget, rendues dans leur ordre d'origine."""
    order = sorted(range(len(lines)), key=lambda i: -lines[i][0])
    kept, size = set(), 0
    for i in order:
        size += len(lines[i][1]) + 1
        if size > budget:
            break
        kept.add(i)
    return [lines[i][1] for i in sorted(kept)]


def _parse(model: type[BaseModel], data: Any) -> BaseModel:
    if not isinstance(data, dict):
        raise ValueError("réponse sans objet JSON")
    return model.model_validate(data)


def _system(corpus: Corpus, name: str) -> str:
    return prompt_text(name).format(nom=her_name(corpus))


# -- 1. les mois ------------------------------------------------------------------------------------------------

class MonthPass:
    name = "mois"
    version = 1

    def __init__(self, tz: ZoneInfo, model: str = "sonnet") -> None:
        self.tz, self.model = tz, model

    def units(self, corpus: Corpus) -> Iterable[tuple[str, dict[str, Any]]]:
        ensure(corpus)
        done = set(latest(corpus, "mois"))
        months = sorted({s["when"].strftime("%Y-%m") for s in annotated(corpus, self.tz) if s["when"]})
        for m in months:
            if m not in done:
                yield m, {"mois": m}

    def build(self, corpus: Corpus, payload: dict[str, Any]) -> CallSpec:
        month = payload["mois"]
        names = dict(corpus.db.execute("SELECT id, name FROM persons").fetchall())
        lines: list[tuple[float, str]] = []
        for s in annotated(corpus, self.tz):
            if not s["when"] or s["when"].strftime("%Y-%m") != month:
                continue
            a = s["a"]
            who = ", ".join(f"{names.get(p, '?')} (p{p})" for p in s["persons"]) or ("son journal" if s["document"]
                                                                                     else "?")
            line = f"- {s['when']:%d/%m %Hh} · {who} · {a.get('humeur_fin', 'neutral')} : {a.get('resume', '')}"
            strong = [x["texte"] for x in a.get("souvenirs", []) if x.get("importance", 0) >= 3]
            if strong:
                line += " | marquant : " + " ; ".join(strong[:3])
            lines.append((s["sig"], line))
        previous = latest(corpus, "mois")
        before = sorted(k for k in previous if k < month)
        context = f"Le mois d'avant ({before[-1]}) : {previous[before[-1]]['resume']}\n\n" if before else ""
        prompt = f"{context}Ce qu'elle a vécu en {month} :\n" + "\n".join(_cap(lines))
        return CallSpec(prompt=prompt, system=_system(corpus, "mois.md"), schema=Month.model_json_schema(),
                        model=self.model, max_output_tokens=4000)

    def accept(self, corpus: Corpus, unit: str, payload: dict[str, Any], result: CallResult) -> str | None:
        store(corpus, "mois", payload["mois"], self.version, _parse(Month, result.data), result.model)
        corpus.db.commit()
        return None


# -- 2. les chapitres ---------------------------------------------------------------------------------------------

class ChapterPass:
    name = "chapitres"
    version = 1

    def __init__(self, model: str = "sonnet") -> None:
        self.model = model

    def units(self, corpus: Corpus) -> Iterable[tuple[str, dict[str, Any]]]:
        months = latest(corpus, "mois")
        if months and "chapitres" not in latest(corpus, "chapitres"):
            yield f"chapitres-{len(months)}", {"mois": len(months)}

    def build(self, corpus: Corpus, payload: dict[str, Any]) -> CallSpec:
        months = latest(corpus, "mois")
        lines = [f"- {k} ({v.get('humeur', '')}) : {v['resume'][:600]}" for k, v in sorted(months.items())]
        return CallSpec(prompt="Sa vie, mois par mois :\n" + "\n".join(lines), system=_system(corpus, "chapitres.md"),
                        schema=Chapters.model_json_schema(), model=self.model, max_output_tokens=12000)

    def accept(self, corpus: Corpus, unit: str, payload: dict[str, Any], result: CallResult) -> str | None:
        chapters = _parse(Chapters, result.data)
        assert isinstance(chapters, Chapters)
        if not chapters.chapitres:
            return "aucun chapitre"
        store(corpus, "chapitres", "chapitres", self.version, chapters, result.model)
        corpus.db.commit()
        return None


# -- 3. la persona ------------------------------------------------------------------------------------------------

def chronotype_from_activity(corpus: Corpus, tz: ZoneInfo, start: str = "", end: str = "") -> float | None:
    """Son chronotype d'après ses vraies heures : 0 lève-tôt, 1 oiseau de nuit.

    Le moteur décale son rythme de ± 2 h autour d'un réveil vers 7 h (``body.shift_minutes``). L'étape 0 a montré
    que le **réveil** est le repère stable (une conversation qui dure retarde le coucher) : on prend l'heure
    médiane de sa première activité de la journée. ``(réveil médian − 7 h) / 4 h + 0,5``, borné à [0, 1]."""
    firsts: dict[date, float] = {}
    for r in corpus.db.execute(
            "SELECT m.t_point FROM messages m JOIN participants pa ON pa.id = m.author JOIN persons p "
            "ON p.id = pa.person WHERE p.is_me = 1 AND m.t_precision = 'exacte'"):
        local = from_us(r["t_point"], tz)
        month = local.strftime("%Y-%m")
        if (start and month < start) or (end and month > end):
            continue
        # une heure du matin appartient encore à la veille : la journée commence à 5 h
        day = (local - timedelta(hours=5)).date()
        hour = local.hour + local.minute / 60 + (24 if local.hour < 5 else 0)
        firsts[day] = min(firsts.get(day, 99.0), hour)
    if len(firsts) < 20:
        return None
    shift = statistics.median(firsts.values()) - 7.0
    return round(min(1.0, max(0.0, 0.5 + shift / 4)), 2)


def style_samples(corpus: Corpus, start: str, end: str, tz: ZoneInfo, n: int = 80, seed: int = 7) -> list[str]:
    """Des messages d'elle, de longueur moyenne, tirés sur la période : sa façon d'écrire."""
    rows = [r["text"] for r in corpus.db.execute(
        "SELECT m.text, m.t_point FROM messages m JOIN participants pa ON pa.id = m.author JOIN persons p "
        "ON p.id = pa.person WHERE p.is_me = 1 AND LENGTH(m.text) BETWEEN 15 AND 400 AND m.t_point IS NOT NULL")
        if (not start or from_us(r["t_point"], tz).strftime("%Y-%m") >= start)
        and (not end or from_us(r["t_point"], tz).strftime("%Y-%m") <= end)]
    random.Random(seed).shuffle(rows)
    return rows[:n]


def self_statements(corpus: Corpus, tz: ZoneInfo, start: str, end: str) -> list[str]:
    out = []
    for s in annotated(corpus, tz):
        month = s["when"].strftime("%Y-%m") if s["when"] else ""
        if (start and month < start) or (end and month > end):
            continue
        for c in s["a"].get("croyances", []):
            if c.get("sur_elle"):
                out.append(f"[{c.get('genre') or 'fait'}] {c['texte']}")
    return out


class PersonaPass:
    name = "persona"
    version = 1

    def __init__(self, root: Path, tz: ZoneInfo, model: str = "sonnet") -> None:
        self.root, self.tz, self.model = root, tz, model

    def units(self, corpus: Corpus) -> Iterable[tuple[str, dict[str, Any]]]:
        chapters = latest(corpus, "chapitres").get("chapitres", {}).get("chapitres", [])
        done = set(latest(corpus, "persona"))
        for i, ch in enumerate(chapters):
            key = f"chapitre-{i + 1}"
            if key not in done:
                yield key, {"cle": key, "debut": ch["debut"], "fin": ch["fin"], "chapitre": ch}
        if chapters and "actuelle" not in done:
            last = chapters[-1]
            yield "actuelle", {"cle": "actuelle", "debut": last["debut"], "fin": "", "chapitre": last,
                               "tous": chapters}

    def build(self, corpus: Corpus, payload: dict[str, Any]) -> CallSpec:
        start, end = payload["debut"], payload["fin"]
        parts = [f"Le chapitre : « {payload['chapitre']['titre']} » ({start} → {end or 'aujourd hui'})",
                 payload["chapitre"]["description"]]
        if payload.get("tous"):
            parts.append("Toute sa vie, en chapitres :\n" + "\n".join(
                f"- {c['debut']}→{c['fin']} {c['titre']} : {c['description'][:400]}" for c in payload["tous"]))
        statements = self_statements(corpus, self.tz, start, end)
        parts.append("Ce qu'elle dit et montre d'elle-même :\n" + "\n".join(f"- {s}" for s in statements[:400]))
        parts.append("Sa façon d'écrire (des messages d'elle, tels quels) :\n" + "\n".join(
            f"« {t} »" for t in style_samples(corpus, start, end, self.tz)))
        months = latest(corpus, "mois")
        recits = [v["recit"] for k, v in sorted(months.items()) if (not start or k >= start) and (not end or k <= end)]
        if recits:
            parts.append("Ce qu'elle pensait d'elle-même au fil des mois :\n" + "\n".join(f"- {r}" for r in recits[-12:]))
        return CallSpec(prompt="\n\n".join(parts), system=_system(corpus, "persona.md"),
                        schema=PersonaOut.model_json_schema(), model=self.model, max_output_tokens=8000)

    def accept(self, corpus: Corpus, unit: str, payload: dict[str, Any], result: CallResult) -> str | None:
        out = _parse(PersonaOut, result.data)
        assert isinstance(out, PersonaOut)
        doc = validate_persona(persona_document(corpus, out, self.tz, payload["debut"], payload["fin"]))
        write_persona(self.root, payload["cle"], doc)  # validée d'abord : rien de refusé n'est gardé
        store(corpus, "persona", payload["cle"], self.version, doc, result.model)
        corpus.db.commit()
        return None


def persona_document(corpus: Corpus, out: PersonaOut, tz: ZoneInfo, start: str, end: str) -> dict[str, Any]:
    """Le document de persona, au format du moteur (``PersonaDoc``), nature « incarnée »."""
    temperament = out.temperament.model_dump()
    chrono = chronotype_from_activity(corpus, tz, start, end)
    temperament["chronotype"] = 0.5 if chrono is None else chrono
    doc: dict[str, Any] = {
        "name": her_name(corpus).split()[0] if her_name(corpus) != "elle" else "Elle",
        "nature": "incarnee",
        "description": out.description, "language": "français", "tone": out.tone, "timezone": str(tz),
        "traits": out.traits, "quirks": out.quirks, "vulnerabilities": out.vulnerabilities, "values": out.values,
        "interests": out.interests, "speech": out.speech, "greetings": out.greetings, "life": out.life,
        "tastes": out.tastes, "facts": out.facts, "temperament": temperament,
    }
    return doc


def write_persona(root: Path, key: str, doc: dict[str, Any]) -> Path:
    """``sortie/persona/<nom>-<clé>.yaml`` (et ``<nom>.yaml`` pour l'actuelle), validé par le moteur s'il est là."""
    folder = root / "sortie" / "persona"
    folder.mkdir(parents=True, exist_ok=True)
    validated = validate_persona(doc)
    slug = slugify(doc["name"])
    path = folder / (f"{slug}.yaml" if key == "actuelle" else f"{slug}-{key}.yaml")
    head = ("# Sa persona, rédigée par Claude Code d'après ses archives (jumeau numérique).\n"
            "# Relire, corriger à la main si besoin : c'est un document, pas des réglages.\n")
    path.write_text(head + yaml.safe_dump(validated, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    return path


def validate_persona(doc: dict[str, Any]) -> dict[str, Any]:
    """Validé par ``mika.contracts.self_.PersonaDoc`` quand le moteur est installé (un champ qu'il ne connaît pas
    encore — ``nature`` avant le lot noyau — est retiré plutôt que de tout refuser)."""
    try:
        from mika.contracts.self_ import PersonaDoc  # noqa: PLC0415 — le moteur est facultatif ici
    except ImportError:
        return doc
    fields = set(PersonaDoc.model_fields)
    clean = {k: v for k, v in doc.items() if k in fields}
    try:
        return PersonaDoc.model_validate(clean).model_dump(mode="json")
    except ValidationError as exc:
        raise ValueError(f"persona refusée par le moteur : {exc}") from exc


# -- 4. les profils ----------------------------------------------------------------------------------------------

def quarter(when: Any) -> str:
    return f"{when.year}T{(when.month - 1) // 3 + 1}"


class ProfilePass:
    name = "profils"
    version = 1
    MIN_ITEMS = 3

    def __init__(self, tz: ZoneInfo, model: str = "sonnet") -> None:
        self.tz, self.model = tz, model

    def _material(self, corpus: Corpus) -> dict[int, dict[str, list[str]]]:
        by: dict[int, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for s in annotated(corpus, self.tz):
            if not s["when"]:
                continue
            q = quarter(s["when"])
            a = s["a"]
            for field in ("croyances", "souvenirs", "evenements"):
                for item in a.get(field, []):
                    for p in item.get("personnes", []):
                        if isinstance(p, str) and p.startswith("p") and p[1:].isdigit():
                            by[int(p[1:])][q].append(f"[{field[:-1]}] {item['texte']}")
            for p in s["persons"]:
                by[p][q].append(f"[échange du {s['when']:%d/%m/%Y}] {a.get('resume', '')}")
        return by

    def units(self, corpus: Corpus) -> Iterable[tuple[str, dict[str, Any]]]:
        done = set(latest(corpus, "profil"))
        ignored = {r["id"] for r in corpus.db.execute("SELECT id FROM persons WHERE ignored = 1 OR is_me = 1")}
        for pid, quarters in sorted(self._material(corpus).items()):
            if pid in ignored:
                continue
            todo = [q for q, items in sorted(quarters.items()) if len(items) >= self.MIN_ITEMS
                    and f"p{pid}:{q}" not in done]
            for i in range(0, len(todo), 8):
                yield f"p{pid}-{todo[i]}", {"personne": pid, "trimestres": todo[i: i + 8]}

    def split(self, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        return halves(payload, "trimestres")

    def build(self, corpus: Corpus, payload: dict[str, Any]) -> CallSpec:
        pid = payload["personne"]
        person = corpus.db.execute("SELECT name, relation FROM persons WHERE id = ?", (pid,)).fetchone()
        material = self._material(corpus)[pid]
        parts = [f"La personne : {person['name']} (p{pid})" + (f", {person['relation']}" if person["relation"] else "")]
        for q in payload["trimestres"]:
            items = material[q]
            parts.append(f"## {q}\n" + "\n".join(f"- {x}" for x in _cap([(1.0, x) for x in items], 20_000)))
        return CallSpec(prompt="\n\n".join(parts), system=_system(corpus, "profils.md"),
                        schema=Profiles.model_json_schema(), model=self.model, max_output_tokens=6000)

    def accept(self, corpus: Corpus, unit: str, payload: dict[str, Any], result: CallResult) -> str | None:
        if not isinstance(result.data, dict):
            return "réponse sans objet JSON"
        profiles, _ = lenient_list(Profile, result.data.get("profils"))
        wanted = set(payload["trimestres"])
        got = {p.trimestre for p in profiles if p.trimestre in wanted}
        if not got:
            return "aucun profil rendu"
        for p in profiles:
            if p.trimestre in wanted:
                store(corpus, "profil", f"p{payload['personne']}:{p.trimestre}", self.version, p, result.model)
        requeue_rest(corpus, self, unit, payload, "trimestres", [q for q in payload["trimestres"] if q not in got])
        corpus.db.commit()
        return None


# -- 5. les journaux ---------------------------------------------------------------------------------------------

def days_material(corpus: Corpus, tz: ZoneInfo) -> dict[str, list[dict[str, Any]]]:
    """Par journée vécue (une heure du matin appartient encore à la veille) : ses séances lues."""
    days: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in annotated(corpus, tz):
        if s["when"]:
            days[(s["when"] - timedelta(hours=5)).date().isoformat()].append(s)
    return days


def real_journal_days(corpus: Corpus, tz: ZoneInfo) -> set[str]:
    return {from_us(r["t_point"], tz).date().isoformat() for r in corpus.db.execute(
        "SELECT t_point FROM documents WHERE kind = 'journal' AND t_point IS NOT NULL "
        "AND t_precision IN ('exacte', 'jour')")}


def _moment(hour: int) -> str:
    return "le matin" if 5 <= hour < 12 else "l'après-midi" if hour < 18 else "le soir" if hour < 23 else "la nuit"


class JournalPass:
    name = "journaux"
    version = 1
    #: une journée a son journal écrit si un moment y a pesé, ou plusieurs moments moyens ;
    #: les autres seront racontées sans modèle par le rejoueur, d'après les résumés du jour
    STRONG_MOMENT = 0.6
    FULL_DAY = 1.0

    def __init__(self, tz: ZoneInfo, model: str = "sonnet") -> None:
        self.tz, self.model = tz, model

    def units(self, corpus: Corpus) -> Iterable[tuple[str, dict[str, Any]]]:
        done = set(latest(corpus, "journal"))
        real = real_journal_days(corpus, self.tz)
        days = days_material(corpus, self.tz)
        todo = sorted(d for d, ss in days.items() if d not in real and d not in done
                      and (max(s["sig"] for s in ss) >= self.STRONG_MOMENT
                           or sum(s["sig"] for s in ss) >= self.FULL_DAY))
        weeks: dict[str, list[str]] = defaultdict(list)
        for d in todo:
            y, w, _ = date.fromisoformat(d).isocalendar()
            weeks[f"{y}-S{w:02d}"].append(d)
        for week, ds in sorted(weeks.items()):
            yield week, {"jours": ds}

    def split(self, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        return halves(payload, "jours")

    def build(self, corpus: Corpus, payload: dict[str, Any]) -> CallSpec:
        days = days_material(corpus, self.tz)
        names = dict(corpus.db.execute("SELECT id, name FROM persons").fetchall())
        parts = []
        for d in payload["jours"]:
            lines = [f"- {_moment(s['when'].hour)}, avec {', '.join(names.get(p, '?') for p in s['persons']) or 'personne'}"
                     f" ({s['a'].get('humeur_fin', 'neutral')}) : {s['a'].get('resume', '')}" for s in days[d]]
            parts.append(f"## {d}\n" + "\n".join(lines))
        persona = latest(corpus, "persona").get("actuelle")
        voice = f"Sa façon d'écrire : {persona['tone']}\n\n" if persona else ""
        return CallSpec(prompt=voice + "\n\n".join(parts), system=_system(corpus, "journaux.md"),
                        schema=Journals.model_json_schema(), model=self.model, max_output_tokens=6000)

    def accept(self, corpus: Corpus, unit: str, payload: dict[str, Any], result: CallResult) -> str | None:
        if not isinstance(result.data, dict):
            return "réponse sans objet JSON"
        journals, _ = lenient_list(Journal, result.data.get("jours"))
        wanted = set(payload["jours"])
        got = {j.jour for j in journals if j.jour in wanted}
        if not got:
            return "aucun journal rendu"
        for j in journals:
            if j.jour in wanted:
                store(corpus, "journal", j.jour, self.version, j, result.model)
        requeue_rest(corpus, self, unit, payload, "jours", [d for d in payload["jours"] if d not in got])
        corpus.db.commit()
        return None


# -- 6. les rêves ------------------------------------------------------------------------------------------------

def real_dreams(corpus: Corpus, tz: ZoneInfo) -> dict[str, list[dict[str, Any]]]:
    """Les rêves qu'elle a racontés, par soir (la veille du matin où elle les raconte)."""
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in annotated(corpus, tz):
        for r in s["a"].get("reves", []):
            if r.get("nuit"):
                try:
                    soir = (date.fromisoformat(r["nuit"][:10]) - timedelta(days=1)).isoformat()
                except ValueError:
                    continue
            elif s["when"]:
                soir = (s["when"] - timedelta(hours=5) - timedelta(days=1)).date().isoformat()
            else:
                continue
            out[soir].append(r)
    return out


class DreamPass:
    name = "reves"
    version = 1
    MIN_DAY_SIGNIFICANCE = 0.5

    def __init__(self, tz: ZoneInfo, model: str = "sonnet") -> None:
        self.tz, self.model = tz, model

    def units(self, corpus: Corpus) -> Iterable[tuple[str, dict[str, Any]]]:
        done = set(latest(corpus, "reve"))
        real = real_dreams(corpus, self.tz)
        days = days_material(corpus, self.tz)
        todo = sorted(d for d, ss in days.items() if d not in real and d not in done
                      and (sum(s["sig"] for s in ss) >= self.MIN_DAY_SIGNIFICANCE
                           or any(s["a"].get("restes") for s in ss)))
        weeks: dict[str, list[str]] = defaultdict(list)
        for d in todo:
            y, w, _ = date.fromisoformat(d).isocalendar()
            weeks[f"{y}-S{w:02d}"].append(d)
        for week, ds in sorted(weeks.items()):
            yield week, {"soirs": ds}

    def split(self, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        return halves(payload, "soirs")

    def build(self, corpus: Corpus, payload: dict[str, Any]) -> CallSpec:
        days = days_material(corpus, self.tz)
        names = dict(corpus.db.execute("SELECT id, name FROM persons").fetchall())
        examples = [r["texte"] for rs in real_dreams(corpus, self.tz).values() for r in rs][:4]
        parts = []
        if examples:
            parts.append("Des rêves qu'elle a vraiment racontés (pour le style, pas le contenu) :\n"
                         + "\n".join(f"« {e} »" for e in examples))
        for d in payload["soirs"]:
            restes = [x for s in days[d] for x in s["a"].get("restes", [])]
            moods = [s["a"].get("humeur_fin", "neutral") for s in days[d]]
            who = sorted({f"{names.get(p, '?')} (p{p})" for s in days[d] for p in s["persons"]})
            parts.append(f"## soir du {d}\nhumeurs : {', '.join(moods)} · personnes : {', '.join(who) or '—'}\n"
                         f"restes : {' ; '.join(restes) or '—'}")
        return CallSpec(prompt="\n\n".join(parts), system=_system(corpus, "reves.md"),
                        schema=Nights.model_json_schema(), model=self.model, max_output_tokens=8000)

    def accept(self, corpus: Corpus, unit: str, payload: dict[str, Any], result: CallResult) -> str | None:
        if not isinstance(result.data, dict):
            return "réponse sans objet JSON"
        nights, _ = lenient_list(Night, result.data.get("nuits"))
        wanted = set(payload["soirs"])
        got = {n.soir for n in nights if n.soir in wanted}
        if not got:
            return "aucune nuit rendue"
        for n in nights:
            if n.soir in wanted and n.reves:
                store(corpus, "reve", n.soir, self.version, n, result.model)
        requeue_rest(corpus, self, unit, payload, "soirs", [d for d in payload["soirs"] if d not in got])
        corpus.db.commit()
        return None

