# Forge — modules auto-gérés par l'IA

La Forge est l'espace confiné où **Mika crée, modifie, teste et supprime ses
propres mini-modules**, sans redémarrage et sans pouvoir toucher au reste du
système. Un seul plugin (`forge`) est visible du `ModuleManager` ; il héberge
N modules forgés stockés dans `data/forge_modules/` (gitignoré).

```
data/forge_modules/
  veille_meteo/
    manifest.yaml        ← déclaratif (écrit par Mika via forge_write_module)
    module.py            ← code sandboxé
    state.json           ← état runtime (enabled, raison de désactivation)
    _versions/<ts>/      ← snapshots auto avant chaque écriture (rollback)
  _trash/<nom>-<ts>/     ← modules effacés (récupérables à la main)
```

## Ce qu'un module forgé peut faire

| Capacité | Comment |
|----------|---------|
| Stockage / « BDD » | `api.storage.set/get/delete/find/keys/count/clear(collection, ...)` — clé/valeur JSON par collections, isolé par module, quotas (`forge.max_records_per_module`, `forge.max_value_kb`) |
| Config utilisateur | section `config:` du manifest → apparaît dans **Dashboard ▸ Configuration ▸ « Forge · \<titre\> »** (types scalaires, `secret`, `select`, et `record_list` pour les listes d'objets). Lu via `api.config.get(key)` / `api.config.rows(key)` |
| Planification | `schedule:` du manifest — `interval:30s/5m/2h`, `cron:0 9 * * MON-FRI`, `idle:15m`, `manual` → appelle `on_tick(api)` |
| Réveil / signaux | `events:` du manifest (motifs `rss.new_entry`, `chat.*`, `forge.autre.*`) → `on_event(api, event)` ; `api.emit(type, data)` émet `forge.<module>.<type>` sur le bus (Conscience + autres modules) ; `api.notify_ai(...)` réveille Mika (cooldown `forge.notify_cooldown_s`) |
| Pages dashboard | `views:` du manifest + fonctions `view_<key>(api, params)` / `view_<key>_detail(api, item_id)` → pages auto-montées dans la sidebar sous `/dashboard/modules/forge/<module>__<vue>/` (rendu générique Option A, payload assaini — pas de HTML brut) |
| Contexte prompt | `context: true` + `get_context(api) -> str` → injecté dans le prompt système de Mika (rafraîchi après chaque tick/événement) |
| HTTP sortant | `api.http_get(url)` — uniquement vers les hôtes de `allowed_domains:`, redirections désactivées, IP privées/loopback bloquées, réponse tronquée |
| Journal | `api.log/warn/error(...)` + `print(...)` → table `ForgeLog`, visible dans la page « Forge » et via `forge_read_logs` |

## Contrat du code (`module.py`)

Fonctions top-level optionnelles, **toutes synchrones** :

```python
def on_start(api): ...              # au chargement
def on_tick(api): ...               # selon schedule
def on_event(api, event): ...       # event = {"type", "source", "data"}
def get_context(api): return "..."  # injecté dans le prompt (si context: true)
def view_stats(api, params): return {"columns": [...], "rows": [...]}
def view_stats_detail(api, item_id): return {"fields": [...]}
```

Modules sûrs déjà disponibles (pas d'`import`) : `math, json, re, datetime,
random, statistics, collections, itertools, functools, hashlib, base64,
uuid, copy, string` (sous-ensemble constantes).

## Le bac à sable

Trois couches (voir [sandbox.py](sandbox.py)) :

1. **Validation AST à l'écriture** — rejette : `import`, code async, tout
   attribut préfixé `_` (donc tous les dunders), `eval/exec/open/getattr/
   setattr/type/globals/...`, `.format`/`.format_map` (traversée
   d'attributs), source > `forge.max_source_kb`. Messages d'erreur en
   français, renvoyés tels quels à Mika pour correction.
2. **Builtins filtrés à l'exécution** — pas d'`__import__`, pas d'`open` ;
   modules sûrs injectés en lecture seule (`FrozenModule`).
3. **Deadline par handler** — chaque appel tourne dans un thread pool dédié
   (2 workers) avec un tracer qui interrompt les boucles infinies au-delà de
   `forge.handler_timeout_s` (défaut 10 s). Un module forgé lent ne bloque
   jamais le scheduler partagé (les ticks partent en tâche de fond).

**Disjoncteur** : `forge.max_consecutive_failures` (défaut 5) échecs
consécutifs de tick/événement → le module est auto-désactivé
(`state.json`), déchargé, et Mika reçoit une notification avec l'erreur
pour qu'elle corrige et réactive elle-même.

**Limites assumées** : le code reste in-process (pas d'isolation OS). Le
validateur bloque les évasions classiques (`__class__`, `__globals__`,
`str.format`, monkey-patch des modules partagés) et l'API capacitaire est
la seule surface d'I/O, mais un adversaire déterminé n'est pas le modèle de
menace — le code est généré localement par Mika. Les appels C bloquants
(regex pathologique) ne sont pas interruptibles : le pool borné + le
timeout asyncio limitent l'impact à la Forge elle-même.

## Gestion (les 3 canaux)

**Outils MCP** (pour Mika) : `forge_list_modules`, `forge_read_module`,
`forge_write_module` (création/màj, validation, archivage, hot reload),
`forge_command` (`enable | disable | reload | rollback | erase |
reset_storage`), `forge_test_module` (exécute un handler immédiatement,
retourne résultat + logs — la boucle d'itération), `forge_read_logs`.

**Routes HTTP** : `GET /api/modules/forge/` (liste), `POST
/api/modules/forge/command` (`{"name", "command", "confirm"?}`), `GET
/api/modules/forge/source?name=`, `GET /api/modules/forge/logs?name=&limit=`.

**Dashboard** : page « Forge » (onglets Modules / Journal / Stockage,
détail par module avec manifest + code + logs, action « Tout recharger »).
Les sections de config des modules forgés apparaissent dans l'éditeur de
configuration standard ; les valeurs survivent aux reload/disable (elles ne
sont supprimées qu'avec la base).

## Exemple complet

```yaml
# manifest.yaml (généré par forge_write_module)
title: Veille météo
description: Relève la météo et me prévient si ça se gâte
schedule: interval:30m
events: []
views:
  - {key: releves, label: Relevés, icon: "☁"}
config:
  - {key: ville, label: Ville, type: str, default: Paris}
allowed_domains: [wttr.in]
context: true
```

```python
# module.py
def on_tick(api):
    ville = api.config.get('ville')
    reponse = api.http_get(f"https://wttr.in/{ville}?format=j1")
    if reponse['status'] != 200:
        api.warn(f"wttr.in a répondu {reponse['status']}")
        return
    data = json.loads(reponse['text'])
    actuel = data['current_condition'][0]
    releve = {'temp': actuel['temp_C'], 'quand': api.now().isoformat()}
    api.storage.set('releves', releve['quand'][:16], releve)
    if int(actuel['temp_C']) < 0:
        api.notify_ai(f"Il gèle à {ville} ({actuel['temp_C']}°C) !")

def get_context(api):
    dernier = api.storage.find('releves', limit=1)
    return f"dernier relevé météo: {dernier[0]['value']['temp']}°C" if dernier else ""

def view_releves(api, params):
    lignes = api.storage.find('releves', limit=int(params.get('limit') or 50))
    return {
        'columns': [{'key': 'key', 'label': 'Quand'}, {'key': 'temp', 'label': '°C'}],
        'rows': [{'id': l['key'], 'key': l['key'], 'temp': l['value']['temp']} for l in lignes],
    }
```

## Réglages (Dashboard ▸ Configuration ▸ « Modules · Forge »)

`forge.handler_timeout_s` (10), `forge.max_modules` (12),
`forge.max_consecutive_failures` (5), `forge.max_records_per_module`
(5000), `forge.max_value_kb` (32), `forge.max_source_kb` (64),
`forge.notify_cooldown_s` (300), `forge.emit_rate_per_min` (12),
`forge.http_timeout_s` (10), `forge.http_max_kb` (512). Répertoire :
`FORGE_DIR` (env, défaut `data/forge_modules/`).

## Tests

`backend/tests/test_forge_sandbox.py` (validateur, env d'exécution,
deadline), `test_forge_store.py` (manifest, versions, corbeille),
`test_forge_api.py` (quotas, HTTP, cooldowns), `test_forge_host.py`
(cycle de vie complet : écriture → tick → événements → disjoncteur →
commandes → vues → config dynamique → outils MCP).
