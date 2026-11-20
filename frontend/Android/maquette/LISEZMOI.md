# Maquette de l'app Android, avec ce que fait le frontendv2

L'app Android d'aujourd'hui (la conversation, « Ce qu'elle fait », les paramètres) à laquelle s'ajoutent les écrans du
frontendv2 : Mail, Teams, Carte, Téléphone, Outils, et les paramètres de la personne connectée. Elle sert à décider
de la place des boutons et des écrans **avant** d'écrire du Kotlin. Les données sont fictives et rien ne parle au
moteur. **Validée le 2026-11-17, en variante « Tiroir »** (« en mode tiroir je préfère ») : c'est la navigation de
l'app (ADR 0235). Les écarts de l'app avec elle, et pourquoi, sont dans `frontend/Android/README.md` (l'ADR 0233 l'emporte
sur Téléphone : ni onglet Notifications, ni sélecteur de téléphone). Ses écrans ne se retouchent plus ; son sprite
d'icônes (`index.html`) reste la source de celles de l'app (`tools/icones.py`) : une icône neuve s'y ajoute.

**Proposé le 2026-11-17, à valider** : la fiche d'un lieu (notes et avis Tripadvisor, infos pratiques d'OpenStreetMap,
ce qu'en dit l'office de tourisme, photos) et un onglet Événements (DATAtourisme), dans `ecrans/carte-avis.js` :
`#carte/manger`, `#carte/fiche/atelier`, `#carte/fiche/reblochon`, `#carte/evenements`, `#carte/evenement/poulenc`.
Les événements sont les vrais, tirés de l'API DATAtourisme le 17 novembre ; les restaurants et leurs avis sont inventés.

## L'ouvrir

```bash
python3 -m http.server 8792 --bind 127.0.0.1     # depuis la racine du dépôt
# puis http://127.0.0.1:8792/frontend/Android/maquette/
```

Sur un ordinateur, le téléphone (un S25, 384 × 832 dp) est à droite et le panneau à gauche :

- **Variantes à comparer** : la navigation par barre du bas (Chat · Mail · Teams · Carte · Plus) ou par tiroir (le
  chat en plein écran, comme aujourd'hui) ; le thème.
- **Cet écran** : ce qu'il montre et ce qu'il reste **à trancher** (les questions de placement).
- **Tous les écrans** : un lien par écran.

Ouverte sur une fenêtre de 760 px ou moins, la maquette prend tout l'écran, sans le cadre ni le panneau.

Paramètres d'adresse : `?theme=dark|light`, `?nav=barre|tiroir`, puis la route après `#` (`#chat`, `#chat/accord`,
`#chat/pro`, `#mail`, `#mail/lire/m-claire`, `#mail/brouillon/d-lefevre`, `#teams/d/claire`, `#carte`,
`#carte/voyage/alpes`, `#telephone/c/rando`, `#outils`, `#plus`, `#parametres`, `#mika`…).

## Ce qu'elle lit ailleurs, sans le copier

- les personnes, l'état de Mika et ses portraits : `frontendv2/maquette/donnees.js` ;
- le fond de carte (la France simplifiée, © OpenStreetMap) : `frontendv2/maquette/ecrans/carte-fond.js` ;
- les portraits pré-rendus : `app/src/main/assets/avatar/` (sous licence, non versionnés ; sans eux, un rond coloré) ;
- la police Inter de la console, si Roboto manque.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `index.html` | le panneau, le cadre du téléphone, les icônes |
| `maquette.css` | les jetons (clair, sombre) et les composants Material 3 |
| `maquette.js` | le moteur : routes, barre du haut, barre du bas ou tiroir, feuilles, menus, fenêtres, son visage, le panneau |
| `ecrans/<écran>.js` | un écran chacun : chat (avec la recherche, les fichiers et « Ce qu'elle fait »), mail, teams, carte, telephone, outils, plus (avec Paramètres) |
