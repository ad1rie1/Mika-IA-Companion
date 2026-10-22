# 0124 — Ses autrices et leurs flux

**Contexte.** La seconde passe (ADR 0112, 0114, 0115) récrit ses réponses et ses initiatives dans le chat. Sa consigne
(`expression.polish.*`) décrit un fil de SMS entre amis : des bulles courtes, des émojis, un ton parlé. Le
2026-10-22, le propriétaire demande un onglet pour « configurer les autrices », avec un tableau de partout où chacune
s'applique : une « autrice message », une « autrice mail pro », une « autrice pro Teams », parce que ce qui part
dans ces flux ne s'écrit pas pareil et n'a pas les mêmes codes. On doit pouvoir les ajouter, les modifier, et les
poser sur des flux.

Le relevé montre que seule la parole du chat passe par une autrice. Les brouillons de courrier (`email_draft`), de
Teams (`teams_draft`) et du téléphone (`phone_draft`) sont des arguments d'outil, que rien ne récrit. Chaque boîte
mail a déjà son ton et ses consignes, Teams une configuration globale. Aucune page de la console ne règle l'autrice :
seul le rôle LLM `polish` l'allume ou l'éteint.

Trois choix du propriétaire :

- sur un brouillon, l'autrice **récrit** le premier jet (une vraie seconde passe, un appel de plus), plutôt que de
  seulement guider le premier jet ;
- **un flux par canal** : le chat (réponses et initiatives), chaque boîte mail, Teams, le téléphone ;
- **le même modèle pour toutes** : le rôle `polish`.

**Décision.**

1. *Une autrice est une façon d'écrire* (`vocab/flows.py::Author`) : une clé, un nom, ses codes (une consigne écrite
   par l'opératrice : tu ou vous, les formules, la longueur, les émojis…) et, facultatif, un exemple de la forme. Le
   flux fournit le cadre, l'autrice les codes. Les flux sont `chat`, `courrier:<boîte>`, `teams` et `telephone` ; la
   forme d'un flux est son préfixe.
2. *Un flux a au plus une autrice*. Sans elle, ce qui part est le premier jet, comme sans modèle au rôle `polish`.
   Le mode pro n'en a jamais (ADR 0116).
3. *Au chat*, la seconde passe garde son cadre (le fil de SMS). Les codes de l'autrice s'y ajoutent
   (`expression.polish.codes`) et son exemple prend la place du fil de référence de la persona. Ce fil reste
   l'exemple de « Message » quand le sien est vide (et le repli d'une passe sans réglage, dans les tests).
4. *Sur un brouillon*, le gestionnaire de l'outil demande `ctx.authored(flux, texte, à propos)`
   (`runtime/tools.py::ToolContext`, posé par le pipeline ; `vocab.flows.written` pour un contexte qui ne l'a pas).
   - Le pipeline (`_author_draft`) appelle le modèle du rôle `polish`, sans outil et en un tour. La consigne vient
     de l'expression (`polish_draft`, `expression.author.*`) : le genre du flux, les codes, l'exemple, ce à quoi le
     brouillon répond (cité), puis le premier jet. Le sens, les faits, les noms et les passages à compléter restent ;
     seule la forme change.
   - Le premier jet est posé tel quel dans quatre cas : pas d'autrice, pas de modèle, une panne, ou un texte vide,
     silencieux ou qui dérive en longueur (plus de 2 fois le premier jet, plus 400 caractères).
   - La trace de l'épisode garde, passe par passe, le flux, l'autrice et le premier jet (`seen["autrice"]`). Le
     registre des appels compte `#autriceN`.
   - L'objet d'un courriel, sa signature et celle de Teams restent ajoutés à part.
5. *Le réglage* (`app/authors.py`, clé `authors` des réglages) est une liste d'autrices et « flux → autrice ».
   - `Settings` le tient en mémoire, car le pipeline le lit à chaque épisode et à chaque brouillon
     (`KernelDeps.authors`, `settings.author_for`).
   - Retirer une autrice libère ses flux. Un flux inconnu est refusé.
   - Rien d'enregistré, l'installation a quatre autrices livrées (`defaults`, leurs mots dans `voix.yaml`), chacune
     d'office sur son flux : « Message » au chat, « Mail pro » à chaque boîte, « Pro Teams » à Teams, « SMS perso »
     au téléphone. Chacune a ses codes et un exemple ; celui de « Message » est le fil de référence de sa persona
     s'il y en a un.
   - Enregistré, le réglage fait foi : un flux laissé vide part en premier jet. Mais un champ laissé vide d'une
     autrice livrée reprend son texte par défaut (`filled`, demandé le 2026-10-22 : « au cas où ils sont vides »). Une
     autrice qu'on a créée garde ses champs tels quels.
   - Chaque boîte mail est un flux : une autrice par compte (« Mail perso », « Mail pro »…).
6. *La page* : Réglages › Personnalité › Autrices (`reglages/autrices`).
   - En tête, un tableau dessiné, « Où elles écrivent » (`app/handmade/authors.py`, gabarit
     `handmade/reglages/autrices.html`) : flux par flux, qui y écrit, ce qu'elle récrit, et ce qui l'en empêcherait
     (aucun modèle au rôle « rendre naturel », Teams désactivé).
   - Puis les autrices en cartes, sous leur nom : où elles écrivent et leurs codes en bref. On les ajoute, les modifie
     et les retire comme les fournisseurs.
   - Puis « Qui écrit où », une ligne par flux. Ses clés sont connues au rendu (`SettingsSection.keys`, une par boîte
     mail), et un choix parmi les entrées se montre sous le nom de l'entrée.

**Conséquences.**

- Dès qu'un modèle sert le rôle `polish`, chaque flux a son autrice : chaque brouillon de courrier, de Teams ou du
  téléphone coûte un appel de plus. Retirer le flux d'une autrice (« Qui écrit où », vide) l'évite.
- Au chat, « Message » ajoute ses codes et son exemple au cadre de la seconde passe : sa voix en est un peu changée
  (à mesurer au banc de conversation).
- L'autrice d'un brouillon voit ce à quoi il répond (le message reçu, cité), pas sa mémoire ni son état : elle récrit
  une forme, elle ne décide rien.
- Le ton et les consignes d'une boîte (`MailAccount.tone`, `instructions`) et ceux de Teams restent ceux du premier
  jet : ils disent quoi écrire et pour qui, l'autrice dit comment.
- Le fil de référence de la persona (`reference_thread`, ADR 0114) n'est plus que le repli du chat : l'exemple de
  l'autrice du chat, qui se règle dans la console, le remplace.
