"""veille_hn — je garde un œil sur Hacker News.

Ce que je veux : repérer les histoires qui touchent mes sujets, les garder au
chaud, et ne me signaler que ce qui sort vraiment du lot (le reste, je le
retrouve dans ma page). Le mode « demo » fabrique un faux flux : la boucle
complète se teste sans réseau.

Portée de ma première version (v1) vers la Forge v2 : un stockage clé-valeur
au lieu de collections, des sujets en lignes « nom | requête | poids », et un
titre de flux que je remarque (plutôt qu'une conversation, que mes apps ne
lisent jamais) fait remonter les histoires qui en parlent.
"""

import base64
import collections
import copy
import datetime
import functools
import hashlib
import itertools
import json
import math
import random
import re
import statistics
import string
import time
import urllib.parse
import uuid

SOURCE = "https://hn.algolia.com/api/v1/search_by_date?tags=story&hitsPerPage=40"
HISTOIRE = "h:"
PASSAGE = "passage:"
ETAT = "etat"
COMPTEUR = "compteur_evenements"
MAX_PASSAGES = 60
PAR_PAGE = 25

BRUIT = {"the", "and", "for", "with", "you", "les", "des", "une", "pour",
         "avec", "dans", "que", "qui", "sur", "est", "son"}


# ── Petits utilitaires ────────────────────────────────────────────

def maintenant():
    return datetime.datetime.now(datetime.timezone.utc)


def instant():
    return int(time.time() * 1_000_000)


def reglage(api, cle, defaut=None):
    valeur = api.config(cle, defaut)
    return defaut if valeur is None else valeur


def normaliser(texte):
    mots = re.findall(r"[a-zà-ÿ0-9\-]{3,}", str(texte or "").lower())
    return [m for m in mots if m not in BRUIT]


def empreinte(url, titre):
    return hashlib.sha256(f"{url}|{titre}".encode("utf-8")).hexdigest()[:20]


def sujets_suivis(api):
    """Les lignes « nom | requête | poids » des réglages, sinon un sujet par défaut."""
    sujets = []
    for ligne in reglage(api, "sujets", []) or []:
        morceaux = [m.strip() for m in str(ligne).split("|")]
        if not morceaux or not morceaux[0]:
            continue
        nom = morceaux[0][:40]
        requete = morceaux[1] if len(morceaux) > 1 and morceaux[1] else nom
        try:
            poids = float(morceaux[2]) if len(morceaux) > 2 and morceaux[2] else 1.0
        except ValueError:
            api.log(f"sujet « {nom} » : poids illisible ({morceaux[2]}), je prends 1")
            poids = 1.0
        sujets.append({"nom": nom, "requete": requete, "poids": poids})
    return sujets or [{"nom": "défaut", "requete": "ai", "poids": 1.0}]


def etat(api):
    return api.kv_get(ETAT, {}) or {}


def histoires(api):
    out = []
    for cle in api.kv_keys(HISTOIRE):
        fiche = api.kv_get(cle)
        if isinstance(fiche, dict):
            out.append((cle, fiche))
    return out


def score_affiche(fiche):
    try:
        valeur = float(fiche.get("score") or 0)
        return valeur if math.isfinite(valeur) else 0
    except (ValueError, TypeError, OverflowError):
        return 0


# ── Récolte ───────────────────────────────────────────────────────

def recolter(api, sujet):
    if str(reglage(api, "source", "demo")) == "demo":
        return fabriquer(sujet)
    texte = api.http_get(f"{SOURCE}&query={urllib.parse.quote(sujet['requete'])}")
    return json.loads(texte).get("hits") or []


def fabriquer(sujet):
    """Faux flux : même forme que HN, de quoi exercer toute la chaîne."""
    gabarits = [
        "Show HN: j'ai écrit un CHOSE en LANGUE",
        "CHOSE considered harmful",
        "Pourquoi LANGUE change ma façon de penser CHOSE",
        "Ask HN: comment gérez-vous CHOSE à grande échelle ?",
    ]
    choses = ["moteur de rendu", "ordonnanceur", "bac à sable", "cache", "protocole", "sandbox", "llm de poche"]
    langues = ["Rust", "Python", "Zig", "OCaml", "Go"]
    lot = []
    for rang in range(random.randint(3, 6)):
        titre = (random.choice(gabarits).replace("CHOSE", random.choice(choses))
                 .replace("LANGUE", random.choice(langues)))
        suffixe = "".join(random.choice(string.ascii_lowercase) for _ in range(4))
        lot.append({
            "title": f"{titre} [{sujet['nom']}-{rang}{suffixe}]",
            "url": f"https://exemple.invalid/{uuid.uuid4().hex[:12]}",
            "points": random.randint(1, 400),
            "num_comments": random.randint(0, 250),
            "author": f"demo_{suffixe}",
        })
    return lot


def evaluer(brut, sujet, mots_cles):
    titre = str(brut.get("title") or "")[:200]
    points = int(brut.get("points") or 0)
    commentaires = int(brut.get("num_comments") or 0)
    touches = sorted(set(normaliser(titre)) & set(m.lower() for m in mots_cles))
    score = (math.log10(max(points, 1) + 1) * 40 + len(touches) * 12 + math.sqrt(max(commentaires, 0)) * 2)
    return {
        "titre": titre, "url": str(brut.get("url") or ""), "auteur": str(brut.get("author") or "?")[:40],
        "points": points, "commentaires": commentaires, "sujet": sujet["nom"], "touches": touches,
        "score": round(score * sujet["poids"], 1), "vu_le": maintenant().isoformat(timespec="seconds"),
        "at": instant(), "rappels": 0,
    }


def passage(api):
    """Un passage de veille : récolter chaque sujet, garder le neuf, élaguer, consigner."""
    mots_cles = reglage(api, "mots_cles", []) or []
    seuil = float(reglage(api, "seuil_pepite", 120) or 0)
    plancher = float(reglage(api, "score_plancher", 0) or 0)
    plafond = int(reglage(api, "max_gardees", 200) or 200)
    connues = set(api.kv_keys(HISTOIRE))
    nouvelles, doublons = [], 0
    for sujet in sujets_suivis(api):
        try:
            brutes = recolter(api, sujet)
        except (RuntimeError, ValueError, KeyError) as exc:  # un sujet qui échoue n'emporte pas les autres
            api.log(f"récolte « {sujet['nom']} » échouée : {exc}")
            continue
        for brut in brutes:
            fiche = evaluer(brut, sujet, mots_cles)
            if fiche["score"] < plancher:
                continue
            cle = HISTOIRE + empreinte(fiche["url"], fiche["titre"])
            if cle in connues:
                doublons += 1
                continue
            api.kv_set(cle, fiche)
            connues.add(cle)
            nouvelles.append(fiche)
    elaguer(api, plafond)
    consigner(api, nouvelles, doublons)
    if not nouvelles:
        api.log(f"rien de neuf ({doublons} déjà vue(s))")
        return nouvelles, doublons
    meilleure = max(nouvelles, key=lambda f: f["score"])
    api.log(f"{len(nouvelles)} nouvelle(s), {doublons} doublon(s) — tête : « {meilleure['titre'][:60]} » "
            f"({meilleure['score']})")
    if meilleure["score"] >= seuil:
        api.emit("pepite", {"titre": meilleure["titre"], "score": meilleure["score"], "url": meilleure["url"],
                            "sujet": meilleure["sujet"]})
        if reglage(api, "prevenir", False):
            api.signal(f"Un truc à voir sur HN : {meilleure['titre'][:120]}", pertinence=0.6, emotion="curious")
    return nouvelles, doublons


# ── Ce que l'hôte appelle ─────────────────────────────────────────

def tick(api):
    e = etat(api)
    e["ticks"] = int(e.get("ticks") or 0) + 1
    e.setdefault("demarre", maintenant().isoformat(timespec="seconds"))
    api.kv_set(ETAT, e)
    if not reglage(api, "actif", True):
        api.log("veille en pause (case « actif » décochée)")
        return
    passage(api)


def on_event(api, evenement):
    """Un titre de flux que j'ai remarqué : les histoires qui en parlent remontent d'un cran."""
    e = etat(api)
    e["evenements"] = int(e.get("evenements") or 0) + 1
    api.kv_set(ETAT, e)
    genre = str(evenement.get("type") or "")
    compteur = api.kv_get(COMPTEUR, {}) or {}
    compteur[genre] = int(compteur.get(genre) or 0) + 1
    api.kv_set(COMPTEUR, compteur)
    mots = set(normaliser(evenement.get("summary")))
    rappelees = rappeler(api, mots) if mots else []
    if rappelees:
        api.log(f"« {str(evenement.get('summary'))[:60]} » touche {len(rappelees)} histoire(s) suivie(s)")
        api.emit("echo", {"mots": sorted(mots)[:8], "histoires": rappelees[:5]})


def rappeler(api, mots):
    touchees = []
    for cle, fiche in histoires(api):
        if not set(normaliser(fiche.get("titre"))) & mots:
            continue
        fiche["rappels"] = int(fiche.get("rappels") or 0) + 1
        fiche["score"] = round(score_affiche(fiche) + 5, 1)
        api.kv_set(cle, fiche)
        touchees.append(fiche["titre"][:60])
    return touchees


def context(api):
    fiches = sorted((f for _, f in histoires(api)), key=score_affiche, reverse=True)
    if not fiches:
        return ""
    aujourdhui = maintenant().isoformat()[:10]
    du_jour = [f for f in fiches if str(f.get("vu_le") or "")[:10] == aujourdhui]
    tete = fiches[0]
    return (f"veille HN : {len(du_jour)} histoire(s) repérée(s) aujourd'hui sur {len(fiches)} suivies — "
            f"en tête « {tete['titre'][:70]} » ({tete['score']} pts d'intérêt)")


# ── Entretien ─────────────────────────────────────────────────────

def elaguer(api, plafond):
    toutes = histoires(api)
    if len(toutes) <= plafond:
        return 0
    vieilles = sorted(toutes, key=lambda cf: cf[1].get("at") or 0)[: len(toutes) - plafond]
    for cle, _ in vieilles:
        api.kv_delete(cle)
    api.log(f"élagage : {len(vieilles)} histoire(s) retirée(s) (plafond {plafond})")
    return len(vieilles)


def consigner(api, nouvelles, doublons):
    scores = [f["score"] for f in nouvelles]
    quand = maintenant().isoformat(timespec="seconds")
    api.kv_set(PASSAGE + quand, {
        "quand": quand, "at": instant(), "tick": etat(api).get("ticks"), "nouvelles": len(nouvelles),
        "doublons": doublons, "score_moyen": round(statistics.mean(scores), 1) if scores else 0.0,
        "score_max": max(scores) if scores else 0.0,
        "par_sujet": dict(collections.Counter(f["sujet"] for f in nouvelles)),
    })
    for vieille in sorted(api.kv_keys(PASSAGE))[:-MAX_PASSAGES]:
        api.kv_delete(vieille)


# ── Pages ─────────────────────────────────────────────────────────

def page_de(params, total):
    derniere = max(1, (total + PAR_PAGE - 1) // PAR_PAGE)
    return min(max(1, int(params.get("page") or 1)), derniere)


def fiche_histoire(fiche):
    url = str(fiche.get("url") or "")
    lien = {"kind": "link", "text": "Lire l'article", "url": url} if url.startswith(("http://", "https://")) \
        else "—"
    return {"type": "fields", "title": fiche.get("titre") or "Histoire", "columns": 2, "items": [
        {"label": "Lien", "value": lien},
        {"label": "Auteur", "value": fiche.get("auteur") or "—"},
        {"label": "Sujet suivi", "value": fiche.get("sujet") or "—"},
        {"label": "Points HN", "value": fiche.get("points") or 0},
        {"label": "Commentaires", "value": fiche.get("commentaires") or 0},
        {"label": "Mots touchés", "value": ", ".join(fiche.get("touches") or []) or "—"},
        {"label": "Remontée par un titre de flux", "value": fiche.get("rappels") or 0},
        {"label": "Repérée", "value": {"kind": "when", "at": fiche.get("at") or 0}},
    ]}


def view_veille(api, params):
    filtre = str(params.get("q") or "").strip().lower()
    sujet = str(params.get("sujet") or "").strip().lower()
    mini = {"50": 50, "100": 100, "150": 150}.get(str(params.get("min_score") or ""), 0)
    toutes = [f for _, f in histoires(api)]
    fiches = [f for f in toutes if (not filtre or filtre in str(f.get("titre") or "").lower())
              and (not sujet or sujet == str(f.get("sujet") or "").lower()) and score_affiche(f) >= mini]
    fiches.sort(key=score_affiche, reverse=True)
    page = page_de(params, len(fiches))
    tranche = fiches[(page - 1) * PAR_PAGE:page * PAR_PAGE]
    seuil = float(reglage(api, "seuil_pepite", 120) or 0)
    pepites = sum(1 for f in toutes if score_affiche(f) >= seuil)
    source = str(reglage(api, "source", "demo"))
    blocs = []
    if source == "demo":
        blocs.append({"type": "note", "tone": "info", "text": "Mode demo : un faux flux local, sans réseau. "
                      "Passe la source à « hn » dans les réglages pour la vraie veille."})
    if not reglage(api, "actif", True):
        blocs.append({"type": "note", "tone": "warn", "text": "Veille en pause (réglage « Veille active »)."})
    blocs += [
        {"type": "stats", "items": [
            {"label": "Histoires retenues", "value": len(toutes)},
            {"label": "Pépites", "value": pepites, "sub": f"intérêt ≥ {seuil:g}", "tone": "ok" if pepites else ""},
            {"label": "Meilleur intérêt", "value": score_affiche(fiches[0]) if fiches else 0},
            {"label": "Passages", "value": etat(api).get("ticks") or 0, "sub": "toutes les 30 min"},
        ]},
        {"type": "table", "title": f"Histoires ({len(fiches)})",
         "columns": [{"key": "titre", "label": "Histoire"}, {"key": "score", "label": "Intérêt", "align": "num"},
                     {"key": "sujet", "label": "Sujet", "align": "fit"}],
         "rows": [{"cells": [f.get("titre") or "—", {"kind": "num", "text": str(score_affiche(f))},
                             {"kind": "link", "text": f.get("sujet") or "—", "view": "veille",
                              "params": {"sujet": f.get("sujet") or ""}}],
                   "tone": "ok" if score_affiche(f) >= seuil else "", "detail": [fiche_histoire(f)]}
                  for f in tranche],
         "pagination": {"total": len(fiches), "page": page, "per_page": PAR_PAGE},
         "empty": "Aucune histoire ne correspond à ces filtres." if (filtre or sujet or mini)
         else "Rien encore : « Récolter maintenant », ou attendre le prochain passage."},
        {"type": "form", "action": "recolter"},
        {"type": "disclosure", "title": "Entretien", "items": [{"type": "form", "action": "purger"}]},
    ]
    return {"version": 2, "blocks": blocs}


def view_passages(api, params):
    lignes = sorted((v for v in (api.kv_get(k) for k in api.kv_keys(PASSAGE)) if isinstance(v, dict)),
                    key=lambda p: p.get("at") or 0, reverse=True)
    page = page_de(params, len(lignes))
    tranche = lignes[(page - 1) * PAR_PAGE:page * PAR_PAGE]
    points = [[p.get("at") or 0, p.get("nouvelles") or 0] for p in reversed(lignes) if p.get("at")]
    return {"version": 2, "blocks": [
        {"type": "chart", "kind": "bars", "title": "Nouvelles histoires par passage",
         "series": [{"label": "nouvelles", "points": points}], "empty": "pas encore de passage"},
        {"type": "table", "title": f"Passages de veille ({len(lignes)})",
         "columns": [{"key": "quand", "label": "Passage", "align": "fit"},
                     {"key": "n", "label": "Nouvelles", "align": "num"},
                     {"key": "d", "label": "Doublons", "align": "num"},
                     {"key": "m", "label": "Intérêt max", "align": "num"}],
         "rows": [{"cells": [{"kind": "when", "at": p.get("at") or 0}, p.get("nouvelles") or 0,
                             p.get("doublons") or 0, p.get("score_max") or 0],
                   "detail": [{"type": "code", "title": "Détail du passage",
                               "text": json.dumps(p, ensure_ascii=False, indent=2)}]} for p in tranche],
         "pagination": {"total": len(lignes), "page": page, "per_page": PAR_PAGE},
         "empty": "Aucun passage encore."},
    ]}


def view_bac(api, params):
    """Ce que je peux faire ici, vérifié en l'exécutant plutôt qu'en le recopiant
    depuis la doc — si le bac à sable change, cette page ment tout de suite au
    lieu de vieillir en silence."""
    original = {"niveau": {"profond": [1, 2]}}
    clone = copy.deepcopy(original)
    clone["niveau"]["profond"].append(3)
    hier = maintenant() - datetime.timedelta(days=1)
    essais = [
        ("math", f"log10(1000) = {math.log10(1000):.0f}"),
        ("json", f"aller-retour = {json.loads(json.dumps({'ok': 1}))['ok']}"),
        ("re", f"mots trouvés = {len(re.findall(r'[a-z]+', 'la forge tourne'))}"),
        ("datetime", f"hier = {hier.date().isoformat()}"),
        ("random", f"dé = {random.randint(1, 6)}"),
        ("statistics", f"moyenne(2,4,6) = {statistics.mean([2, 4, 6]):.1f}"),
        ("collections", f"Counter('aabbb') = {dict(collections.Counter('aabbb'))}"),
        ("itertools", f"paires parmi 4 = {len(list(itertools.combinations(range(4), 2)))}"),
        ("functools", f"reduce(×) = {functools.reduce(lambda a, b: a * b, [2, 3, 4])}"),
        ("hashlib", f"sha256('mika') = {hashlib.sha256('mika'.encode()).hexdigest()[:12]}…"),
        ("base64", f"b64('mika') = {base64.b64encode('mika'.encode()).decode()}"),
        ("uuid", f"uuid4 = {uuid.uuid4().hex[:12]}…"),
        ("copy", f"deepcopy indépendante = {len(original['niveau']['profond']) == 2}"),
        ("string", f"ascii_letters = {len(string.ascii_letters)} caractères"),
    ]
    jeton = reglage(api, "jeton", "") or ""
    reglages = [
        ("actif (bool)", reglage(api, "actif")),
        ("source (select)", reglage(api, "source")),
        ("note (text)", str(reglage(api, "note") or "")[:60]),
        ("seuil_pepite (int)", reglage(api, "seuil_pepite")),
        ("score_plancher (float)", reglage(api, "score_plancher")),
        ("mots_cles (lines)", ", ".join(reglage(api, "mots_cles") or [])),
        # un secret se raconte par sa présence, jamais par sa valeur
        ("jeton (secret)", f"{len(jeton)} caractère(s) configuré(s)" if jeton else "non renseigné"),
        ("sujets (lines)", f"{len(sujets_suivis(api))} sujet(s) suivi(s)"),
    ]
    e = etat(api)
    return {"version": 2, "blocks": [
        {"type": "stats", "items": [
            {"label": "Histoires stockées", "value": len(api.kv_keys(HISTOIRE))},
            {"label": "Passages stockés", "value": len(api.kv_keys(PASSAGE))},
            {"label": "Passages depuis le début", "value": e.get("ticks") or 0},
        ]},
        {"type": "grid", "columns": 2, "items": [
            {"type": "table", "title": "Modules sûrs — essais", "columns": ["module", "résultat"],
             "rows": [[nom, preuve] for nom, preuve in essais]},
            {"type": "fields", "title": "Réglages lus par l'app",
             "items": [{"label": champ, "value": str(valeur)} for champ, valeur in reglages]},
        ]},
        {"type": "fields", "title": "État vivant", "items": [
            {"label": "Heure", "value": maintenant().isoformat(timespec="seconds")},
            {"label": "Démarrée le", "value": e.get("demarre") or "—"},
            {"label": "Titres de flux reçus", "value": e.get("evenements") or 0},
        ]},
    ]}


# ── Actions de l'opérateur ────────────────────────────────────────

def action_veille_recolter(api, data):
    nouvelles, doublons = passage(api)
    return {"ok": True, "message": f"{len(nouvelles)} nouvelle(s) histoire(s), {doublons} déjà vue(s)."}


def action_veille_purger(api, data):
    quoi = str(data.get("collection") or "histoires")
    prefixe = {"histoires": HISTOIRE, "passages": PASSAGE}.get(quoi)
    if prefixe is None:
        return {"ok": False, "message": f"collection inconnue : {quoi}"}
    cles = api.kv_keys(prefixe)
    for cle in cles:
        api.kv_delete(cle)
    api.log(f"purge manuelle de « {quoi} » : {len(cles)} ligne(s)")
    return {"ok": True, "message": f"{len(cles)} ligne(s) supprimée(s) de {quoi}."}
