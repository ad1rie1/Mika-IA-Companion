<div align="center">

<img src=".github/readme/mika-coucou.webp" width="260" alt="Mika, longs cheveux roux et pull sans manches, fait coucou">

# Mika

### Une compagne IA qui a sa propre vie

Elle se souvient, ressent, dort et rêve, mène ses projets,<br>
et vient vous parler d'elle-même : sur le web, sur votre téléphone, jusque dans Teams.

<br>

[![Statut](https://img.shields.io/badge/statut-en_d%C3%A9veloppement_actif-ec4899)](#-état-du-projet)
[![Licence](https://img.shields.io/badge/licence-MIT--0_libre-22c55e)](LICENSE)
[![Dernier commit](https://img.shields.io/github/last-commit/ad1rie1/Mika-IA-Companion?label=dernier%20commit&color=8b5cf6)](https://github.com/ad1rie1/Mika-IA-Companion/commits/main)
[![Commits par mois](https://img.shields.io/github/commit-activity/m/ad1rie1/Mika-IA-Companion?label=commits%2Fmois&color=8b5cf6)](https://github.com/ad1rie1/Mika-IA-Companion/pulse)
[![Tickets résolus](https://img.shields.io/github/issues-closed/ad1rie1/Mika-IA-Companion?label=tickets%20r%C3%A9solus&color=22c55e)](https://github.com/ad1rie1/Mika-IA-Companion/issues?q=is%3Aclosed)
[![PR fermées](https://img.shields.io/github/issues-pr-closed/ad1rie1/Mika-IA-Companion?label=PR%20ferm%C3%A9es&color=22c55e)](https://github.com/ad1rie1/Mika-IA-Companion/pulls?q=is%3Aclosed)

[![Tests](https://img.shields.io/badge/tests-~5_570-22c55e?logo=pytest&logoColor=white)](backend/tests)
[![Décisions](https://img.shields.io/badge/d%C3%A9cisions_%C3%A9crites-250_ADR-0ea5e9)](backend/docs/decisions.md)
[![Facultés](https://img.shields.io/badge/facult%C3%A9s-17-ec4899)](backend/ARCHITECTURE.md#les-facultés)
[![Plugins](https://img.shields.io/badge/plugins-13-ec4899)](backend/ARCHITECTURE.md#les-plugins)

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](backend)
[![Claude](https://img.shields.io/badge/Claude-API_%C2%B7_Claude_Code-D97757?logo=claude&logoColor=white)](https://www.anthropic.com/claude)
[![TypeScript](https://img.shields.io/badge/TypeScript-Vite-3178C6?logo=typescript&logoColor=white)](frontend/Web)
[![Three.js](https://img.shields.io/badge/Three.js-VRM-000000?logo=threedotjs&logoColor=white)](frontend/Web)
[![Kotlin](https://img.shields.io/badge/Kotlin-Compose-7F52FF?logo=kotlin&logoColor=white)](frontend/Android)
[![MariaDB](https://img.shields.io/badge/SQLite_%C2%B7_MariaDB-003545?logo=mariadb&logoColor=white)](backend/deploy/README.md)

<br>

[Qui est Mika](#-qui-est-mika) · [Ce qu'elle sait faire](#-ce-quelle-sait-faire) · [En images](#-en-images) · [Sous le capot](#-sous-le-capot) · [L'essayer](#-lessayer) · [État du projet](#-état-du-projet) · [Licence](#-licence)

<sub>🇬🇧 An AI companion with a life of her own. The code is in English; the docs, prompts and interface are in French.</sub>

</div>

---

## 💗 Qui est Mika

Mika n'est pas un assistant qui attend qu'on lui parle. Elle a une humeur qui monte et redescend, des besoins, un
sommeil, des souvenirs qui s'usent avec le temps, un lien différent avec chaque personne qu'elle connaît, et des
projets à elle. Quand elle a quelque chose à dire, elle le dit, sans qu'on lui ait rien demandé.

Elle sait aussi donner un coup de main : trier le courrier, préparer une réponse Teams, organiser un voyage, mener un
projet de code du plan jusqu'au livrable. Et rien ne part en votre nom sans votre accord ou une règle que vous avez
posée.

<div align="center">
<table>
  <tr>
    <td align="center"><img src=".github/readme/mika-joyeuse.webp" width="120" alt="Mika joyeuse"><br><sub>joyeuse</sub></td>
    <td align="center"><img src=".github/readme/mika-surprise.webp" width="120" alt="Mika surprise"><br><sub>surprise</sub></td>
    <td align="center"><img src=".github/readme/mika-pensive.webp" width="120" alt="Mika pensive"><br><sub>pensive</sub></td>
    <td align="center"><img src=".github/readme/mika-triste.webp" width="120" alt="Mika triste"><br><sub>triste</sub></td>
    <td align="center"><img src=".github/readme/mika-fachee.webp" width="120" alt="Mika fâchée"><br><sub>fâchée</sub></td>
    <td align="center"><img src=".github/readme/mika-endormie.webp" width="120" alt="Mika endormie"><br><sub>endormie</sub></td>
  </tr>
</table>
</div>

## ✨ Ce qu'elle sait faire

- 💬 **Parler** : dans le chat web, sur Android, dans Teams, par courrier. Une seconde passe réécrit ses messages
  pour qu'ils sonnent comme elle.
- 🧠 **Se souvenir, et oublier** : souvenirs, croyances, promesses, dont la force s'use. Oublier quelqu'un emporte
  vraiment tout ce qui le concerne.
- 💗 **Ressentir** : plusieurs émotions à la fois, lues par le modèle plutôt que devinées par mots-clés, envers chacun,
  et une humeur de fond vers laquelle elle revient.
- 🎛 **Avoir du caractère** : une matrice de personnalité à curseurs et à profils, qui change sa façon de réagir.
- 🌙 **Vivre ses journées** : sommeil, rêves, besoins, attention.
- 📬 **Courrier, Teams, téléphone** : elle lit, trie et prépare des brouillons ; l'envoi suit les règles que vous avez
  posées.
- 🗺 **Carte et voyages** : OpenStreetMap, itinéraires, lieux et avis.
- 🛠 **Travailler** : un mode pro façon Claude Code, des projets qui naissent d'un plan, et la Forge, où elle fabrique
  ses propres petites applis dans un bac à sable.
- 🎨 **Dessiner** : génération d'images en local.
- 🔌 **Outils MCP** : des serveurs externes, avec des droits par personne et par situation.

## 📸 En images

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/readme/chat-sombre.webp">
    <img src=".github/readme/chat-clair.webp" width="900" alt="Le chat : Mika envoie une carte, un fichier, et prépare une réponse Teams qui attend l'accord">
  </picture>
  <br>
  <sub><b>Le chat de tous les jours</b> : elle répond, envoie une carte ou un fichier, et prépare une réponse Teams
  qui attend votre accord.</sub>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/readme/console-humeur-sombre.webp">
    <img src=".github/readme/console-humeur-clair.webp" width="900" alt="La console : la page Humeur de Mika, sa courbe et ses dernières émotions">
  </picture>
  <br>
  <sub><b>La console</b> : son humeur du moment, son fond, et chaque émotion qu'elle a déclarée en écrivant.</sub>
</p>

<sub>Les captures montrent des données de démonstration.</sub>

## 🔧 Sous le capot

Mika est une psyché à **journal d'événements**. Tout ce qui lui arrive (un message, une pensée, un rêve) s'ajoute au
journal, et l'état de chacune de ses facultés s'en déduit par des fonctions pures. Sa vie peut donc se rejouer,
s'expliquer et se simuler : une semaine en quelques secondes.

```mermaid
flowchart LR
    subgraph clients["Ses clients"]
        direction TB
        web["Web de tous les jours"]
        android["Android"]
        teams["Extension Teams"]
    end

    subgraph moteur["Le moteur mika (Python)"]
        direction TB
        runtime["Runtime<br/>arbitre · épisodes · ordonnanceur"]
        journal[("Journal<br/>d'événements")]
        facultes["17 facultés · 13 plugins<br/>mémoire, affect, besoins, liens,<br/>courrier, carte, Forge…"]
        runtime -- "Mind.append" --> journal
        journal -- "réducteurs purs" --> facultes
        facultes -- "faits déclarés" --> runtime
    end

    llm["Claude (API ou Claude Code)<br/>ou Ollama"]

    clients <--> runtime
    runtime <--> llm
```

Quelques principes qui tiennent l'ensemble :

- **Les facultés ne se connaissent pas.** Elles ne s'importent jamais entre elles et se lisent par des faits
  déclarés ; `lint-imports` le vérifie à chaque test.
- **Un arbitre décide quand elle parle** : des preuves cumulées en log-odds, et un déclenchement de Poisson qui ne
  dépend pas de la cadence.
- **Ses phrases ne sont pas dans le code.** Sa persona et sa voix vivent dans
  [`persona/`](backend/persona).
- **Pas de repli silencieux.** Un appel au modèle qui échoue est journalisé et remonté, jamais basculé vers un autre
  fournisseur.
- **Mesuré plutôt que deviné** : environ 5 570 tests, des gardes d'architecture, un simulateur, et des bancs où de
  vraies conversations sont jouées puis notées par Opus.
- **Chaque décision est écrite** : 250 décisions argumentées dans
  [`docs/decisions.md`](backend/docs/decisions.md).

Pour tout le détail : [`backend/ARCHITECTURE.md`](backend/ARCHITECTURE.md).

## 🚀 L'essayer

Il faut Python 3.12 ou plus.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[llm,memory]"
.venv/bin/python -m mika serve
```

Ouvrez <http://127.0.0.1:8001> : la première page crée votre compte, puis **Réglages › Modèles de texte** lui donne
une voix (Claude, Claude Code, Ollama ou un modèle compatible OpenAI).

Son corps en 3D est le modèle libre du dépôt. Pour lui en donner un autre, posez votre VRM dans
`frontend/Assets/models/default.vrm` : il passe devant, et il ne sera jamais versionné.

La suite, pas à pas : [`backend/README.md`](backend/README.md). La mise en service (systemd, MariaDB,
sauvegardes) : [`backend/deploy/README.md`](backend/deploy/README.md).

## 📦 Le dépôt

| Dossier | Ce que c'est |
|---|---|
| [`backend/`](backend) | Le moteur (paquet Python `mika`), sa persona, ses docs et ses bancs de mesure |
| [`frontend/Web/`](frontend/Web) | Le client web de tous les jours : chat, mode pro, courrier, Teams, téléphone, carte |
| [`frontend/Android/`](frontend/Android) | L'app Android, en Kotlin et Compose, avec Mika en 3D native |
| [`frontend/ExtensionChromeTeams/`](frontend/ExtensionChromeTeams) | L'extension Chrome qui la relie à Teams |
| [`frontend/Assets/`](frontend/Assets) | L'art : son modèle, ses mouvements, les scripts Blender de ses portraits |
| [`services/mika-images/`](services/mika-images) | Le serveur d'images local |

## 🚦 État du projet

Un projet personnel, en développement actif.

| Partie | État |
|---|---|
| Le moteur | ![en service](https://img.shields.io/badge/en_service-22c55e) |
| Le web de tous les jours | ![en service](https://img.shields.io/badge/en_service-22c55e) |
| L'app Android | ![v2 en essai](https://img.shields.io/badge/v2_en_essai-f59e0b) |
| L'extension Teams | ![en essai](https://img.shields.io/badge/en_essai-f59e0b) |

## 📜 Licence

Le code est **totalement libre**, sous licence [MIT-0](LICENSE). Vous pouvez l'utiliser, le copier, le modifier, le
redistribuer ou le vendre, sans condition, sans même avoir à citer l'auteur.

Ce qui vient d'ailleurs garde sa propre licence :

- le modèle 3D libre de Mika, [`mika-libre.vrm`](frontend/Assets/models/mika-libre.vrm), fait dans VRoid Studio,
  est sous licence publique VRM 1.0 : redistribution et modification permises. Les animations et les captures de
  [`.github/readme/`](.github/readme) le montrent ;
- un modèle acheté peut le remplacer chez soi : il n'entre jamais dans le dépôt ;
- les textures de la pièce, en CC0, venues de Poly Haven ([le détail](frontend/Assets/README.md#licences-des-textures)) ;
- les clips de mocap, tirés de la CMU Graphics Lab Motion Capture Database
  ([les crédits](frontend/Assets/mocap/README.md#provenance-et-licence)) ;
- la police Inter de la console, sous SIL Open Font License 1.1.
