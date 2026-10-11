# 0089 — Ce qui la passionne

Troisième lot du chantier « qui elle devient » (plan du 2026-10-10).

**Contexte.** Ses centres d'intérêt étaient une liste figée de sa persona. Elle les explorait à tour de rôle,
aussi présents après trois mois sans qu'elle y touche qu'au premier jour ; ses flux pondéraient tous leurs mots
pareil ; et rien de ce qu'elle lisait, trouvait en explorant, ou de ce qu'on lui racontait ne devenait jamais un
intérêt à elle — la city pop dont une amie lui avait parlé restait une rêverie d'un après-midi.

Choix de l'utilisateur (2026-10-10) : la persona reste intacte, à l'opératrice ; **ses intérêts naissent et
s'endorment** — un nouveau par semaine au plus, trois vécus au plus ; ceux de la persona s'avivent ou s'endorment,
jamais ne disparaissent ; ses explorations et ses flux suivent.

**Décision.**

1. *Des intérêts vivants* (`faculties/self/interests.py`, état `SelfState.interests`) : ceux de sa persona (clé : la
   ligne, synchronisés à chaque révision — une ligne retirée s'en va, une nouvelle s'allume) et ceux qu'elle a vécus
   (`lived:<nuit>`, leur sujet et ce qu'il est en contenus — l'oubli les efface). Une vivacité qui retombe de moitié en
   `interest_half_life_us` vers un plancher (`persona_floor` pour la persona ; zéro pour un vécu, qui s'en va sous
   `lived_drop_below`) ; trois niveaux — vif, présent, endormi. Un intérêt de la persona est toujours là, même si son
   plancher est réglé à zéro.
2. *Ce qui les nourrit* : une exploration (ou une rêverie) de ce centre d'intérêt menée au bout (`explored_feed`) ;
   un titre de ses flux qui le touche (`rss.noticed.touches`, `touch_feed`, au plus `touch_daily_cap` par journée :
   quarante titres ne font pas une passion) ; la nuit, une piste qui s'y rattache (`lead_feed`, une fois).
3. *Des pistes* (`SelfState.leads`, au plus 40, `lead_keep_us`) : ce qu'elle a médité de ce qu'on lui a raconté
   (`goals.closed` d'un `talk:`), ce qu'elle a trouvé en explorant, un article qu'elle a ouvert (`rss.read`, pas un
   titre survolé). **Jamais une confidence** ; chacune garde de qui elle vient.
4. *Ce qui naît, la nuit* (processus `self.reflect`, rôle `extract`, un appel au plus par nuit) : seulement avec
   `birth_min_leads` pistes neuves venues d'au moins `birth_min_days` journées ; le modèle relit ses intérêts et toutes
   les pistes encore libres, rattache ce qui y revient, et dit si un sujet est en train de la passionner. **Le code
   borne** : au plus une naissance, pas plus d'une tous les `birth_every_us`, pas plus de `lived_max` intérêts vécus
   vivants ; un sujet court (huit mots, soixante caractères), dit dicible à tous, qui ne nomme personne de son cercle ni
   de qui viennent les pistes (sujet et détail), qui n'est pas déjà un de ses intérêts (un mot de sens en commun), avec
   au moins deux preuves de deux journées. Événements publics `self.interest_born` (sujet, détail, de qui, preuves)
   et `self.reflected` (jusqu'où, ce qui s'est rattaché).
5. *L'oubli* : oublier une personne emporte les pistes venues d'elle et les intérêts nés d'elles.
6. *Ses explorations suivent* (`goals/tend`, fait `self.interests`) : le tirage pondère chaque intérêt par son niveau
   (vif ×2, endormi ×0,25) ; un intérêt vécu s'explore par son sujet (« Chercher du neuf autour de la city pop »),
   avec son détail et ceux de qui il est né (l'oubli de la personne efface l'exploration aussi).
7. *Ses flux suivent* (`plugins/rss`, `interest_words`) : les mots d'un intérêt endormi comptent moitié, ceux d'un
   intérêt vécu s'ajoutent ; chaque titre remarqué dit quels intérêts il touche.
8. *Son prompt le dit* (« CE QUE TU SAIS DE TOI ») : ce qui la passionne le plus en ce moment, et ce de sa persona
   qui l'intéresse moins qu'avant — au plus deux de chaque, en mots.
9. *La console* (« Qui elle devient ») : ses intérêts (sujet, d'où, niveau, vivacité, quand ils ont été nourris) et
   ses pistes.
10. Le partagé est dans `vocab/interests.py` (pur) : `InterestView`, `subject_of` (l'ancien `goals.tend.short`),
    `topic_words` et `pertinence` (les anciens `rss.keywords` et `rss.pertinence`, pondérés), `matches`,
    `same_topic`, les poids par niveau ; `vocab.people.mentions` (un nom ou un prénom en mot entier).

**Ce qui n'est pas fait.** Ses avis nés d'une lecture ne sont pas des pistes à part : la lecture elle-même en est
une. Une exploration ne lit encore que ses flux (pas le web). Un intérêt vécu ne s'oublie pas à la main depuis la
console.

**Conséquences.** `SelfState` en version 9 (`interests`, `leads`, `reflected_night`, `reflected_upto`,
`last_birth_at`) ; `records.Interest`, `records.Lead`. Événements nouveaux : `self.interest_born`, `self.reflected`
(libellés). Fait nouveau : `self.interests`. Processus nouveau : `self.reflect` (libellé). `rss.noticed` +
`touches`. Phrases nouvelles : `self.reflect.*`, `self.knows.passion`, `self.knows.asleep`. Réglages nouveaux (groupe
« Ce qui la passionne ») : `self.interest_half_life_us`, `.persona_glow`, `.persona_floor`, `.born_glow`,
`.lived_drop_below`, `.vivid_from`, `.asleep_below`, `.explored_feed`, `.lead_feed`, `.touch_feed`,
`.touch_daily_cap`, `.lead_keep_us`, `.birth_min_leads`, `.birth_min_days`, `.birth_every_us`, `.lived_max`.
Cibles d'intention (`tests/unit/test_interests.py`, 11), chacune rendue rouge en cassant exprès sa correction (19
mutations) : un intérêt de la persona s'endort sans jamais se perdre, même sans plancher ; l'explorer l'avive ; ses
flux le nourrissent, bornés par journée ; un endormi pèse moins dans ce qu'elle remarque et ce qu'elle explore ; une
confidence, un titre survolé ne sont pas des pistes ; une journée de pistes ne suffit pas ; ce qui naît est borné
(deux journées de preuves, aucun nom, dicible, pas déjà là, court, un par semaine, pas de quatrième, un seul par
nuit) ; la réflexion de la nuit fait naître et rattache, une piste ne nourrit qu'une fois ; l'oubli emporte ce qui
est né d'une personne ; un intérêt vécu éteint s'en va ; explorer un intérêt vécu, c'est explorer son sujet.
