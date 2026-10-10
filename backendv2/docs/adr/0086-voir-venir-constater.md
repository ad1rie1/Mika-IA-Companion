# 0086 — Voir venir, constater

Huitième et dernier lot de la refonte du modèle de connaissances (plan du 2026-10-09 : « le futur, sur le socle »).

**Contexte.** Le lot 6 (ADR 0084) a donné au monde un futur — des dates floues, la vraisemblance, les prévisions —,
le lot 7 (ADR 0085) a fait de ses lectures un savoir. Mais rien ne gardait comment un moment avait tourné :

- « reporté » n'était qu'une date qui change, « annulé » n'existait pas ; « alors, ça s'est passé comment ? » se
  demandait pour un entretien annulé, et « bonne chance » se souhaitait pour un rendez-vous déplacé ;
- elle n'apprenait rien de qui reporte tout : une annonce d'Alice, qui avait déjà reporté trois fois, restait « c'est
  prévu » ;
- ses mots restaient aussi sûrs quand ses attentes se trompaient sans cesse ;
- rien de ce qui approche ne se faisait attendre — ni espoir, ni inquiétude —, et l'issue ne faisait rien non plus :
  ni surprise, ni déception, ni soulagement ;
- un moment qu'elle vivait à travers quelqu'un (« samedi je t'emmène au salon, je te montrerai tout ») ne devenait
  jamais un souvenir à elle ;
- un moment du monde qui lui tenait à cœur passait sans qu'elle aille voir comment il avait tourné.

Choix de l'utilisateur (2026-10-09) : elle n'a pas de corps et vit à travers ses relations, d'autant plus fort que
c'est sa propriétaire, « comme si elle y allait » ; ses émotions sont jugées, jamais devinées par des mots.

**Décision.**

1. *L'issue d'un moment* (`memory.resolved` : `happened`, `cancelled`, `moved`, `unknown`), avec ce qu'elle en
   attendait (`likelihood`), la surprise (l'écart à cette attente, pesé par ce que le moment compte :
   `likelihood.surprise`), la sorte d'annonce (`nature` : de la bouche de la personne, rapportée, officielle), qui
   l'avait faite (`teller`) et comment elle l'attendait (`valence`, d'après ce qu'elle-même puis la personne en
   ressentent, ADR 0083). `LifeEvent.outcome`, `.resolved_at` ; l'archive (`memory_life` v5) le garde ; tranché une
   fois pour toutes.
2. *Qui constate.*
   - **La personne concernée**, de ses mots à elle : la relecture voit les moments passés depuis moins de
     `resolve_days` (« Moments passés dont tu ne sais pas encore comment ils ont tourné ») et les désigne dans
     `constats` ; le code exige que les messages cités soient d'une personne que le moment concerne — ce qu'un autre
     en raconte n'est qu'une rumeur. Un moment à venir peut être annulé d'avance (« finalement mon IRM de demain est
     annulée ») — jamais « avoir eu lieu » avant sa date. Un moment passé se désigne aussi pour un report après coup
     (`remplace`).
   - **Ce qu'elle lit**, la nuit (ADR 0085) : les moments du monde à venir ou passés depuis peu sont montrés à la
     relecture avec ses lectures ; un constat n'est retenu que si la lecture parle de ce moment-là (des mots du sujet
     en commun) — « le concert est annulé » ne tranche pas l'éclipse.
   - **Personne** : passé depuis plus de `resolve_grace_days` (21) sans nouvelles, elle ne le saura pas (`unknown`,
     sans appel) — ni surprise, ni leçon.
   - **Un report** se constate quand la date change de jour (`Consolidate._moved`, écrit avant le moment à sa
     nouvelle date) ; préciser une période (« en novembre » → « le 12 ») n'en est pas un.
3. *Ce qu'elle en apprend.* De qui annonce (`MemoryState.track` : tenus, reportés ou annulés) : à partir de
   `track_min_cases` cas, ses annonces suivantes valent sa part de moments tenus, l'a priori comptant pour
   `track_weight` cas — jamais plus que l'a priori (`likelihood.learned`). De ses attentes (`MemoryState.calibration`,
   par sorte d'annonce : l'écart quadratique moyen, le score de Brier) : passé `calibration_cautious` sur au moins
   `calibration_min` moments, « CE QUI VIENT » parle un cran plus prudemment (« c'est sûr » → « c'est prévu »). Le
   chiffre ne se dit jamais.
4. *Ce que l'issue lui fait* (appréciation de `memory.resolved`) : la surprise (`SURPRISED`, cause « tournure »)
   au-delà de `surprise_from` ; un espoir déçu attriste (`SAD`, « attente déçue »), une crainte levée soulage
   (`RELIEVED`, « crainte levée »), une attente comblée réjouit un peu (« attente comblée ») ; ne pas savoir ne fait
   rien.
5. *Ce qu'elle attend* (`attention`, `faculties/attention/anticipation.py`) : le fait `memory.upcoming` (tout moment
   daté, pas tranché, d'ici `upcoming_days`) ; le poids d'un moment = ce qu'il compte × ce que la personne lui est
   (sa propriétaire, une proche, une amie ; du monde, s'il l'attend avec un sentiment ; une connaissance ne se fait pas
   attendre) × sa vraisemblance × sa proximité (une rampe sur `anticipation_ramp_us`). Un seul domine
   (`attention.anticipation`), ressenti une fois par jour, éveillée (`attention.anticipated`) : de l'espoir
   (« impatience ») ou, quand ce qu'on en ressent est sombre, de l'inquiétude (« appréhension »), au plus
   `anticipation_max`.
6. *Vécu à travers quelqu'un* : un moment partagé que la personne dit avoir eu lieu devient un souvenir à elle (« J'ai
   vécu à travers Alice : le salon du jeu vidéo »), de `lived_importance`, ou `lived_owner_importance` avec sa
   propriétaire. Son journal le reprend comme tout souvenir du jour.
7. *Vérifier ce qui lui tient à cœur* (`memory.to_check` → `goals`) : un moment du monde passé depuis moins de
   `check_days`, sans issue, important (`check_importance`) ou attendu avec un sentiment, peut ouvrir une exploration
   « Voir comment ça a tourné » (avec de quoi lire ses flux, `check_steps` séances) — au plus `checks_per_week` sur sept
   jours glissants, une fois par moment. Ce qu'elle y lit, la nuit le constate.
8. *Ce qui est tranché ne se redemande pas* : « CE QUI VIENT » oublie un moment annulé ou reporté ; la vie de la
   personne le dit (« — finalement annulé », « — finalement reporté », « — ça a bien eu lieu ») ; ni « bonne chance »
   ni « alors, comment ça s'est passé ? » pour ce qui n'a pas eu lieu (`others`) ; un moment annulé ou reporté retire
   ce qui en dérivait (`contracts.memory.withdrawals`, `ended`).

**Sonde réelle (2026-10-10, Haiku par la CLI Claude Code, scratchpad `sonde8/`).** Le soir, Alice annonce une IRM
pour le lendemain (« je flippe un peu »), un concert de jazz le soir même (« je te raconterai tout »), un cours de
théâtre le surlendemain. Les trois moments sont notés (l'IRM vécue avec peur, le concert partagé) et l'IRM se fait
attendre — de l'**inquiétude**, seule dominante. Après le concert, Alice raconte (« c'était génial ») et dit le théâtre
annulé : en un appel, le concert est **constaté** par elle et devient un souvenir de Mika (« J'ai vécu à travers
Alice : … »), le théâtre est **annulé d'avance** (surprise, attente déçue — Alice l'attendait avec impatience) ;
l'humeur en garde la cause. Rien de tranché n'est redemandé. La sonde a montré, et on a corrigé avec cible :
- la relecture de cette conversation dépassait ses 2 500 jetons de sortie (des éléments plus riches qu'au début du
  chantier, et la réflexion du modèle qui compte dans ce plafond par la CLI) : 6 000 (`extraction.MAX_OUTPUT_TOKENS`,
  pour la relecture et la relecture de nuit) ; et la CLI rendait ce dépassement comme une **panne**, réessayée à
  l'identique toutes les dix minutes — c'est désormais une réponse tronquée (`stop="max_tokens"`), comme chez les
  autres fournisseurs, que la consolidation diffère et redécoupe (`claude_code.OUTPUT_CAPPED`) ;
- « tu le vivras à travers Alice » se disait d'un concert passé : passé, « tu l'as vécu à travers Alice »
  (`memory.ahead.shared_past`) ;
- la cause « attente déçue » attribuait à Mika l'impatience d'Alice : « un moment attendu avec joie ».

**Ce qui n'est pas fait.** Comment un moment s'est *passé* (bien, mal) reste ce que la relecture retient en souvenir,
pas une issue. Une prévision (une croyance, ADR 0084) ne se constate pas encore ; seuls les moments apprennent. La
calibration se lit dans l'état, pas encore dans une page de la console. Une vérification ne lit que ses flux (pas le
web, faute d'un lot de recherche pris par l'exploration). Un moment annuel (un anniversaire) ne se tranche pas.

**Conséquences.** Événements publics nouveaux : `memory.resolved`, `attention.anticipated` (libellés dans la console,
processus `attention.anticipate`). Faits nouveaux : `memory.upcoming`, `memory.to_check`, `attention.anticipation`.
`LifeEvent` + `outcome`, `resolved_at` ; `memory_life` v5 ; la tranche `memory` en `state_version` 16 (`track`,
`calibration`), `attention` en 13 (`anticipated`). Relecture : `constats` (`XConstat`), bloc « Moments passés… » ; un
moment passé n'est plus parmi les « Moments à venir ». Relecture de nuit : `constats` (`XConstatLu`), bloc « Moments du
monde… », expiration sans appel. Réglages nouveaux : `memory.resolve_days`, `.resolve_grace_days`, `.track_min_cases`,
`.track_weight`, `.surprise_from`, `.surprise_max`, `.disappointment_max`, `.calibration_min`, `.calibration_cautious`,
`.lived_importance`, `.lived_owner_importance`, `.upcoming_days`, `.check_days`, `.check_importance` (groupe « Voir
venir, constater ») ; `attention.anticipation_*` (« Ce qu'elle attend ») ; `goals.checks_per_week`, `.check_steps`.
Causes d'humeur : `tournure`, `attente déçue`, `crainte levée`, `impatience`, `appréhension`. Cibles d'intention
(`tests/unit/test_seeing_ahead.py`, 12, et `tests/contract/test_claude_code.py` pour la sortie tronquée),
chacune rendue rouge en cassant exprès sa correction (33 mutations) : ses
mots constatent son moment (d'avance s'il est annulé), pas ceux d'un autre ; sans nouvelles, on ne sait pas (ni surprise ni leçon, tranché une
fois) ; la surprise est l'écart à l'attente ; les reports rendent la prochaine annonce moins sûre (et préciser une
période n'en est pas un) ; un moment partagé vécu devient son souvenir, plus marquant avec sa propriétaire ; une seule
attente domine, d'autant plus forte que le moment est proche et la personne chère, inquiète quand c'est sombre ; un
espoir déçu attriste, une crainte levée soulage ; un moment du monde constaté par une lecture qui en parle ; elle ne
vérifie que ce qui lui tient à cœur, deux fois par semaine ; ses mots se font prudents quand ses attentes se trompent ;
ce qui est tranché ne se redemande pas ; un moment partagé passé se dit au passé ; un dépassement du plafond de
sortie de la CLI est une réponse tronquée, pas une panne.
