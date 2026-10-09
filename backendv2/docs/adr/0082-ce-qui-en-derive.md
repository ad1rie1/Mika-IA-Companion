# 0082 — Ce qui en dérive

Cinquième lot de la refonte du modèle de connaissances (« elle ferait aussi dépendre chaque texte dérivé — portrait,
résumé — de ses sources », ADR 0074). Il clôt le socle (ADR 0078 à 0082).

**Contexte.** L'ADR 0078 a donné à un rêve, une pensée, un journal la filiation de leurs sources **à leur
naissance**. Mais ce qu'elle sait bouge ensuite : un élément devient secret (« garde-le pour toi », dit après coup),
est remplacé, contesté, joint à un autre. Rien ne le disait aux textes qui en dérivaient :

- le portrait de Sam disait encore ce que Sam venait de demander de taire, et se réécrivait en recopiant l'ancien
  (le modèle reçoit le portrait précédent) ;
- son récit d'elle-même, montré partout, gardait ce qu'un souvenir devenu secret y avait mis ;
- une pensée, un rêve, la version intime d'un journal nés d'un élément devenu secret se disaient encore ;
- le résumé d'un long fil de salon (le repli de `transcript`) gardait un secret dit dans le salon, au-delà de la
  fenêtre de l'historique — la règle « jamais dans un salon » du rappel était contournée — et ne nommait que le salon :
  l'oubli d'un participant ne l'effaçait pas.

**Décision.**

1. *Ce qui se retire, défini une fois* (`contracts.memory.withdrawals`, `WITHDRAWING`) : d'un événement de la mémoire,
   ce qu'il retire — un élément devenu secret (`attested`/`reinforced` secret), remplacé (`replaces`, une récidive),
   contesté, joint à un autre (la nuit), une situation finie. Les facultés qui gardent un texte dérivé réduisent ces
   événements et appellent cette fonction : **aucun événement de plus**, aucune émission à ne pas oublier, et le
   journal d'avant se rejoue avec (le plan prévoyait un événement `memory.withdrawn` ; une fonction pure du contrat
   dit la même chose sans pouvoir manquer).
2. *Un secret fait taire ce qui en dérive, tout de suite* (`PRIVATE_REASONS`) : la pensée s'oublie (`attention`) ; le
   rêve ne se raconte plus et le journal ne montre plus que sa version partageable (`self`, `masked`) ; le récit et le
   portrait se taisent jusqu'à leur réécriture (`narrative_masked`, `Profile.masked` : ni la section, ni l'outil, ni
   le panneau de l'application, ni les centres d'intérêt qui font penser à une amie).
3. *Un changement fait réécrire, sans recopier* : remplacé, contesté (ou devenu secret), un souvenir repris par le
   récit ou un élément repris par le portrait le rend périmé (`stale`) — il se réécrit au plus tôt après
   `self.narrative_stale_after_us` (une heure) ou `social.profile_stale_after_us` (dix minutes), sans attendre du
   nouveau, et **sans recevoir le texte d'avant**. Joint à la même croyance, ou une situation finie, rien ne change.
   Pour cela le récit et le portrait gardent leurs sources (`self.narrated.sources`, `social.profile_revised.sources`).
   Un rêve, une journée écrite restent ce qu'ils étaient (c'est leur histoire) — seulement tus devant un secret.
4. *Les résumés de salon* (`transcript`, `state_version` 2) : un résumé dit qui parlait dans ce qu'il replie
   (`Compacted.speakers`, sujets de l'oubli) ; l'oubli d'un participant l'efface, et un résumé de salon d'avant (qui ne
   le dit pas) s'efface à tout oubli, dans le doute. Un message de salon d'où vient un secret (lu par la porte de la
   mémoire) est tu dans ce qu'on donne à résumer (`withheld`) ; un secret déclaré après coup sur un message déjà
   résumé fait refaire le résumé (`transcript.summary_reset`), le secret tu.

**Ce qui n'est pas fait.**

- Un portrait se tait en entier quand un élément repris devient secret (il ne cite pas ligne par ligne ses sources) :
  il se réécrit dix minutes plus tard au plus tôt.
- Ce que l'atelier d'une réflexion a produit (`goals`, le résultat d'un pas) ne garde pas la filiation de ce qu'il a
  relu : l'oubli d'un tiers dont la réflexion reprenait un fait ne l'atteint pas.
- Hors de la mémoire, le verdict ne relève pas la sensibilité de ce qui touche un sujet délicat d'un portrait
  (ADR 0078) ; la boucle portrait → sujets délicats → rappel reste (elle ne fait que restreindre).

**Conséquences.** Un événement nouveau, `transcript.summary_reset` (libellé). Champs ajoutés, avec défaut :
`self.narrated.sources`, `social.profile_revised.sources`, `transcript.compacted.speakers`, `.withheld` ; les lectures
`DreamReading`, `JournalReading` gagnent `masked`. `attention` passe en `state_version` 12, `self` en 7, `social` en
12, `transcript` en 2 (toutes reconstruites depuis la genèse). Réglages nouveaux : `self.narrative_stale_after_us`,
`social.profile_stale_after_us`. Cibles d'intention (`tests/unit/test_derived_texts.py`, 9), chacune rendue rouge en
cassant exprès sa correction : ce qui se retire, d'après chaque événement ; une pensée née d'un élément devenu secret
s'oublie (remplacé, elle reste) ; un rêve et un journal se taisent ; le récit se tait et se réécrit (joint, rien) ; le
portrait se tait tout de suite ; remplacé, l'ancien portrait ne se redonne pas ; l'oubli d'un participant efface le
résumé du salon (un résumé d'avant aussi) ; un secret dit dans un salon n'entre pas dans son résumé.
