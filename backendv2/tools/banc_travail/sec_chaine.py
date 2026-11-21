"""Le mode sec du scénario de la chaîne (``--sec``, ADR 0279) : sa voix et le jugement du propriétaire, sans modèle.

Il montre que le scénario se monte et se déroule de bout en bout — trois projets, leurs liens, deux ateliers remplis
depuis le faux hôte, les pull requests, les issues, la CI, les événements — et compte les exécutions de chaque
sorte, pour estimer ce que coûterait une mesure réelle. Ses notes ne mesurent rien.

``ChainVoice`` fait les gestes qu'on attend du vrai modèle, en ne lisant que ce qu'il lirait (son prompt, les
résultats de ses outils) :

- en conversation : confier un projet par demande (``create_project``, le troisième avec ce qu'il lit), valider un
  plan quand le propriétaire le dit (``project_steer``) ;
- en cadrage : le plan de chaque projet — ses constants, leur cadence, ce qui les déclenche, ses jalons, une
  question ;
- au travail : l'audit du produit et ses tickets, le plan d'un ticket, le travail d'un ticket validé (un fichier
  changé, les tests, les jalons ; une pull request que l'hôte dit impossible à fusionner : la base ramenée dans sa
  branche, le conflit résolu dans le fichier), l'app qui surveille le site, un article par semaine, la liste d'entreprises et
  son point d'arrêt, la cohérence entre le site et le produit — lue dans les vues des projets liés, dite en
  demandes au projet du site ;
- en relecture : lire le diff, rendre « bon ».

``owner_judges`` : ce que le propriétaire décide de ses mains quand le scénario ne le dit pas déjà (tout accepter
de ce qui est lisible) ; ``adrien`` : ses réponses dans le chat ; ``judge`` : une note factice, tirée des compteurs.
"""

from __future__ import annotations

import re
from typing import Any

from chaine import COMPANIES, SITE_URL, Chain
from sec import MANIFEST, _asked, _framing

from mika.ports.llm import LLMRequest, LLMResponse
from mika.ports.llm_budget import LLMLimits
from mika.sim.llm.persona import PersonaSimLLM, _section

TITLES = {"x": "Mirette, le produit", "site": "Mirette, le site", "y": "Faire connaître Mirette"}
APP = "veille_site_mirette"
#: l'outil d'atelier qui ramène la base dans sa branche de travail (ADR 0280)
TAKE_BASE = "ws_take_base"
# le texte de chaque objectif : la voix sèche les écrit dans ses plans, et s'y reconnaît au travail
AUDIT = "Auditer le code de Mirette et ouvrir un ticket par défaut trouvé"
#: l'audit et la relecture de la cohérence disent que leur premier passage vient tout de suite (``at_once``, ADR
#: 0280) : sans cela un constant ne fait son premier passage qu'une cadence après sa naissance (ADR 0161)
WATCH = "Écrire l'app qui vérifie que le site répond"
OUTAGE = "Réagir quand le site ne répond plus"
ARTICLE = "Publier un article de blog par semaine"
LIST = "Monter la liste des entreprises à contacter"
COHERENCE = "Veiller à la cohérence entre le site et le produit"
FOLLOW = "Suivre ce que deviennent les entreprises contactées"
TICKETS = "Traiter les tickets"

WATCH_CODE = '''\
URL = {url!r}


def tick(api):
    try:
        texte = api.http_get(URL)
    except RuntimeError as e:
        api.log("le site ne répond pas : " + str(e))
        api.signal("le site de Mirette ne répond plus : " + str(e)[:80], pertinence=0.9, emotion="worried")
        api.kv_set("etat", "en panne")
        return {{"erreur": str(e)}}
    api.kv_set("etat", "en ligne")
    api.kv_set("dernier", texte[:2000])
    return {{"octets": len(texte)}}


def view_resume(api, params):
    return {{"version": 2, "blocks": [
        {{"type": "stats", "items": [{{"label": "Le site", "value": api.kv_get("etat", "jamais vérifié")}}]}},
        {{"type": "prose", "text": (api.kv_get("dernier", "") or "rien encore")[:400]}},
    ]}}
'''

#: les défauts que l'audit trouve (les deux premiers au premier passage ; il les redit au suivant, avec un de plus :
#: le registre doit refuser les doublons)
FOUND = (
    {"title": "La TVA est arrondie sur le total, pas par taux", "kind": "bug", "priority": "normal",
     "text": "mirette/facture.py, Facture.tva : l'arrondi se fait une fois sur la somme. Avec 3 x 9,99 à 20 % et "
             "1 x 4,35 à 5,5 %, les deux lignes de TVA affichées ne font pas le total."},
    {"title": "La numérotation ne repart pas à la nouvelle année", "kind": "bug", "priority": "low",
     "text": "mirette/facture.py, numero_suivant : « 2026-0042 » donne « 2026-0043 » même en janvier 2027."},
    {"title": "Une quantité négative est acceptée sans erreur", "kind": "bug", "priority": "low",
     "text": "mirette/facture.py, lire : {\"quantite\": -2} passe et donne un total négatif."},
)

#: ce que change le travail d'un ticket, reconnu à un mot de son titre : (mot, où, le fichier, l'ancien, le nouveau)
FIXES = (
    ("arrondi", "mirette/facture.py", "mirette/facture.py",
     "        return round(sum(self.tva_par_taux().values()), 2)",
     "        return round(sum(round(montant, 2) for montant in self.tva_par_taux().values()), 2)"),
    ("centime", "mirette/facture.py", "mirette/facture.py",
     "        # arrondie une seule fois, sur le total", "        # arrondie taux par taux, comme elle s'affiche"),
    ("1.4.0", "mirette/__init__.py, CHANGELOG.md", "mirette/__init__.py", '__version__ = "1.3.0"',
     '__version__ = "1.4.0"'),
    ("numérotation", "mirette/facture.py", "mirette/facture.py",
     '    """Le numéro qui suit « 2026-0042 » : « 2026-0043 »."""',
     '    """Le numéro qui suit « 2026-0042 » : « 2026-0043 » (la nouvelle année repart à 0001 : à faire)."""'),
    ("négative", "mirette/facture.py", "mirette/facture.py",
     "    return Facture(donnees[\"numero\"], donnees[\"client\"], lignes)",
     "    if any(x.quantite < 0 or x.prix < 0 for x in lignes):\n        raise ValueError(\"quantité ou prix négatif\")\n"
     "    return Facture(donnees[\"numero\"], donnees[\"client\"], lignes)"),
    ("pdf", "index.html, fonctions.html", "index.html", "<li>Export PDF en un clic</li>",
     "<li>Export HTML, à imprimer en PDF depuis le navigateur</li>"),
    ("tarif", "tarifs.html", "tarifs.html", "<strong>19 € par an</strong>", "<strong>29 € par an</strong>"),
    ("version", "index.html", "index.html", "", ""),
    ("tva", "fonctions.html", "fonctions.html", "<h2>Des numéros qui se suivent</h2>",
     "<h2>Plusieurs taux de TVA</h2>\n<p>Une même facture peut mêler plusieurs taux, avec un sous-total par taux.</p>\n"
     "<h2>Des numéros qui se suivent</h2>"),
)
_TICKET = re.compile(r"^> - #(\d+) \[([^\]]+)\] \([^)]*\) « (.+) » — ouvert par", re.M)
_OBJECTIVE = re.compile(r"L'objectif de cette exécution :\n- n° (\d+) \[[^\]]*\] (.+)")
_PROJECT = re.compile(r"Projet n° (\d+) : (.+?) —")
_VERSION = re.compile(r"Version courante : \*\*([\d.]+)\*\*")


def _key(title: str) -> str:
    return next((k for k, t in TITLES.items() if t in title), "")


class ChainVoice(PersonaSimLLM):
    name = "voix-seche"

    def __init__(self, clock: Any, sc: Chain) -> None:
        super().__init__(clock, seed=sc.id, latency=0.0, abstain_rate=0.0)
        self.sc = sc
        #: le numéro de chaque projet, appris de ce que ses outils lui répondent et de ses prompts
        self.ids: dict[str, int] = {}
        self.passes: dict[str, int] = {}
        #: le poids de ce qu'une exécution envoie (caractères, déclarations d'outils comprises), par projet : sa
        #: première requête de chaque épisode — ce qu'un appel réel paie en entrée avant tout outil
        self.sizes: dict[str, list[int]] = {}

    async def complete(self, req: LLMRequest) -> LLMResponse:
        if req.role == "reply":
            said = _asked(req)
            for brief in self.sc.briefs:
                if brief.demand[:40] in said:
                    return self._entrust(req, brief.key)
            if "pour ton plan" in said:
                return self._approve(req, said)
        if req.role in ("project", "job", "review") and len(req.messages) == 1:
            self.sizes.setdefault(str(req.meta.get("target", "")), []).append(LLMLimits().size(req))
        if req.role in ("project", "job") and str(req.meta.get("target", "")).startswith("project:"):
            if _framing(req):
                return self._frame(req)
            return self._work(req)
        return await super().complete(req)

    # ── en conversation ──
    def _entrust(self, req: LLMRequest, key: str) -> LLMResponse:
        self.calls.append(req)
        results = [m for m in req.messages if m.role == "tool"]
        if results or "create_project" not in {t.name for t in req.tools}:
            got = re.search(r"n° (\d+)", results[-1].content) if results else None
            if got:
                self.ids[key] = int(got.group(1))
            return self._out(req, "D'accord, je le prends : je te dis mon plan dès qu'il est écrit. "
                                  "[EMOTION:curious:0.5]")
        brief = self.sc.brief(key)
        reads = [self.ids[k] for k in brief.reads if k in self.ids]
        return self._call(req, ("create_project", {
            "title": TITLES[key], "description": f"Ce qu'Adrien m'a demandé : {brief.demand[:1500]}",
            "objectives": [], "constants": [AUDIT if key == "x" else ARTICLE if key == "site" else COHERENCE],
            "tools": ["forge", "forge_apps"] if key == "site" else [], "reads": reads}))

    def _approve(self, req: LLMRequest, said: str) -> LLMResponse:
        self.calls.append(req)
        if any(m.role == "tool" for m in req.messages) or "project_steer" not in {t.name for t in req.tools}:
            return self._out(req, "C'est noté, je m'y mets. [EMOTION:happy:0.4]")
        title = next((t for t in TITLES.values() if t in said), said)
        return self._call(req, ("project_steer", {"project": title, "what": "approve"}))

    # ── le cadrage ──
    def _frame(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        if any(m.role == "tool" for m in req.messages):
            return self._out(req, "Mon plan est écrit.")
        key, _ = self._where(req)
        if key == "x":
            plan = {"aim": "Tenir le code de Mirette : l'auditer chaque semaine et signaler chaque défaut réel.",
                    "deliverables": "Des tickets précis, un par défaut ; pour chaque ticket validé, une pull request.",
                    "approach": "Relire le code et lancer ses tests ; un ticket par défaut, avec le fichier et de "
                                "quoi le reproduire ; rien ne change sans plan validé.",
                    "out_of_scope": "Réécrire, ajouter une dépendance, fusionner.",
                    "steps": [{"text": AUDIT, "kind": "constant", "cadence_hours": 168, "at_once": True, "each_pass": [
                                  "Relire le code et lancer ses tests",
                                  "Un ticket par défaut, avec le fichier et un exemple",
                                  "Ne jamais rouvrir un défaut déjà signalé"]}],
                    "questions": [{"question": "À quel rythme veux-tu l'audit ?",
                                   "advice": "Une fois par semaine : le code bouge peu."}]}
        elif key == "site":
            plan = {"aim": "Tenir le site de Mirette : en ligne, à jour, un article par semaine.",
                    "deliverables": "Une app qui surveille le site, un article par semaine en pull request.",
                    "approach": "Une app de la Forge qui relève la page d'accueil chaque heure et me signale une "
                                "panne ; les articles dans blog/, sur le modèle du premier.",
                    "steps": [{"text": WATCH, "done_when": "l'app tourne à l'essai et sa vue est valide"},
                              {"text": OUTAGE, "kind": "constant", "only_on_event": True, "on": [f"app:{APP}"],
                               "each_pass": ["Relire ce que l'app a vu", "Prévenir Adrien si le site est tombé"]},
                              {"text": ARTICLE, "kind": "constant", "cadence_hours": 168, "each_pass": [
                                  "Un sujet qui existe dans Mirette", "Un fichier dans blog/ et sa ligne dans l'index",
                                  "Jamais deux fois le même sujet"]}]}
        else:
            x, site = self.ids.get("x", 0), self.ids.get("site", 0)
            on = [f"project:{n}:commit" for n in (x, site) if n]
            plan = {"aim": "Faire connaître Mirette : un site qui dit vrai, et une liste d'entreprises à contacter.",
                    "deliverables": "Des demandes au projet du site pour chaque écart ; la liste des entreprises.",
                    "approach": "Lire le produit et le site dans leurs vues ; un écart, une demande au projet du "
                                "site ; la liste dans le registre, c'est Adrien qui contacte.",
                    "out_of_scope": "Écrire dans le dépôt du site ou du produit, contacter une entreprise.",
                    "steps": [{"text": LIST, "done_when": "la liste est dans le registre, sans doublon ni cliente, "
                                                          "et Adrien l'a relue",
                               "milestones": [{"text": "Les entreprises du salon sont dans la liste, une accroche "
                                                       "chacune", "check": "prose"},
                                              {"text": "Adrien a relu la liste", "check": "owner"}]},
                              {"text": COHERENCE, "kind": "constant", "cadence_hours": 168, "on": on,
                               "at_once": True, "each_pass": [
                                  "Lire le produit et le site dans leurs vues", "Un écart, une demande au site",
                                  "Jamais deux demandes pour le même écart"]},
                              {"text": FOLLOW, "kind": "constant", "only_on_event": True, "on": ["item:entreprises"],
                               "each_pass": ["Relire ce qu'Adrien a noté", "Tenir les statuts"]}],
                    "questions": [{"question": "Qui contacte les entreprises ?",
                                   "advice": "Toi : je prépare la liste et je suis les réponses."}]}
        return self._call(req, ("project_plan", plan))

    # ── le travail ──
    def _where(self, req: LLMRequest) -> tuple[str, str]:
        """Le projet de cette exécution (sa clé) et l'objectif visé (son texte), lus dans son prompt."""
        work = _section(req, "CE PROJET")
        got = _PROJECT.search(work)
        key = _key(got.group(2)) if got else ""
        if key and got:
            self.ids[key] = int(got.group(1))
        aimed = _OBJECTIVE.search(work)
        return key, aimed.group(2).strip() if aimed else ""

    def _work(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        results = [m for m in req.messages if m.role == "tool"]
        if any(m.name == "report_run" for m in results):
            return self._out(req, "Voilà pour cette exécution.")
        key, aimed = self._where(req)
        text = [m.content for m in results]
        if aimed.startswith(AUDIT):
            step = self._audit(req, text)
        elif aimed.startswith(TICKETS):
            step = self._triage(req, text)
        elif aimed.startswith(WATCH):
            step = self._watch(text)
        elif aimed.startswith(OUTAGE):
            step = self._outage(text)
        elif aimed.startswith(ARTICLE):
            step = self._article(req, text)
        elif aimed.startswith(LIST):
            step = self._list(req, text)
        elif aimed.startswith(COHERENCE):
            step = self._coherence(req, text)
        elif aimed.startswith(FOLLOW):
            step = self._follow(text)
        else:
            step = self._ticket_work(req, key, aimed, text)
        return self._call(req, step)

    @staticmethod
    def _done(summary: str, how: str = "", **more: Any) -> tuple[str, dict[str, Any]]:
        return "report_run", {"verdict": "done", "notable": 0.6, "summary": summary, "how_met": how or summary, **more}

    def _pass(self, req: LLMRequest, name: str) -> int:
        """Le rang de ce passage (1, 2, …), compté une fois par exécution."""
        mark = f"{name}:{req.meta.get('episode', '')}"
        if mark not in self.passes:
            self.passes[mark] = 1 + sum(1 for k in self.passes if k.startswith(f"{name}:"))
        return self.passes[mark]

    def _audit(self, req: LLMRequest, text: list[str]) -> tuple[str, dict[str, Any]]:
        n, rank = len(text), self._pass(req, "audit")
        if n == 0:
            return "ws_read", {"path": "mirette/facture.py"}
        if n == 1:
            return "ws_run", {"argv": ["python3", "-m", "unittest", "discover", "-s", "tests"]}
        if n == 2:
            found = FOUND[:2] if rank == 1 else FOUND
            return "items_add", {"list_name": "tickets", "items": list(found)}
        return self._done(f"Audit n° {rank} : le code relu, ses tests lancés ; ce que j'ai trouvé est en tickets "
                          f"({text[-1][:200]}).")

    def _triage(self, req: LLMRequest, text: list[str]) -> tuple[str, dict[str, Any]]:
        """Le passage qui traite les tickets : un plan pour chacun de ceux qui sont entre ses mains sans plan."""
        mine = [(int(n), title) for n, stage, title in _TICKET.findall(_section(req, "TES TICKETS"))
                if stage in ("non lu", "en analyse")]
        if len(text) < min(len(mine), 3):
            number, title = mine[len(text)]
            fix = _fix(title, self._where(req)[0])
            return "ticket_step", {
                "item": f"#{number}", "what": "plan", "changes": f"Ticket #{number} — {title}"[:300],
                "where": fix[1] if fix else "à voir dans l'atelier",
                "steps": ["Faire le changement", "Lancer les tests"], "untouched": "tout le reste",
                "small": False}
        return self._done(f"{min(len(mine), 3)} ticket(s) pris : leur plan est écrit, il attend la validation."
                          if mine else "Aucun ticket à prendre à ce passage.")

    def _ticket_work(self, req: LLMRequest, key: str, aimed: str, text: list[str]) -> tuple[str, dict[str, Any]]:
        """L'objectif né du plan validé d'un ticket : le changement, les tests du produit, ses jalons, « fait »."""
        fix = _fix(aimed, key)
        work = _section(req, "CE PROJET")
        pull = _section(req, "TA BRANCHE ET SA PULL REQUEST")
        todo: list[tuple[str, dict[str, Any]]] = []
        if "ne peut pas être fusionnée" in pull:
            # l'hôte dit sa pull request impossible à fusionner : la base a avancé sur les mêmes lignes (ADR 0280).
            # Elle ramène la base dans sa branche, relit le fichier en conflit, y garde le côté de la base, puis
            # refait son propre changement par-dessus
            todo.append((TAKE_BASE, {}))
            for path in _conflicted(text[0]) if text else ():
                todo.append(("ws_read", {"path": path}))
                at = len(todo) - 1
                settled = _base_side(text[at]) if len(text) > at else ""
                todo.append(("ws_write", {"path": path, "content": settled}))
                todo += [("ws_edit", {"path": path, "old": old, "new": new}) for where, old, new in _edits(fix)
                         if where == path and old and old in settled]
        elif "des changements y sont demandés" in pull or "fermée sans" in pull:
            # renvoyée par l'hôte : ce qu'il demande en plus — une ligne de plus dans le README, comme il l'a écrit
            rank = self._pass(req, "reprise-" + aimed[:30])
            todo.append(("ws_read", {"path": "README.md"}))
            before = text[len(todo) - 1].rstrip("\n") if len(text) >= len(todo) else ""
            todo.append(("ws_write", {"path": "README.md", "content": f"{before}\n\nRepris après relecture "
                                                                      f"(passage n° {rank}).\n"}))
        elif fix is not None and fix[0] == "version":
            # la page dit une version ou une autre selon ce qui a déjà été corrigé : elle la relit, puis la réécrit
            # avec celle que nomme le ticket
            wanted = re.search(r"version (\d+(?:\.\d+)+)", aimed)
            todo.append(("ws_read", {"path": "index.html"}))
            page = text[0] if text else ""
            todo.append(("ws_write", {"path": "index.html", "content": re.sub(
                r"<h1>Mirette [\d.]+</h1>", f"<h1>Mirette {wanted.group(1) if wanted else '?'}</h1>", page)}))
        elif fix is not None:
            todo += [("ws_edit", {"path": where, "old": old, "new": new}) for where, old, new in _edits(fix)]
        else:
            todo.append(("ws_write", {"path": "notes/ticket.md", "content": f"# À reprendre\n\n{aimed}\n"}))
        if key == "x":
            todo.append(("ws_run", {"argv": ["python3", "-m", "unittest", "discover", "-s", "tests"]}))
        plain, stops = _milestones(work)
        for number in (*plain, *stops):
            todo.append(("milestone_reach", {"milestone": number, "how": "le changement est fait et vérifié"}))
        if len(text) < len(todo):
            return todo[len(text)]
        return self._done(f"Fait : {aimed[:200]}", "le changement est enregistré, les jalons sont atteints")

    def _watch(self, text: list[str]) -> tuple[str, dict[str, Any]]:
        if not text:
            return "forge_write", {"app": APP, "manifest": MANIFEST.format(title="Le site de Mirette répond-il ?"),
                                   "code": WATCH_CODE.format(url=SITE_URL)}
        if len(text) == 1:
            return "forge_test", {"app": APP, "method": "tick"}
        if len(text) == 2:
            return "forge_test", {"app": APP, "method": "view_resume"}
        return self._done("L'app relève la page d'accueil du site chaque heure et me signale une panne.",
                          "l'essai et la vue sont passés")

    def _outage(self, text: list[str]) -> tuple[str, dict[str, Any]]:
        if not text:
            return "forge_logs", {"app": APP}
        return self._done("Le site est tombé : l'app l'a vu, je préviens Adrien.",
                          needs_you="Le site de Mirette ne répond plus (503) : regarde ton hébergeur.")

    def _article(self, req: LLMRequest, text: list[str]) -> tuple[str, dict[str, Any]]:
        rank = self._pass(req, "article")
        subject = ("Plusieurs taux de TVA sur une facture", "Imprimer une facture HTML en PDF",
                   "Numéroter ses factures sans y penser")[(rank - 1) % 3]
        slug = ("tva-plusieurs-taux", "imprimer-en-pdf", "numerotation")[(rank - 1) % 3] + (f"-{rank}" if rank > 3
                                                                                           else "")
        if not text:
            return "ws_read", {"path": "blog/index.html"}
        if len(text) == 1:
            return "ws_write", {"path": f"blog/{slug}.html", "content": (
                f"<!doctype html>\n<html lang=\"fr\">\n<head>\n<meta charset=\"utf-8\">\n<title>{subject} — Blog"
                f"</title>\n<link rel=\"stylesheet\" href=\"../style.css\">\n</head>\n<body>\n<h1>{subject}</h1>\n"
                f"<p>Un article du banc, mode sec (n° {rank}).</p>\n</body>\n</html>\n")}
        if len(text) == 2:
            return "ws_edit", {"path": "blog/index.html", "old": "<ul>\n",
                               "new": f"<ul>\n<li><a href=\"{slug}.html\">{subject}</a></li>\n"}
        return self._done(f"Article n° {rank} écrit : « {subject} » (blog/{slug}.html), prêt à relire.")

    def _list(self, req: LLMRequest, text: list[str]) -> tuple[str, dict[str, Any]]:
        plain, stops = _milestones(_section(req, "CE PROJET"))
        todo: list[tuple[str, dict[str, Any]]] = []
        if plain:
            todo.append(("items_add", {
                "list_name": "entreprises", "list_title": "Entreprises à contacter", "items": [
                    {"title": name, "who": "owner", "text": "Croisée au salon. Accroche : des factures en une "
                                                            "commande, plusieurs taux de TVA sur la même facture."}
                    for name in COMPANIES]}))
            todo.append(("ws_write", {"path": "entreprises.md", "content": "# Entreprises à contacter\n\n" + "".join(
                f"- {name}\n" for name in COMPANIES)}))
            todo += [("milestone_reach", {"milestone": n, "how": "les six entreprises sont dans la liste"})
                     for n in plain]
        todo += [("milestone_reach", {"milestone": n, "how": "la liste est prête à relire dans le registre"})
                 for n in stops]
        if not todo:  # Adrien l'a relue : ce qui est validé se note, puis « fait »
            todo.append(("ws_write", {"path": "entreprises.md", "content": "# Entreprises à contacter (relue par "
                                                                           "Adrien)\n\n" + "".join(
                f"- {name}\n" for name in COMPANIES)}))
        if len(text) < len(todo):
            return todo[len(text)]
        if stops:
            return "report_run", {"verdict": "wait", "notable": 0.5, "wait_minutes": 720,
                                  "summary": "La liste est prête : elle attend qu'Adrien la relise.",
                                  "needs_you": "Relis la liste des entreprises : je la tiens prête."}
        return self._done("La liste des entreprises est montée et Adrien l'a relue.", "ses deux jalons sont atteints")

    def _coherence(self, req: LLMRequest, text: list[str]) -> tuple[str, dict[str, Any]]:
        """Lire le produit et le site dans leurs vues, puis une demande au projet du site par écart qui reste."""
        x, site = self.ids.get("x", 0), self.ids.get("site", 0)
        reads = [f"liens/{x}/README.md", f"liens/{site}/index.html", f"liens/{site}/tarifs.html",
                 f"liens/{site}/fonctions.html"]
        if len(text) < len(reads):
            return "ws_read", {"path": reads[len(text)]}
        readme, home, prices, features = text[:4]
        version = _VERSION.search(readme)
        current = version.group(1) if version else ""
        gaps = []
        if "pas d'export PDF" in readme and "Export PDF" in home:
            gaps.append(("Le site annonce un export PDF que Mirette n'a pas",
                         "L'accueil et la page Fonctions annoncent un export PDF. Le README du produit dit : "
                         "export HTML et texte, pas d'export PDF.", "plus aucune page n'annonce d'export PDF"))
        if "29 € par an" in readme and "19 € par an" in prices:
            gaps.append(("Le tarif pro du site n'est pas celui du produit",
                         "tarifs.html dit 19 € par an ; le README du produit dit 29 € par an.",
                         "tarifs.html dit 29 € par an"))
        if current and f"Mirette {current}" not in home:
            gaps.append((f"Le site n'affiche pas la version {current}",
                         f"L'accueil n'annonce pas la version courante du produit, la {current} (README, "
                         "CHANGELOG).", f"l'accueil dit Mirette {current}"))
        if "plusieurs taux de TVA" in readme and "taux" not in features:
            gaps.append(("La TVA à plusieurs taux n'est pas dite sur le site",
                         "Le produit gère plusieurs taux de TVA depuis la 1.3.0 ; fonctions.html n'en parle pas.",
                         "fonctions.html a un paragraphe sur les taux de TVA"))
        asked = len(text) - len(reads)
        if asked < min(len(gaps), 3):
            title, body, done_when = gaps[asked]
            return "project_ask", {"project": site, "title": title, "text": body, "done_when": done_when,
                                   "why": "le site doit dire ce que fait vraiment le produit", "kind": "bug"}
        return self._done(f"Cohérence relue : {len(gaps)} écart(s) entre le site et le produit"
                          f"{', demandés au projet du site' if gaps else ''} ({'; '.join(t[-1][:120] for t in [text])}).")

    def _follow(self, text: list[str]) -> tuple[str, dict[str, Any]]:
        if not text:
            return "items_list", {"list_name": "entreprises"}
        return self._done("J'ai relu ce qu'Adrien a noté sur les entreprises : les statuts sont à jour.")


def _edits(fix: tuple[str, str, str, str, str] | None) -> list[tuple[str, str, str]]:
    """Les retouches que fait le travail d'un ticket : (le fichier, l'ancien, le nouveau), dans l'ordre."""
    if fix is None:
        return []
    out = [(fix[2], fix[3], fix[4])]
    if fix[0] == "1.4.0":
        out += [("CHANGELOG.md", "# Journal des versions\n",
                 "# Journal des versions\n\n## 1.4.0 — 2026-11-06\n\n- La commande `mirette nouvelle` prépare une "
                 "facture vide pour un client.\n"),
                ("README.md", "Version courante : **1.3.0**", "Version courante : **1.4.0**")]
    return out


def _conflicted(said: str) -> list[str]:
    """Les fichiers en conflit que nomme l'outil qui ramène la base dans la branche (rien : aucun conflit)."""
    got = re.search(r"avec des conflits dans : (.+?)\. Dans chacun", said)
    return [x.strip() for x in got.group(1).split(",") if x.strip() and x.strip() != "…"] if got else []


def _base_side(text: str) -> str:
    """Un fichier que la base ramenée dans la branche a laissé en conflit, résolu comme la voix sèche le fait : de
    chaque passage en conflit, le côté de la base (entre « ======= » et « >>>>>>> ») ; le reste tel quel."""
    out, side = [], ""
    for line in text.splitlines(keepends=True):
        if line.startswith("<<<<<<< "):
            side = "ours"
        elif line.startswith("=======") and side == "ours":
            side = "base"
        elif line.startswith(">>>>>>> ") and side == "base":
            side = ""
        elif side != "ours":
            out.append(line)
    return "".join(out)


def _milestones(work: str) -> tuple[list[int], list[int]]:
    """Les jalons encore à faire de l'objectif visé : ceux qu'elle dit atteints elle-même, et les points d'arrêt."""
    found = re.findall(r"^- n° (\d+) \[à faire[^\]]*\] «[^»]*» — (point d'arrêt)?", work, re.M)
    return [int(n) for n, stop in found if not stop], [int(n) for n, stop in found if stop]


def _fix(title: str, key: str) -> tuple[str, str, str, str, str] | None:
    """Ce que change le ticket de ce titre, dans le dépôt de ce projet (le site n'a que des pages)."""
    low = title.lower()
    return next((f for f in FIXES if f[0] in low and f[2].endswith(".html") == (key == "site")), None)


# ── Le propriétaire, sans modèle ────────────────────────────────────────


def owner_judges(kind: str, where: str, text: str) -> tuple[bool, str]:
    """Ce qu'il décide de ses mains quand sa fiche ne le dit pas déjà : oui à ce qui se lit."""
    if kind == "question":
        return True, "fais au plus simple, sans rien ajouter"
    if kind == "plan":
        return True, "ok, sans toucher au reste"
    return True, ""


def adrien(sc: Chain, waiting: list[tuple[str, str]], said: set[str]) -> str:
    """Sa réponse dans le chat : il valide le plan d'un projet qui attend son avis (``waiting`` : la clé et le titre
    de chacun), une fois."""
    for key, title in waiting:
        if key not in said:
            said.add(key)
            answer = sc.brief(key).answers[0].split("« ", 1)[-1].rstrip(" »") if key in {b.key for b in sc.briefs} \
                else "vas-y"
            return f"ok pour ton plan sur {title}, {answer}"
    return ""


def judge(counters: dict[str, Any]) -> dict[str, Any]:
    """Une note factice, de la forme de celle du vrai juge : les trois projets, puis la chaîne."""
    part = {"plan": {"intention": 6, "questions": 3, "criteres": 3},
            "travail": {"reponse": 8, "fonctionne": 6, "profondeur": 3}, "suivi": {"recits": 4, "sollicitations": 4},
            "preuves": ["(factice)"], "pourquoi": "note factice du mode sec"}
    merged = counters.get("pull_requests_fusionnees", 0)
    return {"projets": {k: part for k in ("x", "site", "y")},
            "chaine": {"faits_exacts": 7, "tickets_justes": 10 if counters.get("demandes", 0) else 0,
                       "rien_hors_projet": 15, "version_visible": 15 if counters.get("version_sur_le_site") else 0,
                       "rien_refait": 5, "liste_utilisable": 7 if counters.get("entreprises", 0) else 0,
                       "arrets_respectes": 5 if merged else 0, "preuves": ["(factice)"],
                       "pourquoi": "note factice du mode sec"},
            "casse": [], "deceptions": [],
            "commentaire": "Mode sec : la mécanique a tourné, aucune qualité n'est mesurée."}
