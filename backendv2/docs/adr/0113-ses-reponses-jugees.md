# 0113 — Ses réponses jugées par sa propriétaire, depuis le chat

**Contexte.** Le banc de conversation (ADR 0112) mesure sa voix avec un juge, Opus. Son étalon, ce sont une dizaine de
réponses que la propriétaire a trouvées pas naturelles, recopiées à la main de ses captures d'écran. Le 2026-10-15,
elle propose de les donner au fil de l'eau : dans ses vrais chats, dire si une réponse est adaptée ou non, et écrire
ce qu'elle aurait dû dire. « Je ne sais pas trop ce qu'on pourra en faire, mais ce seront des exemples concrets. »

**Décision.**

1. *Un avis sur une de ses réponses* (`transcript.judged`, propriétaire `transcript`) : le message jugé (son `seq`),
   l'avis (`ok` adaptée, `ko` pas adaptée, vide : retiré), un commentaire facultatif (un `Content`, 2 000 caractères
   au plus : ce qu'elle aurait dû dire, ou pourquoi), qui juge et à qui elle répondait.
   - Le dernier avis vaut.
   - **Ce n'est pas quelque chose qu'elle vit** : l'événement n'est pas public, aucune autre faculté ne le lit. Il ne
     touche ni son humeur, ni sa mémoire, ni son estime.
   - Le commentaire déclare ses sujets (la personne, l'opératrice) : l'oubli de la personne l'emporte. Une
     reconstruction du fil ne le fait pas revenir.
2. *Le chemin des actions de la console.* L'avis est l'action `transcript.juger` (validée, auditée par
   `runtime.operated`), la même depuis le chat et depuis la console. Elle refuse ce qui n'est pas une de ses
   réponses.
3. *Gardé à côté du message.* La projection du fil (version 7) gagne `verdict` et `verdict_note`.
4. *Dans le chat, pour l'opératrice seulement.*
   - La trame client `verdict` (`message_id`, `verdict`, `comment`) ; réponse `verdict_result`.
   - Une connexion qui n'est pas d'opératrice ne peut pas juger (`forbidden`).
   - L'historique ne porte `verdict` et `verdict_note` qu'aux connexions d'opératrice : la personne à qui elle
     répondait ne voit jamais ce qu'on a pensé de sa réponse.
   - Sous chacune de ses réponses, 👍 et 👎 ; un champ facultatif pour dire ce qu'elle aurait dû dire.
5. *Dans la console.* La page « Pourquoi a-t-elle dit ça ? » montre l'avis (« Ton avis ») à côté du prompt entier qui
   a écrit la réponse ; la vue Fil › « Ses réponses jugées » les liste (ce qu'on lui avait écrit, sa réponse, l'avis,
   ce qu'elle aurait dû dire), filtrables par avis.

**Conséquences.**

- Chaque avis est un exemple réel : la réponse, l'appel qui l'a écrite (son prompt, tant que la trace vit), ce
  qu'elle aurait dû dire. Ce que l'on en fera reste ouvert : l'étalon du juge du banc, les exemples de sa voix, des
  cas de test, un jour un petit modèle réentraîné.
- Rien de son comportement ne change : l'avis n'est lu par aucune faculté.
- Un avis donné depuis un autre appareil n'apparaît sur une bulle déjà affichée qu'au prochain fil initial (les
  clients ne retouchent pas une ligne qu'ils ont déjà).
