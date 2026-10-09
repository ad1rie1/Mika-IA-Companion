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
     conversation (`People.near`) : c'est l'Inès qu'ils connaissent tous deux ;
   - un prénom porté par l'un des locuteurs sous une autre de ses adresses (« Robert » sur Telegram, « Bob » ici).

   Les salons se lisent une fois, puis seulement la suite du fil (`Consolidate.seen_rooms`).

   Un prénom seul, sinon, reste une mention de cette conversation (`name:<portée>:<prénom>`).
2. *L'identité la présume* (`identity.presumed`). C'est la seule personne connue qui porte ce nom, tant que la
   mention n'est reliée à personne et qu'un opérateur n'a pas écarté ce couple. La présomption est lue à chaque
   fois, sans événement : une seconde Alice connue, un « Ce n'est pas elle », un « C'est la personne dont on lui a
   parlé », et elle tombe d'elle-même. Rien n'est à réécrire, puisque la mention garde sa clé.
3. *Une présomption sert à y penser, jamais à la traiter comme elle.*
   - Le rappel range une mention faite ailleurs sous la personne présumée quand on la nomme (`named_people`). Dans
     la conversation où la mention a été faite, le nom désigne d'abord cette mention : chez Bob, « Alice » est sa
     collègue, et l'Alice que Mika connaît ne revient pas mélangée.
   - La ligne rappelée porte son doute (`memory.tag.presumed`, aussi dans `memory_search`), en nommant qui parlait :
     « c'est Bob qui parlait de « Alice » : peut-être pas la personne que tu connais sous ce nom ». Une première
     tournure, sans le nom (« « Alice » ici, c'est ce qu'on t'en a dit »), a été lue par le modèle comme un doute
     sur l'Alice qu'elle connaît elle-même (sonde réelle). Pas de doute devant celui qui l'a raconté : il sait de qui
     il parle, et la ligne lui apprendrait qu'elle connaît une Alice.
   - `identity.person` ne la suit pas, ni la porte de la fiche de la personne présumée (la mention reste un tiers),
     ni les liens de l'ADR 0058 (`social.TIES`), ni son portrait.
   - *Une présomption ne protège jamais moins qu'une liaison.* Quand une mention présumée figure parmi les personnes
     concernées, le lien qui ouvre une confidence (`privacy.tied_to`) est exigé avec la personne présumée, comme
     si elle était reliée ; une mention de quelqu'un d'inconnu reste un détail de l'histoire, comme avant. Un
     appelant qui ne sait pas lire la présomption (`hearable` des pensées, des rêves, des buts) ne laisse rien
     passer par un lien dès qu'une mention figure : dans le doute, rien ne s'ouvre. Les sujets délicats de la
     personne présumée relèvent la sensibilité (`sensitivity_of`), comme ceux d'une personne reliée.
4. *Le cas Carol demande une confirmation.* Le lien qui ouvre les confidences d'Alice à Carol naît quand un opérateur
   relie la mention (« À valider › Noms à relier »), ou d'emblée si Mika les a vues en salon ensemble. Le relier
   après coup suffit : `social.TIES` résout les clés au moment de la lecture.
5. *L'oubli prend la présomption* (`identity.inspect.presumed_mentions`). Oublier Alice oublie aussi les mentions
   présumées être elle, partout où elles figurent : l'index des sujets du journal (`EventStore.subjects`), pas
   seulement « à propos de » — une mention qui tient une opinion (`holder`), qui a raconté, à qui l'on a promis.
   Dans le doute, on oublie plus, jamais moins. La règle était déjà celle des anciens noms sans portée
   (`name_aliases`) ; elle s'étend aux mentions.
6. *Une mention de la conversation reste visible à l'extraction* (`_known_beliefs`) : un « garde-le pour toi » dit
   après coup peut encore la viser (`confidentiel`, `remplace`). Et une note « sur elle » qui nomme quelqu'un
   (`People.names_someone`) n'est pas sa vie à elle : « je sais que tu es comptable à Lyon », redit par elle, était
   devenu une note sur elle qui ne concernait personne, donc dicible à tous (sonde réelle). Elle suit le chemin
   commun, où redire n'est pas apprendre.
7. *Une croyance naît bornée par sa nature* (`extraction.born_confidence`) :
   - 0,8 pour ce qu'on lui a dit ;
   - 0,9 pour ce qu'elle a vu ou vécu ;
   - 0,6 pour ce qu'elle déduit, une hypothèse comprise.

   Le modèle qui l'extrait ne la rend pas plus sûre, et redire n'ajoute rien. Seule une autre personne qui le lui
   dit aussi (`corroborated`) la fait monter, jusqu'à 0,95 comme avant.

**Conséquences.**

- `tests/unit/test_presumed_names.py` : la mention et ses contre-exemples (nom complet, rencontre en salon, un
  locuteur), la présomption qui tombe, l'opérateur qui tranche, l'oubli, le rappel et son doute, la confiance à la
  naissance, et ce qu'une présomption doit protéger autant qu'une liaison.
- Six tests changent d'attente, chacun pour la raison ci-dessus :
  - `test_memory_privacy` : ce que Bob dit d'Alice ; la proche d'Alice, qui attend la confirmation ; le souvenir qui
    nomme Bob, oublié avec lui ;
  - `test_audit_regressions` : l'opinion de Bob sur Alice ;
  - `test_identity_security` : l'oubli sans liaison emporte la mention présumée ;
  - `test_disclosure` : `tied_to` lit la présomption, et ferme sans elle.
- Plus de mentions attendront dans « Noms à relier » : chaque prénom d'une personne connue dit en son absence. C'est
  le prix de ne plus confondre.
- Les éléments déjà au journal, reliés d'office avant cette décision, le restent. Seules les extractions nouvelles
  gardent une mention. Une croyance ancienne reliée à Alice et une nouvelle posée sur une mention ne se remplacent
  ni ne se fusionnent (`_can_replace` et `_twin` comparent les personnes) : elles peuvent coexister.
- Une promesse faite à une mention n'est réglée par personne tant que la mention n'est pas reliée.
- La relecture du 2026-10-09 a trouvé ce que la première version ne tenait pas (une Carol présumée qui protégeait
  moins qu'une Carol reliée, des sujets délicats ignorés, un secret demandé après coup sans cible, un oubli
  incomplet, la confusion dans l'autre sens) : `test_presumed_names.py` en porte les cas (16 tests).
- *Sans lien avec les noms* : la sonde réelle (Haiku par la CLI Claude Code) a montré une réponse amputée de son
  début (« pas, et je ne connais pas ton équipe… »). La CLI ne rend dans `result` que son dernier message ; quand
  le modèle s'interrompt au milieu d'une phrase pour chercher un outil (`ToolSearch`) puis reprend, le début se
  perdait. L'adaptateur le rend désormais (`claude_code.answer`), un préambule fini restant écarté comme sur l'API
  (`test_claude_code.py::test_a_sentence_cut_by_a_tool_search_keeps_its_beginning`).
