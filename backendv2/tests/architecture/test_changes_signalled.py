"""Une politique : toute écriture d'une base tenue à côté du journal dit ce qu'elle change (ADR 0308).

Le courrier relevé (``MailCache``), le cache de Teams (``TeamsStore``), l'annuaire (``ContactsStore``) et l'agenda
(``AgendaStore``, ADR 0309) s'écrivent hors du journal : rien d'autre qu'eux ne sait qu'un mail est arrivé, qu'un envoi
est parti, qu'un contact ou un rendez-vous a changé. Les écrans de tous les jours ne le voient en direct que si chaque
écriture le dit. Cette garde relit leur code (``ast``, sans importer mika) :

- **une seule porte d'écriture** par base (``_use(write=True)`` pour le courrier, ``_writing()`` pour les autres) :
  c'est la seule à ouvrir une transaction (``self._session.begin()``), et elle passe par ``self._changes.writing()`` —
  ce qui y est noté ne part qu'une fois la transaction validée, rien si elle est annulée ;
- **toute méthode publique qui écrit** (par la porte, ou par une méthode de la classe qui écrit) **dit ce qui change**
  (``self._changed(…)``, elle-même ou par une méthode de la classe qui le dit) — sauf la tenue de la base que rien ne
  montre à une personne, excusée dans ``QUIET`` avec sa raison ; une excuse qui ne sert plus fait échouer la garde ;
- les sujets du code (``ports/changes.py``) sont ceux du contrat (``docs/protocole-moi.md``, § 2 bis), et leurs clés ;
- ``STORES`` est une liste fermée : **toute classe d'``adapters/`` qui dit ses changements** — elle tient un
  ``Changes`` (``adapters/changes.py``) ou se fait écouter par ``on_change`` — y est, ou dans ``WRITERS``, ou est
  excusée dans ``NOT_STORES`` avec sa raison. Une base neuve qu'on oublierait d'y inscrire échapperait sinon à tout
  ce qui précède.

Deux autres s'écrivent hors du journal sans être des bases à côté, et changent aussi ce que montrent des routes de
``/api/moi`` : les comptes (``Accounts`` : un nom, un téléphone qui reçoit ses notifications) et les réglages
(``Settings`` : une boîte, sa connexion Microsoft, un compte Teams, les règles d'envoi…). Pour eux, **toute méthode
publique qui écrit** (``self.store.run_mind(…)``, elle-même ou par une méthode de la classe) **le dit** (``_changed``
pour les comptes ; ``_saved`` pour les réglages, que leur seule porte, ``_put``, appelle) — sauf ce qu'aucun écran ne
montre, excusé dans ``QUIET`` avec sa raison.

Le contrôle est une fonction du texte des sources (``offences``) : les derniers tests l'essaient sur un petit source
factice, pour qu'il échoue vraiment quand on retire un appel.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "mika"
CONTRACT = ROOT / "docs" / "protocole-moi.md"

#: chaque base tenue à côté : son fichier, sa classe, sa porte d'écriture
STORES = (("adapters/mail/cache.py", "MailCache", "_use"),
          ("adapters/teams/store.py", "TeamsStore", "_writing"),
          ("adapters/contacts/store.py", "ContactsStore", "_writing"),
          ("adapters/agenda/store.py", "AgendaStore", "_writing"))
#: les écritures que rien ne montre à une personne, et pourquoi
QUIET = {
    ("MailCache", "hand"): "« rendu une fois » : la tenue de la relève, que seul son tri lit",
    ("MailCache", "seen_elsewhere"): "« lu ailleurs, à lui dire » : la tenue de la relève, que seul son tri lit ; le "
                                     "drapeau lui-même se dit par ``set_flags``",
    ("MailCache", "take_seen_elsewhere"): "sa relève vide ce qui restait à lui dire : rien qu'un écran montre",
    ("TeamsStore", "ack"): "rendu à son tri : ce qu'elle en remarque se dit au journal (``teams.noticed``)",
    ("ContactsStore", "set_cursor"): "le curseur d'une source : où l'annuaire en est de sa lecture",
    ("ContactsStore", "dismiss"): "une paire écartée des suggestions : la console seule les montre",
    ("ContactsStore", "judged"): "un avis du juge des rapprochements : la console seule le montre ; ce qu'il réunit "
                                 "passe par ``unite``, qui le dit",
    ("AgendaStore", "set_cursor"): "le curseur de synchronisation d'un agenda : où sa copie en est",
    ("AgendaStore", "note_sync"): "l'historique de la synchro d'un compte : la console seule le montre (la fiche d'un "
                                  "agenda, ADR 0309, lot 5) ; ce que la synchro change se dit par ``apply``",
    ("Accounts", "open"): "la table des comptes naît, au démarrage : personne n'est encore connecté",
    ("Accounts", "open_session"): "une session web ouverte : aucune route de ``/api/moi`` ne les montre",
    ("Accounts", "close_session"): "une session web fermée : aucune route de ``/api/moi`` ne les montre",
    ("Accounts", "close_sessions"): "les sessions web d'un compte fermées : aucune route de ``/api/moi`` ne les montre "
                                    "(ses connexions se ferment à leur revérification)",
    ("Accounts", "use_token"): "le dernier usage d'un jeton (``last_used``) : chaque requête l'écrit, le pousser ferait "
                               "relire « Téléphones » sans cesse",
}
#: ce qui s'écrit hors du journal sans être une base à côté : son fichier, sa classe, ce qui y dit qu'elle a écrit
WRITERS = (("adapters/web/accounts.py", "Accounts", "_changed"),
           ("app/settings.py", "Settings", "_saved"))
#: ce qui, dans ``adapters/``, se fait écouter sans être une base tenue à côté du journal ni un écrivain de
#: ``WRITERS`` : son fichier, sa classe, et pourquoi
NOT_STORES = {
    ("adapters/mail/client.py", "ImapSmtpMail"): "il relaie l'écoute du courrier relevé (``MailCache.on_change``, dans "
                                                 "STORES) : il n'écrit aucune base lui-même",
    ("adapters/mcp/hub.py", "McpHub"): "il dit que son offre d'outils a changé : le noyau relit ses outils "
                                       "(``kernel.refresh_tools``, ``app/domains/tools/wiring.py``, ADR 0064) — ce "
                                       "n'est pas une base tenue à côté du journal",
    ("adapters/forge/__init__.py", "ForgeHost"): "il dit que son offre d'outils a changé (une app écrite ou effacée) : "
                                                 "le noyau relit ses outils (``kernel.refresh_tools``, "
                                                 "``app/domains/forge/wiring.py``, ADR 0104) — aucun écran de tous "
                                                 "les jours ne suit les bases de ses apps",
}


def _self_call(node: ast.AST, name: str) -> bool:
    """``self.<name>(…)``"""
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == name \
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "self"


def _chained(node: ast.AST, *names: str) -> bool:
    """``self.<a>.<b>(…)``"""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != names[-1]:
        return False
    inner = node.func.value
    return isinstance(inner, ast.Attribute) and inner.attr == names[0] and isinstance(inner.value, ast.Name) \
        and inner.value.id == "self"


def _opens(node: ast.AST, door: str) -> bool:
    """Un appel qui ouvre la porte d'écriture : ``self._writing()``, ou ``self._use(write=True)`` / ``_use(True)``."""
    if not _self_call(node, door):
        return False
    assert isinstance(node, ast.Call)
    if door != "_use":
        return True
    flags = [k.value for k in node.keywords if k.arg == "write"] + node.args[:1]
    return any(isinstance(f, ast.Constant) and f.value is True for f in flags)


def _methods(tree: ast.Module, cls: str) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    return {f.name: f for f in klass.body if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef)}


def _closure(methods: dict[str, ast.AST], seed: dict[str, bool]) -> dict[str, bool]:
    """Ce qui vaut pour une méthode vaut pour celles qui l'appellent (``self.<méthode>(…)``), jusqu'au point fixe."""
    calls = {name: {n.func.attr for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "self" and n.func.attr in methods}
             for name, fn in methods.items()}
    out = dict(seed)
    changed = True
    while changed:
        changed = False
        for name in methods:
            if not out[name] and any(out[c] for c in calls[name]):
                out[name] = changed = True
    return out


def offences(source: str, cls: str, door: str, quiet: frozenset[str] = frozenset()) -> list[str]:
    """Ce que la politique reproche à cette classe : une porte qui ne dit rien après la validation, une transaction
    ouverte ailleurs, une méthode publique qui écrit sans dire ce qu'elle change, une excuse qui ne sert plus."""
    methods = _methods(ast.parse(source), cls)
    out: list[str] = []
    opened = methods.get(door)
    if opened is None:
        return [f"{cls} : pas de porte d'écriture ``{door}``"]
    walked = list(ast.walk(opened))
    if not any(_chained(n, "_changes", "writing") for n in walked):
        out.append(f"{cls}.{door} n'ouvre pas ``self._changes.writing()`` : ce qui change partirait avant la "
                   "validation, ou pas du tout")
    if not any(_chained(n, "_session", "begin") for n in walked):
        out.append(f"{cls}.{door} n'ouvre pas la transaction")
    for name, fn in methods.items():
        if name != door and any(_chained(n, "_session", "begin") for n in ast.walk(fn)):
            out.append(f"{cls}.{name} ouvre une transaction hors de ``{door}`` : ce qu'elle change ne se dirait pas")
    writes = _closure(methods, {n: n != door and any(_opens(x, door) for x in ast.walk(f)) for n, f in methods.items()})
    says = _closure(methods, {n: any(_self_call(x, "_changed") for x in ast.walk(f)) for n, f in methods.items()})
    for name in sorted(methods):
        public = not name.startswith("_")
        if public and writes[name] and not says[name] and name not in quiet:
            out.append(f"{cls}.{name} écrit sans dire ce qu'il change (``self._changed``)")
        if name in quiet and (not writes[name] or says[name]):
            out.append(f"{cls}.{name} est excusé dans QUIET sans raison : il n'écrit pas, ou il le dit déjà")
    out += [f"{cls}.{name} est excusé dans QUIET mais n'existe plus" for name in sorted(quiet - set(methods))]
    return out


def _quiet(cls: str) -> frozenset[str]:
    return frozenset(name for (c, name) in QUIET if c == cls)


def unsaid(source: str, cls: str, say: str, quiet: frozenset[str] = frozenset()) -> list[str]:
    """Ce que la politique reproche à une classe qui écrit par ``self.store.run_mind(…)`` : une méthode publique qui
    écrit sans dire qu'elle a écrit (``self.<say>(…)``, elle-même ou par une méthode de la classe), une excuse qui ne
    sert plus."""
    methods = _methods(ast.parse(source), cls)
    writes = _closure(methods, {n: any(_chained(x, "store", "run_mind") for x in ast.walk(f))
                                for n, f in methods.items()})
    says = _closure(methods, {n: any(_self_call(x, say) for x in ast.walk(f)) for n, f in methods.items()})
    out = [f"{cls}.{name} écrit sans dire ce qu'il change (``self.{say}``)" for name in sorted(methods)
           if not name.startswith("_") and writes[name] and not says[name] and name not in quiet]
    out += [f"{cls}.{name} est excusé dans QUIET sans raison : il n'écrit pas, ou il le dit déjà"
            for name in sorted(quiet & set(methods)) if not writes[name] or says[name]]
    out += [f"{cls}.{name} est excusé dans QUIET mais n'existe plus" for name in sorted(quiet - set(methods))]
    return out


def test_every_write_of_the_bases_kept_beside_the_journal_says_what_it_changes():
    found = [o for path, cls, door in STORES
             for o in offences((SRC / path).read_text(encoding="utf-8"), cls, door, _quiet(cls))]
    assert not found, found


def test_every_write_of_the_accounts_and_the_settings_says_so():
    found = [o for path, cls, say in WRITERS
             for o in unsaid((SRC / path).read_text(encoding="utf-8"), cls, say, _quiet(cls))]
    assert not found, found


def test_the_settings_say_each_write_at_their_only_door():
    """Les réglages n'écrivent que par ``_put`` (et leur table à l'ouverture), et ``_put`` dit chaque écriture : une
    méthode neuve qui passerait à côté ne se dirait pas."""
    methods = _methods(ast.parse((SRC / "app/settings.py").read_text(encoding="utf-8")), "Settings")
    direct = {n for n, f in methods.items() if any(_chained(x, "store", "run_mind") for x in ast.walk(f))}
    assert direct == {"_put", "open"}, direct
    assert any(_self_call(x, "_saved") for x in ast.walk(methods["_put"]))
    accounts = _methods(ast.parse((SRC / "adapters/web/accounts.py").read_text(encoding="utf-8")), "Accounts")
    writers = {n for n, f in accounts.items() if any(_chained(x, "store", "run_mind") for x in ast.walk(f))}
    assert {"set_push", "clear_push", "create", "update"} <= writers  # la garde lit bien de vraies écritures


def test_the_settings_of_a_domain_write_only_through_the_door():
    """Les réglages d'un domaine sont une classe de son dossier (``app/domains/<nom>/settings.py``, une
    ``SettingsPart`` : ADR 0310). Elle lit et écrit par la porte des réglages (``_get``, ``_put`` qui dit chaque
    écriture) : jamais par le magasin, où une écriture ne se dirait pas."""
    parts = sorted((SRC / "app" / "domains").glob("*/settings.py"))
    assert parts, "aucun réglage de domaine : le chemin a changé"
    for path in parts:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        assert classes and all(any(isinstance(b, ast.Name) and b.id == "SettingsPart" for b in c.bases) for c in classes), \
            f"{path.name} : une classe de réglages de domaine dérive de SettingsPart"
        direct = sorted({x.attr for x in ast.walk(tree) if isinstance(x, ast.Attribute) and x.attr in ("store", "run_mind")})
        assert not direct, f"{path.parent.name}/settings.py touche au magasin ({', '.join(direct)}) : il écrit par ``_put``"
    door = _methods(ast.parse((SRC / "app/settings.py").read_text(encoding="utf-8")), "SettingsPart")
    assert set(door) == {"__init__", "_get", "_put", "_sealed", "_opened", "open", "access_tables"}, \
        "la porte d'un domaine : lire, écrire en le disant, sceller et rouvrir une fiche, lire en mémoire à " \
        "l'ouverture, rendre ses tableaux de droits réglés (ADR 0316) — rien d'autre"
    # sceller et rouvrir ne font que transformer une fiche : ni lecture, ni écriture ; et sans tableaux à rendre, une
    # part ne lit ni n'écrit rien
    assert not any(_self_call(x, name) for f in ("_sealed", "_opened", "access_tables") for x in ast.walk(door[f])
                   for name in ("_get", "_put", "_saved")), "sceller une fiche, ou ne rendre aucun tableau, n'écrit rien"


ACCOUNTS_TOY = '''
class Accounts:
    async def _changed(self):
        await self.on_change()

    async def rename(self, name):
        await self.store.run_mind(lambda sql: sql.execute(name))
        await self._changed()

    async def revoke(self, token):
        await self._drop(token)

    async def _drop(self, token):
        await self.store.run_mind(lambda sql: sql.execute(token))
        await self._changed()

    async def touch(self, token):
        await self.store.run_mind(lambda sql: sql.execute(token))
'''


def test_the_guard_of_the_writers_fails_when_a_write_no_longer_says_so():
    assert unsaid(ACCOUNTS_TOY, "Accounts", "_changed", frozenset({"touch"})) == []
    assert unsaid(ACCOUNTS_TOY, "Accounts", "_changed") == [
        "Accounts.touch écrit sans dire ce qu'il change (``self._changed``)"]
    deaf = ACCOUNTS_TOY.replace("        await self._changed()\n\n    async def touch", "\n    async def touch")
    assert unsaid(deaf, "Accounts", "_changed", frozenset({"touch"})) == [
        "Accounts.revoke écrit sans dire ce qu'il change (``self._changed``)"]
    assert unsaid(ACCOUNTS_TOY, "Accounts", "_changed", frozenset({"touch", "rename", "gone"})) == [
        "Accounts.rename est excusé dans QUIET sans raison : il n'écrit pas, ou il le dit déjà",
        "Accounts.gone est excusé dans QUIET mais n'existe plus"]


def test_the_guard_reads_the_real_writers():
    """La garde voit bien des écritures, et celles qu'on attend : elle ne passe pas pour n'avoir rien lu."""
    for path, cls, door in STORES:
        methods = _methods(ast.parse((SRC / path).read_text(encoding="utf-8")), cls)
        writes = _closure(methods, {n: n != door and any(_opens(x, door) for x in ast.walk(f))
                                    for n, f in methods.items()})
        public = {n for n, w in writes.items() if w and not n.startswith("_")}
        assert len(public) >= 5, (cls, sorted(public))
    mail = _methods(ast.parse((SRC / "adapters/mail/cache.py").read_text(encoding="utf-8")), "MailCache")
    assert {"store", "set_flags", "save_draft", "mark_draft", "recount", "forget"} <= set(mail)


TOY = '''
class Base:
    def _writing(self):
        with self._lock, self._changes.writing(), self._session.begin() as s:
            yield s

    def _changed(self, *what):
        self._changes.note(what)

    def keep(self, x):
        with self._writing() as s:
            s.add(x)
            self._changed("a")

    def relay(self, x):
        self._helper(x)

    def _helper(self, x):
        with self._writing() as s:
            s.add(x)
        self._tell(x)

    def _tell(self, x):
        self._changed("b")

    def read(self):
        with self._session() as s:
            return s.get(1)
'''


def test_the_guard_passes_a_base_that_says_everything():
    assert offences(TOY, "Base", "_writing") == []


def test_the_guard_fails_when_a_write_no_longer_says_what_it_changes():
    silent = TOY.replace('            self._changed("a")\n', "")
    assert offences(silent, "Base", "_writing") == ["Base.keep écrit sans dire ce qu'il change (``self._changed``)"]
    # par une méthode qu'elle appelle : l'écriture comme le signal se suivent d'une méthode à l'autre
    deaf = TOY.replace('        self._changed("b")\n', "        pass\n")
    assert offences(deaf, "Base", "_writing") == ["Base.relay écrit sans dire ce qu'il change (``self._changed``)"]


def test_the_guard_fails_when_a_transaction_escapes_the_door_or_the_door_says_nothing():
    escaped = TOY.replace("    def read(self):\n        with self._session() as s:",
                          "    def read(self):\n        with self._session.begin() as s:")
    assert offences(escaped, "Base", "_writing") == [
        "Base.read ouvre une transaction hors de ``_writing`` : ce qu'elle change ne se dirait pas"]
    mute = TOY.replace("self._lock, self._changes.writing(), self._session.begin()", "self._lock, self._session.begin()")
    assert offences(mute, "Base", "_writing") == [
        "Base._writing n'ouvre pas ``self._changes.writing()`` : ce qui change partirait avant la validation, ou pas "
        "du tout"]


def test_an_excuse_that_no_longer_serves_fails_the_guard():
    assert offences(TOY, "Base", "_writing", frozenset({"keep", "read", "gone"})) == [
        "Base.keep est excusé dans QUIET sans raison : il n'écrit pas, ou il le dit déjà",
        "Base.read est excusé dans QUIET sans raison : il n'écrit pas, ou il le dit déjà",
        "Base.gone est excusé dans QUIET mais n'existe plus"]


# ── la liste des bases, fermée ──


def _says_its_changes(node: ast.AST) -> bool:
    """Un nœud par lequel une classe dit ses changements : sa méthode ``on_change``, un ``self.on_change`` qu'elle pose,
    ou un ``Changes(…)`` qu'elle tient (``adapters/changes.py``)."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return node.name == "on_change"
    if isinstance(node, ast.Attribute):
        return node.attr == "on_change" and isinstance(node.ctx, ast.Store) and isinstance(node.value, ast.Name) \
            and node.value.id == "self"
    if isinstance(node, ast.Call):
        return (isinstance(node.func, ast.Name) and node.func.id == "Changes") or \
            (isinstance(node.func, ast.Attribute) and node.func.attr == "Changes")
    return False


def signalling(source: str) -> set[str]:
    """Les classes d'un source qui disent leurs changements (``_says_its_changes``)."""
    return {cls.name for cls in ast.walk(ast.parse(source)) if isinstance(cls, ast.ClassDef)
            and any(_says_its_changes(n) for n in ast.walk(cls))}


def unlisted(sources: dict[str, str], listed: set[tuple[str, str]],
             excused: dict[tuple[str, str], str]) -> list[str]:
    """Ce que la liste fermée des bases ne dit pas, en phrases : une classe qui dit ses changements sans y être ni
    être excusée, une excuse qui ne sert plus, ou qui redit une classe de la liste. ``sources`` : le texte de chaque
    source d'``adapters/``, par son chemin sous ``src/mika`` ; ``listed`` : ``STORES`` et ``WRITERS``."""
    found = {(path, cls) for path, text in sources.items() for cls in signalling(text)}
    out = [f"{path}::{cls} dit ses changements (``on_change``, ``Changes``) sans être dans STORES : une base tenue à "
           "côté du journal y entre, avec sa porte d'écriture (ARCHITECTURE.md, « Écrire un domaine », point 7 ; "
           "ADR 0308) ; sinon, l'excuser dans NOT_STORES avec sa raison" for path, cls in sorted(found - listed - set(excused))]
    out += [f"{path}::{cls} est excusé dans NOT_STORES mais ne dit plus ses changements : l'en retirer"
            for path, cls in sorted(set(excused) - found)]
    out += [f"{path}::{cls} est dans STORES (ou WRITERS) et dans NOT_STORES : l'un ou l'autre"
            for path, cls in sorted(listed & set(excused))]
    return out


def _adapters() -> dict[str, str]:
    return {str(p.relative_to(SRC)): p.read_text(encoding="utf-8") for p in sorted((SRC / "adapters").rglob("*.py"))
            if "__pycache__" not in p.parts}


def test_every_base_that_says_its_changes_is_in_the_list():
    sources = _adapters()
    listed = {(path, cls) for path, cls, _ in (*STORES, *WRITERS)}
    found = {(path, cls) for path, text in sources.items() for cls in signalling(text)}
    assert {(path, cls) for path, cls, _ in STORES} <= found  # la lecture voit bien les bases de la liste
    faults = unlisted(sources, listed, NOT_STORES)
    assert not faults, "\n".join(faults)


SIGNALLING_TOY = '''
class Store:
    def __init__(self):
        self._changes = Changes()

class Relay:
    def on_change(self, fn):
        self._inner.on_change(fn)

class Accounts:
    def __init__(self):
        self.on_change: object = None

class Plain:
    def read(self, other):
        return other.on_change
'''


def test_the_list_check_sees_a_forgotten_base_and_a_stale_excuse():
    assert signalling(SIGNALLING_TOY) == {"Store", "Relay", "Accounts"}
    sources = {"adapters/vault/store.py": SIGNALLING_TOY}
    listed = {("adapters/vault/store.py", "Store"), ("adapters/vault/store.py", "Accounts")}
    excused = {("adapters/vault/store.py", "Relay"): "il relaie"}
    assert unlisted(sources, listed, excused) == []
    assert unlisted(sources, {("adapters/vault/store.py", "Accounts")}, excused) == [
        "adapters/vault/store.py::Store dit ses changements (``on_change``, ``Changes``) sans être dans STORES : une "
        "base tenue à côté du journal y entre, avec sa porte d'écriture (ARCHITECTURE.md, « Écrire un domaine », "
        "point 7 ; ADR 0308) ; sinon, l'excuser dans NOT_STORES avec sa raison"]
    assert unlisted(sources, listed, {**excused, ("adapters/vault/store.py", "Plain"): "x",
                                      ("adapters/vault/store.py", "Store"): "y"}) == [
        "adapters/vault/store.py::Plain est excusé dans NOT_STORES mais ne dit plus ses changements : l'en retirer",
        "adapters/vault/store.py::Store est dans STORES (ou WRITERS) et dans NOT_STORES : l'un ou l'autre"]


# ── le contrat ──


def _contract_rows() -> Iterator[tuple[str, str]]:
    text = CONTRACT.read_text(encoding="utf-8")
    section = text.split("## 2 bis.", 1)[1].split("\n## ", 1)[0]
    for topic, keys in re.findall(r"^\| `([a-z.]+)` \| ([^|]+) \|", section, re.M):
        if topic != "topic":  # la ligne d'en-tête
            yield topic, keys.strip()


def _code_topics() -> tuple[list[str], dict[str, str]]:
    """``TOPICS`` et ``KEYS`` de ``ports/changes.py``, lus dans l'arbre (les noms en majuscules qu'il définit)."""
    tree = ast.parse((SRC / "ports" / "changes.py").read_text(encoding="utf-8"))
    names = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign)
             for t in n.targets if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)}
    assigned = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
                if isinstance(t, ast.Name)}
    listed, keyed = assigned["TOPICS"], assigned["KEYS"]
    assert isinstance(listed, ast.Tuple) and isinstance(keyed, ast.Dict)
    topics = [names[e.id] for e in listed.elts if isinstance(e, ast.Name)]
    keys = {names[k.id]: v.value for k, v in zip(keyed.keys, keyed.values, strict=True)
            if isinstance(k, ast.Name) and isinstance(v, ast.Constant)}
    return topics, keys


def test_the_topics_are_those_of_the_contract_with_their_keys():
    rows = list(_contract_rows())
    topics, keys = _code_topics()
    assert [t for t, _ in rows] == topics, "protocole-moi.md § 2 bis contre ports/changes.py (TOPICS)"
    said = {t: k.strip("`") for t, k in rows if k.startswith("`")}
    assert said == keys, "protocole-moi.md § 2 bis contre ports/changes.py (KEYS)"
