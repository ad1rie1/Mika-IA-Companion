# 0095 — Chaque cause de ce qu'elle ressent se dit

**Contexte.** Son humeur garde la cause de chaque impulsion (`Mark.cause`) pour pouvoir dire d'où elle vient (« Ça
vient d'un message resté sans réponse »). Chaque faculté écrivait sa raison en français (`reason="sans réponse"`), et
une table (`affect/prose.CAUSES`) la traduisait en phrase. Rien ne tenait la table à jour : « c'est toujours elle qui
écrit », la contagion, un lien qui s'approfondit ou se refroidit, le rêve de la nuit (et un rêve oublié), la nuit qui
a apaisé ce qui pesait, un projet refermé ou abandonné, et les pensées nées d'un remords ou d'un mensonge se taisaient
— sa tristesse devenait « sans trop savoir pourquoi » alors que la cause était connue.

**Décision.** Une cause est un code (`vocab/causes.py`) et se dit par la phrase `affect.cause.<code>` de
`persona/voix.yaml`, sans table intermédiaire. Les origines d'une pensée (`contracts.attention` : `exchange`,
`revision`, `remorse`, `lie`…) et les sources d'un signal (`email`, `rss`, `world`, `teams`, `social`, `forge:<app>`)
sont des causes sous leurs propres codes ; deux d'entre elles se disent par la phrase d'une autre (`ALIASES` :
`concern` → `worried`, `blocked` → `stuck`). `talk` (ce qu'elle a dit) reste dit selon la personne en face.

Une garde (`tests/architecture/test_causes_are_said.py`) : aucune évaluation ne porte une raison écrite à la main ;
chaque code, chaque origine de pensée, chaque source de signal (trouvée dans le code : un brouillon qui porte une
pertinence), chaque vide ressenti (`lonely`, `bored`) a sa phrase.

**Conséquences.** Nouvelles phrases sous `affect.cause` : `contagion`, `one_sided`, `bond_warming`, `bond_cooling`,
`remorse`, `lie`, `dream_forgotten`, `project_closed`, `project_abandoned`, `reflected` (ADR 0096), `teams`, `social`,
`world`. Les causes gardées dans l'état d'avant (raisons en français) disparaissent au rejeu (`affect` v5, ADR 0094).
Mutations rouges : une raison écrite à la main, une phrase retirée, un alias perdu.
