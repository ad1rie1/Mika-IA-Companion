# 0088 — Ce qu'elle sait d'elle

Deuxième lot du chantier « qui elle devient » (plan du 2026-10-10).

**Contexte.** Ce qu'elle réussit et ce qu'elle rate ne laissait de trace que dans son estime : un chiffre qui revient
vers 0,5 en trois jours, qui se ressent sans se savoir. Elle ne savait pas qu'elle tient parole, ni qu'elle bloque
souvent sur ce qu'elle entreprend, ni que ce qu'elle voit venir tombe juste — alors que tout y était : les promesses
tenues ou échues (`memory.promise_resolved`), en retard (`attention.expectation_missed`), les buts menés au bout ou
bloqués (`goals.closed`, `projects.objective_closed`), et depuis l'ADR 0086 comment les moments ont tourné au regard
de ce qu'elle en attendait (`memory.resolved`). Ses changements d'avis sur elle-même (ADR 0087) ne lui étaient pas
rappelés non plus.

Choix de l'utilisateur (2026-10-10) : réussites et ratés dans son image d'elle-même, **estime inchangée** — une
promesse tenue ne la gonfle toujours pas (ADR 0046).

**Décision.**

1. *Des marques* (`records.Mark` : quand, domaine, issue, valeur, référence), gardées dans l'état (`SelfState.record`,
   au plus 400, pas plus de 90 jours), par des réducteurs purs (`faculties/self/model.py`) :
   - **tenir parole** : tenue (`HONORED`) ; laissée filer — échue sans être tenue (`EXPIRED_BY`), ou en retard
     (l'attente `PROMISE` manquée) ; une promesse en retard puis tenue ne compte qu'une fois, comme filée ; une
     promesse à laquelle la personne renonce, ou qu'un rappel programmé porte, n'est ni l'un ni l'autre ;
   - **mener au bout** : un but abouti ou bloqué — ni un rappel dit, ni une rêverie, ni un abandon (renoncer n'est pas
     un échec) ; un objectif de projet seulement dans son mode à elle ;
   - **voir venir** : l'écart au carré entre ce qu'elle attendait et ce qui est arrivé — ni une date officielle, ni
     ce qu'elle n'a jamais su, ni un moment sans attente.
2. *Ce qu'elle en sait* (le fait `self.knows`, `model.knows`, pur) : des codes de tendance — `promises_kept` (assez
   de tenues, aucune filée : une seule échue l'efface), `promises_slip` (assez de filées, plus que de tenues),
   `finishing_done` (assez d'aboutis, au plus moitié de blocages), `finishing_struggle` (assez de blocages, plus que
   d'aboutis), `foresight_right` / `foresight_off` (sur assez de moments, l'écart moyen — un score de Brier — sous ou
   au-dessus d'un seuil). Les fenêtres et seuils sont des réglages (groupe « Ce qu'elle sait d'elle »).
3. *Son prompt le lui dit* (section `self_model`, « CE QUE TU SAIS DE TOI », conversation) : ses tendances en mots
   (`self.knows.*`) — jamais un nombre, et « des tendances, pas des règles » — et, au plus un, son changement d'avis
   récent sur elle-même (`memory_self_changes`, pendant `change_shown_us`), l'avant et le maintenant, devant qui
   leurs sources permettent de l'entendre : une note qu'elle a demandé de taire ne s'y dit jamais.
4. *La console* : une page « Qui elle devient » (section vie) — ses marques, les seuils, ce que son prompt en dit ;
   ses changements d'avis ; ce qu'elle a dit d'elle qui la définit (goûts, avis, faits de sa vie durables).
5. *L'estime n'en bouge pas* : aucun réducteur de l'estime ne lit ces marques.

**Conséquences.** `SelfState` en version 8 (`record`). Fait nouveau : `self.knows` (codes dans `contracts/self_.py`).
Section nouvelle : `self_model` (libellée dans la console), entre l'estime et ses absences. Phrases nouvelles :
`self.knows.*`. Réglages nouveaux : `self.know_window_us`, `.know_kept_from`, `.know_slipped_from`,
`.know_done_from`, `.know_stuck_from`, `.foresight_window_us`, `.foresight_min`, `.foresight_right_below`,
`.foresight_off_above`, `.change_shown_us`. Vue de console : `self/devenir`. Cibles d'intention
(`tests/unit/test_self_knowledge.py`, 8), chacune rendue rouge en cassant exprès sa correction (11 mutations) :
trois promesses tenues font « tu tiens parole », une échue l'efface ; en retard puis tenue ne compte pas ; ni une
renonciation ni un rappel ; ses buts menés au bout, pas ses rêveries, ni un objectif impersonnel ; voir venir se
juge sur assez de moments, jamais une date officielle ni l'inconnu ; la fenêtre glisse et les vieilles marques
s'en vont ; jamais un nombre, un changement d'avis secret jamais dit, un vieux changement plus présent ; trois
promesses tenues laissent l'estime à 0,5 ; la console montre marques, seuils et ce que dit son prompt.
