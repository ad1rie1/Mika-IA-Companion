# 0080 — Une proposition, des témoignages

Troisième lot de la refonte du modèle de connaissances (« les assertions, avec leur auteur, leur nature et leurs
preuves », ADR 0074).

**Contexte.** Une croyance était une ligne de `memory_items` qui portait **à la fois** ce qu'elle tient pour vrai et
qui avait le droit de l'entendre. Pour ne jamais élargir une permission, un jumeau exigeait les mêmes confidents
(`_twin`) : la même chose dite par Alice puis par Bob faisait **deux lignes**. Conséquences :

- la confiance ne se cumulait pas (deux témoins valaient un) ;
- la plus stricte décidait seule, ou l'autre, selon la ligne que le rappel trouvait d'abord : le secret d'Alice
  taisait ce que Bob avait dit devant tout le monde ;
- une discrétion demandée après coup (« garde-le pour toi ») ne touchait que la ligne désignée ;
- le journal réel en garde des doublons.

Choix de l'utilisateur (2026-10-09) : elle peut en parler **là où un témoignage le permet**, en l'attribuant à ce
témoin, sans laisser deviner qu'un autre le lui avait confié ; une discrétion demandée par **la personne concernée**
ferme tout, celle d'un autre ne ferme que ce qu'il en a dit ; les doublons sont **réunis la nuit**.

**Décision.**

1. *Une proposition, des témoignages.* La ligne reste la proposition (le texte, ses personnes, sa nature, son
   porteur) ; chaque façon dont elle l'a apprise est un témoignage (`memory_testimonies`, projeté avec
   `memory_items`, v10) : qui le lui a dit et de qui il le tient (`informants`), qui l'a entendu, la sensibilité, le
   secret, ce qui n'appartient qu'à elles deux, la confiance de ce témoin. `memory.believed` porte le premier ; un
   nouvel événement public, `memory.attested`, chacun des suivants. Un fait rapporté n'a plus de porteur (ses témoins
   le disent) ; un avis, une hypothèse restent à qui les porte.
2. *Le jumeau d'une croyance est la même proposition*, quel qu'en soit le témoin (mêmes mots, mêmes personnes, même
   nature, même porteur pour un avis, la plus ancienne) : la consolidation écrit un témoignage, plus jamais une
   seconde ligne. Ce que la même personne redit, de la même source, met à jour son témoignage (la date, les messages)
   sans rien ajouter ; ce qu'elle rapporte d'un autre (« Bob dit que… ») est un autre témoin.
3. *La confiance se met en commun* sur des témoins distincts (`faculties/memory/knowledge.py::pooled`) : le plus sûr,
   plus la moitié de ce que chacun des autres apporte en log-cotes, bornée à 0,95 (deux témoins à 0,8 : ~0,89, ce
   qu'ajoutait un ancien renfort corroboré). L'enveloppe de la ligne la met en commun sur tous ; le rappel, **sur les
   seuls témoignages que l'audience peut entendre** — sinon le secret d'Alice la rendrait plus sûre devant Carol.
4. *Le verdict d'une croyance est celui du témoignage qui la laisse dire* (`recall.hearing`) : celui de
   l'interlocuteur d'abord (c'est sa fiche), puis le plus ouvert, puis de première main, puis le plus récent. Elle
   l'attribue à ce témoin (l'étiquette et le doute d'une mention présumée ne nomment que lui) ; aucun ne la laisse
   dire : le verdict du témoignage de la personne concernée, pour ce qu'elle sait savoir. La ligne, elle, garde
   **l'enveloppe la plus stricte** (secret si un témoignage l'est, la plus haute sensibilité) : ce qu'en lisent les
   autres facultés par la porte (ADR 0078) reste fermé dans le doute.
5. *La discrétion après coup* : `memory.attested` avec `restricts` (rien de nouveau n'est dit) ferme le témoignage de
   qui la demande, ou **tous** (`everyone`) quand c'est une personne concernée ; un témoin qui demande le silence le
   demande pour tout ce qu'il en a dit. La relecture l'écrit pour les croyances que la conversation désigne
   (`confidentiel`). Elle ne voit que des croyances : les **souvenirs nés des mêmes messages** de qui demande la
   discrétion se ferment avec elles (`memory.reinforced` secret, `Consolidate._closed_souvenirs`) — la sonde réelle
   du 2026-10-09 a vu « Alice m'a dit qu'elle allait quitter sa boîte », noté avant le « garde-le pour toi », rester
   dicible à toute amie et revenir dans le portrait d'Alice. Une autre croyance née du même message ne se ferme pas
   d'elle-même : la relecture la voit et la désigne si elle laisse deviner le secret. Et la discrétion de la personne concernée **reste fermée** : un témoignage arrivé après (Bob qui le redit, ou un doublon joint la nuit) est fermé lui aussi (`projections._settle`, ADR 0085).
6. *Les anciens renforts ne s'ouvrent pas.* Un `memory.reinforced` d'avant reste ce qu'il était : sa discrétion et sa
   sensibilité valent pour tous les témoignages ; corroboré, il compte un témoin de plus pour la confiance, par un
   témoignage **muet** (`speaks` faux) qui reprend les droits du premier — il pouvait reposer sur une ressemblance.
7. *L'oubli d'un témoin* efface son témoignage, et la projection rejoue son oubli (`kernel.subject_forgotten` fait
   partie de ses types) : reconstruite, elle ne le fait pas revenir. Oublier le premier témoin emporte la proposition
   (son texte est le sien) : on oublie plus, jamais moins.
8. *La nuit réunit les doublons* (`night.joinable_pairs`, `memory.night_max_joins`) : les croyances actives aux mêmes
   mots, sur les mêmes personnes, de même nature (même porteur pour un avis), pas un mensonge — la plus ancienne garde,
   chaque autre devient un de ses témoignages (`memory.joined`, statut `joined`, hors de ce qu'elle tient pour sien).
   Ses témoignages, ses liens du graphe (`social`), ce qu'elle en avait raconté (`memory_told`), sa matière (`needs`)
   passent à la gardée.

**Ce qui n'est pas fait.** La vérité se juge encore avec l'audience : une correction n'en remplace une autre que si
leurs confidents sont les mêmes (`_can_replace`) — c'est le lot suivant (le vrai, le contesté, le révolu). Ce que la
personne concernée confirme d'elle-même après qu'un tiers l'a dit ne devient pas une matière d'initiative (`needs`
n'apprend que des croyances qui naissent). Les autres facultés lisent l'enveloppe, pas les témoignages.

**Conséquences.** Deux événements publics nouveaux, `memory.attested` et `memory.joined` (libellés dans la console) ;
statut `joined` ; réglage `memory.night_max_joins`. `memory_items` passe en v10 (les témoignages ; reconstruite au
démarrage : chaque croyance du journal retrouve son premier témoignage, les anciens renforts corroborés un témoignage
muet ; les confiances bougent un peu), `memory_told` en v2, `social_relations` en v3, `social` en `state_version` 11.
La genèse accepte `attest(…)`. Trois tests figeaient l'ancien modèle et sont réécrits selon la nouvelle intention
(`test_memory.py`, `test_audit_regressions.py`, `test_presumed_names.py`). Cibles d'intention
(`tests/unit/test_propositions.py`, 12), chacune rendue rouge en cassant exprès sa correction : un second témoin
témoigne au lieu d'écrire une ligne ; la même personne qui redit n'ajoute rien (à la projection comme à la mise en
commun) ; là où le témoignage de Bob le permet, elle le dit en ne nommant que Bob ; aucun témoignage, rien ; la
discrétion de la personne concernée ferme tout, celle d'un autre son seul témoignage ; la relecture l'écrit pour tous ;
le souvenir né des mêmes mots se ferme avec la croyance ; un ancien renfort n'ouvre rien ; la confiance devant Carol ignore le secret d'Alice ; un témoin oublié ne revient pas
au rebâtissage ; la nuit joint les doublons et le graphe suit ; un avis et un fait ne se joignent pas.
