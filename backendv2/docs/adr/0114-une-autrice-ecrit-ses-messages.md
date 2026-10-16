# 0114 — Une autrice écrit ses messages

**Contexte.** Le banc de conversation (ADR 0112) plafonnait. Avec Sonnet, sa voix en service, il donnait 58 sur 100 ; Opus
partout, ou une seconde passe sur Opus, donnait 64 ou 65. Réécrire une consigne déplaçait le défaut sans le retirer :
moins de questions, mais des réponses jugées « plates ». Rejouées une à une, de vraies répliques ratées montraient
que son portrait seul valait le prompt entier. Le 2026-10-16, la propriétaire montre une conversation tenue avec
Opus sur claude.ai :

- joué tour par tour, le personnage parle comme ici (de longues phrases, des questions, de l'attention à l'autre) ;
- quand on lui demande d'écrire un fil de SMS entier, des deux côtés, le même modèle écrit une conversation qu'elle
  juge parfaite : réactions, messages, sujets, une dispute.

Tour par tour, le modèle reste une assistante qui joue un rôle et s'occupe de son interlocuteur. En autrice, il fait
parler deux personnes, et aucune des deux ne joue au service.

**Décision.**

1. *La seconde passe est une autrice* (rôle `polish`, `expression.polish`). Elle reçoit :
   - sa persona telle que la conversation la rend (son portrait, sa voix, ce qui est vrai d'elle, son caractère) ;
   - les 16 derniers messages du fil, une ligne par bulle (« Mika : … », « L'autre : … ») ;
   - ce que le premier jet voulait dire (« son idée, pas forcément ses mots »).

   Elle écrit la suite du fil : les prochains messages de Mika, puis la réponse probable de l'autre. Écrire cette
   réponse la garde autrice. Seuls les messages de Mika partent, une bulle chacun (`authored`).
2. *Le premier jet reste la tête.* Son prompt, son état, sa mémoire et ses outils ne changent pas. Ses balises
   (émotion, ce qu'elle lit en face, ses mensonges) restent celles du premier jet, et l'autrice n'ajoute aucun fait.
3. *Un fil de référence* (`PersonaDoc.reference_thread`, console › Sa parole). C'est un vrai fil de SMS, tel qu'on
   voudrait qu'elle écrive. Seule l'autrice le lit, pour le registre et jamais pour les sujets. Le fil livré est
   celui que la propriétaire a choisi comme étalon (« Léa, Lisbonne ») : il montre une amie extravertie qui
   propose, tranche, charrie, se vexe et se réconcilie, en messages de quelques mots.
4. *Toutes ses réponses passent par l'autrice*, même les courtes : un « ah merde. » peut devenir deux bulles. Une
   réponse récrite qui dépasse deux fois le premier jet plus 120 caractères a dérivé : le premier jet part.
5. Le polisseur dit ce qu'on garde de ce que l'appel a écrit : le contrat `Polisher` rend
   `(consigne, message, garder)`, et reçoit la persona rendue au lieu du seul nom.

**Mesures** (banc de conversation, deux mesures par réglage, ±2 points de bruit) :

| Réglage | Score |
|---|---|
| Sonnet seul (main) | 58,3 |
| Sonnet, seconde passe Sonnet low (relecture, ADR 0112) | 62,0 |
| Sonnet, seconde passe Opus (relecture) | 64,4 |
| Opus partout, seconde passe Sonnet low | 64,2 |
| Sonnet, autrice Opus (sans fil de référence) | 63,4 |
| Une réécriture par Opus faite pour plaire au juge (plafond du juge) | 71,0 |

Le juge Opus plafonne : même des répliques réécrites exprès pour lui n'obtiennent que 71. Avec le fil de référence,
l'autrice rapproche ses messages de l'étalon :

| | Longueur moyenne | Messages de plus de 80 caractères | Avec une question |
|---|---|---|---|
| L'étalon (Léa) | 29 | 0 % | 10 % |
| Opus partout, seconde passe | 96 | 49 % | 27 % |
| Autrice Opus avec le fil de référence | 53 | 12 % | 14 % |

Jugées par la propriétaire à l'aveugle, contre l'ancien réglage, sur quatre situations (banale, dispute, histoire,
tâche) et deux caractères, ses conversations sont « quasi que des 100 ».

**Conséquences.**

- Le rôle `polish` sert désormais à écrire ses messages, plus seulement à les relire. Son meilleur modèle est Opus,
  qui ne lit que le portrait et le fil : bien moins de contexte que la voix entière, sans outils.
- Sans modèle pour `polish`, rien ne change : le premier jet part, comme avant.
- Le juge du banc n'est plus l'arbitre final : il ne distingue plus les meilleurs réglages, et l'étalon est le goût
  de la propriétaire (ses 👍/👎, ADR 0113, et ses conversations réécrites).
- À suivre : elle cède encore vite dans une dispute, propose rarement d'elle-même, et donne parfois un conseil
  en plusieurs bulles.
