# Maquette du frontendv2

Le client web de tous les jours d'une personne connectée : le chat avec Mika (et le mode pro), ses outils, son
courrier, son Teams, son téléphone et ses paramètres. Pas de monde 3D : Mika vit dans un coin de l'écran. Cette page
est une **maquette à valider** : les données sont fictives et rien ne parle au moteur.

## L'ouvrir

- **Avec la VRM** (servie en HTTP, depuis la racine du dépôt) :

  ```bash
  python3 -m http.server 8791 --bind 127.0.0.1
  # puis http://127.0.0.1:8791/frontendv2/maquette/
  ```

- **Sans serveur** : ouvrir `index.html` dans le navigateur. Les modules étant refusés en `file://`, Mika garde son
  portrait pré-rendu, qui cligne des yeux.

La VRM (`frontend/Web/public/models/default.vrm`), les portraits (`frontend/Android/app/src/main/assets/avatar/`) et
la police Inter (`backendv2/src/mika/inspector/static/fonts/`) sont lus là où ils sont : rien n'est copié ici. La VRM et
les portraits sont sous licence et ne sont pas versionnés.

Paramètres d'adresse utiles pour les captures : `?theme=dark|light`, `?vrm=0` (portrait seul), `?pro=1` (chat en
mode pro), `?notes=1` (panneau des notes ouvert), et la route après `#` :

| Écran | Routes |
|---|---|
| Chat | `#chat` (le bouton Pro du champ passe en mode pro) |
| Outils | `#outils/droits` (la matrice des droits, ressource par ressource), `#outils/services`, `#outils/accords` |
| Mail | `#mail/messages`, `#mail/messages/m-claire`, `#mail/messages/d-lefevre`, `#mail/contacts` |
| Teams | `#teams/discussions/lumen`, `#teams/discussions/claire`, `#teams/brouillons` |
| Téléphone | `#telephone/messages/julien`, `#telephone/notifications`, `#telephone/position` (le sélecteur en haut passe d'un téléphone à l'autre) |
| Paramètres | `#parametres/compte`, `#parametres/comptes-mail/pro`, `#parametres/teams`, `#parametres/telephones`, `#parametres/partages`, `#parametres/mcp/factures` |

## Les notes

Le bouton **Notes**, en haut, ouvre pour chaque écran la liste de ce que le moteur sait déjà faire (« Existe »), de
ce qui est en chantier (« En cours ») et de ce qui manque ou reste à décider, avec les fichiers du moteur. C'est là,
et pas dans l'interface, que la maquette dit ce qui n'existe pas encore.

## Le thème

- Fond blanc et filets, sans aplat gris en clair ; sombre complet. Inter, Inter Display pour les titres.
- La navigation est en haut ; sur un téléphone, elle passe en barre du bas, comme sur Android.
- Chaque écran a une barre de titre : son nom, ses onglets, puis ses actions à droite.
- Un écran tient dans la fenêtre ; chaque liste défile dans son cadre.
- Deux couleurs portent un sens : **l'indigo** de l'app Android pour ce que tu fais, **le rose** de Mika pour ce
  qu'elle fait (ce qu'elle a lu, ce qu'elle propose, ce qu'elle a rédigé).
- Mika a une place fixe, qui ne couvre rien : dans le chat, sa VRM en buste en bas à droite (la conversation et
  son champ s'arrêtent avant elle) ; partout ailleurs, et en mode pro, son visage — sa VRM encore — au bout de la
  barre de titre, comme sur Android. Un clic sur son visage ou sur son nom ouvre « Ce qu'elle fait ».
- Ctrl K cherche partout : un mail, une personne, une discussion, un outil, un réglage.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `index.html` | le cadre : la barre du haut, les icônes, le coin de Mika, la palette |
| `maquette.css` | les jetons (clair, sombre) et les composants communs |
| `maquette.js` | le moteur : routes, barre de titre, coin de Mika, palette, menus, fenêtres, toasts |
| `donnees.js` | qui est connecté, les personnes, l'état de Mika et le fil rouge entre les écrans |
| `mika-vrm.js` | la VRM du coin (module, HTTP seulement) |
| `ecrans/<écran>.js` et `.css` | un écran chacun : chat, outils, mail, teams, telephone, parametres |

L'API d'un écran est décrite en tête de `maquette.js`.
