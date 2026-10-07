# Évolution de la gestion de contexte — du plafonnement au budget

*Proposition d'architecture, 2026-08-08. État de référence : le pipeline
`ChatPrompt` (préfixe stable en cache / état volatil dans le dernier tour /
historique en vrais messages) et les plafonds fixes posés le même jour.*

> **v1 archivée (`old/backend/`).** Les chemins cités plus bas (`memory/`, `pipeline/`, `ai/`) et
> `manage.py` sont ceux de l'ancien moteur, sous `old/backend/`. Le moteur vivant est
> [`backendv2/`](../backendv2/README.md), décrit dans [`ARCHITECTURE.md`](../backendv2/ARCHITECTURE.md).

> **État d'implémentation (2026-08-08 soir)** — le plan approuvé (voir
> CLAUDE.md § Memory pour la carte du code) est implémenté : mémoire à
> trois étages avec index épisodique (`memory/episodic/`), passe de
> préparation (`pipeline/preparation.py`, rôle `preparation` à mapper),
> budget par modèle (`ai/budget.py`, champ `context_window` des lignes
> IA · Modèles), compaction du fil (`memory/compaction.py`, rôle
> `compaction` à mapper), réorganisation nocturne (`memory/reorg.py`,
> phase 4 du sommeil). Backfill : `python manage.py backfill_episodic`.
> Reste à faire : compteurs dans GestionSystème (vue système), TTL cache 1h.
> Les chiffres ci-dessous restent la référence de dimensionnement.

---

## 1. Diagnostic — pourquoi les plafonds fixes sont un pis-aller

Les caps posés aujourd'hui (`self_concept` 1 600 car., modules 1 800,
historique 20 messages × 4 000 car., 5 souvenirs + 10 connaissances…)
résolvent un vrai problème — **aucun bloc ne portait de borne, rien en aval
ne mesurait** — mais ils le résolvent par le bas :

- Ils sont dimensionnés pour le pire cas (un petit modèle local) et
  s'appliquent au meilleur (1M de fenêtre chez Claude). Avec 1M de contexte,
  tronquer le récit de soi à 1 600 caractères ou l'historique à 20 messages,
  c'est amputer précisément ce qui fait l'intérêt du projet : la continuité
  d'une identité, d'une relation, d'une journée.
- Ils sont **absolus** alors que la ressource est **relative** : la bonne
  question n'est jamais « ce bloc dépasse-t-il N caractères ? » mais « quelle
  part de la fenêtre ce bloc mérite-t-il, face aux autres, sur ce modèle ? ».
- Leur seul mode de dégradation est la troncature. Or couper la fin d'un
  historique ou d'un profil perd le *sens* ; un résumé le garderait.

Le principe à retenir des caps : chaque couche doit être bornée. Le principe
à remplacer : la borne fixe, par une **allocation budgétaire par modèle,
avec une échelle de dégradation par couche** dont la troncature est le
dernier barreau, pas le premier.

---

## 2. Principes

1. **La fenêtre est un plafond, pas une cible.** Remplir 1M par réflexe
   coûte cher (même en cache-read à 0,1×) et dilue l'attention. Le budget
   cible par tour est une fraction configurée de la fenêtre ; le reste est
   de la marge pour les longues sessions avant compaction.
2. **Chaque couche déclare son contrat** : priorité, budget minimal, budget
   idéal, et *comment elle dégrade* quand elle n'obtient pas l'idéal
   (élaguer → compacter par LLM → réduire à une ligne → disparaître).
   L'allocateur ne connaît aucun contenu ; il distribue et applique.
3. **La volatilité décide du transport, le budget décide de la taille.**
   L'architecture cache-first actuelle (stable en système, volatil en fin de
   dernier tour) reste inchangée — le budget s'y superpose.
4. **On ne perd jamais d'information, on la déplace.** Ce qui sort du
   contexte vif doit exister ailleurs : la compaction produit un résumé *et*
   le verbatim reste en base ; l'extraction (souvenirs) a déjà eu lieu avant
   toute compaction. La fenêtre est un cache de travail, la base est la
   vérité.
5. **Un seul chemin de code pour 1M et 256K.** Les deux cas sont le même
   mécanisme avec des nombres différents — jamais deux pipelines.

---

## 3. L'imbrication — six couches, du plus froid au plus chaud

| Couche | Contenu | Volatilité | Transport | Cache |
|---|---|---|---|---|
| **L0 — Noyau** | personality.yaml, consignes d'outils, règles de sortie | statique (processus) | système, tête | préfixe cacheable |
| **L1 — Identité interne** | self-narrative **entier**, valeurs apprises, projets actifs (résumé) | ~quotidienne (consolidateur) | système, après L0 | même bloc cacheable |
| **L2 — Relationnel** | certitude d'identité, profil de la personne, engagements, historique émotionnel 30 j, *derniers échanges avec elle* | par personne, par session | système, fin (ou début des messages) | cacheable par personne |
| **L3 — Épisodique** | le fil de la conversation : **résumé compacté** des segments anciens + **verbatim** récent | à chaque tour (croît) | messages | breakpoint mobile sur l'avant-dernier tour |
| **L4 — État instantané** | humeur PAD, circadien, fatigue, ruminations, drives, indice d'humeur de l'interlocuteur, état modules | à chaque tour (change) | dernier tour user, bloc `--- ETAT INTERNE ---` | jamais (voulu) |
| **L5 — Rappel sémantique** | souvenirs + connaissances remontés par la requête du tour | à chaque tour (dépend du message) | dernier tour user, après L4 | jamais (voulu) |

Ce qui change par rapport à aujourd'hui : **L3 devient élastique et à deux
étages** (résumé + verbatim), **L2 gagne deux membres** (échanges récents
avec la personne, historique émotionnel étendu), et **L5 devient
proportionnel** au budget au lieu de 5+10 fixes.

L'ordre de lecture du modèle reste celui de `_LAYERS` — l'imbrication ne
réordonne rien, elle dimensionne.

---

## 4. Le budget — allocation par modèle déclaré

### 4.1 Déclaration

Chaque ligne *IA · Modèles* gagne un champ **`context_window`** (comme
`max_tokens` aujourd'hui ; défaut prudent 128 000 si absent). Le routeur le
transmet à `gather_context` via un objet `ContextBudget`.

```
utilisable = context_window × ai.context.usage_ratio   (défaut 0.5)
           − max_tokens (réserve de sortie)
           − poids_outils (mesuré, pas estimé : sérialisation réelle)
           − marge de sécurité (5 %)
```

`usage_ratio` existe parce que la fenêtre est un plafond, pas une cible
(principe 1) : à 1M, viser ~500k utilisables laisse la moitié de la fenêtre
comme zone tampon avant compaction, et borne le coût du pire tour.

### 4.2 Parts par couche — les deux profils demandés

Chiffres en **tokens**, dérivés automatiquement de `context_window` (aucun
« profil » codé en dur — les colonnes ci-dessous sont l'*effet* du calcul
sur les deux fenêtres visées) :

| Couche | part | 1M (≈490k utilisables) | 256K (≈115k utilisables) | plancher |
|---|---|---|---|---|
| L0+L1 noyau + identité | ce que ça coûte | ~4k (narrative entier) | ~4k | 2k |
| L2 relationnel | 4 % | ~8k (profil + 30 j + 20 échanges) | ~4k | 1,5k |
| L3 épisodique | **60 %** | ~290k verbatim avant compaction | ~70k | 8k |
| L4 état instantané | ce que ça coûte | ~1,5k | ~1,5k | 1k |
| L5 rappel sémantique | 6 % | ~12k (≈ 25 souvenirs + 30 connaissances) | ~7k | 2k |
| non alloué (marge de croissance intra-session) | reste | ~175k | ~28k | — |

Lecture : sur 1M, **la conversation vit en verbatim pendant des heures**
(290k ≈ plusieurs centaines de tours) avant la première compaction ; sur
256K, la compaction devient un événement normal de milieu de journée. Les
caps fixes actuels deviennent les **planchers** — le filet de sécurité quand
la fenêtre est petite ou la config illisible — et cessent d'être la règle.

### 4.3 Mesure des tokens

Pas de tokenizer embarqué (dépendance lourde, faux par modèle). À la place :
l'estimation chars/4 actuelle, **calibrée en continu** — le routeur reçoit
déjà l'usage réel de chaque réponse ; on maintient par provider une moyenne
mobile `ratio = tokens_réels / caractères_envoyés` et l'allocateur l'utilise.
Auto-correct, gratuit, sans dépendance. (Le français tourne autour de
3,4–3,9 car./token selon le modèle — l'écart justifie la calibration.)

### 4.4 Les outils ne sont plus un problème de fenêtre

7k tokens de déclarations sur 256k utilisables = 6 %. Avec le préfixe en
cache, ils ne coûtent presque rien par tour. **`ai.conversation_tool_modules`
change donc de sens** : ce n'est plus un knob de fenêtre mais un knob de
*latence de prefill local* (Ollama) — la doc de config doit le dire, et le
défaut hébergé devient « tous les modules ». Si la Forge fait un jour
exploser le compte d'outils (×10), l'horizon est le `defer_loading` / tool
search côté API — pas un retour au rationnement.

---

## 5. L'échelle de dégradation — ce qui se passe quand c'est trop grand

Chaque couche implémente la même interface :

```
degrade(content, budget) → content'
```

avec une échelle propre, appliquée barreau par barreau jusqu'à tenir :

| Couche | 1. élaguer | 2. compacter (LLM) | 3. minimal | 4. absent |
|---|---|---|---|---|
| L1 identité | — (jamais élagué) | résumé du narrative si > budget | 1re phrase | jamais |
| L2 relationnel | échanges récents 20→5, historique 30 j→7 j | résumé du profil | ligne d'affect seule | si inconnu |
| L3 épisodique | **rien à élaguer — on compacte** | segments anciens → résumé roulant (voir §6) | résumé seul + 10 derniers tours | jamais |
| L4 état | signaux 4→2, ruminations 3→1 | — (déjà minimal) | humeur dominante seule | jamais |
| L5 rappel | score-based : garder les mieux classés | — (le retriever *est* déjà une compression) | 3 souvenirs | oui |

Deux règles transverses :

- **La troncature brute (`…`) ne survit que comme tout dernier recours**,
  quand un barreau LLM a échoué et que le plancher est dépassé — et elle se
  loggue dans le registre de dégradations (`degradations.record`), parce
  qu'une coupe silencieuse est exactement ce qu'on a reproché à l'existant.
- **Aucun appel LLM de dégradation dans le tour.** Tout barreau « compacter »
  est produit *hors tour* par une boucle de fond (voir §6) ; le tour consomme
  ce qui est prêt et tolère un dépassement temporaire (c'est la marge non
  allouée du §4.2). La latence d'un tour de conversation ne paie jamais une
  compaction.

---

## 6. La compaction conversationnelle — la pièce neuve

### 6.1 Mécanisme

Un **résumé roulant par conversation**, entretenu en arrière-plan, à la
manière de la compaction serveur de l'API Claude mais possédé par nous
(donc portable sur les petits modèles).

- **Modèle de données** : `ConversationSummary(conversation FK,
  upto_message_id, content, est_tokens, version, created_at)` — une ligne
  vivante par conversation, remplacée à chaque passe (les versions
  précédentes gardées N jours pour audit).
- **Déclencheur** : tick du consolidateur (ou boucle dédiée `PeriodicLoop`,
  60 s). Condition : `tokens_verbatim_estimés > seuil_haut` où
  `seuil_haut = part_L3`. La passe replie les messages les plus anciens
  jusqu'à redescendre à `seuil_bas = 0,5 × part_L3`.
- **Incrémental** : entrée de la passe = résumé précédent + tranche à
  replier ; sortie = nouveau résumé. On ne re-résume jamais toute la
  conversation.
- **Garde-fous** :
  - ne replie jamais les messages **au-delà du checkpoint du consolidateur**
    (`upto_message_id ≤ checkpoint`) : l'extraction de souvenirs a toujours
    lieu avant qu'un verbatim ne quitte le contexte vif — principe 4 ;
  - **plancher de récence verbatim** : les ~30 derniers messages restent
    toujours en clair, quoi qu'il arrive ;
  - échec LLM → on garde le verbatim (la fenêtre absorbe, c'est la marge),
    on loggue, on retente au tick suivant. Une compaction ratée ne perd rien.
- **Rôle IA dédié** : `AIRole.COMPACTION`, mappé dans le dashboard comme les
  autres (Haiku côté hébergé, le modèle local sinon). Non mappé → compaction
  désactivée, dégradation = élagage des plus anciens **avec mention visible**
  dans le prompt (« [N messages plus anciens non disponibles] »).

### 6.2 Le prompt de compaction

Première personne (c'est *son* fil), et il préserve dans l'ordre :
engagements pris, faits appris sur les personnes, décisions, tonalité
relationnelle et son évolution, questions restées ouvertes, éléments dont on
risque de reparler. Il jette : les formules, les redites, le small talk sans
suite. Sortie bornée (~2k tokens).

### 6.3 Lecture

`memory_manager.get_conversation_context()` renvoie désormais
`(summary | None, tail_messages)`. `ChatPrompt` gagne un champ
`conversation_summary`, rendu comme **premier message user** du tableau :

```
[Fil de la conversation jusqu'ici — résumé]
…
```

suivi du verbatim. Il change rarement (à chaque passe de compaction), donc
il vit *dans* la zone cacheable des messages — le breakpoint mobile sur
l'avant-dernier tour continue de fonctionner tel quel.

### 6.4 Ce que ça remplace

- `memory.short_term_limit` (20 messages) devient un plafond de *comptage*
  secondaire très haut (par ex. 500) ; la vraie borne est le budget L3.
- `resume_window_minutes` (120) peut s'assouplir : reprendre une
  conversation de la veille devient viable puisque son poids est déjà
  compacté — la frontière naturelle redevient le journal (nuit).
- La compaction **ne remplace pas** l'extraction : le consolidateur produit
  la mémoire structurée (souvenirs, connaissances, engagements), la
  compaction produit la *continuité conversationnelle*. Les deux coexistent,
  ancrées sur le même checkpoint.

---

## 7. Ce que le budget débloque, sous-système par sous-système

- **Identité interne (L1)** : le self-narrative entre entier. Le cap 1 600
  ne s'applique plus qu'en plancher (fenêtre minuscule).
- **Mémoire longue (L5)** : `retrieval_souvenirs` / `retrieval_connaissances`
  deviennent des *maxima* que le budget module (25/30 sur 1M, 8/12 sur 256K,
  5/10 en plancher). Le re-ranking existant (récence × personne × pertinence)
  devient réellement utile puisqu'il choisit dans un ensemble plus large.
- **Humeurs** : l'état (L4) reste court — c'est un vecteur, pas un texte.
  Mais l'*historique* émotionnel (L2) passe de 7 à 30 jours agrégés quand le
  budget le permet : les tendances (« vous vous êtes rapprochées ces
  dernières semaines ») deviennent réelles.
- **Historique des personnes (L2)** : nouveau bloc « vos derniers échanges »
  — les K derniers échanges directs avec *cette* personne, tous fils
  confondus, remontés par handle. Distinct du buffer partagé (qui reste la
  pièce commune) et distinct de la fiche compilée : c'est du vécu direct,
  donc pas soumis au seuil de divulgation — c'est ce qu'elle a elle-même
  entendu et dit. La fiche (profil, engagements) reste gated par la
  certitude d'identité, exactement comme aujourd'hui.
- **Outils** : tous chargés côté hébergé (cache), allow-list réservée au
  local (latence de prefill).

---

## 8. Coût et cache — les chiffres qui contraignent le design

Le point dur n'est pas la fenêtre, c'est **la réécriture du cache après une
pause**. TTL 5 min : toute reprise après une pause paie la réécriture du
préfixe (×1,25). Avec un L3 gonflé à 290k tokens :

| préfixe cacheable | réécriture (×1,25, Sonnet $3/M) | réécriture (Opus $5/M) |
|---|---|---|
| 30k (aujourd'hui, typique) | ~$0,11 | ~$0,19 |
| 120k | ~$0,45 | ~$0,75 |
| 300k | ~$1,13 | ~$1,88 |

Conséquences intégrées à la proposition :

1. **TTL 1 h sur le préfixe** (`cache_control: {ttl: "1h"}`, écriture ×2 mais
   une conversation avec des pauses de 5–60 min ne repaie plus tout à chaque
   relance) — knob `ai.claude.cache_ttl`, défaut `5m`, à passer à `1h` dès
   que les logs montrent des réécritures fréquentes.
2. **`usage_ratio` à 0,5 par défaut** : le pire tour d'une session marathon
   coûte un montant connu d'avance, pas « la fenêtre entière ».
3. **Observabilité d'abord** : le log `AI call OK` gagne trois champs —
   `cache_read`, `cache_write`, répartition estimée par couche — et une vue
   GestionSystème « Budget de contexte » montre les jauges par couche et le
   taux de hit. On ajuste les parts *après* avoir vu, pas avant.

---

## 9. Plan d'implémentation

**P1 — Le budget (fondation, ~1 journée)**
`context_window` sur les lignes `ai.models` ; `ai/budget.py`
(`ContextBudget`, parts, planchers = caps actuels) ; `gather_context(budget)`
dimensionne L2/L5 et les caps deviennent dérivés ; calibration EMA
chars→tokens dans le routeur ; champs cache dans le log.
*Sans P2, L3 reste au comptage actuel — P1 est utile seul.*

**P2 — La compaction (~2 jours)**
Modèle `ConversationSummary` + migration ; `AIRole.COMPACTION` + mapping
dashboard ; passe incrémentale ancrée sur le checkpoint du consolidateur
(watermarks, plancher de récence, échec = no-op) ; lecture deux-étages dans
`manager` ; champ `conversation_summary` dans `ChatPrompt` + rendu ;
`short_term_limit` → 500, budget L3 aux commandes ; tests (watermarks,
ancrage checkpoint, échec LLM sans perte, résumé dans la zone cacheable).

**P3 — Le relationnel étendu (~1 journée)**
Bloc « derniers échanges avec X » (requête par handle, budget L2) ;
historique émotionnel 30 j ; comptes de retrieval budgétés.

**P4 — Observabilité et réglage (~½ journée)**
Vue « Budget de contexte » dans GestionSystème (jauges par couche, hit-rate
cache, compactions récentes) ; knob `ai.claude.cache_ttl` ; documentation
CLAUDE.md.

Ordre pensé pour que chaque phase livre seule : P1 relâche déjà les caps sur
1M ; P2 est la pièce maîtresse ; P3/P4 enrichissent.

---

## 10. Ce qu'on ne fait pas (anti-buts)

- **Pas de remplissage de fenêtre par principe.** 1M sert à ne pas avoir à
  choisir pendant des heures, pas à tout mettre.
- **Pas de compaction dans le tour.** Jamais. La marge non allouée existe
  pour ça.
- **Pas de compaction serveur (`compact-2026-01-12`)** comme mécanisme
  principal : elle est Claude-only et opaque ; la nôtre est portable (256K
  local), inspectable (ligne en base, visible dans le dashboard) et ancrée
  sur l'extraction. Rien n'empêche de l'activer *en plus*, en ceinture,
  côté hébergé.
- **Pas de second pipeline pour les petits modèles.** Mêmes couches, mêmes
  barreaux, nombres plus petits.
- **Pas de suppression du filet actuel.** Les caps d'aujourd'hui restent le
  plancher de l'échelle — le budget les *dépasse*, il ne les remplace pas.
