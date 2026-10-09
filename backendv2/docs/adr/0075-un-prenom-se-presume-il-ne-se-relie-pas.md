# 0075 — Un prénom se présume, il ne se relie pas

**Contexte.** L'ADR 0074 a laissé de côté un constat de l'audit de la mémoire (2026-10-08). Quand un prénom n'était
porté que par une seule personne connue, l'extraction le reliait d'office à elle (`People.one`, l'annuaire). La
nouvelle collègue « Alice » de Bob devenait ainsi l'Alice que Mika connaît. Ce que Bob en disait partait dans la
fiche de son amie et dans son portrait. Mika pouvait le lui resservir comme si c'était « à elle ». L'ADR 0048 disait
pourtant qu'un nom se relie et ne se devine pas.

Exiger qu'Alice et Bob aient été vus ensemble cassait le cas ordinaire de l'ADR 0058. Alice parle de sa meilleure amie
« Carol » ; Carol écrit à Mika de son côté. La lecture de l'ancien moteur l'a confirmé : il ne savait pas distinguer
deux homonymes. Il confondait même toutes les « Alice » en une seule fiche, et le cas Carol ne tenait que par cette
même coïncidence de prénom.

Le même passage a relevé un second point : la confiance d'une croyance était celle que donnait le modèle. Une
déduction pouvait naître à 0,95.

**Décision.**

1. *Ce qui relie encore à l'extraction* :
   - un locuteur de la conversation ;
   - un nom complet qu'une seule personne connue porte ;
   - un prénom porté par une seule personne connue, si elle a été vue dans un salon avec quelqu'un de la
     conversation (`People.near`) : c'est l'Inès qu'ils connaissent tous deux.

   Un prénom seul, sinon, reste une mention de cette conversation (`name:<portée>:<prénom>`).
2. *L'identité la présume* (`identity.presumed`). C'est la seule personne connue qui porte ce nom, tant que la
   mention n'est reliée à personne et qu'un opérateur n'a pas écarté ce couple. La présomption est lue à chaque
   fois, sans événement : une seconde Alice connue, un « Ce n'est pas elle », un « C'est la personne dont on lui a
   parlé », et elle tombe d'elle-même. Rien n'est à réécrire, puisque la mention garde sa clé.
3. *Une présomption sert à y penser, jamais à la traiter comme elle.*
   - Le rappel range la mention sous la personne présumée quand on la nomme (`named_people`). La ligne rappelée
     porte son doute (`memory.tag.presumed`, aussi dans `memory_search`) : « « Alice » ici, c'est ce qu'on t'en a
     dit ».
   - `identity.person` ne la suit pas, ni le verdict de divulgation (la mention reste un tiers, jamais la fiche de la
     personne présumée), ni les liens de l'ADR 0058 (`social.TIES`), ni son portrait.
4. *Le cas Carol demande une confirmation.* Le lien qui ouvre les confidences d'Alice à Carol naît quand un opérateur
   relie la mention (« À valider › Noms à relier »), ou d'emblée si Mika les a vues en salon ensemble. Le relier
   après coup suffit : `social.TIES` résout les clés au moment de la lecture.
5. *L'oubli prend la présomption* (`identity.inspect.presumed_mentions`). Oublier Alice oublie aussi les mentions
   présumées être elle. Dans le doute, on oublie plus, jamais moins. La règle était déjà celle des anciens noms sans
   portée (`name_aliases`) ; elle s'étend aux mentions.
6. *Une croyance naît bornée par sa nature* (`extraction.born_confidence`) :
   - 0,8 pour ce qu'on lui a dit ;
   - 0,9 pour ce qu'elle a vu ou vécu ;
   - 0,6 pour ce qu'elle déduit, une hypothèse comprise.

   Le modèle qui l'extrait ne la rend pas plus sûre, et redire n'ajoute rien. Seule une autre personne qui le lui
   dit aussi (`corroborated`) la fait monter, jusqu'à 0,95 comme avant.

**Conséquences.**

- `tests/unit/test_presumed_names.py` (9 tests) : la mention et ses contre-exemples (nom complet, rencontre en
  salon), la présomption qui tombe, l'opérateur qui tranche, l'oubli, le rappel et son doute, la confiance à la
  naissance.
- Cinq tests changent d'attente, chacun pour la raison ci-dessus :
  - `test_memory_privacy` : ce que Bob dit d'Alice ; la proche d'Alice, qui attend la confirmation ; le souvenir qui
    nomme Bob, oublié avec lui ;
  - `test_audit_regressions` : l'opinion de Bob sur Alice ;
  - `test_identity_security` : l'oubli sans liaison emporte la mention présumée.
- Plus de mentions attendront dans « Noms à relier » : chaque prénom d'une personne connue dit en son absence. C'est
  le prix de ne plus confondre.
- Les éléments déjà au journal, reliés d'office avant cette décision, le restent. Seules les extractions nouvelles
  gardent une mention.
- `_rooms` lit à chaque consolidation les couples (personne, salon) distincts du fil. C'est le même genre de lecture
  que l'annuaire (`_directory`).
