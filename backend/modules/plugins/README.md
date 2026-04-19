# Écrire un module

Un module est un plugin auto-contenu qui vit sous `backend/modules/plugins/<nom>/`. Il peut au choix :

- tourner en tâche de fond (`worker_cron`, connexions, pollers…)
- exposer des **outils MCP** à Mika (`return_tools`)
- écouter / émettre des **événements inter-modules** (`on_event`, `module_manager.emit_event`)
- notifier Mika pour déclencher une réponse (`self._notify_ai(...)`)
- déclarer ses propres **tables Django** (`get_models`)
- exposer des **paramètres** dans l'éditeur de configuration (`config_schema`)
- monter des **routes HTTP** techniques (`get_routes`)
- **contribuer des pages au dashboard** (`get_views`) ← documenté ici

Toutes ces capacités sont opt-in. Un module minimal n'implémente que `instantiate()` + `shutdown()`.

Le contrat complet est défini dans [backend/modules/base.py](../base.py) (`BaseModule`).

---

## Arborescence d'un module

```
backend/modules/plugins/<nom>/
├── __init__.py          ← exporte la classe (ex: from .module import EmailModule)
├── module.py            ← la classe qui hérite de BaseModule
├── models.py            ← (optionnel) modèles Django
├── config_schema.py     ← (optionnel) sections + items pour l'éditeur de config
├── views.py             ← (optionnel) ModuleView[] exposés au dashboard
├── templates/<nom>/     ← (optionnel) templates Django custom
│   └── <view>.html
└── static/<nom>/        ← (optionnel) JS/CSS custom
    └── views/<view>.js
```

Après création, enregistrer le module dans [backend/modules/apps.py](../apps.py) :

```python
from modules.plugins.<nom> import <NomModule>
module_manager.register(<NomModule>())
```

Les modules inactifs (config manquante, `is_available()==False`) apparaissent quand même dans l'admin, mais leurs outils / routes / vues ne sont montés qu'une fois activés.

---

## Dashboard views — ajouter des pages au dashboard

Chaque module peut surfacer plusieurs **pages de visualisation** dans la sidebar du dashboard (boîte de réception, historique, stats, comptes…). Le système est symétrique à `config_schema()` : le module déclare, le dashboard découvre et monte automatiquement.

### Ce que tu obtiens gratuitement

Pour chaque `ModuleView` déclarée, le shell du dashboard monte sans aucune configuration :

| Endpoint | Méthode | Qui consomme |
|----------|---------|--------------|
| `/dashboard/modules/<mod>/<view>/` | GET | Page HTML (template du module, sinon shell générique) |
| `/dashboard/api/modules/<mod>/views` | GET | Liste des vues d'un module |
| `/dashboard/api/modules/<mod>/views/<view>` | GET | Appelle `data_handler(request)` |
| `/dashboard/api/modules/<mod>/views/<view>/items/<id>` | GET | Appelle `detail_handler(request, id)` |
| `/dashboard/api/modules/<mod>/views/<view>/actions/<key>` | POST | Exécute l'action déclarée |

Une vue est visible dans la sidebar uniquement si le module est **activé ET running**. Désactiver le module la fait disparaître.

### Contrat `ModuleView` ([backend/modules/types.py](../types.py))

```python
ModuleView(
    key            = "inbox",              # slug unique dans le module
    label          = "Boîte de réception", # libellé sidebar
    icon           = "✉",                  # un caractère
    order          = 10,                   # ordre d'affichage

    data_handler   = async (request) -> dict,
    detail_handler = async (request, item_id: str) -> dict | None,
    id_field       = "id",                 # nom du champ ligne qui porte l'id

    template       = None,                 # "email/inbox.html" pour opt-in custom
    js             = None,                 # "/static/email/views/inbox.js"

    actions        = [ModuleViewAction(...), ...],
)
```

```python
ModuleViewAction(
    key     = "mark_all_read",
    label   = "Tout marquer comme lu",
    handler = async (request) -> dict,
    method  = "POST",
    confirm = "Sûr ?",  # optionnel : prompt de confirmation côté UI
)
```

### Deux façons de rendre une vue

#### Option A — shell générique (zéro fichier dans le module)

Tu renvoies juste du JSON depuis tes handlers et le dashboard s'occupe du rendu. **Conventions de forme** comprises automatiquement par [dashboard/js/views/module_default.js](../../dashboard/static/dashboard/js/views/module_default.js) :

**Liste paginée** (retourné par `data_handler`) :
```json
{
  "columns": [{"key": "id", "label": "#"}, {"key": "subject", "label": "Sujet"}],
  "rows":    [{"id": 1, "subject": "Hello"}, ...],
  "total": 128, "page": 0, "limit": 25
}
```
Query params standards (à lire dans `request.GET`) : `page`, `limit`, `q`. La pagination est de la responsabilité du handler.

**Détail** (retourné par `detail_handler`) :
```json
{"fields": [{"key":"from","label":"De","value":"alice@x"}, ...]}
```
ou n'importe quel dict plat → rendu en grille clé/valeur dans une modale.
Si `detail_handler` est déclaré, le renderer ajoute automatiquement une colonne **"Voir"** aux lignes dont `row[id_field] != null`.

**Action** (retourné par `ModuleViewAction.handler`) : n'importe quel dict JSON-sérialisable. Un bouton par action est placé en tête de la vue.

Exemple (simplifié) :
```python
# modules/plugins/todo/views.py
async def _list(request):
    rows = await sync_to_async(
        lambda: list(Task.objects.all().values("id", "title", "done"))
    )()
    return {
        "columns": [{"key":"id","label":"#"}, {"key":"title","label":"Titre"},
                    {"key":"done","label":"Fait"}],
        "rows": rows, "total": len(rows),
    }

async def _detail(request, item_id):
    t = await sync_to_async(Task.objects.get)(pk=int(item_id))
    return {"fields": [
        {"key":"title", "label":"Titre", "value": t.title},
        {"key":"notes", "label":"Notes", "value": t.notes},
    ]}

def todo_views():
    return [
        ModuleView(
            key="tasks", label="Tâches", icon="✓",
            data_handler=_list, detail_handler=_detail,
        ),
    ]
```

Dans ta classe module :
```python
def get_views(self):
    from modules.plugins.todo.views import todo_views
    return todo_views()
```

Et voilà — sidebar, table paginée, bouton "Voir", modale clé/valeur, le tout sans HTML ni JS.

#### Option B — template + JS custom

Pour un rendu riche (split master/détail, graphiques, form complet, rendu HTML d'un mail…), tu shipes ton propre template + JS dans le module lui-même.

**Déclaration** :
```python
ModuleView(
    key="inbox",
    ...
    template="email/inbox.html",       # résolu depuis modules/plugins/email/templates/
    js="/static/email/views/inbox.js", # résolu depuis modules/plugins/email/static/
)
```

**Découverte automatique** — [backend/config/settings.py](../../config/settings.py) scanne au démarrage :
- `backend/modules/plugins/*/templates` → ajouté à `TEMPLATES[0]['DIRS']`
- `backend/modules/plugins/*/static` → ajouté à `STATICFILES_DIRS`

Nomenclature conventionnelle : préfixer les dossiers par le nom du module (`templates/email/inbox.html`, `static/email/views/inbox.js`) pour éviter les collisions entre modules.

**Template minimal** — le plus simple est d'étendre `dashboard/base.html` et d'exposer `window.ModuleView` pour que le JS retrouve les URLs :

```html
{% extends "dashboard/base.html" %}
{% block scripts %}
  <script>
    window.ModuleView = {
      module: "{{ module_name }}",
      key: "{{ view_key }}",
      label: "{{ view_label|escapejs }}",
      dataUrl: "/dashboard/api/modules/{{ module_name }}/views/{{ view_key }}",
      itemUrl: (id) =>
        `/dashboard/api/modules/{{ module_name }}/views/{{ view_key }}/items/${encodeURIComponent(id)}`,
      actionUrl: (key) =>
        `/dashboard/api/modules/{{ module_name }}/views/{{ view_key }}/actions/${encodeURIComponent(key)}`,
      hasDetail: {% if view_has_detail %}true{% else %}false{% endif %},
      idField: "{{ view_id_field|default:'id'|escapejs }}",
    };
  </script>
  <script src="{{ view_js }}"></script>
{% endblock %}
```

**Outils JS disponibles** (chargés par `base.html`, exposés sur `window.Dash`) :
- `Dash.api(url)` — fetch + JSON + gestion d'erreur silencieuse
- `Dash.escapeHTML(str)` — échappement XSS
- `Dash.fmtDate(iso)`, `Dash.fmtRel(iso)`, `Dash.pct(v)`, `Dash.clip(s, n)`
- `Dash.openModal({title, body, footer})` — modale, clic backdrop/échap ferme
- `Dash.confirm(msg)` — promesse qui résout bool
- `Dash.pager({total, limit, offset, onPrev, onNext})` — élément de pagination
- `Dash.emoChip(emotion, weight)` — puce d'émotion colorée
- `Dash.render(async fn)` — wrapper recommandé pour ton renderer principal

Exemple complet : [modules/plugins/email/static/email/views/inbox.js](email/static/email/views/inbox.js).

### Mélanger A et B

Les deux coexistent à l'échelle d'un même module. Vois [modules/plugins/email/views.py](email/views.py) :
- `inbox` → Option B (template custom + JS split master/détail)
- `contacts` → Option A (shell générique + `detail_handler` → modale clé/valeur)
- `accounts` → Option A simple (juste une liste, pas de détail)

Tu peux commencer en A (vite), passer en B plus tard sans casser les URLs (même `data_handler`, même `detail_handler`, même actions).

### Sécurité & performance

- **XSS** : le shell générique et les helpers `escapeHTML`/`escapejs` protègent par défaut. Ne JAMAIS injecter du HTML non sanitisé (ex: `body_html` d'un email) sans passer par un sanitizer — l'exemple `inbox.js` affiche toujours le texte brut ou une version *stripped* du HTML.
- **Pagination** : les listes non bornées vont finir par exploser la page. Cap le `limit` côté serveur (voir `_int(request, "limit", 25, hi=100)` dans `email/views.py`).
- **Performance** : les handlers sont async ; toute lecture ORM doit passer par `sync_to_async`. Les modules sont libres de retourner un `JsonResponse` directement si tu veux contrôler `status` ou `headers`.
- **Permissions** : pas d'auth sur le dashboard actuellement. Si ça change, le filtre sera ajouté au niveau du shell (`module_views.py`) — les modules n'ont pas à se préoccuper.

### Où regarder quand un truc ne marche pas

| Symptôme | Où chercher |
|----------|-------------|
| Vue absente de la sidebar | Le module est-il **enabled + running** ? `/dashboard/api/modules` liste l'état |
| 404 sur `/dashboard/modules/<mod>/<view>/` | `get_views()` retourne-t-elle bien la vue ? (page `modules/` recharge la liste) |
| Template introuvable | Nom correct, arborescence `templates/<mod>/<view>.html` ? Redémarrer le serveur (les `DIRS` sont scannées au boot) |
| JS 404 | Chemin préfixé `/static/` ? Fichier dans `static/<mod>/...` ? Même point : scan au boot |
| "Voir" n'apparaît pas | Les lignes du `data_handler` contiennent-elles `id_field` (par défaut `"id"`) ? `detail_handler` déclaré ? |
| Handler lève | Le shell log `logger.exception` et renvoie HTTP 500 + `{"error": "..."}`. Regarde la console `uvicorn` |
