# Écrire un module

> **Note** : ce guide concerne les modules « système » écrits par un humain dans
> le code. Les modules que **Mika écrit elle-même** passent par la **Forge**
> ([forge/README.md](forge/README.md)) — un espace confiné (`data/forge_modules/`)
> avec validation sandbox, hot reload, disjoncteur et outils MCP dédiés.

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

## Panneaux — ajouter des pages à l'espace du module

Un module déclare `get_panels()` et reçoit un **espace** sous
`/gestion/modules/<nom>/` : son état, son cycle de vie, sa configuration et
ses pages, dans une seule sous-navigation. L'espace existe dès que le module
est *enregistré*, qu'il tourne ou non — c'est justement quand il ne démarre
pas qu'on a besoin de ses réglages.

### Le principe : tu décris, tu ne rends pas

Un gestionnaire renvoie des **blocs typés** faits de **cellules typées**. Tu
déclares une intention (« ceci est un badge d'alerte », « ceci est une
jauge ») ; la mise en forme appartient à GestionSystème.

Ce n'est pas une contrainte esthétique. Le contrat précédent renvoyait du
JSON qu'un script injectait via `innerHTML` : un module qui faisait transiter
un corps d'e-mail, un article RSS ou une page aspirée obtenait du XSS stocké
sur l'interface qui édite les clés d'API. Avec des cellules typées, le rendu
n'a **aucun chemin** d'une donnée vers du balisage — la classe de bug a
disparu au lieu d'être filtrée.

### Ce que tu obtiens gratuitement

- pagination et filtres pilotés par l'URL (partageables, compatibles retour arrière) ;
- échappement automatique de Django sur tout ;
- boutons d'action protégés par CSRF, qui conservent le contexte de l'écran ;
- thème clair/sombre, tableaux adaptatifs, états vides ;
- une page qui reste navigable même si ton panneau lève une exception.

### Exemple complet

```python
# modules/plugins/todo/panels.py
from GestionSysteme import panels as P
from GestionSysteme import tables


def liste(request):
    from modules.plugins.todo.models import Tache

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    etat = fs.add(tables.select_filter(
        request, "etat", "État", [("todo", "à faire"), ("done", "faite")],
    ))
    q = fs.add(tables.search_filter(request, "q", "Recherche"))

    qs = Tache.objects.all()
    if etat.value:
        qs = qs.filter(status=etat.value)
    if q.value:
        qs = qs.filter(titre__icontains=q.value)

    page = tables.paginate(request, qs.order_by("-cree_le"), per_page=fs.per_page)

    return P.Table(
        caption="Tâches",
        filters=fs,
        columns=[
            P.Column("Titre"),
            P.Column("État", align="fit"),
            P.Column("Avancement"),
            P.Column("Créée", align="fit"),
        ],
        rows=[
            P.Row(
                # Rend la ligne cliquable : le détail est une URL, donc
                # partageable, et le retour arrière ferme la fiche.
                href=tables.url_with(request, tache=t.pk),
                cells=(
                    P.text(t.titre, clamp=True),
                    P.badge(t.status, tone="ok" if t.status == "done" else "warn"),
                    P.meter(t.progression),
                    P.mono(t.cree_le.strftime("%d/%m %H:%M")),
                ),
            )
            for t in page.rows
        ],
        page=page,
        empty="Aucune tâche ne correspond à ces filtres.",
    )


def tout_terminer(request):
    from modules.plugins.todo.models import Tache

    n = Tache.objects.filter(status="todo").update(status="done")
    return P.Note(f"{n} tâche(s) terminée(s).", tone="ok")


def get_panels() -> list:
    return [
        P.ModulePanel(
            key="taches", label="Tâches", icon="✓", order=10,
            handler=liste,
            description="Ce qu'il reste à faire.",
            actions=(
                P.PanelAction(
                    key="tout_terminer", label="Tout terminer",
                    handler=tout_terminer,
                    confirm="Marquer toutes les tâches comme faites ?",
                ),
            ),
        ),
    ]
```

Puis dans `module.py` :

```python
    def get_panels(self) -> list:
        from modules.plugins.todo.panels import get_panels
        return get_panels()
```

### Les blocs disponibles

| Bloc | Pour quoi |
|---|---|
| `Table(columns, rows, page=, filters=, empty=, caption=)` | une liste |
| `Fields(items=[Field(label, value, kind=, tone=, href=)])` | une fiche clé/valeur |
| `Stats(items=[Stat(label, value, sub=, tone=)])` | des tuiles de chiffres |
| `Note(text, tone=, title=)` | un encadré (info / ok / warn / danger) |
| `Prose(text, title=)` | du texte long (narratif, corps de message) |
| `Blocks(items=[...])` | plusieurs blocs dans un panneau |
| `Template(name, context)` | ton propre gabarit Django (voir plus bas) |

### Les cellules disponibles

`P.text(v, clamp=)` · `P.mono(v)` · `P.num(v)` · `P.muted(v)` ·
`P.badge(v, tone=)` · `P.link(v, href=)` · `P.meter(ratio, tone=)` ·
`P.boolean(v)` · `P.emotion(nom, weight=)`

`tone` vaut `""`, `ok`, `warn`, `danger` ou `info`. Un `kind` inconnu retombe
sur du texte échappé : inventer une valeur ne casse pas la page.

### L'échappatoire : ton propre gabarit

`Template("todo/vue.html", {...})` rend un gabarit que **tu** livres dans
`modules/plugins/todo/templates/todo/`. C'est du code que tu possèdes, pas
une donnée que tu relaies, et il passe quand même par le moteur de gabarits
— donc échappé par défaut. À réserver aux mises en page que les blocs ne
savent pas exprimer.

### Détail, actions, asynchrone

- **Détail** : pas de contrat séparé. Lis un paramètre d'URL
  (`request.GET.get("tache")`) et préfixe un `Fields` à ton tableau. C'est ce
  que fait le module email pour ses messages.
- **Actions** : `PanelAction` produit un bouton en haut de page, servi en POST
  derrière un formulaire CSRF. Le formulaire **reporte la chaîne de requête**,
  donc ton action sait quelle fiche est ouverte et quels filtres sont posés.
  Elle renvoie une `Note` (ou une chaîne).
- **Asynchrone** : un gestionnaire peut être `def` ou `async def`. Pas de
  cérémonie pour un panneau qui lit trois lignes en base.

### Sécurité et performance

- Tu ne produis jamais de balisage : il n'y a rien à assainir.
- Un panneau qui lève devient un bloc d'erreur ; l'espace reste navigable.
- **Pagine** : `tables.paginate` prend un queryset *ou* une liste en mémoire.
  Un panneau qui charge tout ne se voit qu'en production.
- Les filtres passent par `tables.select_filter` / `search_filter`, qui
  bornent la saisie et refusent toute valeur hors liste — rien n'atteint
  l'ORM sans passer par une liste fermée.

### Où regarder quand un truc ne marche pas

| Symptôme | Vérifier |
|---|---|
| Le module n'a pas d'espace | Déclare-t-il `get_panels()` **ou** une section de configuration ? Un module sans ni l'un ni l'autre n'a rien à montrer. |
| L'espace est là, pas le panneau | `get_panels()` lève-t-elle ? L'exception est journalisée, la liste retombe à vide. |
| « Le panneau a échoué : … » | C'est ton gestionnaire ; le message porte l'exception. |
| Les clés `etat` / `configuration` sont ignorées | Réservées par la coquille. |

### Configuration

Elle ne passe pas par les panneaux : déclare `config_schema()` et
GestionSystème la rend elle-même dans l'onglet *Configuration* de ton espace.
Rien de ton côté à écrire pour l'affichage.
