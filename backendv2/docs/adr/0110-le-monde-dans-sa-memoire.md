# 0110 — Le monde dans sa mémoire : une seule base

**Contexte.** Le 2026-10-14, Mika lit des nouvelles pour sa propriétaire (Trump, Macron…). Celle-ci s'attend à les
retrouver dans sa mémoire. Elle demande aussi s'il faut une base de connaissance du monde à part, peut-être une base
de vecteurs distincte, pour que cent personnes vues dans les médias ne noient pas sa vie à elle.

Voici ce qui existe aujourd'hui (ADR 0085). Ce qu'elle lit (`rss.read`, et `mcp.consulted` pendant un travail)
devient, la nuit, une croyance « lue ». Une telle croyance n'a pas de personne (`about=()`). Son témoin est la source
(`rss:Le Monde`). Elle est anodine, et sa confiance ne dépasse pas 0,7. Une personnalité publique n'est pas une
personne de sa vie : elle n'a ni adresse, ni profil, ni lien, et elle vit dans le texte des faits. Tout est dans le
même index que ses souvenirs (`memory_vectors`).

**Le banc** (`tools/banc_memoire/`). `generer.py` écrit le corpus avec la CLI Claude Code (Haiku), à partir des flux
du jour et de résumés Wikipédia. Le corpus est gardé dans `data/`, qui n'est jamais versionné. Il compte :

- 880 éléments sur 40 de ses proches, dont 25 portent le prénom d'une personnalité du corpus (Emmanuel, Marine,
  Jordan…) ;
- 4 666 faits du monde : les nouvelles, 150 personnalités et 20 sujets ;
- 234 messages sur ses proches et 356 questions sur le monde, qui visent chacun un élément sans en reprendre les
  mots ;
- 30 messages banals.

`banc.py` fait passer chaque message par les vraies fonctions du rappel. Il compare deux configurations, à trois
tailles du monde :

- A, une base : le monde concourt pour les mêmes places que ses proches ;
- B, deux bases : ses proches dans un index, le monde dans un autre, avec son propre seuil (plus strict de 0,1) et
  trois places au plus.

Mesures avec EmbeddingGemma 2, au réglage de l'ADR 0111 (0,35 / 0,65) :

| Faits du monde | Config | Proches | Homonymes | Monde | Faits du monde parmi ses proches | Bruit |
|---|---|---|---|---|---|---|
| 0 | — | 36,8 % | 45,1 % | — | — | 1,00 |
| 1 000 | A | 36,8 % | 45,1 % | 65,4 % | 0,04 | 1,00 |
| 1 000 | B | 36,8 % | 45,1 % | 52,0 % | 0,00 | 1,00 |
| 4 666 | A | 36,8 % | 45,1 % | 61,8 % | 0,11 | 1,07 |
| 4 666 | B | 36,8 % | 45,1 % | 45,8 % | 0,01 | 1,03 |

Une recherche, globale puis propre à la personne qui parle, prend 1,7 ms sur 5 546 vecteurs (16 Mo).

**Décision.**

1. *Une seule base.* Le monde ne noie pas ses proches. Avec 4 666 faits du monde, elle retrouve ses proches aussi bien
   que sans aucun : 36,8 % dans les deux cas. Les homonymes ne sont pas confondus : on lui parle d'Emmanuel, le
   collègue, et Macron ne prend pas sa place. Un fait du monde se glisse parmi ce qui revient d'un proche une fois
   sur neuf messages. Trois raisons à cela : un fait du monde n'a pas de personne ; le rappel cherche aussi parmi ce
   qui touche la personne qui parle ; le classement favorise l'importance et la personne en face. Une base à part
   ferait perdre un tiers de ce qu'elle sait du monde (61,8 % contre 45,8 %), doublerait les recherches et
   compliquerait l'oubli, pour presque rien.
2. *Une personnalité publique n'est pas une personne de sa vie.* Ce qu'elle sait de Macron est un ensemble de faits
   lus. Aucune personne n'est créée, il n'y a ni profil, ni lien, ni « CE QUE TU SAIS D'ELLE ». Ses relations restent
   les gens à qui elle parle et ceux dont on lui parle.
3. *À revoir* si le monde dépasse 20 000 faits environ, car les faits du monde parmi ses proches augmentent avec lui
   (0,04 à 1 000, 0,11 à 4 666). À revoir aussi si l'index passe sur disque (`max_resident_vectors`, 50 000). Le
   banc se relance : `banc.py --tailles …`.

**Ce qui reste ouvert.** Les nouvelles lues pour sa propriétaire n'ont rien laissé, et ce n'est pas une affaire de
base. L'ADR 0085 ne garde pas une lecture faite en conversation : « ce qu'on cherche pour quelqu'un est à lui ». Une
recherche dit ce qui préoccupe la personne (des symptômes, un avocat). Garder aussi ces lectures-là, et à quelles
conditions, est à décider avec la propriétaire. On pourrait par exemple garder les nouvelles et non les recherches
personnelles, ou garder la lecture comme confiée par la personne qui l'a demandée.
