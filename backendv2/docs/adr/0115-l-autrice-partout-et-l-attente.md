# 0115 — L'autrice écrit aussi ce qu'elle lance, et elle attend qu'on lui réponde

**Contexte.** Le 2026-10-16, sur le PC, juste après le déploiement de l'autrice (ADR 0114), une conversation :

| Heure | Qui | Message |
|---|---|---|
| 16:22:53 | Adrien | « coucou » |
| 16:23:42 | Mika (autrice) | « coucou ! la terrasse t'a pas englouti alors 😄 ta journée ? » |
| 16:23:52 | Mika, d'elle-même | un paragraphe sur une étude lue dans Le Monde (262 malades suivis, 5 % de crises en moins…) |
| 16:24:56 | Adrien | « je vais déléguer la pelle à quelqu'un d'autre pour avoir un corps de rêve xd » |
| 16:25:36 | Mika (autrice) | « euh mauvais calcul… bras spaghetti 💀 il est au courant au moins le pauvre ? » |
| 16:25:54 | Mika, d'elle-même | un autre paragraphe, sur un rapport du Citizen Lab |

Trois causes :

1. *Elle lançait un sujet dix secondes après sa réponse.* Partager ce qu'elle a fini (`goals.SHARE`) est dans
   `FOR_THEM`. Ces raisons n'attendent pas que son dernier message ait trouvé sa réponse, et l'attente ordinaire
   (`quiet_after_reply_us`, 4 h) ne les retenait pas. Le défaut existait déjà, mais à côté de petits SMS il saute aux
   yeux.
2. *Ce qu'elle lançait ne passait pas par l'autrice*, seulement ses réponses (`polished = [REPLY]`) : de petits SMS,
   puis un paragraphe de journaliste.
3. *Une réponse prenait 40 à 50 s* : la tête (environ 5 s), puis la relecture (ADR 0112, environ 5 s), puis
   l'autrice (Opus en effort élevé, 26 à 39 s), qui récrit de toute façon le sens et non les mots.

**Décision.**

1. *Pendant une conversation, elle attend.* Tant que son dernier message attend sa réponse depuis moins de
   `live_wait_us` (15 min, réglable dans la console), aucune initiative ne part vers cette personne, pas même ce qui la
   regarde (partager, prendre des nouvelles). Ce qui prévient (`INFORMS`) passe toujours. Au-delà de 15 minutes, les
   règles d'avant s'appliquent.
2. *L'autrice écrit aussi ses initiatives* (`polished` = `CONVERSATIONAL`). Ce qu'elle « vient d'entendre » est le
   message reçu (`req.message`), jamais la consigne d'une initiative (« personne ne vient de t'écrire… »), qui n'est
   pas une ligne du fil.
3. *Pas de relecture quand l'autrice récrit derrière.* La relecture reste quand le rôle `polish` n'a pas de modèle.
4. *L'autrice en effort moyen.* C'est un réglage, sans code (un fournisseur à part pour `polish`). Sur le tour de
   16:25, rejoué :

   | Effort | Durée de l'appel |
   |---|---|
   | élevé | 36 s |
   | moyen | 14 à 21 s |
   | bas | 12 s |

   Le rendu est le même aux trois efforts (même réplique, même ton, émojis), et la suite imaginée reste plausible.

**Conséquences.**

- Une réponse coûte deux appels au lieu de trois, et environ 20 à 25 s au lieu de 45.
- Un message qu'elle lance a la même voix que ses réponses : un SMS, plus un article résumé.
- Une raison nouvelle de `FOR_THEM` n'a rien à faire pour attendre une conversation en cours : la règle passe
  avant.
