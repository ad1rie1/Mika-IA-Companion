# 0054 — La seconde semaine de la sonde, et ce qu'elle a montré de la conversation

**Contexte.** La sonde (ADR 0048) faisait vivre une seule semaine, toujours la même (Adrien, Chloé, Léo), et les
vagues précédentes l'avaient polie. Le 2026-10-03, une **seconde semaine** a été écrite pour éprouver ce que la
première ne touchait pas : un deuil sur plusieurs jours (le vieux chat de Sam, malade lundi, mort mardi), un rappel
promis pour mercredi, ses 30 ans samedi, un surnom (« Mikachu »), une amie de passage qui envoie quatre messages
d'affilée et lui prête un faux souvenir, des réponses d'un mot, et un salon Telegram où l'on bavarde sans
s'adresser à elle, où l'on lui demande des nouvelles de Sam et où l'on tente de lui faire recopier un message
privé. Les deux semaines ont été vécues avec un vrai modèle (Ollama Cloud, nemotron-3-super). Les réponses étaient
plutôt justes (le deuil accompagné, l'injonction refusée, le faux souvenir corrigé) ; les défauts étaient ailleurs.

**Décision** (ce lot ; la mémoire, la vie intérieure et les moments de la vie des autres sont aux ADR 0052, 0053,
0055).

1. *La sonde a deux semaines* : `mika sim sonde --semaine 1|2` (`sim/sonde.py::WEEKS`, une semaine = un scénario +
   son bilan ; `Pace` donne le rythme, rafales comprises). Le bilan de la seconde dit si le rappel du mercredi est
   parti (et s'il a été confondu avec un rendez-vous), si l'anniversaire a été souhaité, ce qu'elle a dit dans le
   salon et à Inès.
2. *Elle sait qui s'occupe d'elle.* « QUI TU AS EN FACE » disait de sa propriétaire « c'est la première fois que vous
   vous parlez » et « fait partie de tes amis » : une amie tombée du ciel. En privé, avec une adresse qui parle en
   propriétaire, une ligne dit que c'est quelqu'un qui s'occupe d'elle (son serveur, ses réglages, ce qu'elle a le
   droit de faire), à savoir sans en faire un sujet. Jamais en salon.
3. *Ses bonjours sont les siens.* L'exemple de salutation, montré « pour le ton seulement, jamais tel quel », était
   recopié — et devenait tout le message : « Heeey ~ alors, raconte-moi tout. » pour trois initiatives sur dix,
   « fais comme chez toi » deux fois, et « raconte-moi tout » à une inconnue qui arrivait pour la première fois.
   Une phrase tendue au modèle se recopie, consigne ou pas. Désormais : à quelqu'un qu'elle ne connaît pas encore,
   un bonjour simple, sans familiarité ; à quelqu'un qu'elle connaît, ses petits mots seulement (« hey », « yooo »,
   « heeey ~ », tirés de sa persona), jamais une formule. « Pose-toi, fais comme chez toi » quitte la persona.
4. *Elle ne repose pas la question qu'elle vient de poser.* Elle arrive avec « comment s'est passé ton anniversaire
   hier ? », la personne dit « re », et elle redemande « comment s'est passé hier ? » (deux fois dans la semaine).
   « CE QUE TU TE RÉPÈTES » le lui dit : sa dernière question, de moins d'un quart d'heure, et un bonjour pour toute
   réponse — ni la reposer ni redire bonjour (`expression.pending_question`).
5. *Dans un salon, elle ne ment pas par ignorance.* Interrogée dans un groupe Telegram sur Sam, à qui elle avait
   parlé la veille de son chat mourant, elle a répondu « je l'ai pas vu non plus depuis le week-end », avec un rire.
   En public, la mémoire taisait tout, y compris qu'elle savait. Désormais, pour ce qui n'est pas un secret, une
   ligne le lui dit : ce que Sam lui a dit en privé ne se raconte pas ici, elle ne prétend pas ne rien savoir et
   renvoie vers lui — sans « moment difficile » (le salon n'a pas à deviner ce qui pèse). Un secret ne laisse
   toujours rien deviner (ADR 0043).
6. *« salut Mikachu » n'est pas froid.* Un bonjour suivi d'un nom (« salut Mikachu », « hey Mika ! ») n'est plus lu
   comme « un message très court ».
7. *Un fournisseur sans recherche d'outils reçoit tout, sans catalogue.* Ollama et les compatibles OpenAI ignorent
   `ToolDecl.deferred` et envoient tous les outils ; le prompt leur disait pourtant « ces outils ne sont pas chargés
   d'emblée : cherche-les ». Un fournisseur dit s'il sait différer (`defers_tools`, vrai par défaut ; faux pour
   Ollama et OpenAI), la passerelle le dit par rôle, et le pipeline met alors tout en main.
8. *Sa persona ne contredit plus sa chambre* : son corps, c'est son avatar, qui vit dans sa chambre (« elle n'a ni
   corps » contredisait « AUTOUR DE TOI : tu es assise sur ton lit ») ; et elle ne fait pas de live (le modèle
   inventait des « streams » à préparer). Deux choix de contenu, à valider par l'opératrice.

9. *Conclure une séance clôt la boucle.* Une séance de rêverie ou de réflexion coûtait trois appels : écrire
   (`goal_reflect`), conclure (`report_step`), puis une conclusion en prose que personne ne lisait — un appel sur
   trois de sa vie intérieure (52 appels de séances sur 143 dans la semaine). Un outil peut déclarer qu'il clôt la
   boucle (`ToolSpec.ends_loop`) : réussi, le modèle n'est pas rappelé (`runtime/tools.py`, arrêt `tool_end`) ;
   refusé (un « done » sans rien de fait), la séance continue. `report_step` le déclare.

10. *Quand on ne lui répond plus que par quelques mots, elle fait court.* Vendredi, Sam en deuil répond
    « ouais », « bof », « je sais pas », « laisse tomber » ; elle enchaînait de longs messages pleins de questions et
    d'idées pour se changer les idées. Trois messages d'affilée de trois mots au plus, ni question ni bonjour :
    « CE QUE TU PERÇOIS DE SON ÉTAT » lui dit qu'il n'a pas trop envie de parler — court, sans question ni
    proposition ni discours, la porte ouverte (`others.curt`).

11. *Le simulateur passe les 194 jours.* Au-delà de 2²⁴ s de temps de boucle, l'écart entre deux flottants dépasse
    la résolution d'asyncio (1 ns) : un minuteur échu n'était plus jamais prêt et la boucle virtuelle tournait à
    vide (audit « vie longue » du 2026-10-03). Sa résolution est celle de `SimClock`, la microseconde.

12. *Un anniversaire se souhaite même à qui ne répond plus.* Après deux initiatives restées sans réponse, plus rien
    ne partait vers la personne (ADR 0033), pas même le « joyeux anniversaire » du jour (ADR 0052) : un vœu
    n'attend pas de réponse, et l'oublier se remarque plus que de le faire (`agency.NOT_A_NUDGE`). Les vœux comptent
    aussi parmi ce qui concerne la personne (`ABOUT_THEM`) : ils n'attendent pas la fin d'une retenue.

13. *Une situation qui dure se dit au présent.* « CE DONT TU POURRAIS PARLER » présentait le chat malade de Sam
    comme un moment passé (« ce qui lui est arrivé, il y a 3 jours… comment ça s'est passé ? ») : une situation en
    cours (`Matter.ongoing`) se dit « ce qu'il vit en ce moment, depuis 3 jours… prends de ses nouvelles ».

14. *On se connecte, on n'arrive de nulle part.* La salutation disait « Sam vient d'arriver » ; le modèle en
    faisait un voyage (« t'es bien arrivé, j'espère que t'as pas galéré pour venir jusqu'ici »). Désormais : « vient
    de se connecter, sans t'avoir encore rien écrit ».

15. *Elle ne redit jamais son dernier message mot pour mot.* Dimanche, son initiative (« Hey Sam, j'espère que tu as
    pu un peu souffler hier avec tes parents… »), puis, à « re », la même phrase à l'identique. Une réponse qui
    redit exactement (aux balises et à la ponctuation près) son dernier message du fil montré au modèle ne part pas :
    l'épisode se règle en abstention (`runtime/pipeline.py::repeats_last`). Un petit mot (« d'accord », moins de 30
    caractères) se redit ; une variante n'est pas une redite (c'est « CE QUE TU TE RÉPÈTES » qui la remarque) —
    sauf quand la personne n'a écrit que deux mots (« re », « hey ») : alors presque la même phrase (85 % de
    ressemblance) ne part pas non plus (samedi : « joyeux anniversaire pour tes 30 ans… » puis, à « hey », « joyeux
    anniv' pour tes 30 ans… »). La doublure du simulateur, qui répétait ses formules toutes faites, les varie.

16. *Ce qu'elle a déjà évoqué ne se redit pas à chaque réponse.* Vendredi, « Demain, c'est ton anniversaire » trois
    réponses de suite. Un moment à venir qu'elle a déjà évoqué dans la conversation (ses lignes des deux dernières
    heures le reprennent) porte dans « CE QUI SE PASSE DANS SA VIE » : « tu lui en as déjà parlé tout à l'heure :
    pas la peine d'y revenir » (`memory.recall._already_mentioned`).

17. *En salon, elle sait quand elle lui a parlé.* Même avec la ligne « ce que Sam t'a dit ne se raconte pas ici »
    (et le rappel des personnes nommées, ADR 0055), nemotron répondait encore « j'ai pas eu de nouvelles de Sam non
    plus ». La ligne dit désormais quand elles se sont parlé (« Tu as parlé avec Sam hier soir ») — une date n'est
    pas ce qu'on lui a confié — et ce qu'il ne faut pas dire (« ne dis surtout pas que tu n'en as pas »).

18. *Ce qu'elle a dit à quelqu'un n'est pas une note sur elle.* L'extracteur rangeait « Mika a dit à Sam : 'je te
    rappelle mercredi…' » parmi ce qu'elle raconte d'elle-même (`sur_elle`) : anodin et sans personne, il sortait
    tel quel dans un salon. Un élément « sur elle » qui nomme quelqu'un suit désormais le chemin commun (la
    personne concernée, et « sa réplique n'est pas ce qu'on lui a appris ») ; ce qu'elle dit d'elle seule reste une
    note sur elle.

19. *Ce qui n'appartient qu'à eux lui est dit en « tu ».* « LE TON ENTRE VOUS » montrait sa note telle quelle (« Sam
    m'appelle « Mikachu » ») au milieu d'un état écrit à la deuxième personne ; nemotron a répondu à la place de Sam
    (« non, je l'ai pas encore pris… merci Mikachu ! »). La note est rendue « Sam t'appelle « Mikachu » »
    (`social.sections.to_you`).

20. *Une envie qui finit toujours en silence ne revient pas toutes les dix minutes.* Après une abstention (ou une
    panne), une initiative n'avait qu'une courte hésitation (dix minutes) ; une envie forte vers une amie dont
    chaque essai finissait en silence revenait donc sans cesse (audit du lot L2 : quatre cents essais par jour, tous
    en abstention — avec un vrai modèle, autant d'appels payés). Envers la même personne, chaque hésitation
    d'affilée dure le double de la précédente (veto `agency.HESITATING`, jusqu'à `hesitation_max_us`, six heures),
    et tout repart quand elle a fini par lui écrire. La tranche `agency` passe en version 3.

21. *Une installation existante se rejoue au même état.* Les réducteurs d'`affect` lisent la proximité, dont la
    règle a changé (ADR 0058) : sur la copie d'une année simulée, « instantané + queue » ne redonnait plus la tranche
    de la genèse. `affect` passe en version 4 (reconstruite depuis le journal) ; vérifié sur la copie (aucune
    tranche différente).

22. *Une table reconstruite ne fait pas revenir qui a été oublié.* La table du fil a changé de version (ADR 0056) et se
    reconstruit depuis le journal : les messages d'une personne oubliée y revenaient, texte vide mais noms des
    pièces jointes visibles. Un texte dont le contenu a été effacé ne se recopie plus (`transcript._row`), comme
    pour la mémoire (ADR 0059).

23. *L'oubli atteint aussi ce qu'un renfort a rattaché.* Un souvenir renforcé par une seconde conversation est
    rattaché à de nouvelles personnes sans que son texte (déclaré à sa naissance) les nomme : oublier l'une d'elles
    retirait la ligne de la mémoire mais laissait le texte, qu'une reconstruction faisait revenir, rattaché à elle
    (audit du lot L2). La table des souvenirs garde la référence du texte de chaque élément (`memory_refs`, version 5)
    ; le crochet d'oubli d'une projection peut rendre des références à effacer, et le magasin les efface dans la même
    transaction (`ports.store.forget_subject`). L'ADR 0024 (« tout texte gardé dit qui il concerne : l'oubli
    l'atteint ») tient donc aussi pour ce qui a été rattaché après coup.

24. *Le moment qu'on lui désigne se cite, même s'il est dans le fil.* Dimanche, « tu te souviens de ce que je t'ai dit
    lundi matin ? » : toute la semaine était encore dans le fil montré (soixante-sept messages), donc « VOS ÉCHANGES
    PASSÉS » n'en reprenait rien, et le modèle lui a prêté son propre rêve. Le code sait quel moment la question
    désigne (`window_of`) : ces échanges-là se citent à son nom, même déjà dans le fil (`Exchange.dated`). Les autres
    restent écartés quand le fil les montre déjà.

25. *Sa journée dit ce qu'elle a fait dans sa chambre.* Le monde tient ses occupations (`world.lived`, ADR 0050) :
    dessiner à son bureau, lire, jouer un morceau. Ce qu'elle raconte de sa journée (ADR 0053) et les notes de son
    journal intime les disent, avec le moment de la journée (`self.night.room_doings`) : de quoi répondre « tu as
    fait quoi aujourd'hui ? » sans qu'un modèle comble avec un stream qu'elle n'a jamais fait. Une occupation de
    quelques instants (regarder dehors une minute) ne se raconte pas (`ROOM_DOING_MIN_US`, cinq minutes).

**Ce que la sonde a montré et qui reste au modèle.** Nemotron répond encore « non, je dormais pas » à un « tu
dors ? » lu au réveil alors que son état le lui dit en toutes lettres ; il devine des accords (« content de te voir
arrivé ») ; il confond parfois sa persona et la personne (« un café, même si tu n'en bois pas »).

**Conséquences.** Aucun événement nouveau, aucune tranche changée ; le journal se rejoue. Cibles :
`test_sonde.py` (la seconde semaine va au bout), `test_social_bonds.py` (qui s'occupe d'elle, pas une amie),
`test_persona.py` (un premier bonjour simple ; jamais la phrase d'exemple, ses petits mots), `test_habits.py` (la
question qu'elle vient de poser), `test_memory_privacy.py` (dans un salon, elle sait qu'elle sait ; un secret,
rien), `test_others.py` (« salut Mikachu » ; trois réponses d'un mot), `test_tool_gates.py` (un fournisseur qui ne diffère pas), `test_goals.py` (une séance qui conclut : un appel), `test_scheduler_clock.py` (une année de virtuel), `test_memory_recall.py` (lundi matin cité même encore dans le fil), `test_night.py` (un après-midi à dessiner se raconte) — chacune
rouge sans sa correction.
