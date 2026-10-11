# 0091 — Raconter sans nommer

Cinquième et dernier lot du chantier « qui elle devient » (plan du 2026-10-10).

**Contexte.** Ce qu'elle savait des autres se disait nommément, devant qui le pouvait, ou pas du tout. Une humaine
raconte autrement : à quelqu'un qui ne connaîtra jamais la personne, elle dit « une amie vient de perdre son
travail ». Mika, elle, se taisait — ou, dans le rappel, une ligne « elle t'a confié des choses » trahissait déjà
qu'il y avait quelque chose.

Choix de l'utilisateur (2026-10-10) : ce qu'elle raconte dépend de qui l'écoute — sa confiance en la personne, et si
cette personne n'a **aucun lien connu** avec ceux dont elle parle, elle peut raconter sans nommer, gradué (l'anodin à
tous, le personnel dès qu'elle la connaît un peu, une confidence à une amie ou une proche) ; **jamais un secret, même
anonymisé** ; **jamais la vie de sa propriétaire** ; **en réponse seulement** ; **le modèle généralise** les détails
qui identifient (employeur, lieu, animal, nombre), le code garde un filet sur les noms.

**Décision.** Principe : n'étendre que ce qui est fermé — ce qui se dit nommé se dit nommé (`admissible` et l'oracle
de la politique sont inchangés) ; un lien qui *ouvre* doit être prouvé, un lien qui *ferme* seulement soupçonné ;
toute panne ferme.

1. *La version sans nom* : la relecture écrit `sans_nom` pour un souvenir ou un fait qui concerne quelqu'un d'autre
   (« la même chose, racontée sans qu'on puisse reconnaître la personne », phrase de champ) ; le code garde un filet
   (`extraction.veiled_of` : au plus `VEILED_MAX` caractères, aucun nom qu'elle connaît, aucun chiffre) et n'en garde
   jamais pour un secret, ce qui n'appartient qu'à deux personnes, un avis ou une hypothèse, ni sa réplique recopiée.
   `Believed.veiled`, `Remembered.veiled` (contenus à sujets : l'oubli les efface), colonne `memory_items.veiled`. Les
   éléments d'avant n'en ont pas : jamais racontés sans nom.
2. *Le niveau de qui écoute* (`vocab.privacy.veiled`, facette `Disclosure.veiled_level`, `Audience.veiled_level`) :
   l'anodin seulement (rien de neuf) dans un salon, en public, ou devant qui elle n'est pas assez sûre de connaître ; le
   personnel devant quelqu'un qu'elle connaît ; une confidence devant une amie, une proche ou sa propriétaire dont elle
   est sûre (`confidence_threshold`). Des constantes de la politique, pas des réglages.
3. *Le verdict* (`vocab.retelling.retellable`, pur) : fermé si déjà dicible, sans version sans nom, secret ou
   discrétion demandée, mensonge, entre deux personnes, texte dérivé, pas un simple fait, mention présumée, si qui
   écoute est concerné (ou l'a dit, ou l'a entendu), plus d'une personne, sa propriétaire, un événement marquant
   (importance ≥ 0,9), au-dessus du niveau — ou un lien qu'on n'a pas prouvé absent.
4. *« Aucun lien connu »* (`faculties/memory/links.py`) : le graphe social (`social.ties`, dans un sens ou dans
   l'autre, lu par son fait, pas sa table), un salon où ils ont parlé tous les deux, un élément qui les nomme ensemble,
   l'un qui lui a parlé de l'autre (une mention présumée comprise), le nom de l'un dans ce que l'autre lui a écrit, ce
   qu'elle a déjà raconté nommément de la personne à qui écoute ; un nom qu'elle ne connaît pas, une panne : fermé.
   Liens directs seulement.
5. *Où* (`faculties/memory/veiled.py`, lu par le rappel) : en réponse seulement — ce que la question réveille et que
   l'audience ne peut pas entendre nommé, et, quand on lui demande des nouvelles (« quoi de neuf ? »), ce qu'elle a
   appris de récent (`veiled_fresh_days`). Section « CE QUE TU PEUX RACONTER SANS NOMMER PERSONNE » : la version sans
   nom et ce que la personne est pour elle en mots épicènes (« quelqu'un que tu aimes bien »), un conseil (ne pas dire
   de qui il s'agit, même deviné ; ne rien ajouter qui la fasse reconnaître). Au plus `veiled_max_shown` par réponse
   et `veiled_per_person` par personne et par auditeur ; ce qu'elle lui a déjà raconté ainsi revient comme tel (« garde-
   le sans nom », `veiled_keep_days`) ; la ligne qui nomme quelqu'un de qui elle tait quelque chose ne s'ajoute pas à
   côté. Ni ses initiatives, ni son journal, ni son récit n'en sont.
6. *Le second rempart* (`kernel/prompt.py`) : un bloc sans nom porte les noms qu'il tait (`SectionBody.veils`) ; il
   se mesure au niveau sans nom de l'audience (`audible(veiled_level=…)`), et le compositeur le retire si l'un de ces
   noms paraît ailleurs dans le prompt (une autre section, le fil, le message : `unveiled`).
7. *Les traces* : sa provenance `veiled:<élément>` ; `memory_told` en version 3 (colonne `veiled`, une fois nommé il
   reste nommé), la vue `memory_retold` la porte. La relecture ne voit pas le texte d'une de ses répliques qui
   racontait sans nom (`memory.extraction.render.veiled_said`) et n'en tire aucune note sur elle. Ce qu'elle a
   raconté à quelqu'un, même sans nom, n'est plus une preuve d'identité (`identity/reading` exclut tout ce qui a été
   raconté à une autre adresse).
8. *La console* : la page d'identité dit ce que chaque adresse ouvre sans nommer personne.

**Conséquences.** `Believed`, `Remembered` + `veiled` ; `memory.believed`, `memory.remembered` portent ce contenu.
`Disclosure.veiled_level`, `Audience.veiled_level`, `privacy.decide(owner=…)`. Projecteurs : `memory_items` v16
(colonne `veiled`), `memory_told` v3 (colonne `veiled`). `contracts.memory.VEILED_PROVENANCE`. Section nouvelle :
`veiled` (libellée). Réglages nouveaux (groupe « Raconter sans nommer ») : `memory.veiled_max_shown`,
`.veiled_per_person`, `.veiled_fresh_days`, `.veiled_keep_days`. Phrases nouvelles : `memory.veiled.*`,
`memory.extraction.fields.sans_nom`, `memory.extraction.render.veiled_said`. Modules nouveaux : `vocab/retelling.py`,
`faculties/memory/links.py`, `faculties/memory/veiled.py`. Cibles d'intention (`tests/unit/test_veiled_retelling.py`,
36), chacune rendue rouge en cassant exprès sa correction (27 mutations) : une connaissance sans lien entend le
licenciement sans nom ni employeur, une amie dont elle est sûre la rupture, jamais le secret ni la vie de sa
propriétaire, et l'étiquette ne devine pas le genre ; rien de neuf en salon, à qui elle n'est pas sûre de connaître, ni
sur un bonjour, ni en initiative ; ce qui se dit nommé ne se dit pas sans nom, et rien à la personne elle-même ; chaque
sorte de lien ferme, une panne ferme ; le verdict ferme chacun de ses cas ; le filet écarte un nom, un chiffre, la
longueur ; une fois racontée, elle la garde sans nom, le budget par personne compte, un élément nommé reste nommé ; un
récit sans nom n'est jamais une preuve d'identité ; le compositeur retire le bloc à côté du nom, et au-dessus du niveau
sans nom ; la relecture ne voit pas ses répliques sans nom et n'en tire pas de note sur elle ; l'oubli n'en laisse
rien ; la relecture écrit la version sans nom seulement pour un fait qui peut en avoir une.

**Ce qui n'est pas fait.** La recherche dans l'index des vecteurs ne sait pas encore chercher parmi ce qui est fermé
seulement : un élément fermé très proche de la question ne vient que s'il est dans les candidats ordinaires.
