# 0044 — Ce qui est dû, ce qui prévient, et le courrier dit à l'énoncé

**Contexte.** L'audit des jonctions entre lots (audit B, 2026-10-02) a trouvé des contrats implicites qui se
contredisaient d'une faculté à l'autre :

- *La rancune ne savait rien de ce qui est dû.* Le veto `grudge` de `social` (ADR 0013, antérieur aux rappels, aux
  besoins des projets et à « prévenir ») tombait sur **toute** initiative vers quelqu'un qui lui en veut. Kev
  l'insulte douze fois, puis lui demande « rappelle-moi dans 20 minutes de rappeler Paul » : elle accepte, le but
  s'ouvre, et le rappel reste quatre heures sous veto avant d'échouer « trop tard ». Elle promet, puis ne tient pas
  parole. Un mail urgent pour sa propriétaire, « j'ai besoin de toi pour ton projet », de même. Pendant ce temps,
  `agency` et `others` gardaient chacune leur propre liste de ce qui est dû (`GREETING or REMIND`), `attention` une
  troisième, `social` une quatrième.
- *Le courrier se comptait au départ.* L'annonce d'un mail important était consommée au **départ** de l'initiative
  (tous les non-lus marqués « signalés ») : un `[SILENCE]`, une initiative devancée par un message de la
  propriétaire, un murmure « finalement non » — et le mail urgent n'était jamais dit. ADR 0033 (« le budget se
  compte à l'énoncé visible ») ne s'y appliquait pas ; S17 comptait les départs, ce qui figeait le défaut.
- *L'annonce et son contenu ne jugeaient pas la même chose* : l'annonce partait à toute adresse d'une propriétaire
  (`IS_OWNER(personne)`), le contenu qu'elle annonce n'est montré qu'à l'adresse qui parle pour elle
  (`SPEAKS_AS_OWNER`, ADR 0035).
- *Ce qui est cité est coupé en premier — même l'objet de l'épisode* : avec un petit contexte, elle rédigeait la
  réponse à un mail réduit à 595 caractères, ou annonçait un mail absent de son prompt.
- *Des essais qui n'en étaient pas* : un récit, un appel à l'aide devancés (la personne écrit pendant qu'elle
  compose — le cas courant quand elle est active) comptaient comme des tentatives ; deux, et elle ne racontait
  jamais ce qu'elle avait fini.
- *Elle resaluait tout le monde à chaque redémarrage* (la présence est volatile : chaque onglet qui se reconnecte
  redevenait une arrivée), et après chaque coupure réseau.
- *Telegram disait « Désolée, je n'arrive pas à te répondre là tout de suite… Réessaie dans un instant ? »* des
  heures après une question abandonnée au démarrage parce qu'il était trop tard.

**Décision.**

1. *Ce qui est dû, ce qui prévient, ce qui salue : déclaré une fois, dans le contrat d'`agency`.*
   `OWED = {goals.remind}` (tenir parole), `INFORMS = {email.mail_mention, projects.project_need}` (prévenir de ce
   qui ne peut pas attendre et regarde la personne au premier chef), `GREETS = {social.greeting}`, et
   `NOT_SPEAKING_UP = GREETS | OWED` (ni compté au budget, ni réfractaire, ni attendu en retour). `agency` (budget,
   ne pas harceler, consigne), `social` (rancune, qui ouvre une conversation), `others` (réceptivité, délai de
   réponse) et `attention` (attentes) le lisent ; aucune ne le redit. « J'ai besoin de toi pour ton projet » en est :
   c'est l'état d'un travail que la personne a elle-même confié, borné par sa source (une fois par objectif, deux
   essais) — on le dit même à quelqu'un qui n'a pas répondu à un bavardage, comme à un patron avec qui on est en
   froid. « Alors, cet entretien ? » (`others.follow_up`) n'en est pas : c'est de l'attention, une rancune l'arrête.
2. *La rancune retient l'ordinaire, jamais une promesse.* Une ligne qui porte une raison due n'a ni veto ni
   décalage (tenir parole, à l'heure, envers un troll aussi — la rancune colore le ton, elle ne reprend pas la
   promesse) ; une ligne qui prévient n'est que décalée (`social.grudge_inform_shift`, −2 : elle prévient sans se
   presser) ; tout le reste reste sous veto, salutation comprise (ADR 0013) — et la salutation n'est plus même
   proposée à quelqu'un qu'elle a en grippe, pour qu'un rappel dû ne parte pas avec un « coucou ».
3. *Un mail est dit à l'énoncé, et seulement ce qui a été annoncé.* L'initiative porte les mails qu'elle annonce
   (les plus importants, trois au plus) ; ils ont leur section, citée (`email.mail_mention`, « LE MAIL IMPORTANT
   QUI VIENT D'ARRIVER », vers laquelle la consigne renvoie), dont la provenance (`mail:<référence>`) voyage dans
   l'énoncé. Un énoncé visible les « signale », eux seuls (le courrier ordinaire non lu à côté ne l'est plus). Un
   silence choisi ou une panne compte comme un essai (`email.mention_attempts`, 2 : elle n'insiste pas au-delà) ; une
   annonce devancée, interrompue, annulée, ou dont elle s'est ravisée, non. L'annonce ne part qu'à l'adresse qui
   parle pour sa propriétaire (`SPEAKS_AS_OWNER`), comme le contenu. S17 compte les énoncés, et vérifie qu'elle a le
   mail sous les yeux en le disant.
4. *Ce qui est l'objet de l'épisode garde un plancher.* Sans toucher au composeur (ce qui vient d'ailleurs reste
   coupé en premier) : le mail auquel elle prépare une réponse (`email.task_mail`, 1 500 caractères), le mail
   qu'elle annonce (`email.mail_mention`, 500), ce qui a fait naître une exploration (`goals.step_origin`, 400), ce
   que le réseau a rendu (`projects.project_network`, 600). Une section de confiance de rang plus bas est coupée à
   leur place.
5. *Ce qui est un essai, une seule fois* (`agency.UNTRIED`, `agency.tried`) : une fin devancée, préemptée,
   interrompue, annulée n'a pas eu lieu ; un murmure sans suite (`agency.renounced` à l'adresse visée, depuis le
   départ) est un « pas maintenant ». Les rappels, les récits (`goals`), les récits et appels à l'aide (`projects`),
   les annonces de mail comptent ainsi.
6. *Une arrivée, pas une reconnexion.* `social` retient qui était là (les connexions vues passer) et quand chaque
   adresse est partie ; une connexion n'est une arrivée qu'après une absence d'au moins `social.away_us` (une heure).
   À un redémarrage (`kernel.boot`), qui était là est compté parti à l'instant où elle revient : son onglet qui se
   reconnecte n'est pas une arrivée. Un arrêt propre journalise les déconnexions à l'arrêt : une interruption de
   quelques minutes (un déploiement) ne fait saluer personne ; après plus d'une heure d'absence d'elle, un bonjour
   au retour se défend.
7. *Telegram, trop tard : une excuse honnête en privé, rien dans un salon.* Se taire laisserait la personne avec
   une question vue et jamais répondue ; « réessaie dans un instant » des heures après serait faux. En privé :
   « Désolée, je n'ai pas pu te répondre plus tôt… Si c'est encore d'actualité, redis-le-moi ? » — ce que l'on dit en
   retrouvant un message manqué. Dans un salon, la conversation est passée à autre chose et un mot sans destinataire
   ne voudrait rien dire : rien. Une panne sur le moment dit toujours « réessaie dans un instant ». L'adaptateur lit
   le détail « trop tard » de la fin d'épisode ; un test de bout en bout épingle ce lien avec le moteur.

**Conséquences.** Tranches reconstruites depuis la genèse : `social` v3, `goals` v3, `projects` v3, `email` v4 (qui
corrige aussi l'élagage des demandes de rédaction ajouté sans changer de version, BUG-11). Le journal existant se
rejoue ; un énoncé d'annonce d'avant cette règle (sans provenance) signale les mails retenus au départ de son
initiative. Trois réglages nouveaux, bornés et documentés (`social.grudge_inform_shift`, `social.away_us`,
`email.mention_attempts`), une section nouvelle (`email.mail_mention`) ; aucun événement nouveau. Cibles d'intention,
chacune vérifiée en cassant exprès la correction : `test_social.py` (la rancune et la promesse, une seule déclaration
lue par toutes les retenues, le troll dont elle tient le rappel, la reconnexion et le redémarrage), `test_senses.py`
(le mail tu puis dit une fois, pas d'insistance, ce qui est un essai, l'adresse qui ne parle pas pour elle),
`test_goals.py` et `test_projects.py` (ce qui compte comme un essai), `test_composer.py` (les planchers),
`tests/protocol/test_telegram.py` (trop tard) ; S02 (le troll demande un rappel : il part à l'heure, et rien
d'ordinaire vers lui), S17 (compté à l'énoncé). Reste : le murmure (`expression`) peut encore « se raviser » d'un
rappel dû — ce n'est plus compté comme un essai, le rappel repart cinq minutes plus tard, mais on ne devrait pas se
raviser de tenir parole ; et le détail « trop tard pour répondre » est une chaîne du moteur, qu'une constante
partagée rendrait plus sûre.
