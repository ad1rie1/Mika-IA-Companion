# 0092 — Nommer exige un lien ; raconté, c'est dit ; ce qui se reconnaît

Suite du lot 5 du chantier « qui elle devient » (ADR 0091), après la sonde réelle du 2026-10-11 et sa relecture.

**Contexte.** Cinq écarts entre ce que le plan voulait et ce que le code faisait :

1. *Montré n'est pas dit.* `memory_told` compte ce que le prompt d'un énoncé montrait (sa provenance). Un récit sans
   nom montré à Chloé mais jamais dit lui revenait ensuite « déjà raconté, garde-le sans nom » — faux — et prenait la
   place d'une vraie nouvelle dans le budget. Et un récit déjà raconté revenait **sans repasser le verdict** : devenu
   secret depuis, ou une fois Chloé liée à Alice, il ressortait encore.
2. *Seuls les liens directs ferment, et le filet du texte est mince.* Une amie commune reconnaîtrait « une amie qui
   vient de se séparer » ; une version sans nom qui garde « en janvier », « chez ubisoft » (en minuscules), « un CDI »
   ou « en Italie » passait le filet (un nom connu, une année, un jour et un mois chiffrés seulement).
3. *Le nom de l'un dans ce que l'autre a écrit* ne se cherchait que dans ses 2 000 derniers messages.
4. *Une demande de silence contagieuse.* Alice confie un licenciement, une rupture, puis « je suis enceinte, dis-le à
   personne » : le modèle (Haiku) marquait les trois secrets — le licenciement ne se disait plus à personne.
5. *Une amie de Mika entendait la vie d'Alice nommément.* La règle d'ADR 0058 ouvre le personnel à toute amie de Mika ;
   le plan attendait qu'Inès, amie sans lien avec Alice, l'entende sans nom.

**Décision.**

1. *La vie d'autrui ne se dit nommément qu'à qui a un lien avec la personne* — une relation qu'elle a déclarée
   elle-même (`tied`) — *ou qui était là* (`witness`) : au-delà de l'anodin, le reste se raconte sans nom ou se garde.
   C'est une facette de plus, pas une réécriture : `vocab.privacy.untied` → `Disclosure.untied_level` →
   `Audience.untied_level` (facultatif : absent, c'est `level` ; toute audience réelle le précise, une garde
   d'architecture le vérifie — `tests/architecture/test_audiences_say_who_knows_whom.py`). La lisent la porte de la
   mémoire (`privacy.admissible`), ses pensées (`attention.admissible`), ses rêves (`self.night.hearable`) et ce dont
   elle pourrait parler (`needs.matter`) : ce qu'elle sait, pense ou rêve de quelqu'un. Une pensée qui se dit sans
   son contenu devant qui écoute (les mots d'Alice tus) est sa vie à elle : la règle d'une amie, comme la ligne
   « Alice t'a confié traverser un moment difficile » du rappel — mais elle ne nomme Alice qu'à qui a un lien avec
   elle (`attention.named`) ; sinon « un échange avec quelqu'un m'a marquée ». En sonde, le prénom dans ses pensées
   faisait retirer par le compositeur le récit sans nom d'Alice (à juste titre : les deux ensemble la désignaient). Ses projets, ses buts, son
   monde et les fichiers gardent la règle d'une amie (`level`, ADR 0058) : la propriétaire voit toujours le projet que
   Béa lui a confié. Ce que quelqu'un a dit de l'interlocuteur lui-même, c'est sa vie à lui : le redire suit la règle
   d'une amie (une mention qu'elle présume le désigner comprise). Un interrupteur de la politique
   (`TrustPolicy.named_needs_tie`) rend la règle d'avant ; ce n'est pas un réglage.
2. *Raconté, c'est dit.* `memory_told` (v4) garde, pour un récit sans nom, chaque énoncé qui le montrait
   (`memory_told_lines` : élément, adresse, numéro de l'énoncé — c'est aussi la ligne de sa réponse dans le fil). Le
   jugement se fait à la lecture, pur (`veiled.echoed`) : la part des mots qui portent le récit (hors ceux qui le
   tournent, `vocab.retelling.FRAMING` ; radicaux courts, « perdu » ≈ « perdre ») que sa réponse reprend, au moins
   `memory.veiled_said_share` (0,5). Une seule réponse qui le dit suffit, une suivante qui n'en dit rien ne le défait
   pas. Un récit qui ne porte aucun mot à lui compte (ce qui ferme le moins mal). Ceux qui ferment — un lien « déjà
   raconté nommément », une preuve d'identité — gardent « montré » : dans le doute, ce qu'on lui a montré pour parler à
   Chloé, Chloé le sait. Un récit déjà raconté ne revient que sous le même verdict (secret, lien, niveau…).
3. *Ce qui se reconnaît.* Le filet (`extraction.veiled_refusal(texte, annuaire, original)`) écarte aussi : un mois ou
   un jour de la semaine ; un mot à majuscule ailleurs qu'en tête de phrase (un prénom, un lieu, une marque, un
   sigle — « un CDI » est perdu, c'est voulu) ; un mot qui porte une majuscule dans l'original (« Ubisoft »), même en
   minuscules dans la version sans nom ; un mot en tête de phrase à majuscule dans les deux, hors mots courants
   (`vocab.words.OPENERS`). La consigne de la relecture demande en plus « ni métier ou formation précis : l'essentiel,
   en termes généraux ». Au second degré (`memory.veiled_link_depth`, 2) : quelqu'un que le graphe social relie aux
   deux (`contracts.social.RELATIONS_TABLE`, lue sans s'écrire ; toute relation, dans un sens ou dans l'autre, quel
   qu'en soit l'état : un lien qui ferme n'a pas à être prouvé) ferme ; une relation finie ou hostile entre les deux
   ferme dès le premier degré. Une mention qu'elle présume désigner qui écoute compte pour lui comme pour la personne
   (sonde réelle : Alice parle de « Bob, mon collègue », jamais relié ; Bob aurait reconnu sa collègue dans « une amie
   a été licenciée avec toute son équipe ») ; les mentions se cherchent dans sa mémoire et dans le graphe.
4. *Tout l'historique.* Le nom se cherche dans tous leurs messages : la base ne rend que ceux qui contiennent le prénom
   sous une de ses graphies (un `LIKE` de SQLite ne replie pas la casse des lettres accentuées : « inès », « Inès »,
   « INÈS », « ines ») ; le mot entier se vérifie ensuite (« inestimables » n'est pas Inès).
5. *Une demande de silence couvre ce qu'elle vise* (`extraction.silence_scope`, `scoped_secrets`, appliqué à la
   relecture avant tout le reste). Dans un message qui raconte, la demande couvre ce message ; seule (« garde ça pour
   toi », « motus ») elle couvre ce que la même personne vient de dire, jusqu'à sa demande précédente. Un élément qui
   s'appuie sur un message couvert est un secret, que le modèle l'ait noté ou non. Un « secret » que le modèle pose
   hors de toute demande, dans une conversation où l'on en a fait une, ne l'est pas — sauf si ses messages laissent
   d'eux-mêmes entendre qu'il est à garder (« je l'ai encore dit à personne », « tu es la seule à savoir » :
   `PRIVATE_CUES`) — mais devient au moins une **confidence** : dans le doute, discret, pas muet. Sans demande dans la
   conversation, ou sans message cité, le modèle seul en juge (la règle d'avant).
6. *Ce que la sonde a encore montré.* Une rupture concerne toujours deux personnes : « Alice et Paul se sont séparés »
   tombait sous « plus d'une personne », et aucune rupture ne se racontait jamais. Un prénom que l'identité ne présume
   être personne de connu (« Paul ») est un **détail de l'histoire** de qui la raconte (la règle d'ADR 0058) : la
   version sans nom le tait déjà (« son compagnon »), le bloc le porte parmi les noms qu'il tait, et si qui écoute a
   lui-même écrit ce prénom, ça ferme ; une mention présumée reste une personne et ferme. Et une même histoire rangée
   deux fois (un souvenir et une croyance du même message) ne se raconte qu'une fois (`veiled.SAME_STORY` : deux
   récits qui partagent 60 % de leurs mots) — sinon elle épuisait le budget d'une personne et le licenciement ne
   passait jamais.

**Conséquences.** `Disclosure.untied_level`, `Audience.untied_level` (+ propriété `untied`), `privacy.untied`,
`TrustPolicy.named_needs_tie`, `hearable(untied_level=…)`. Projecteur `memory_told` v4 (table `memory_told_lines`).
Réglages nouveaux (groupe « Raconter sans nommer ») : `memory.veiled_link_depth`, `memory.veiled_said_share`.
`contracts.memory.TOLD_LINES_TABLE` ; `vocab.retelling.FRAMING`, `vocab.words.OPENERS`. Console : la page d'identité
dit ce qui se dit de la vie de quelqu'un sans lien (« sa vie, sans lien ») ; la fiche mémoire d'une personne ne parle
plus de « ce qu'elle lui a raconté » mais de « ce qu'elle avait en tête en lui parlant ». Les tests qui supposaient
qu'une amie de Mika entend la vie d'Alice nommément lui donnent désormais un lien déclaré par Alice
(`test_social`, `test_memory_privacy`), ou attendent le récit sans nom (`test_veiled_retelling`). Cibles :
`test_disclosure` (la facette, son interrupteur, la porte, les pensées — son ressenti nommé, jamais le contenu —,
`untied ≤ level ≤ tied` pour toute audience),
`test_veiled_retelling` (montré n'est pas raconté ; ce qui compte comme dit ; un récit raconté repasse le verdict ; une
amie commune ferme au second degré, pas au premier ; une mention présumée de qui écoute ferme ; le nom au fond de
l'historique et sous ses graphies ; le filet du texte et de la relecture), `test_memory_privacy` (la portée d'une demande ; le secret contagieux gardé en confidence ;
de bout en bout, la proche liée entend le licenciement, jamais la grossesse), et la garde des audiences. 35 mutations,
toutes rouges.

**Ce qui n'est pas fait.** Le jugement « dit » est lexical : une reformulation très libre peut passer pour non dite
(elle redevient une nouvelle qu'elle peut raconter — sans danger, sans nom). La reconnaissance par un détail rare mais
sans majuscule (un métier peu courant, une ville écrite en minuscules par le modèle) repose sur la consigne de la
relecture. Les liens au-delà du second degré ne ferment pas. Le premier message après un démarrage peut arriver avant
que le modèle de plongements soit chargé : le rappel dépasse son délai et ce tour se fait sans mémoire (vu en sonde,
hors de ce lot).
