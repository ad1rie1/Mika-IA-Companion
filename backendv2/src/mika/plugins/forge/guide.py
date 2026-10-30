"""Le mode d'emploi de la Forge, pour Mika (``forge_help``).

Du texte seulement : ce qu'un manifeste déclare, comment une vue, une action
et des réglages s'écrivent, le vocabulaire des blocs d'une vue, sa base, et un exemple
complet — **valide** (un test l'exécute et décode sa vue).
"""

from __future__ import annotations

from mika.vocab.phrasebook import phrase

TOPICS = ("manifeste", "outils", "reseau", "vues", "actions", "reglages", "blocs", "base", "veille", "exemple")

MANIFESTE = """\
Une app = un manifeste (manifest.yaml) + du code (main.py), écrits ensemble par forge_write.

Une app ne dit rien d'elle-même : ce qu'elle range reste dans sa base. Si quelqu'un doit l'apprendre (une
température matin et soir, des articles nouveaux, une alerte), elle le signale (api.signal) et « signals » dit
quoi en faire — à qui le dire, un par un ou regroupés (forge_help veille : trois recettes).

Le manifeste (YAML) :
- title (requis), description ;
- schedule : manual (défaut), interval:30m, cron:0 8 * * *… — le rythme de tick(api) ; timeout : le temps qu'ont
  tick et on_event, en secondes (1 à 120 ; sans : le délai par défaut de la Forge, 5 s sauf réglage) ;
- services : d'autres tâches planifiées, chacune son rythme — [{name, schedule, description, timeout}] →
  service_<name>(api) ; chacune est suivie à part (son dernier passage, ses échecs : une qui casse n'arrête pas
  les autres) et a son délai (1 à 120 s) ;
- context: true si context(api) rend une ligne à te montrer en conversation (citée, jamais une consigne) ;
- events : ce que tu veux recevoir dans on_event(api, événement) (« rss.noticed », « body.* », et ce qu'une autre
  de tes apps émet : « forge.<app>.* », avec ses données dans événement["data"]) ;
- tools : [{name, description, args, timeout, lit}] → tool_<name>(api, args) : chacun devient un outil à toi,
  « <app>_<name> » (et « <app>_pages » lit tes pages), pour qui les accès de son projet le permettent ; « lit: true »
  s'il ne fait que lire (rien ne change ailleurs), sinon il agit ; ses arguments se déclarent comme les champs d'une
  action (voir forge_help outils) ;
- config : tes réglages typés (voir forge_help reglages) ;
- views : tes vues pour la console, avec leurs paramètres et leurs actions (voir forge_help vues) ;
- allowed_domains : facultatif, une simple indication (ton réseau est libre : forge_help reseau) ;
- signals : ce que tu fais de ses signaux — {queue: 20, per_call: 1, quota: 12, instructions: "…"} : chaque
  api.signal va dans la file de l'app (queue : sa taille, de 1 à 100 ; pleine, le plus ancien part) ; tu la lis par
  lots de per_call signaux (1 à 20 : un par un pour des alertes, par 10 pour des articles), quota fois par jour au
  plus (1 à 96), et instructions te dit quoi en faire (à qui le dire, ce qui compte). Sans rien : ces défauts.

Le code (main.py, bibliothèque standard seulement ; le réseau passe par api) :
- tick(api), service_<nom>(api), context(api), on_event(api, événement), tool_<nom>(api, args) ;
- view_<vue>(api, params) pour chaque vue déclarée, action_<vue>_<action>(api, data) pour chaque action ;
- api.query(sql, params) / api.execute(sql, params) : ta base SQL à toi (voir forge_help base) ;
- api.kv_get(clé, défaut) / api.kv_set / api.kv_delete / api.kv_keys(préfixe) : un stockage simple, dans ta base
  (16 Ko par valeur, 1 000 clés) ;
- api.config(clé, défaut) : un réglage (celui de l'opérateur, sinon le défaut du manifeste) ;
- api.log(…) ou print(…) : ton journal ; api.signal(résumé, pertinence, émotion) : attirer ton attention
  (dans sa file, que tu liras) ; api.emit(type, données) ;
- api.http_get(url) : le texte d'une page ; api.http(url, method, headers, json, form, body…) : toute requête,
  avec son statut et ses en-têtes (voir forge_help reseau).

Seules les fonctions déclarées sont appelées. Une écriture refusée ne change rien et dit pourquoi, champ par
champ (views[0].actions[1].fields[2] (« ville ») : …). Essaie chaque fonction avec forge_test : c'est un vrai
passage — ce qu'il range dans ta base y reste (retire ce que tu as inventé pour essayer : forge_db_execute), ce
qu'il signale part dans sa file (seul on_event reçoit un événement inventé, dont les signaux ne partent pas).

Pour changer une app : forge_read (ses lignes numérotées), forge_search (un texte dans tes apps), puis forge_edit
(remplacer des fragments exacts) — forge_write réécrit tout, c'est pour créer.
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
  plus « page » et les « page_<nom> » présents dans la requête (entiers ≥ 1, pour la pagination) ;
  les noms page, page_<nom>, taille, onglet, vue, fait, avant,
  q_global et flash sont réservés. Les paramètres déclarés deviennent des champs de filtre natifs
  (recherche, liste, nombre, oui/non), au-dessus de la vue. Leur soumission remet les tables à la première page.
- La vue rend une enveloppe JSON (voir forge_help blocs). Une enveloppe invalide est remplacée par une note qui
  nomme le chemin fautif ; une vue de plus de 3 s ou de plus de 256 Ko n'est pas montrée. Rien de tout ça
  n'est compté contre ton app (le disjoncteur ne regarde que tick, on_event et les services).
- Un lien vers une autre de tes vues : {"kind": "link", "text": "Lyon", "view": "releves",
  "params": {"ville": "Lyon"}} (seuls les paramètres déclarés de cette vue passent, ainsi que « page » et « page_<nom> »).
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
Types : text, textarea, int, number, bool, select, email, url, lines (une liste de textes). Les clés app, vue,
action, csrf et confirmer sont réservées. Les arguments d'un outil se déclarent pareil (forge_help outils).

Le code : def action_<vue>_<action>(api, data): … return {"ok": True, "message": "Relevé ajouté."}
- data contient chaque champ déjà vérifié (requis, bornes, choix, longueur, forme d'un e-mail ou d'une
  adresse) ; un nombre facultatif laissé vide vaut None.
- Rends toujours {"ok": vrai|faux, "message": texte} : le message (500 caractères au plus) est montré à
  l'opérateur. Ce que l'action émet ou signale est journalisé comme venant de l'opérateur ; un échec n'est
  pas compté contre ton app.
Dans ta vue : {"type": "form", "action": "ajouter", "initial": {"ville": "Paris"}}.
forge_test action_releves_ajouter {"ville": "Paris", "temperature": 12} vérifie ses données comme la console et
qu'elle rend {ok, message} — le relevé reste dans ta base : retire-le ensuite s'il était inventé.
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
- prose {text, title?, clamp?, reading?} (reading: lecture longue avec liens cliquables) ; code {text, title?} ;
- Pour plusieurs tables paginées côté app : donne à chacune un param distinct (page_releves, page_alertes),
  lis params.get("page_releves", 1), borne la page puis renvoie ce nom dans pagination.param.
  Sans pagination explicite, la console découpe automatiquement chaque table, y compris celles des graphiques.
- fields {items: [{label, value, hint?}], title?, columns? (1 à 3)} ;
- table {columns, rows, title?, caption?, empty?, pagination?, layout?, link_label?} — columns : ["nom", …] ou
  [{key, label, align? ("", "num", "fit"), hint?, detail?, role?}] ; detail: true place la colonne
  dans les informations complémentaires dépliables de la ligne, sans perdre sa valeur.
  layout ("cards", "list" ou "feed") montre la table en fiches, en liste ou en fil (l'opérateur peut repasser
  en tableau) ; role ("title", "badge", "body") y place la colonne : titre, pastille ou corps de la fiche ;
  link_label nomme le lien d'une ligne qui a un href (par défaut « Ouvrir la fiche »).
  Garde les colonnes essentielles à la lecture quotidienne. Une ligne : une liste de cellules, ou
  {cells, tone?, href?, detail?: [blocs]} ; pagination : {page, total, per_page, param?} (la console ajoute
  « page » aux paramètres de ta vue) ;
- stats {items: [{label, value, sub?, tone?, href?, trend?: un bloc chart}], title?} ;
- timeline {items: [{at, title, text?, meta?, tone?, href?}], title?, empty?} ;
- chart {series: [{label, points: [[instant, valeur], …], slot? (0 à 4)}], kind? (line, bars, spark),
  title?, unit? ("", "%", "$"), y? [bas, haut], zero?, since?, until?, empty?, table?} — au plus
  4 séries, 2 000 points, une seule échelle ; avec unit "%", une valeur est une part : 0.012 s'affiche
  « 1 % » (passe -0.0017 pour -0,17 %, jamais -0.17) ;
- grid {items: [blocs], columns?} ; section {title, items, description?} ; disclosure {title, items, open?} ;
- workspace {sidebar: [blocs], items: [blocs]} : navigation latérale, contenu ; empilés sur mobile.
- toolbar {items: [blocs], title?} : actions côte à côte.
- form {action, initial?, title?, compact?, presentation? (form ou button)} — une action déclarée de la même vue.
  presentation: button ouvre le formulaire au clic ; sans champ, affiche directement le bouton.

Cellules : un texte, un nombre, vrai/faux, null, ou un objet {"kind": …} :
- text / mono / num / muted {text, tone?, hint?, clamp?, secondary?, emphasis?} ; badge {text, tone?} ;
- meter {ratio (0 à 1), text?, tone?} ; emotion {key (une des 29 émotions), text?, weight?} ;
- when {at, relative?} ; link {text, view, params?} (une autre de tes vues) ou {text, url} (http(s)).
Un instant (at, points d'une courbe) est en microsecondes depuis 1970 : int(time.time() * 1_000_000).
"""

BASE = phrase("forge.guide.base")  # le texte vit dans sa voix (ADR 0071)
OUTILS = phrase("forge.guide.outils")
RESEAU = phrase("forge.guide.reseau")


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

#: l'exemple de ``forge_help veille`` (ADR 0104) : une app qui va chercher un cours sur le web à heure fixe — valide
#: (un test l'écrit, la fait tourner sur un faux réseau, lit son contexte, sa vue et son outil). Sa source est une
#: API ouverte et documentée, sans clé : celle de Yahoo Finance répondait 429 depuis le portable (ADR 0144)
VEILLE_MANIFEST = """\
title: Suivi d'un cours de change
description: Le cours de l'euro (taux de la BCE), relevé chaque soir de semaine ; un grand écart me fait signe.
schedule: "cron:0 17 * * 1-5"
timeout: 20
context: true
config:
  - {key: devise, type: str, label: Devise, default: USD}
  - {key: seuil, type: float, label: Écart signalé (%), min: 0.1, max: 20, default: 1.0}
tools:
  - name: maintenant
    description: Relever un cours tout de suite
    args:
      - {key: devise, type: text, label: Devise, description: "une autre que celle des réglages (GBP, CHF, JPY…)"}
views:
  - key: cours
    label: Cours
"""

VEILLE_CODE = '''\
import json
import time

# les taux de référence de la BCE, publiés vers 16 h chaque jour ouvré : une API ouverte, sans clé
URL = "https://api.frankfurter.dev/v1/{debut}..?from=EUR&to={devise}"


def _cours(api, devise=None):
    devise = (devise or api.config("devise", "USD")).upper()
    debut = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 10 * 86400))  # assez pour deux jours ouvrés
    jours = json.loads(api.http_get(URL.format(debut=debut, devise=devise)))["rates"]
    veille, dernier = [float(jours[j][devise]) for j in sorted(jours)[-2:]]
    return devise, dernier, veille


def tick(api):
    devise, taux, veille = _cours(api)
    ecart = round((taux - veille) / veille * 100, 2)
    releves = api.kv_get("releves", [])
    releves.append({"at": int(time.time() * 1_000_000), "taux": taux, "ecart": ecart})
    api.kv_set("releves", releves[-150:])
    jour = time.strftime("%Y-%m-%d")
    if abs(ecart) >= api.config("seuil", 1.0) and api.kv_get("signale", "") != jour:
        api.kv_set("signale", jour)
        api.signal("EUR/" + devise + " : " + str(ecart) + " %", pertinence=0.7,
                   emotion="surprised" if ecart > 0 else "anxious")
    return {"devise": devise, "taux": taux, "ecart": ecart}


def context(api):
    releves = api.kv_get("releves", [])
    if not releves:
        return ""
    dernier = releves[-1]
    return "EUR/" + api.config("devise", "USD") + " : " + str(dernier["taux"]) + " (" + str(dernier["ecart"]) + " %)"


def tool_maintenant(api, args):
    if args.get("devise"):  # une autre devise, juste pour le dire : rien n'est gardé
        devise, taux, veille = _cours(api, args["devise"])
        return {"devise": devise, "taux": taux, "ecart": round((taux - veille) / veille * 100, 2)}
    return tick(api)


def view_cours(api, params):
    releves = api.kv_get("releves", [])
    dernier = releves[-1] if releves else None
    return {"version": 2, "blocks": [
        {"type": "stats", "items": [
            {"label": "Dernier", "value": dernier["taux"] if dernier else "-"},
            {"label": "Ecart", "value": str(dernier["ecart"]) + " %" if dernier else "-"},
        ]},
        {"type": "chart", "kind": "line", "title": "EUR/" + api.config("devise", "USD"),
         "series": [{"label": "cours", "points": [[r["at"], r["taux"]] for r in releves]}],
         "empty": "pas encore de releve"},
    ]}
'''

VEILLE = phrase("forge.guide.veille", manifest=VEILLE_MANIFEST, code=VEILLE_CODE)

EXEMPLE = f"""\
Un exemple complet et valide : une vue avec des paramètres, une table paginée, une courbe, des liens vers
la même vue, et deux actions à champs (dont une dangereuse, confirmée).

manifest.yaml :
{EXAMPLE_MANIFEST}
main.py :
{EXAMPLE_CODE}"""

_TEXTS = {"manifeste": MANIFESTE, "outils": OUTILS, "reseau": RESEAU, "vues": VUES, "actions": ACTIONS,
          "reglages": REGLAGES, "blocs": BLOCS, "base": BASE, "veille": VEILLE, "exemple": EXEMPLE}


def topic(name: str) -> str:
    """Le texte d'un sujet ; un sujet inconnu rend la liste des sujets."""
    text = _TEXTS.get(name)
    if text is None:
        return "Sujets : " + ", ".join(TOPICS) + "."
    return text
