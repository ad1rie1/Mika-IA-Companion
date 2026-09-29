"""Le mode d'emploi de la Forge, pour Mika (``forge_help``).

Du texte seulement : ce qu'un manifeste déclare, comment une vue, une action
et des réglages s'écrivent, le vocabulaire des blocs d'une vue, et un exemple
complet — **valide** (un test l'exécute et décode sa vue).
"""

from __future__ import annotations

TOPICS = ("manifeste", "vues", "actions", "reglages", "blocs", "exemple")

MANIFESTE = """\
Une app = un manifeste (manifest.yaml) + du code (main.py), écrits ensemble par forge_write.

Le manifeste (YAML) :
- title (requis), description ;
- schedule : manual (défaut), interval:30m, cron:0 8 * * *… — le rythme de tick(api) ;
- context: true si context(api) rend une ligne à te montrer en conversation (citée, jamais une consigne) ;
- allowed_domains : les seuls hôtes que api.http_get peut appeler (jamais une adresse privée) ;
- events : ce que tu veux recevoir dans on_event(api, événement) (« rss.noticed », « body.* ») ;
- tools : [{name, description}] → tool_<name>(api, args), utilisables quand tu travailles ;
- config : tes réglages typés (voir forge_help reglages) ;
- views : tes vues pour la console, avec leurs paramètres et leurs actions (voir forge_help vues).

Le code (main.py, bibliothèque standard seulement, sans réseau ni processus) :
- tick(api), context(api), on_event(api, événement), tool_<nom>(api, args) ;
- view_<vue>(api, params) pour chaque vue déclarée, action_<vue>_<action>(api, data) pour chaque action ;
- api.kv_get(clé, défaut) / api.kv_set / api.kv_delete / api.kv_keys(préfixe) : ton stockage (16 Ko par valeur) ;
- api.config(clé, défaut) : un réglage (celui de l'opérateur, sinon le défaut du manifeste) ;
- api.log(…) ou print(…) : ton journal ; api.signal(résumé, pertinence, émotion) : attirer ton attention
  (espacé) ; api.emit(type, données) ; api.http_get(url) vers tes domaines déclarés.

Seules les fonctions déclarées sont appelées. Une écriture refusée ne change rien et dit pourquoi, champ par
champ (views[0].actions[1].fields[2] (« ville ») : …). Essaie chaque fonction avec forge_test.
"""

VUES = """\
Une vue est une page de la console que l'opérateur ouvre sur la fiche de ton app (onglet « Vues »).

Déclaration (au plus 8 vues) :
  views:
    - key: releves            # minuscules, chiffres, _ (24 au plus)
      label: Relevés
      description: …
      order: 10               # l'ordre des onglets de vues
      params:                 # au plus 10
        - {key: ville, label: Ville, kind: search}                      # un texte
        - {key: periode, label: Période, kind: select, choices: [jour, semaine], default: jour}
        - {key: n, label: Combien, kind: int, default: 10}
        - {key: froid, label: Sous zéro, kind: bool}
      actions: [...]          # voir forge_help actions

Le code : def view_releves(api, params): … return {"version": 2, "blocks": [...]}
- params contient chaque paramètre déclaré, déjà vérifié (texte, entier ou None, vrai/faux, choix connu),
  plus « page » (un entier ≥ 1, pour la pagination) ; les noms page, taille, onglet, vue, fait, avant,
  q_global et flash sont réservés.
- La vue rend une enveloppe JSON (voir forge_help blocs). Une enveloppe invalide est remplacée par une note qui
  nomme le chemin fautif ; une vue de plus de 3 s ou de plus de 256 Ko n'est pas montrée. Rien de tout ça
  n'est compté contre ton app (le disjoncteur ne regarde que tick et on_event).
- Un lien vers une autre de tes vues : {"kind": "link", "text": "Lyon", "view": "releves",
  "params": {"ville": "Lyon"}} (seuls les paramètres déclarés de cette vue passent, et « page »).
- Un formulaire d'action en place : {"type": "form", "action": "ajouter", "initial": {"ville": "Lyon"}}.
- Une ancienne view(api) sans vues déclarées devient la vue « principale ».
forge_test view_releves {"ville": "Lyon"} rend la vue et te dit si l'enveloppe est valide.
"""

ACTIONS = """\
Une action est un formulaire que l'opérateur remplit dans une de tes vues ; elle s'exécute chez toi.

Déclaration (dans une vue, au plus 10) :
  actions:
    - key: ajouter
      label: Ajouter un relevé
      description: …
      confirm: Tu es sûre ?     # facultatif : une case à cocher avant d'envoyer
      danger: false             # vrai : le bouton est marqué comme dangereux
      fields:                   # au plus 30
        - {key: ville, type: text, label: Ville, required: true, max_length: 60}
        - {key: temperature, type: number, label: Température, min: -60, max: 60}
        - {key: jour, type: select, choices: [lundi, mardi]}
        - {key: urgent, type: bool}
        - {key: contact, type: email}
Types : text, textarea, int, number, bool, select, email, url. Les clés app, vue, action, csrf et
confirmer sont réservées.

Le code : def action_<vue>_<action>(api, data): … return {"ok": True, "message": "Relevé ajouté."}
- data contient chaque champ déjà vérifié (requis, bornes, choix, longueur, forme d'un e-mail ou d'une
  adresse) ; un nombre facultatif laissé vide vaut None.
- Rends toujours {"ok": vrai|faux, "message": texte} : le message (500 caractères au plus) est montré à
  l'opérateur. Ce que l'action émet ou signale est journalisé comme venant de l'opérateur ; un échec n'est
  pas compté contre ton app.
Dans ta vue : {"type": "form", "action": "ajouter", "initial": {"ville": "Paris"}}.
forge_test action_releves_ajouter {"ville": "Paris", "temperature": 12} vérifie qu'elle rend {ok, message}.
"""

REGLAGES = """\
Tes réglages sont ce qu'un opérateur peut régler pour ton app, dans la console (onglet « Réglages »),
même quand elle est cassée. Tu les lis avec api.config(clé, défaut).

  config:                     # au plus 30
    - {key: ville, type: str, label: Ville, group: Lieu, default: Paris, description: …}
    - {key: resume, type: text, label: Texte long}
    - {key: n, type: int, min: 1, max: 20, default: 5}
    - {key: seuil, type: float, min: 0, max: 1, default: 0.5}
    - {key: actif, type: bool, default: true}
    - {key: unite, type: select, choices: [celsius, fahrenheit], default: celsius}
    - {key: villes, type: lines, default: [Paris, Lyon]}      # une liste de textes
    - {key: cle_api, type: secret, label: Clé d'API}          # jamais de défaut
Types : str, text, int, float, bool, secret, select, lines. Un secret est scellé au repos et jamais
montré (la console dit seulement « défini » ou « non défini ») ; toi, tu le lis en clair.
L'ancienne forme plate (config: {seuil: 3, actif: false}) reste comprise.
"""

BLOCS = """\
L'enveloppe d'une vue : {"version": 2, "blocks": [ … ]} — des objets fermés (un champ inconnu invalide
la vue), au plus 200 blocs, 8 niveaux, 200 lignes, 30 colonnes, 10 000 caractères par texte,
300 000 au total, des nombres finis.

Blocs ("type") :
- note {text, tone?, title?} — tone : info, ok, warn, danger, muted ;
- prose {text, title?, clamp?} ; code {text, title?} ;
- fields {items: [{label, value, hint?}], title?, columns? (1 à 3)} ;
- table {columns, rows, title?, caption?, empty?, pagination?} — columns : ["nom", …] ou
  [{key, label, align? ("", "num", "fit"), hint?}] ; une ligne : une liste de cellules, ou
  {cells, tone?, href?, detail?: [blocs]} ; pagination : {page, total, per_page} (la console ajoute
  « page » aux paramètres de ta vue) ;
- stats {items: [{label, value, sub?, tone?, href?, trend?: un bloc chart}], title?} ;
- timeline {items: [{at, title, text?, meta?, tone?, href?}], title?, empty?} ;
- chart {series: [{label, points: [[instant, valeur], …], slot? (0 à 4)}], kind? (line, bars, spark),
  title?, unit? ("", "%", "$"), y? [bas, haut], zero?, since?, until?, empty?, table?} — au plus
  4 séries, 2 000 points, une seule échelle ;
- grid {items: [blocs], columns?} ; section {title, items, description?} ; disclosure {title, items, open?} ;
- form {action, initial?, title?, compact?} — une action déclarée de la même vue.

Cellules : un texte, un nombre, vrai/faux, null, ou un objet {"kind": …} :
- text / mono / num / muted {text, tone?, hint?, clamp?} ; badge {text, tone?} ;
- meter {ratio (0 à 1), text?, tone?} ; emotion {key (une des 29 émotions), text?, weight?} ;
- when {at, relative?} ; link {text, view, params?} (une autre de tes vues) ou {text, url} (http(s)).
Un instant (at, points d'une courbe) est en microsecondes depuis 1970 : int(time.time() * 1_000_000).
"""

EXAMPLE_MANIFEST = """\
title: Carnet météo
description: Des relevés de température par ville, notés par l'opérateur, avec leur courbe.
schedule: manual
config:
  - {key: ville, type: str, label: Ville par défaut, group: Lieu, default: Paris}
  - {key: par_page, type: int, label: Relevés par page, min: 5, max: 50, default: 10}
  - {key: unite, type: select, label: Unité, choices: [celsius, fahrenheit], default: celsius}
views:
  - key: releves
    label: Relevés
    description: Les relevés d'une ville, page par page, et leur courbe.
    params:
      - {key: ville, label: Ville, kind: search}
      - {key: froid, label: Seulement sous zéro, kind: bool}
    actions:
      - key: ajouter
        label: Ajouter un relevé
        fields:
          - {key: ville, type: text, label: Ville, required: true, max_length: 60}
          - {key: temperature, type: number, label: Température (°C), required: true, min: -60, max: 60}
          - {key: note, type: text, label: Remarque, max_length: 80}
      - key: vider
        label: Effacer cette ville
        danger: true
        confirm: Effacer tous les relevés de cette ville ?
        fields:
          - {key: ville, type: text, label: Ville, required: true}
"""

EXAMPLE_CODE = '''\
import time


def _releves(api, ville):
    return api.kv_get("releves:" + ville.lower(), [])


def _degres(api, celsius):
    if api.config("unite", "celsius") == "fahrenheit":
        return round(celsius * 9 / 5 + 32, 1), "°F"
    return round(celsius, 1), "°C"


def view_releves(api, params):
    ville = (params.get("ville") or api.config("ville", "Paris")).strip()
    par_page = api.config("par_page", 10)
    tous = sorted(_releves(api, ville), key=lambda r: r["at"], reverse=True)
    if params.get("froid"):
        tous = [r for r in tous if r["temperature"] < 0]
    total = len(tous)
    derniere = max(1, (total + par_page - 1) // par_page)
    page = min(max(1, params.get("page", 1)), derniere)
    morceau = tous[(page - 1) * par_page:page * par_page]
    lignes = []
    for r in morceau:
        valeur, unite = _degres(api, r["temperature"])
        lignes.append([{"kind": "when", "at": r["at"]}, {"kind": "num", "text": f"{valeur} {unite}"},
                       r.get("note") or ""])
    points = [[r["at"], _degres(api, r["temperature"])[0]] for r in reversed(tous[:200])]
    dernier = _degres(api, tous[0]["temperature"]) if tous else None
    villes = sorted(api.kv_get("villes", []))
    return {"version": 2, "blocks": [
        {"type": "stats", "items": [
            {"label": "Relevés", "value": total},
            {"label": "Le dernier", "value": f"{dernier[0]} {dernier[1]}" if dernier else "—"},
        ]},
        {"type": "chart", "kind": "line", "title": f"Température à {ville}",
         "series": [{"label": ville, "points": points}], "empty": "pas encore de relevé"},
        {"type": "table", "title": f"Relevés à {ville}",
         "columns": ["quand", {"key": "t", "label": "température", "align": "num"}, "remarque"],
         "rows": lignes, "empty": "aucun relevé", "pagination": {"page": page, "total": total, "per_page": par_page}},
        {"type": "table", "title": "Les villes", "columns": ["ville"],
         "rows": [[{"kind": "link", "text": v, "view": "releves", "params": {"ville": v}}] for v in villes],
         "empty": "aucune ville"},
        {"type": "form", "action": "ajouter", "initial": {"ville": ville}},
        {"type": "disclosure", "title": "Effacer", "items": [
            {"type": "form", "action": "vider", "initial": {"ville": ville}}]},
    ]}


def action_releves_ajouter(api, data):
    ville = data["ville"].strip()
    releves = _releves(api, ville)
    releves.append({"temperature": float(data["temperature"]), "note": data.get("note") or "",
                    "at": int(time.time() * 1_000_000)})
    api.kv_set("releves:" + ville.lower(), releves[-60:])
    villes = api.kv_get("villes", [])
    if ville not in villes:
        api.kv_set("villes", (villes + [ville])[-50:])
    if data["temperature"] <= -10:
        api.signal("il gèle fort à " + ville, pertinence=0.4, emotion="surprised")
    return {"ok": True, "message": "Relevé ajouté pour " + ville + "."}


def action_releves_vider(api, data):
    ville = data["ville"].strip()
    n = len(_releves(api, ville))
    api.kv_delete("releves:" + ville.lower())
    api.kv_set("villes", [v for v in api.kv_get("villes", []) if v != ville])
    return {"ok": True, "message": str(n) + " relevé(s) effacé(s) à " + ville + "."}
'''

EXEMPLE = f"""\
Un exemple complet et valide : une vue avec des paramètres, une table paginée, une courbe, des liens vers
la même vue, et deux actions à champs (dont une dangereuse, confirmée).

manifest.yaml :
{EXAMPLE_MANIFEST}
main.py :
{EXAMPLE_CODE}"""

_TEXTS = {"manifeste": MANIFESTE, "vues": VUES, "actions": ACTIONS, "reglages": REGLAGES, "blocs": BLOCS,
          "exemple": EXEMPLE}


def topic(name: str) -> str:
    """Le texte d'un sujet ; un sujet inconnu rend la liste des sujets."""
    text = _TEXTS.get(name)
    if text is None:
        return "Sujets : " + ", ".join(TOPICS) + "."
    return text
