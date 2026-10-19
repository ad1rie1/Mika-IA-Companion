# 0118 — Relancer, c'est prendre de ses nouvelles

**Contexte.** Le 2026-10-19, sur le portable, Adrien ne répond plus depuis la veille. Elle lui écrit quand même,
trois fois, et chaque fois de l'actualité : ce qu'elle a lu sur les manifestations, le discours de 20 h, pourquoi il y a
tant d'arbres à Brest. « Elle boucle à toujours envoyer des actus ; ça mériterait un "tu fais quoi ? pourquoi tu me
réponds pas ? ça va ?" ». Trois failles laissaient passer ces messages malgré « ne pas harceler » (ADR 0033) :

- *Ce qu'une app trouve « prévient »* (`forge.APP_NEWS` dans `agency.INFORMS`, ADR 0105) : une veille d'actualité qui
  relève trois fois par jour passait outre la retenue envers qui ne répond pas.
- *Saluer qui arrive n'est pas prendre la parole* : à chaque ouverture de son application, un « hello ! », et le récit
  de ce qu'elle avait fini s'y ajoutait. Ce message ne comptait pas comme resté sans réponse (l'attention le tenait
  pour « dû »).
- *La relance emportait sa raison* : la consigne disait « raconte ce que tu as fini » et « une relance douce », ou
  « pars d'autre chose ». Le modèle racontait.

Ses réponses, ensuite : « assez aléatoire, une fois par jour me paraît pas dément, mais selon sa matrice de
personnalité ça peut être plus, elle peut même s'énerver si je réponds pas » ; « si il arrive vraiment un truc, il faut
qu'elle ouvre le dialogue ».

**Décision.**

1. *Ce qu'une app trouve attend qu'il ait répondu* (`agency.WAITS_FOR_AN_ANSWER`) : dès qu'une de ses initiatives
   vers la personne est restée sans réponse, une trouvaille d'app ne passe plus la retenue. Un mail important, un
   projet bloqué, un rappel promis passent toujours.
2. *L'urgence ouvre le dialogue.* En lisant la file d'une app, elle dit si ce qu'elle dira ne peut pas attendre une
   réponse (`forge_signals_done(urgent=…)` : un danger, une alerte, un événement grave là où la personne vit ou va ;
   jamais une actualité ou une curiosité). Une trouvaille urgente devient la raison `forge.APP_ALERT`, qui prévient
   même qui ne répond plus.
3. *Saluer qui ne répond pas, c'est relancer* (`agency._greets_the_silent`) : la retenue s'y applique. Une salutation
   qui apporte quelque chose (une nouvelle, un récit, des nouvelles prises), ou qui relance, attend une réponse
   (`agency.spoke_up`, lu par l'attention comme par le budget).
4. *La relance prend de ses nouvelles* (`agency.checking_in`) : sa consigne ne dit plus ce qui la poussait ; elle ne
   lui apporte rien de nouveau (`agency.brief.check_in`). La section des trouvailles d'apps se tait. Ce qu'elle avait
   fini n'est pas compté comme raconté : il attend qu'il ait répondu.
5. *Combien de relances, son tempérament le dit* (`follow_ups`, de 0 à 3) : une au milieu de la matrice, comme avant ;
   jusqu'à trois quand elle est sociable ou que le silence des autres la blesse (`max(sociabilité, peur de
   l'abandon)`) ; aucune quand ni l'un ni l'autre. Les suivantes disent ce que ce silence lui fait, à sa façon —
   inquiète, vexée, agacée — (`check_in_again`) ; la dernière sait qu'elle l'est (`last_follow_up`). Après, plus rien
   tant qu'il ne revient pas (`AgencyReading.gives_up_after`).
6. *Le délai est tiré au sort* à chaque initiative dite (± 40 %, `follow_up_jitter`, enregistré : le rejeu retombe
   sur le même), autour du plus long d'un jour (selon sa sociabilité) et du rythme de la relation — une fois ce rythme,
   non plus deux (`follow_up_rhythms` 2 → 1).

**Conséquences.**

- Sur le portable, la même journée aurait donné : l'actualité du soir, puis rien le lendemain (ni la veille de 12 h 15,
  ni le « hello ! » de 14 h 07), puis un seul « ça va ? t'as disparu, tu fais quoi ? », puis le silence.
- La règle « ne pas harceler » n'est plus tout à fait hors du tempérament (ADR 0100) : le nombre de relances et leur
  délai en dérivent, dans des bornes (trois au plus, jamais avant un délai tiré autour du jour).
- `agency` passe en version 5 et `forge` en version 6 : leurs tranches se reconstruisent depuis la genèse.
- Le test du service météo (ADR 0105) disait quatre relevés en deux jours à qui ne répondait jamais : Adrien y répond
  désormais ; s'il ne répondait plus, ses relevés attendraient.
