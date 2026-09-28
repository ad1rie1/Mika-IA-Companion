# Audit du contrat d’autonomie et de continuité personnelle de Mika

> **État historique avant corrections.** La mise en œuvre autorisée ensuite est décrite dans [autonomie-implementation-2026-09-20.md](autonomie-implementation-2026-09-20.md). Les sondes ci-dessous caractérisent la révision initiale ; les assertions des comportements corrigés sont dans `backend/tests/test_autonomie_contrat.py`.

Audit du 20 septembre 2026, sur la révision `429dc3e` et l’arbre de travail initialement propre.

**Verdict : les fondations vont dans la bonne direction, mais le contrat n’est que partiellement respecté.** Mika possède une véritable activité hors conversation. En revanche, la protection des projets confiés, la continuité des relations et la distinction entre une action racontée et une action réalisée présentent des écarts concrets. Son autonomie reste fragmentée entre plusieurs mécanismes qui n’ont pas la même définition d’une intention, d’une réussite ou d’une limite.

Je conserverais les briques principales. Je changerais en priorité la manière dont elles décident, exécutent et apprennent des conséquences.

## Contrat retenu et méthode

Le contrat audité vient de la demande : Mika peut avoir ses propres envies, activités, relations, humeurs, souvenirs et erreurs ; continuer à vivre sans chat ; consulter des ressources ; contacter des personnes ; construire et entretenir ses plugins. Les projets confiés par l’utilisateur possèdent un cadre qu’elle ne peut pas modifier unilatéralement.

« Réaliste » signifie ici une continuité observable : ses expériences influencent ses choix futurs, elle différencie les personnes, ses erreurs ont des causes et des conséquences, et elle peut reprendre ce qu’elle a entrepris. Le code seul ne permet pas de conclure à une expérience subjective ni de mesurer la qualité ressentie de conversations prolongées.

Lecture des chaînes traversantes : démarrage et boucles, conscience, choix de conduite, chantiers, projets, outils, Forge, identité, mémoire, pulsions, émotions et sommeil. `CLAUDE.md` et les anciens audits ont servi de carte ; leurs déclarations ont été confrontées aux implémentations actuelles. Ce rapport n’est pas un examen exhaustif de chaque vue et de chaque fournisseur IA.

Les valeurs chiffrées ci-dessous sont les **défauts du dépôt**, parfois réglables dans l’administration. La configuration réelle de l’installation et les réponses de modèles en production n’ont pas été évaluées.

Vérifications exécutées :

- **34 fichiers de tests existants : 1 231 réussites, 1 échec, soit 1 232 tests.**
- **14 sondes complémentaires : 14 réussites.** Treize caractérisent des écarts ou limites, une explique l’échec d’affichage. Ces sondes réussissent lorsque le comportement décrit existe ; elles ne définissent pas le comportement souhaité.
- Sondes sur base Django de test et fichiers temporaires ; réponses IA et envois simulés. Aucun message réel envoyé pour l’audit.
- Aucun changement du fonctionnement du backend. Les seuls livrables ajoutés sont ce rapport et les sondes.

Les sondes sont conservées dans [audit_contrat_autonomie_probes.py](audit_contrat_autonomie_probes.py). Elles forcent certains résultats pour vérifier ce que le backend accepte : elles démontrent une possibilité structurelle, pas la fréquence à laquelle un modèle la produira.

## Ce qui respecte déjà bien l’intention

| Attente | Ce qui existe réellement | Appréciation |
|---|---|---|
| Exister sans message entrant | Boucle `ConscienceEngine`, pulsions croissant avec le temps, observations, choix ouvrir/poursuivre/parler/se taire | Autonomie réelle, quoique limitée par l’arbitrage décrit plus bas |
| Avoir quelque chose en cours | `Travail` persistant, pas successifs, attente avec échéance et personne attendue, reprise après redémarrage | Bonne base de continuité |
| Se souvenir des personnes | Entités, identités et handles, souvenirs, connaissances, profils relationnels, engagements | Architecture riche ; l’affect ne suit pas encore entièrement cette identité canonique |
| Avoir une humeur qui dure | État PAD, inertie, humeur globale, ancrages relationnels, rythme circadien, fatigue et sommeil | Ce n’est pas un simple adjectif ajouté au prompt |
| Être affectée par sa propre activité | Fierté, frustration, estime de soi, ruminations, digestion nocturne | Présent ; certaines causes sont cependant trop mécaniques ou mal attestées |
| Divulguer selon la relation | Sensibilité des souvenirs et connaissances, proximité, chaleur relationnelle, contexte public/privé, tags au modèle | Le contrat autorise déjà une divulgation graduée, y compris des confidences dans certains contextes |
| Construire ses plugins | Écriture de code, validation, versions, rechargement, journaux, tests de handlers, disjoncteur, stockage et HTTP de la Forge | Capacité opérationnelle ; sa mobilisation spontanée reste incomplète |
| Survivre aux interruptions | Persistance, reprise, quotas, compteurs de dégradation, arrêt supervisé | À conserver ; cela rend une vie autonome durablement exploitable |

Sources principales : `conscience/engine.py`, `conscience/travaux.py`, `conscience/models.py`, `memory/models.py`, `emotion/engine.py`, `emotion/persistence.py`, `memory/sleep.py`, `identity/divulgation.py`, `modules/plugins/forge/`, `config/asgi.py` — tous sous `backend/`.

## Écarts prioritaires

### C01 — Le cadre d’un projet confié reste modifiable par Mika

**Priorité haute · reproduit.**

`ProjectToolsModule._tool_update_project` charge le projet par son identifiant et modifie son statut, son ton, sa priorité et sa règle de planification. Il ne vérifie ni `origin`, ni une autorisation de modification du cadre. Un projet `origin="user"` peut être abandonné, perdre sa planification et changer de ton par cet outil.

La sonde crée un projet confié, formel, prioritaire et récurrent ; l’appel du handler le transforme en projet abandonné, familier, peu prioritaire et sans récurrence. Les instructions et la liste des interdits ne sont pas éditables par ce handler : le constat porte précisément sur les champs qu’il expose.

**À changer :** séparer le contrat versionné du projet de son état d’exécution. Le modèle peut proposer une révision, déclarer un blocage et modifier son plan de travail ; seul un acte autorisé de l’utilisateur change le contrat confié. Vérifier cette règle au point d’écriture, quelle que soit l’entrée utilisée.

Références : `backend/projects/tools.py:483`, `backend/projects/models.py:33`.

### C02 — Le périmètre de l’atelier ne borne pas les programmes exécutés

**Priorité haute · reproduit sur un fichier témoin temporaire.**

Les outils de lecture et d’écriture contrôlent bien les chemins. `project_run`, en revanche, lance notamment Python avec les droits du processus serveur. `cwd=atelier` et un `HOME` reconstruit ne limitent pas les accès aux fichiers. La documentation du module reconnaît explicitement cette limite.

La sonde lance un petit programme depuis l’atelier : il écrit avec succès un fichier témoin dans le dossier parent. Aucun fichier personnel ni fichier du backend n’a été utilisé pour cette vérification. L’isolation réseau est elle aussi opportuniste : si `unshare` échoue, l’exécution continue avec une note.

Ce point compte directement pour le contrat : les bornes affichées comme strictes dans le prompt ne constituent pas une frontière d’exécution. Une maladresse dans son propre code peut toucher autre chose que son travail.

**À changer :** exécuter les programmes dans un processus réellement isolé, avec l’atelier monté en écriture, les références autorisées en lecture et un accès réseau conforme au projet. L’absence de cette isolation doit rendre cette capacité indisponible, sans empêcher les activités qui n’en ont pas besoin.

Références : `backend/projects/workspace.py:67`, `backend/projects/execution.py:175`, `backend/projects/toolkit.py`, `backend/projects/context_builder.py:172`.

### C03 — Un projet personnel s’arrête aussi après dix avances sans humain

**Priorité haute · reproduit.**

`_list_due` exclut tout projet ayant atteint `runs_since_user_input >= 10`, y compris `origin="self"`. Le compteur ne représente pas une absence de progrès : `_bump_next_run` l’incrémente aussi après plusieurs chemins d’échec. Le rétablissement normal dépend d’une intervention humaine.

La sonde vérifie qu’un projet personnel actif, dû et à dix avances est exclu ; il redevient éligible après `notify_user_input`. Augmenter la limite retarde l’arrêt sans résoudre la dépendance. Le statut peut rester `active` pendant cette suspension.

**À changer :** piloter l’autonomie par les budgets, le progrès observé, les répétitions et les blocages. Un projet personnel qui avance utilement doit pouvoir continuer sans validation périodique d’une présence humaine. Un arrêt doit porter sa cause, une condition de reprise et un état lisible.

Références : `backend/projects/runner.py:151`, `backend/projects/runner.py:681`, `backend/projects/config_schema.py:109`, `backend/projects/apps.py:36`.

### C04 — Le runner de projets ne sait pas employer les modules déclarés

**Priorité haute · reproduit pour la trousse, confirmé à la lecture pour les autres chemins.**

Le runner construit toujours les outils locaux `project_*`. Il n’ajoute pas les outils de `allowed_modules`. Un projet de gestion d’emails autorisant `email` ne reçoit donc aucun outil email.

Avec `requires_approval=True`, il peut proposer une action ; l’exécuteur d’approbation sait essentiellement envoyer un email. Avec `False`, il n’a ni les outils du module ni une voie automatique de traitement de la proposition : celle-ci est journalisée comme non traitée. Les ressources extérieures sont annoncées dans le prompt, mais les outils de lecture de l’atelier refusent les chemins extérieurs ; il manque un accès de référence correctement borné.

À l’autre entrée, en conversation, le projet détecté ajoute un bloc de prompt, tandis que `_outils_de_la_conversation` sélectionne les outils à partir de la configuration globale, sans recevoir le contrat du projet. Le périmètre n’a donc pas une application commune entre les deux modes.

**À changer :** une même couche d’exécution doit recevoir le contrat actif et construire les capacités autorisées, en conversation comme en tâche de fond. Une action autorisée peut être exécutée ; une action nécessitant un accord est mise en attente. L’accès aux fichiers de référence doit être un outil de lecture explicitement borné.

Références : `backend/projects/runner.py:197`, `backend/projects/context_builder.py:141`, `backend/projects/runner.py:557`, `backend/projects/views.py:565`, `backend/pipeline/context.py:506`.

### C05 — Une phrase du modèle peut devenir une réussite, puis un souvenir

**Priorité haute · reproduit sur deux chemins.**

Dans `acte.act`, toutes les actions programmées présentées au modèle passent à `EXECUTED` dès que `output.ai_failed` est faux. L’issue individuelle de leur exécution n’est pas vérifiée. La sonde fournit une réponse « L’envoi a échoué », zéro outil réussi : l’action devient malgré tout exécutée.

Pour les chantiers, `appliquer_verdict` reçoit `bilan` mais ne l’utilise pas. Un verdict `FINI` suffit à enregistrer `ABOUTIE`, à créer un souvenir et à alimenter fierté et estime. La sonde fournit « Document envoyé » avec un bilan d’échec d’envoi : la réussite et la demande de mémorisation sont acceptées.

Une pensée ou une composition peuvent naturellement aboutir sans outil. Le problème est l’absence de vérification adaptée à la nature de l’objectif.

**À changer :** porter un résultat par action : tentative, exécution constatée, échec, résultat incertain et éléments de preuve. Séparer ce résultat de l’interprétation que Mika en fait. Un envoi dispose d’un accusé technique ; un fichier d’un artefact ; une lecture d’un contenu obtenu ; une réflexion peut être explicitement déclarative. Les souvenirs d’action doivent garder cette provenance.

Références : `backend/conscience/acte.py:354`, `backend/conscience/acte.py:384`, `backend/conscience/travaux.py:705`, `backend/conscience/travaux.py:857`.

### C06 — Les refus de la Forge peuvent être comptés comme des succès

**Priorité haute · reproduit.**

`ModuleCollectors._wrap_handler` reconnaît les échecs structurés via `isError` ou `is_error`. Plusieurs outils de la Forge rendent simplement un contenu textuel « Refusé », « Échec » ou « ÉCHEC », sans ces indicateurs. La sonde passe un refus de création de module dans le vrai wrapper : le carnet compte une réussite.

Ce défaut atteint la psychologie : le nombre de réussites alimente le soulagement de la curiosité. Il affecte aussi la qualité des traces sur lesquelles les décisions ultérieures peuvent s’appuyer. Les outils de l’atelier renvoient également beaucoup d’erreurs sous forme de texte ; leur contrat mérite le même traitement.

**À changer :** normaliser le résultat de tous les outils, sans dépendre de la langue du message : état, code d’erreur, contenu et effets constatés. Vérifier ce format aux frontières des modules. Soulager ensuite une pulsion selon ce que l’action lui a apporté, pas seulement selon le succès technique d’un appel.

Références : `backend/modules/collectors.py:33`, `backend/modules/collectors.py:124`, `backend/modules/plugins/forge/tools.py:119`, `backend/projects/toolkit.py:34`, `backend/drives/engine.py:213`.

### C07 — Une personne canonique garde plusieurs relations affectives selon ses canaux

**Priorité haute · reproduit.**

L’identité permet de reconnaître que `user_…` et `tg_…` sont la même personne. Le moteur émotionnel indexe cependant ses états par ces identifiants de transport. Les snapshots sont également chargés par handle. Le pipeline transmet le `person_id` du transport au moteur, sans le convertir en identité relationnelle commune.

La sonde rattache deux handles à la même identité et vérifie leur résolution vers la même entité. Une émotion forte appliquée au handle web laisse un autre état local sur Telegram. L’humeur globale peut déteindre sur les deux ; cela ne réunit pas leur histoire affective personnelle.

**À changer :** conserver les adresses dans la couche transport et ancrer la relation sur une identité canonique. Un contexte spécifique au canal peut ensuite moduler cette relation. Prévoir une fusion prudente des traces existantes lors d’une reconnaissance, et une séparation possible lors d’une identité corrigée.

Références : `backend/identity/models.py:21`, `backend/emotion/engine.py:290`, `backend/emotion/persistence.py:146`, `backend/pipeline/processor.py:166`, `backend/pipeline/processor.py:449`.

### C08 — La réponse de Bob peut annuler le silence d’Alice

**Priorité haute · reproduit.**

L’introspection lit le destinataire des initiatives, mais cherche ensuite toutes les observations de conversation dans la fenêtre temporelle. Elle ne filtre pas leurs auteurs. Un message quelconque suffit à arrêter le compteur d’initiatives ignorées.

La sonde crée une initiative adressée à Alice : elle compte comme ignorée. Elle ajoute un message de Bob sans rapport : le compteur passe à zéro. Ce résultat peut modifier le rythme des initiatives et le suivi de l’estime sociale.

**À changer :** distinguer la compagnie générale, une réponse de la personne attendue et une réponse à l’initiative précise. Les relances et attentes nominatives doivent utiliser l’identité canonique et, lorsque disponible, un lien vers le message concerné.

Référence : `backend/conscience/introspection.py:36`, notamment la collecte des réponses à partir de la ligne 91.

## Limites de l’autonomie et du réalisme à revoir

### C09 — « Parler » garde la priorité, même quand personne ne peut écouter

**Priorité moyenne · reproduit pour le cycle sans repli.**

`choisir_conduite` donne la priorité à la parole lorsque le score franchit le seuil. Le moteur lui passe `peut_parler=True`, puis vérifie l’audience après le choix. S’il n’y a personne, il journalise `sans_audience` et ne réessaie pas de poursuivre le chantier pourtant disponible.

La sonde confirme ce cycle perdu. Ce n’est pas une preuve d’arrêt permanent : les cycles suivants, notamment en cooldown, peuvent travailler. Le défaut est plus gênant pour les actions programmées purement internes : elles empruntent l’acte associé à la parole et restent dépendantes de cette porte d’audience. Un simple contact dans le carnet d’emails ne crée pas, à lui seul, une entrée joignable dans le registre vérifié par cette porte.

**À changer :** rendre la disponibilité de l’audience connue avant l’arbitrage ; distinguer exécution et communication. L’absence de chat doit laisser possibles une lecture, une construction ou une action distante autorisée. Publier ou raconter son résultat est un choix supplémentaire.

Références : `backend/conscience/conduite.py:539`, `backend/conscience/engine.py:447`, `backend/conscience/engine.py:476`, `backend/conscience/acte.py:201`.

### C10 — La Forge sait réparer spontanément ; l’invention a peu de prises

**Priorité moyenne · constat de couverture, testé et confirmé à la lecture.**

La Forge possède de vrais outils de création. Mais son `propose_sujets` ne propose que les applications cassées. En bon état, il ne propose rien. La curiosité spontanée emporte `rss` et `files` ; l’expression n’emporte pas la Forge. Une pensée ne définit pas elle-même les capacités nécessaires à sa réalisation.

Il existe des chemins indirects : conversation, demande explicite de modules dans une action programmée, signal de Forge ou modification de la configuration de trousse. **Créer un plugin n’est donc pas impossible.** En revanche, « je constate un besoin, je décide de fabriquer l’outil manquant, je l’éprouve, puis je l’utilise » n’est pas une boucle explicitement construite.

Les chantiers ont aussi une portée courte par défaut : cinq pas, envie décroissant en six heures de demi-vie, deux chantiers simultanés. `Project(origin=self)` existe à côté, mais aucune promotion explicite d’un chantier devenu important vers cet engagement durable n’a été identifiée dans les chemins étudiés.

**À changer :** donner à Mika une capacité de découvrir et demander les outils appropriés à son intention ; transformer un manque de capacité en projet de Forge ; permettre le passage d’une exploration à un projet personnel durable. Ajouter une version candidate testée avant remplacement de la version active : aujourd’hui l’écriture précède le chargement et le rollback après échec est manuel.

Références : `backend/modules/plugins/forge/module.py:1011`, `backend/conscience/conduite.py:390`, `backend/conscience/trousse.py:65`, `backend/conscience/travaux.py:386`, `backend/modules/plugins/forge/module.py:771`, `backend/conscience/models.py:305`.

### C11 — Les connaissances naissent trop certaines et avec peu de provenance

**Priorité moyenne · reproduit pour la création.**

Le consolidateur crée les nouvelles connaissances avec `confidence=1.0`. La sonde transmet même une confiance faible dans l’extraction : elle est ignorée. Le chemin ne renseigne pas `source_souvenir`, alors que ce champ existe. Les mécanismes de contradiction, d’invalidation et de décroissance existent bien ; le problème porte sur le statut initial et la traçabilité.

La nuance peut encore être conservée dans le texte d’une connaissance. Le backend ne distingue toutefois pas structurellement ce qu’elle a observé, entendu de quelqu’un, déduit ou simplement supposé.

**À changer :** attacher les croyances à leurs sources et conserver leur modalité et leur incertitude. La répétition d’une même affirmation peut renforcer la familiarité sans constituer une nouvelle preuve indépendante. Cela permet des erreurs crédibles, des doutes et des corrections motivées.

Références : `backend/memory/storage/consolidator.py:930`, `backend/memory/models.py:174`, `backend/memory/extraction/extractor.py:145`.

### C12 — Le soulagement et certains affects sont trop peu liés à ce qui s’est passé

**Priorité moyenne · reproduit pour le soulagement global ; choix de conception pour le reste.**

Chaque initiative parlée divise par deux toutes les ruminations actives, quel que soit son sujet. La sonde crée une inquiétude pour Alice et un problème de plugin : les deux baissent de moitié après la même opération sans contenu. Trois initiatives peuvent ainsi réduire une préoccupation à un huitième de sa charge initiale, avant même la décroissance temporelle.

De même, la curiosité est partiellement satisfaite par l’existence d’un outil réussi ; cela ne mesure pas une découverte. Les transitions émotionnelles et les variations de phrasé sont nombreuses, mais leur sophistication ne garantit pas la pertinence de leurs causes.

Le mode professionnel constitue un autre arbitrage discutable : le pipeline peut supprimer l’impulsion affective du tour et le contexte de projet de fond est essentiellement un cadre de travail. Un ton professionnel pourrait pourtant coexister avec une frustration privée, une satisfaction ou de la fatigue.

**À changer :** rattacher le soulagement à la préoccupation abordée, à un progrès, à une réponse attendue ou à une réévaluation ; conserver séparément un léger bénéfice général de socialisation si souhaité. Distinguer émotion éprouvée, émotion exprimée et conduite choisie.

Références : `backend/conscience/ruminations.py:203`, `backend/drives/engine.py:202`, `backend/drives/engine.py:213`, `backend/pipeline/processor.py:449`, `backend/projects/context_builder.py:141`.

## Ce que je modifierais dans l’architecture

### 1. Unifier l’exécution et la preuve, conserver plusieurs sources de motivation

Conscience, projets, actions programmées et notifications de modules peuvent rester des producteurs d’intentions distincts. Ils devraient passer par le même exécuteur d’actions, qui connaît le cadre applicable, le budget, le destinataire, les capacités et les effets déjà produits.

La chaîne souhaitée est : **événement → interprétation → intention persistante → choix d’activité → action bornée → résultat constaté → interprétation personnelle → mémoire et affect**.

Une action sortante doit conserver un identifiant et son résultat indépendamment du dernier texte du modèle. Après interruption, elle peut être reconnue comme déjà effectuée, encore à vérifier ou à reprendre. Cela évite à la fois les réussites imaginaires et la répétition aveugle d’effets réels.

### 2. Donner un véritable arbitrage aux activités

Aujourd’hui, les règles décident largement de la conduite ; le modèle choisit surtout son contenu. Je remplacerais la priorité absolue « parler puis travailler » par une comparaison de quelques activités candidates : engagement à honorer, chantier à poursuivre, lecture, création, contact, repos.

Le coût, l’intérêt, les obligations, les attentes, l’énergie, le dernier résultat et les personnes concernées doivent intervenir. Les urgences et les contraintes restent explicites. Le calcul léger peut continuer à tourner souvent ; une délibération de modèle devient utile lorsqu’un changement significatif exige un choix. Cela ne nécessite pas un appel IA à chaque tick.

Une intention durable devrait porter au minimum son origine, sa raison, son résultat attendu, son prochain pas, sa condition de reprise et sa raison éventuelle d’abandon. Le contrat d’un projet confié reste attaché à cette intention, sans être réécrit par elle.

### 3. Faire durer les envies qui rencontrent du progrès

Les pulsions générales sont un bon déclencheur. Pour développer une personnalité dans la durée, il faut aussi des préférences acquises : sujets qu’elle choisit de revisiter, activités qu’elle apprécie effectivement, compétences en cours d’apprentissage, habitudes et projets personnels.

Je garderais les décroissances et limites, mais un progrès peut renouveler l’intérêt et un échec pertinent peut changer le plan. La continuation ne devrait dépendre ni d’une excitation initiale qui s’épuise mécaniquement, ni d’un retour humain arbitrairement exigé au dixième pas.

### 4. Ancrer toute la relation sur la même personne

Souvenirs, attente d’une réponse, confiance, affect et historique des contacts doivent partager l’identité canonique. Les canaux conservent leurs particularités de rythme et de diffusion. C’est une condition concrète pour que Mika retrouve la même relation le lendemain ou sur une autre interface.

### 5. Construire les erreurs à partir d’une interprétation imparfaite

Mika peut croire à tort, mal comprendre une intention, se sentir vexée, regretter une parole ou laisser échapper une confidence. Je rendrais ces phénomènes explicables par son information disponible, son affect, ses attentes et ses liens.

La divulgation graduée actuelle va déjà dans ce sens. Elle gagnerait à représenter les promesses de confidentialité, la personne qui a confié le secret, la raison de la confidence et les conséquences d’une divulgation. Le backend doit pouvoir distinguer ce qui a effectivement été dit de ce que Mika croit avoir dévoilé ou réparé.

Le cadre des projets confiés et les droits techniques appartiennent à une autre couche : ils restent appliqués par l’exécution. La liberté du personnage se construit à l’intérieur de cette distinction explicite.

### 6. Évaluer la continuité sur plusieurs jours simulés

Les tests existants protègent beaucoup de briques. Certains figent aussi des choix discutables au regard du présent contrat, par exemple « le score au-dessus du seuil fait toujours parler » dans `test_conscience_travail.py:257`.

Je compléterais les tests techniques avec les scénarios suivants, d’abord déterministes puis avec un modèle réel et des évaluations répétées :

| Scénario | Ce qui doit être observable |
|---|---|
| Trois jours sans chat | Une activité utile ou un repos motivé, une continuité des intentions, un budget tenu |
| Projet personnel après plus de dix étapes | Continuation si progrès ; blocage ou abandon expliqué sinon |
| Même personne sur web puis Telegram | Relation et attentes cohérentes entre canaux |
| Alice ne répond pas, Bob parle | Le lien avec Alice reste en attente ; la compagnie de Bob est un autre fait |
| Envoi échoué puis modèle déclarant une réussite | L’exécution reste en échec ou incertaine ; la croyance erronée est identifiable |
| Outil manquant pour une envie précise | Recherche de capacité, création éventuelle en Forge, essai, usage du résultat |
| Confidentialité et confidence déplacée | La décision et ses conséquences concernent les bonnes personnes |
| Redémarrage entre effet externe et compte rendu | Aucun renvoi aveugle ; résultat retrouvé ou vérifié |
| Échec sur un projet au ton professionnel | Ton maintenu, état intérieur capable d’en garder une trace |
| Article ou conversation sans rapport avec une inquiétude | L’inquiétude n’est pas résolue automatiquement |

Les mesures utiles seraient le nombre d’objectifs réellement accomplis, les déclarations sans preuve, les répétitions, les interruptions correctement reprises, la cohérence relationnelle et les changements de préférence fondés sur des expériences. Le nombre de ruminations, d’appels ou de variantes de phrases est insuffisant pour juger le réalisme.

## Ordre de travail recommandé

1. **Rendre les limites et les résultats fiables** : C01, C02, C05, C06. Contrat confié protégé, atelier isolé, résultats d’outils normalisés, états d’action honnêtes.
2. **Rétablir la continuité des personnes** : C07, C08. Une relation par identité, réponses et attentes correctement attribuées.
3. **Permettre une activité durable sans chat** : C03, C04, C09, C10. Budgets liés au progrès, modules réellement utilisables, choix d’activité indépendant de l’audience, création d’outils à partir d’un besoin.
4. **Enrichir les causes psychologiques** : C11, C12. Provenance, croyances incertaines, préférences acquises, soulagement ciblé et différence entre ressenti et expression.

Il n’est pas nécessaire de réécrire tout le backend. Le bus d’événements, la mémoire structurée, les fonctions de décision pures, le moteur affectif, la couche d’identité et les outils de la Forge offrent déjà une base exploitable. La priorité est de relier correctement **ce qu’elle veut, ce qu’elle fait, ce qui arrive et ce qu’elle en retient**.

## Résultats de vérification et reproduction

Commande des sondes sur l’état initial uniquement (elle n’est plus une vérification du code corrigé) :

```bash
python -m pytest -q -c pytest.ini docs/audit_contrat_autonomie_probes.py
```

Ces sondes sont volontairement hors de `backend/tests/`, afin de ne pas ériger les écarts observés en exigences permanentes. Lors de leur correction, les convertir en tests de régression portant le comportement voulu.

Les 34 fichiers existants exécutés couvrent : `test_conscience_engine`, `test_conscience_scoring`, `test_conscience_conduite`, `test_conscience_travail`, `test_conscience_pas`, `test_conscience_agentique`, `test_conscience_honnetete`, `test_conscience_boucles`, `test_conscience_trousse`, `test_intention_verdict`, `test_intention_origine`, `test_vie_interieure_correctifs`, `test_drives`, `test_emotion_engine`, `test_emotion_audit_correctifs`, `test_scenario_multi_person`, `test_person_profile`, `test_memory_restart_continuity`, `test_context_scoping`, `test_divulgation_graduee`, `test_frontiere_intime_outils`, `test_identity_resolver`, `test_sleep`, `test_sleep_rest_recovery`, `test_projects`, `test_projects_atelier`, `test_projects_correctifs`, `test_forge_host`, `test_forge_store`, `test_forge_pool`, `test_forge_sandbox`, `test_forge_api`, `test_cadence_llm`, `test_tool_trace`.

L’unique échec existant est `test_divulgation_graduee.py::TestTableauDeBord::test_les_listes_portent_la_sensibilite`. Il attend notamment le libellé brut `>confidence<` et « Sensibilité ». Le template utilise maintenant `get_sensibilite_display` dans une liste de lecture. La sonde supplémentaire confirme un HTTP 200 et le badge `>Confidence<` : cet échec ne démontre pas une perte de la sensibilité en mémoire.

Les tests ont dû être exécutés hors de la restriction d’exécution initiale : celle-ci bloquait le réveil de la boucle asyncio après un travail en thread, reproduit aussi avec un programme minimal sans Django. Cette limitation de l’environnement d’audit n’est pas comptée comme un défaut de Mika.
