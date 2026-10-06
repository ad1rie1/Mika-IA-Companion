# 0071 — Sa voix dans un seul fichier : `persona/voix.yaml`

**Contexte.** La propriétaire a demandé (2026-10-06) de regrouper **toutes les phrases qui façonnent sa
personnalité** dans un seul fichier bien documenté, pour pouvoir changer la grammaire (les accords au féminin, le
tutoiement), le ton, une règle de vie ou une consigne sans toucher au code. Ces phrases étaient écrites en dur,
dispersées dans une quarantaine de modules : la consigne de sa nature (`self.NATURE`), les sections du prompt et
leurs titres (« TA FAÇON DE DIRE BONJOUR »), les consignes des modèles de fond (journal, rêve, récit, relecture d'une
conversation, fiche d'une personne, résumé d'un long fil), les cadrages de chaque épisode, les descriptions des
outils et de leurs paramètres, les mots de ses humeurs (`vocab/affect.FR`), les repères de temps du fil, et ce
qu'elle produit sans modèle (sa journée « à raconter », ses bonjours de secours). Le jumeau numérique (ADR 0070,
`INJECTION/`) en a fait un besoin : une persona incarnée a besoin d'autres tournures que l'IA qui le sait, sans
fourcher le moteur.

**Décision.**

1. *Un fichier, à côté de la persona.* `backendv2/persona/voix.yaml` : un arbre YAML de phrases, documenté en tête
   (ce qu'on y trouve, comment écrire une phrase, la grammaire, une autre voix, comment vérifier) et phrase par
   phrase (où elle sert, quand le modèle la lit, ce que contient chaque trou). Sa persona dit **qui** elle est ; ce
   fichier dit **comment on le lui dit**, et comment elle se dit les choses.
2. *Le code demande une phrase par sa clé.* `mika.vocab.phrasebook` : `phrase("self.night.dream.system",
   tone=…)`, `phrases(clé)` (une liste de tournures), `family(préfixe)` (un groupe choisi à l'exécution : une
   émotion, une raison, un ton). Les **trous** (`{tone}`) sont stricts : le code passe exactement ceux du texte, ni
   plus ni moins ; un écart lève `VoiceError`, qui nomme le fichier, la clé et le trou. Les trous se remplissent en
   une passe : une valeur qui contient elle-même « {trou} » (l'objet d'un mail, du code) reste telle quelle. Le
   fichier se lit une fois,
   au premier besoin ; rien ne se recharge à chaud (ce qu'elle a dit sous une voix reste dit sous elle).
   `mika.vocab` est sous `contracts` : toutes les couches au-dessus de `kernel` peuvent le lire.
3. *Une autre voix sans fourche.* `MIKA_VOIX` désigne un autre fichier (un jumeau a le sien :
   `INJECTION/sortie/voix.yaml`, passé au moteur gelé de l'avance rapide puis au service).
4. *Ce qui n'y est pas.* La console de l'opératrice (fiches, actions, libellés et aides des réglages), la ligne de
   commande, les journaux techniques : ni le modèle ni elle ne les lisent. Les **codes** restent dans le code : les
   raisons et causes gardées au journal, les graines de hachage (les changer casserait le rejeu), les clés de
   dictionnaire, les noms d'émotion anglais. Les **détecteurs** aussi (`vocab/words.py`, marqueurs de secret,
   expressions régulières) : ce ne sont pas des phrases qu'on lui dit. Et le **noyau** (`kernel/`, qui n'a pas le
   droit d'importer `vocab`) garde ses marqueurs de structure (« --- ETAT INTERNE --- », « (reprise de la
   conversation) »).
5. *Gardes.*
   - `tests/architecture/test_phrasebook.py` (AST) : chaque clé demandée par le code existe, ses trous
     correspondent, aucune phrase du fichier n'est orpheline, une clé construite à l'exécution
     (`phrase(f"affect.mood.{x}")`) n'a pas de trou ;
   - `tests/unit/test_phrasebook.py` : lecture, trous stricts, erreurs qui disent où ;
   - `tests/architecture/test_no_new_prose.py` : une heuristique (AST) cherche la prose française écrite en dur dans
     les facultés et les greffons, hors docstrings, journaux techniques, libellés de réglages, raisons d'humeur,
     expressions régulières et fichiers de console. Ce qui reste a été trié (textes de console, valeurs gardées au
     journal, listes de mots, le serveur de recherche autonome qui ne peut pas lire la voix) : un plafond par
     fichier, qui ne peut que baisser. Elle vérifie aussi qu'aucun dossier de fragments ne traîne ;
   - `python -m mika.vocab.phrasebook` : le fichier se lit-il, combien de phrases.

**Comment la migration s'est faite.** Trois zones, chacune dans un fragment provisoire, puis fusionnées en un seul
fichier de **1 657 entrées** (dont 603 à trous et 8 listes), rangées en dix sections par propriétaire :
- elle-même : 344 entrées — `self`, `expression`, `affect`, `body`, `needs`, `agency` ;
- les autres et sa mémoire : 526 — `identity`, `social`, `others`, `memory`, `transcript`, `attention`, `world`,
  `shares` ;
- ses buts, ses projets, ses greffons et ce qu'on lui montre : 787 — `goals`, `projects`, les greffons, `runtime`,
  les textes des adaptateurs, `circadian`.

Le repère : un instantané de **tout ce que le modèle lit** (et des textes gardés au journal) sur les 22 scénarios de
la voie rapide du simulateur — 4 611 requêtes —, pris avant la migration et comparé après chaque zone puis après la
fusion. Il est resté **identique au caractère près** : la migration ne change aucun comportement, seulement d'où
vient le texte.

**Conséquences.**
- Changer une tournure : éditer `voix.yaml`, redémarrer. Une clé ou un trou renommé par erreur est refusé au
  démarrage et par les tests, avec la clé en cause.
- Un mot d'humeur changé dans `affect.mood.*` change aussi ce que la balise `[EMOTION:…]` reconnaît (la table des
  synonymes en dérive).
- Une phrase nouvelle que le modèle lit s'écrit dans `voix.yaml`, commentée — jamais en dur.
- Ce qui reconnaît une consigne à ses mots (le rejoueur d'`INJECTION/`) lit la même voix au lieu de les recopier.
- Relevé pendant la migration, **sans le corriger** (ce serait changer son comportement) : des tournures qui
  trahissent une IA pour une persona incarnée (« la machine », « opérateur », « console », « tes apps », « un réveil
  par API », « Tu n'es pas une assistante », « ce portrait »), des réponses d'outils à la première personne au milieu
  d'autres qui la tutoient, quelques coquilles, et une cause d'humeur au réveil (« le rêve de cette nuit ») qui ne
  correspond à aucun code de cause — son humeur du matin se dit alors « sans trop savoir pourquoi ». Elles se
  corrigent maintenant dans le fichier, avec la propriétaire.
- Restent hors du fichier, et signalés : le noyau (ses marqueurs de structure) ; le greffon Teams et
  `adapters/web/app.py` (une autre session y travaillait) ; `ports/preprocess.py` et `ports/workshop.py` (des textes
  que le modèle lit, mais dans des ports) ; le mode d'emploi de la forge (`forge/guide.py`) ; le serveur de recherche
  web, qui tourne seul dans sa cage. Quelques couplages au texte sont commentés dans le fichier (un code qui retire
  « il y a » d'une tournure, un titre de section cité dans un brief) : changer ces phrases demande de relire leur
  commentaire.
