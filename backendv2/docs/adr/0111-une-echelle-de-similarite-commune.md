# 0111 — Une échelle de similarité commune à tous les modèles

**Contexte.** L'ADR 0109 a changé le modèle de plongements du portable : EmbeddingGemma 2 au lieu de
`paraphrase-multilingual-MiniLM-L12-v2`. Les seuils de sa mémoire avaient été réglés pour l'ancien, sur sa
similarité cosinus brute : `recall_floor` 0,45, `strong_cue` 0,75, `dedup_similarity` 0,92,
`night_merge_similarity` 0,9. Or chaque modèle a sa propre échelle. Pour MiniLM, deux phrases sans rapport valent
environ 0,05 ; pour EmbeddingGemma 2, environ 0,6 ; pour Qwen3-Embedding, 0,25. Avec Gemma, le seuil de 0,45 laissait
tout passer, et la fusion de la nuit risquait de confondre des souvenirs distincts.

Le 2026-10-14, la propriétaire demande de garder Gemma et d'ajuster les seuils.

Le même jour, un défaut de l'ADR 0109 apparaît. L'index plongeait toute recherche comme une question, y compris
quand un texte de sa mémoire est comparé à d'autres : le doublon d'une promesse ou d'un moment, la fusion de la nuit,
la confrontation de deux témoignages. La comparaison n'était plus symétrique.

**Décision.**

1. *La similarité rendue est centrée* (`adapters/vectors/index.py`). Le fond d'une recherche est la médiane de sa
   similarité avec 64 phrases sans rapport. Ces phrases imitent des souvenirs, des faits lus et des messages
   (`adapters/vectors/background.py`). Elles sont plongées une fois, comme des documents. L'index rend
   `(s − fond) / (1 − fond)`, avec un fond borné entre 0 et 0,95 : 0 pour un texte quelconque, 1 pour l'identique.
   La transformation est croissante : l'ordre des résultats et le départage par clé ne changent pas, ni en mémoire
   ni sur disque. Le fond se calcule pour chaque requête : une requête vague (« ok ») ressemble à tout, et son fond
   le compense.
2. *Une comparaison n'est pas une recherche.* `VectorIndex.search` gagne `document=True` : le texte est plongé comme
   ceux qu'il compare. Quatre appels en ont besoin : le doublon d'une promesse et celui d'un moment
   (`consolidation.py`), la fusion de la nuit (`night.py`) et la confrontation de deux croyances (`reread.py`). Les
   autres appels restent des recherches : le rappel, `memory_search`, les lectures de la nuit, ce qu'elle sait déjà
   d'une conversation, les pièces jointes et la constellation.
3. *Les seuils se lisent sur cette échelle*, réglés pour le modèle en service (EmbeddingGemma 2) par le banc de
   mémoire (`tools/banc_memoire/`, ADR 0110) :

   | Réglage | Avant (MiniLM, brut) | Maintenant (centré) |
   |---|---|---|
   | `recall_floor` | 0,45 | 0,35 |
   | `strong_cue` | 0,75 | 0,65 |
   | `dedup_similarity` | 0,92 | 0,90 |
   | `night_merge_similarity` | 0,90 | 0,87 |

**Les mesures.** Le corpus compte 880 éléments sur 40 de ses proches, dont des homonymes de personnalités publiques,
et 4 666 faits du monde. Il comprend 234 messages sur ses proches et 356 questions sur le monde, tapés comme on les
tape et sans reprendre les mots de l'élément visé, ainsi que 30 messages banals qui ne visent rien. Chaque message
passe par les vraies fonctions du rappel : la recherche globale, celle de la personne qui parle, l'hybride, le seuil
et l'écart, les souvenirs endormis, le classement et les plafonds. Un élément est trouvé s'il est montré au modèle. Le
bruit compte ce qui remonte pour un message banal.

| Modèle, réglage | Proches trouvés | Monde trouvé | Faits du monde parmi ses proches | Bruit |
|---|---|---|---|---|
| MiniLM, l'ancien réglage (0,45 brut, soit 0,41 centré) | 31,6 % | 52,5 % | 0,68 | 1,5 |
| Gemma, 0,45 / 0,75 | 24,4 % | 50,6 % | 0,01 | 0,67 |
| Gemma, 0,40 / 0,70 | 29,5 % | 55,6 % | 0,04 | 0,83 |
| Gemma, 0,38 / 0,68 | 33,3 % | 57,6 % | 0,06 | 0,90 |
| **Gemma, 0,35 / 0,65** | **36,8 %** | **61,8 %** | **0,11** | **1,07** |
| Gemma, 0,33 / 0,63 | 38,0 % | 64,3 % | 0,13 | 1,17 |
| Gemma, 0,30 / 0,60 | 38,9 % | 66,9 % | 0,24 | 1,33 |
| MiniLM, 0,35 / 0,65 | 36,3 % | 53,4 % | 1,15 | 1,93 |

À 0,35 / 0,65, Gemma fait mieux que l'ancien réglage sur les quatre mesures. Au-dessous, chaque point gagné coûte du
bruit. Les taux restent bas parce que le banc est dur : les messages évitent les mots de l'élément visé, et 501
éléments sur 880, jamais rappelés depuis des mois, dorment.

Les doublons ont été mesurés sur 294 paires de documents. Chaque élément y a deux variantes : une reformulation du
même fait, comme une autre relecture l'aurait notée, et un fait voisin, qui change un seul détail (une autre date, une
autre équipe). Voici, pour Gemma, la part des paires au-dessus de chaque seuil :

| Seuil | Même fait | Fait voisin | Le plus proche des autres éléments de la personne |
|---|---|---|---|
| 0,85 | 93 % | 39 % | 0,2 % |
| 0,87 | 90 % | 32 % | 0,2 % |
| 0,89 | 87 % | 27 % | 0 % |
| 0,91 | 82 % | 18 % | 0 % |

L'ancien réglage de MiniLM, 0,92 brut, équivaut à 0,914 centré : 88 % des mêmes faits et 17 % des voisins passaient.
La fusion de la nuit exige en plus les mêmes mots et les mêmes personnes. Elle peut donc descendre à 0,87. Le doublon
d'un moment ou d'une promesse n'a pas de second filtre : il reste à 0,90.

**Conséquences.**
- Changer de modèle ne rend plus les seuils absurdes. L'échelle n'est pourtant pas parfaitement commune : à seuil
  égal, MiniLM laisse passer plus de bruit, parce qu'il distingue moins bien ce qui se ressemble. Les défauts
  conviennent au modèle en service. Pour MiniLM, l'équivalent de l'ancien réglage est 0,41 / 0,73, qu'on règle
  dans la console.
- Un réglage enregistré dans la console pour ces paramètres l'a été sur l'ancienne échelle : il faut le revoir.
- Les scores affichés par la constellation sont centrés. Son seuil (0,4, choisi par la propriétaire) garde sa
  valeur et se lit sur la nouvelle échelle.
- Les seuils des pièces jointes (`SIM_FLOOR` 0,25, `LINK_FLOOR` 0,3) ne bougent pas.
- Le banc se relance quand on change de modèle : `banc.py --etalonner <modèle>` pour les distributions, la grille
  (`--grille seuil:indice,…`) pour le rappel complet.
