# Audit adverse de la vie intérieure de Mika — 2026-08-09

> ## RÉSOLUTION — 2026-08-09, même journée
>
> **Les 39 constats ont été traités. Aucun écarté.** Le rapport ci-dessous est conservé tel qu'il a
> été écrit : il décrit l'état *avant* correction et reste la meilleure explication de ce qui n'allait
> pas. Ce qui suit dit ce qu'il en est maintenant.
>
> **Vérification d'abord.** Les 7 constats marqués *[plausible]* (P1–P7), que l'audit d'origine
> n'avait jamais contre-vérifiés faute de budget, l'ont été. **Tous confirmés, aucun réfuté**, la
> plupart reproduits par exécution. Rien de ce qui a été corrigé ne reposait sur une intuition.
>
> **Suite de tests** : de **10 échecs / 2 124 verts** à **1 échec / 2 478 verts** (+354 tests,
> 43 fichiers de tests modifiés, 10 créés, solde net **+241 assertions**). Frontend : 102/102 et
> `npm run build` vert. Trois passes complètes, résultat identique, en ordre fixe comme aléatoire.
>
> **Les deux tests documentés comme instables selon l'heure ne le sont plus** — ils épinglent
> désormais le biais circadien au lieu d'être exclus en CI. La ligne de `CLAUDE.md` recommandant de
> les `--deselect` a été retirée : une suite qui exclut ses tests difficiles ne mesure que les faciles.
>
> ### L'unique test laissé rouge, et pourquoi
>
> `test_scenario_rollercoaster.py::TestRollercoasterWithMelancholicTemperament::test_melancholic_resonates_with_sadness`
> **n'est pas un pin périmé : il n'a jamais mesuré ce qu'il nomme.** Sous l'ancien moteur il passait
> en lisant `excited 0,61` puis `hopeful 0,74` — des positions pointant à cos = −0,90 de l'ancre
> triste, c'est-à-dire le reliquat des tours précédents, l'impulsion en vitesse ne déplaçant rien à
> l'instant de la lecture. Un tempérament `default` le satisfaisait tout aussi bien. Sous le cliquet,
> mélancolique et default tombent à 4,7 % l'un de l'autre, et cet écart vient entièrement
> d'`intensity_base`, pas de `default_mood`. **Un tempérament ne résonne pas réellement avec sa
> propre valence : la propriété n'est pas implémentée.** Le rendre vert reviendrait à l'inventer.
> Deux correctifs chiffrés sont proposés (`dynamics.py::apply_impulse`, gain sensible à l'opposition ;
> `engine.py::process_emotion`, alignement au tempérament) — **arbitrage ouvert, à toi.**
>
> ### Ce qui a changé au-delà du périmètre de l'audit
>
> - **Le SDK CLI `claude_agent_sdk` et l'authentification par jeton OAuth sont supprimés** (Anthropic
>   ne supporte plus cet usage). Seule l'API Messages subsiste. Un 401 remonte désormais au lieu de
>   basculer silencieusement sur un second transport. Un garde AST interdit tout réimport.
> - **Tous les providers reçoivent le tour structuré**, outillé comme non outillé. GLM et Gemini
>   n'avaient pas de méthode de conversation et recevaient un prompt aplati sans raison technique ;
>   le chemin *outillé* — le plus cher, celui où les ~6 500 jetons de déclarations d'outils sont
>   réécrits à chaque itération — ne l'était pour aucun provider sauf Claude.
> - **Cinq tests qui ne passaient que par l'ordre d'exécution** ont été isolés : ils lisaient la base
>   de l'installation réelle et ne tenaient que tant qu'un cache était chaud.
>
> ### Reste ouvert (rien de bloquant)
>
> 1. `backend/configs/service.py::db_read._call` — cause de production de la fragilité ci-dessus
>    (`close_old_connections()` hors de tout garde-fou), décrite mais non corrigée.
> 2. `/gestion/inner/historique/` — la barre de filtres partagée ne transmet pas la personne quand on
>    change de granularité (un GET n'envoie pas ce qu'il n'affiche pas). Défaut d'UI réel, trouvé en chemin.
> 3. `ai/router.py` n'alimente jamais le relevé `tool_weight.note` ; il l'est depuis `build_chat_prompt`.
> 4. `backend/drives/models.py` et sa migration `0001_initial` sont **non suivis par git** : ils doivent
>    entrer dans le commit, sinon l'app casse au déploiement.
> 5. Sept migrations en attente dans `ai` et `configs` — renommages d'index auto-générés, antérieurs
>    au chantier, sans effet sur le runtime.
> 6. Le câblage de `main.ts` (`handleSpeech → applyEmotion`) n'est épinglé par aucun test : c'est la
>    dernière ligne où le constat S7 pourrait revenir.

**Méthode** : 9 auditeurs indépendants (coutures, boucles, affect causal, uncanny, continuité,
concurrence, panne partielle, comportemental, conservation), puis vérification contradictoire —
un sceptique par constat, chargé de le réfuter maillon par maillon dans le code réel et de le
reproduire quand c'était faisable (scripts purs + pytest en base mémoire). L'audit a été
interrompu (budget) à 23/39 vérifications : les constats non contre-vérifiés sont marqués
**[plausible]**. **REPRODUIT** = exécuté (script/pytest) ; **CONFIRMÉ** = chaque maillon
vérifié dans le code par le sceptique. 47 constats bruts, dédoublonnés ci-dessous.
La sécurité est hors périmètre de cet audit.

## Synthèse

L'ensemble ne tient pas comme un être cohérent, et les fractures ne sont pas là où on les
attend. Le code des organes est soigné, mais **trois défauts d'échelle traversent tout** :

1. **L'échelle de temps de l'affect est fausse d'un ordre de grandeur.** L'oscillateur PAD
   revient au repos en ~27 s alors qu'un tour dure 30–120 s : l'émotion n'existe qu'*entre*
   les tours, jamais *dans* un tour. Tout ce qui lit la position (prompt, snapshots, fiche
   affect, gestes) lit du vide. L'invariant « l'affect cause, il ne décore pas » est faux en
   pratique — pire : c'est le tag choisi par le LLM qui est la seule émotion réelle du
   système, et lui-même est mal archivé.
2. **La nuit mentale n'a presque jamais lieu.** Le gate d'entrée du sommeil est
   infranchissable en usage réel, donc journal, rêves, digestion et réorg — la moitié
   « guérison » de la psyché — sont structurellement rares. Et quand un organe nocturne
   meurt, rien ne le compte.
3. **L'invariant « échec silencieux mais COMPTÉ » est tenu partout sauf dans la psyché.**
   Les 72 sites câblés couvrent la plomberie ; les chemins d'échec des organes de la vie
   intérieure (rappel mémoire, extraction, journal, rêve, digestion, boucles elles-mêmes)
   rendent `""`/`[]`/`None` sans jamais toucher le registre. La « coquille polie » que
   l'invariant 5 devait empêcher est l'état de panne par défaut.

---

## BLOQUANTS (2)

### B1 — La nuit mentale est structurellement rare, et un restart du soir la supprime
`backend/memory/sleep.py:448` — CONFIRMÉ, REPRODUIT, design qui se retourne.

L'entrée en sommeil exige `rest_tension >= 0.5` après 15 min d'idle, mais REST est en RAM
pure (reset au boot, `backend/drives/engine.py:51`), ne croît que par activité
(~0.05–0.08/réponse, `growth_rate=0.0`) et décroît de 0.36/h. Scénario type : conversation
18h–20h30, coucher — à 23h15, tension 0.010 < 0.5 → **AWAKE toute la nuit** : pas de journal
(« TON FIL D'HIER » vide à jamais pour cette date), pas de rêve, ruminations non digérées,
avatar les yeux ouverts. Variante : le seul profil qui dormait (chat jusqu'à 22h30, tension
0.73) est annulé par un reboot à 22h50. L'`except` du gate force en plus `rest_tension=0.0`
— fail-**closed**, non compté.

### B2 — Une dispute de 10 tours se lit et s'archive comme « playful »
`backend/emotion/engine.py:171` — CONFIRMÉ, REPRODUIT, design qui se retourne.

Tempérament par défaut → ζ=0.65, ω₀=0.23 : retour au repos en ~27 s, inférieur à l'intervalle
entre tours. L'impulsion n'étant que vélocité, `gather_context` et le snapshot (lus juste
après `backend/pipeline/processor.py:280-281`) voient la position pré-impulsion, déjà revenue
au home. Reproduit : 10 tours à 45 s, LLM émettant `[EMOTION:angry:0.8]` à chaque fois →
chaque prompt suivant lit « tu te sens **playful (0.40)** » et chaque snapshot persiste
playful. Aucun cliquet d'escalade n'existe ; la colère n'est qu'un pic facial de ~5 s entre
les tours via `emotion_update`.

---

## SÉRIEUX — confirmés par contre-vérification (18)

### Affect décoratif / chaîne émotionnelle

- **S1. Tag absent ou inconnu = impulsion physique vers le zéro.** `backend/emotion/types.py:85`
  — REPRODUIT. Pas de tag (fréquent en local/tours à outils) → `EmotionData(NEUTRAL, 0.5)`
  appliqué comme vraie impulsion vers l'origine PAD. Mesuré : un troll vient d'énerver Mika
  (angry 0.7), le tour suivant sans tag ramène la colère à 0.22 en 2 s puis l'oscillateur
  *dépasse* le zéro et affiche `dreamy` — le raté de parsing est vécu comme un apaisement
  rêveur.
- **S2. Le snapshot émotionnel rate systématiquement le dernier échange.**
  `backend/pipeline/processor.py:281` — REPRODUIT. Snapshot pris à l'instant précis où
  l'impulsion est invisible + throttle 30 s posé au *premier* message : un unique message
  bouleversant se persiste `neutral:0.00`. Fiche affect et tendance hebdo ignorent l'échange.
- **S3. « Comme d'habitude » écrase l'intensité.** `backend/emotion/state.py:173` — REPRODUIT.
  `label == default_mood` → même phrase pour happy 0.15 et happy 0.95. Avec le défaut `happy`,
  toute l'amplitude dans la direction du tempérament est muette : euphorie au visage
  (sync 3 s), platitude dans la voix.
- **S4. Le facteur « débordement d'humeur » de la conscience est numériquement mort.**
  `backend/emotion/engine.py:605` — REPRODUIT. Le bleed global fait une impulsion *vers une
  cible réduite* (norme ≤ 0.373) alors que le Facteur 3 exige 0.7 (norme 0.87). Bombardement
  d'impulsions I=1.0 pendant 20 min : intensité max 0.38 — *inférieure* au repos circadien de
  14h (0.40). L'émotion vécue fait **baisser** l'humeur globale.
- **S5. La stance par personne s'évapore en ~15 s vers le home circadien *global*.**
  `backend/emotion/engine.py:766` — REPRODUIT, design qui se retourne. Le bloc « envers cette
  personne » devient le même boilerplate horaire pour l'ami, le troll et l'inconnu ; une
  frustration d'hier réhydratée traverse angry→amused→hopeful en 10 s à la reconnexion.
- **S6. Palette émotionnelle des souvenirs : 7 valeurs sur 29, jamais validée.**
  `backend/memory/extraction/extractor.py:27` — REPRODUIT. Le prompt d'extraction impose
  7 émotions, le stockage ne valide rien. Émotions négatives atteignables par un souvenir :
  exactement {angry, sad} — un cauchemar né de la peur est impossible ; la saillance mesure
  une charge 0.00 sur un mot hors-liste.
- **S7. Les gestes n'ont aucun chemin synchronisé avec ce qu'elle dit.**
  `frontend/src/vtuber/animation/gestures.ts:137` — CONFIRMÉ, design qui se retourne. La frame
  `speech` porte l'émotion pré-impulsion (sous le seuil des one-shots) ; la montée réelle
  arrive 6 s après par `emotion_update`… dont la porte `ambient` interdit les one-shots.
  Texte furieux, corps placide, TTS modulée sur happy — par construction.

### Coutures / prompt

- **S8. Mode professionnel : 1 canal affectif coupé sur 6.** `backend/pipeline/prompt.py:117`
  — REPRODUIT, design qui se retourne. `emotion_policy=OFF` ne mute que `emotion_context` ;
  fatigue (« laisse-toi être moins parfaite »), rêve (« tu peux le mentionner »), ruminations,
  mood-hint et tags `[excited]` des souvenirs restent — et la mémoire émotionnelle est rendue
  *après* la directive projet, dans la zone de récence qui pèse le plus.
- **S9. Aucune borne globale du tour ; le terme « − outils » du budget n'est jamais
  alimenté.** `backend/ai/budget.py:147` — REPRODUIT. `tools_chars` est un paramètre mort
  (aucun appelant ne le passe). Pire cas mesuré ≈ **19 300 tokens** pour une fenêtre de repli
  16 384 (1,18×), **2,36×** une 8k locale : la roue de secours documentée tronque par la
  tête — c'est-à-dire le préfixe stable, la personnalité.
- **S10. Le marquage « qui parle » n'atteint aucun provider.** `backend/ai/chat.py:111`
  — REPRODUIT. `_label_history_speakers` annote `{"speaker": nom}`… que ni `chat_messages()`
  ni `legacy_pair()` ne lisent. Le buffer partagé (compromis assumé) devient : les confidences
  d'Alice rendues comme des tours « user » anonymes dans le prompt de Bob — le modèle les lui
  attribue.

### Frontière de l'intime

- **S11. Les outils MCP mémoire contournent entièrement le seuil de divulgation.**
  `backend/memory/module.py:248` — REPRODUIT. `memory_search` / `memory_list_commitments` /
  etc. sont statiques : aucun scoping sur l'interlocuteur ni sa certitude, alors que le
  ContextVar nécessaire existe et sert ailleurs (`backend/pipeline/tracing.py:49`). Un inconnu
  (certitude 0.25) demande « que t'a dit Thomas sur sa santé ? » : la gate retient la fiche,
  l'outil la ressort.
- **S12. La passe de préparation injecte le verbatim des conversations d'autrui.**
  `backend/pipeline/preparation.py:292` — REPRODUIT, design qui se retourne. `execute_plan`
  interroge l'épisodique avec `person=<nom fourni par le petit LLM>` (« consommateur
  interne ») mais fusionne le résultat dans le bloc mémoire du tour de **conversation** :
  « qu'est-ce que Thomas t'a raconté hier soir ? » → les chunks de son DM Telegram, mot pour
  mot, dans le prompt de Bob. Vide la politique « own identity only » de la voie chaude.

### Mémoire / continuité

- **S13. Le checkpoint de consolidation avance par-dessus une extraction en échec.**
  `backend/memory/storage/consolidator.py:178` — REPRODUIT. Tout échec transport rend `[]`,
  indistinguable de « rien à extraire » ; le checkpoint est persisté inconditionnellement.
  Provider d'extraction mort de 14h à 18h → rien de cet après-midi ne deviendra jamais
  souvenir/connaissance/engagement, sans une ligne au registre.
- **S14. Le self-narratif est synthétisé depuis le top-importance toutes-époques.**
  `backend/memory/narrative.py:186` — CONFIRMÉ. Le gate compte les souvenirs *nouveaux* mais
  l'échantillon est `order_by("-importance")[:25]` sans fenêtre : les souvenirs boostés en
  permanence occupent le pool, une semaine riche à importance ordinaire n'y entre pas —
  « QUI TU ES DEVENUE » converge vers un paragraphe figé. La dérive vers le générique est
  mécanique.
- **S15. La décroissance peut détruire un souvenir que la conscience vient de booster.**
  `backend/memory/storage/consolidator.py:697` — CONFIRMÉ. Lot lu à T0, traité avec awaits ;
  un boost (0.11→0.61) tombé pendant la passe est écrasé ou le souvenir est *supprimé* sur la
  copie périmée — précisément le souvenir ancien que le boost existait pour ranimer.

### Panne invisible (l'invariant 5 dans la psyché)

- **S16. ChromaDB mort = amnésie polie non comptée.** `backend/memory/manager.py:321`
  — CONFIRMÉ. Les deux enveloppes du rappel + le filet de `gather_context` avalent tout avec
  un logger, zéro `degradations.record` — dans des fichiers qui l'appellent 13 fois ailleurs.
  Mika ne se souvient plus de rien, pendant des jours, santé au vert.
- **S17. Le filet terminal des boucles de fond n'est pas câblé, et rien ne montre l'âge du
  dernier tick réussi.** `backend/utils/periodic.py:94` — CONFIRMÉ. Un `database is locked`
  persistant : 3 jours sans extraction, décroissance, rétention, narrative, profils — boucle
  « running », santé à zéro.
- **S18. Asymétrie systématique du comptage LLM nocturne.** `backend/memory/sleep.py:620`
  — CONFIRMÉ. Journal, rêve, extraction : seul le JSON illisible est compté ; timeout/provider
  mort/rôle non mappé ne le sont jamais. Avec `SLEEP_LLM_TIMEOUT=45s` contre les 76–219 s
  mesurés en local, la vie nocturne s'éteint à l'installation, indéfiniment, sans signal.

---

## SÉRIEUX — plausibles, non contre-vérifiés (audit interrompu) (7)

- **P1. La conscience lit son propre échafaudage comme l'état émotionnel du destinataire.**
  `backend/pipeline/context.py:248` — reproduit par le chasseur. `user_mood_hint` gardé par
  person_id, pas par intent : un `INTERNAL_TRIGGER` visant Thomas fait tourner
  `detect_user_mood_hint` sur le prompt d'action que Mika s'est écrit — « il a besoin de
  vider son sac » à propos d'un texte que personne n'a envoyé.
- **P2. La rétention supprime le seul checkpoint des deux boucles mémoire.**
  `backend/memory/retention.py:59` — reproduit par le chasseur. `keep_days=14` sans protéger
  la ligne la plus récente : machine éteinte 15 jours → au boot, le checkpoint est balayé ;
  tout l'historique est ré-extrait, daté d'aujourd'hui.
- **P3. Souvenir fantôme Chroma/ORM.** `backend/memory/retrieval/retriever.py:445`
  — `_enrich_souvenirs` confond « chargement ORM échoué » et « ligne supprimée » : un souvenir
  effacé (décroissance, fusion) dont l'entrée Chroma survit est servi pour toujours,
  importance figée. L'oubli décidé devient inoubliable.
- **P4. Chaque journée est extraite deux fois.** `backend/memory/reorg.py:105` — la réorg
  nocturne re-passe les chunks déjà extraits au fil de l'eau ; `_store_souvenir` crée
  inconditionnellement → paraphrases jumelles, que la dédup ne rattrape que partiellement
  (et voir M6 : la copie nocturne, mal datée, *surclasse* l'originale).
- **P5. La conscience ignore le cycle de sommeil.** `backend/conscience/engine.py:358`
  — reproduit par le chasseur. Aucun facteur ne lit `sleep_cycle.phase` ; dormir *vide* REST
  donc réduit la pénalité fatigue : à 3h, score 0.77 ≥ 0.5 → elle parle spontanément, TTS
  actif (`SCREEN` autorisé pendant le sommeil), en plein deep_sleep. Dormir la rend plus
  bavarde.
- **P6. Le réveil est un effet de bord d'une réponse réussie.**
  `backend/conscience/engine.py:209` — `_last_activity` n'est écrit que par `observe()` sur
  `chat.message`, émis *après* un appel IA réussi : elle répond les yeux fermés (la frame
  porte `sleep_phase="deep_sleep"` pendant que le TTS parle), et un tour en échec la laisse
  dormir.
- **P7. Trois semaines d'absence = vingt-cinq minutes.** `backend/drives/state.py:51`
  — reproduit par le chasseur. SOCIAL sature en ~17 min, l'historique est rendu sans
  horodatage, le buffer ne vieillit jamais tant que le processus tourne : « tu m'as manqué »
  n'a aucune base mécanique — si elle le dit, c'est une confabulation du LLM.

---

## MINEURS (regroupés)

- **M1. Le rêve est brûlé par un tour qui échoue** — `backend/pipeline/context.py:620`,
  trouvé indépendamment par **trois** axes. `mark_dream_recalled` pendant `gather_context`,
  avant l'appel IA : un timeout au premier message du matin (le moment où un modèle local est
  froid) consomme le rêve à jamais — contre la doctrine « un échange raté n'est pas un vrai
  échange ».
- **M2. Aucun garde-fou anti-répétition dans le rappel** —
  `backend/memory/retrieval/retriever.py:534` + `:89`. L'expansion associative est
  déterministe (même « ça me rappelle… » tour après tour) et le biais ×1.5 <1h rend collant
  le souvenir créé pendant la conversation même. La texture mécanique que la saillance devait
  éviter.
- **M3. Entêtes de sections vides sous cap** — `backend/memory/retrieval/retriever.py:694`,
  REPRODUIT. « [Quelque chose te revient] » suivi de rien : sur petit modèle, une invitation
  à confabuler le souvenir manquant.
- **M4. Digestion nocturne : pannes avalées non comptées** — `backend/memory/sleep.py:871`,
  `except: return 0` et `except: pass` nus (deux axes l'ont trouvé).
- **M5. Deux horloges dans l'agrégation émotionnelle** —
  `backend/memory/storage/consolidator.py:823`, REPRODUIT. `timezone.now().date()` (UTC)
  contre un lookup `__date` en heure locale : entre minuit et 2h, la journée émotionnelle se
  range dans le mauvais jour — la violation exacte de l'invariant « une horloge », dans un
  angle mort du test qui le pinne.
- **M6. `occurred_at` = l'instant d'extraction** —
  `backend/memory/storage/consolidator.py:338`. Les souvenirs de la réorg de 3h sont datés
  d'aujourd'hui et volent le boost de récence ×1.3 à l'original d'hier.
- **M7. Résumé roulant écrasé par une complétion dégénérée** —
  `backend/memory/compaction.py:219`. Seule garde : « non vide ». Un refus d'une phrase du
  petit modèle remplace des semaines de contexte compressé (le verbatim survit en SQL —
  l'invariant 3 tient — mais la représentation *vivante* est perdue).
- **M8. Rejeu de tours sans horizon temporel** — `backend/pipeline/turns.py:265`.
  `awaiting_reply` sans borne d'âge : une question d'il y a une semaine est rejouée au boot
  et répondue avec l'humeur et le journal d'aujourd'hui.
- **M9. Course à l'arrêt sur `person_moods`** — `backend/emotion/engine.py:208`.
  `_save_state()` itère le dict avec awaits *avant* d'annuler la boucle de decay qui peut
  évincer pendant l'itération.
- **M10 (requalifié). Écritures croisées digestion/conscience sur `Rumination`** —
  `backend/memory/sleep.py:917` : réel et **REPRODUIT** (résurrection d'une rumination
  résolue), mais l'effet s'auto-résorbe en minutes dans une fenêtre nocturne étroite →
  mineur ; le résidu durable est sémantique (`faded` au lieu de `resolved`).

## REQUALIFIÉS / RÉFUTÉS en tant que bugs (2)

- **Journal/rêve injectés pour tout interlocuteur** (`backend/pipeline/context.py:255`) :
  mécanique exacte (le récit nocturne nomme les personnes et est servi à un inconnu,
  invitation à le mentionner comprise), mais le sceptique l'a jugé compromis documenté —
  requalifié **mineur**, tension de design réelle à arbitrer, pas un bug.
- **Dérive des ruminations : aucune issue positive stable**
  (`backend/conscience/engine.py:615`) : REPRODUIT (hopeful→anxious en ~2 min, ancre
  `updated_at` jamais rafraîchie par les `bulk_update`) mais documenté comme mélancolie
  voulue — requalifié **mineur/style**. À noter quand même : un élan de joie devient
  mécaniquement de l'anxiété dans le prompt suivant.

## STYLE (1)

- **La voix du comité dans les couches émotionnelles** — `backend/emotion/state.py:142`,
  REPRODUIT. « tu te sens a peine amused (intensite: 0.3) », tendance « warming », teinte
  « excited » : chiffres bruts et libellés anglais dans la prose française, exactement ce que
  le dépôt s'interdit pour le bloc identité (« never prints a number »). Un modèle moyen les
  recite.

---

## Lecture d'ensemble

Le fil commun des deux bloquants et de S1–S7 : **le seul endroit où l'émotion « existe » à
l'échelle d'une conversation est le tag que le LLM s'auto-attribue** — et le système le jette
(snapshot pré-impulsion, frame speech pré-impulsion, palette d'extraction amputée).
L'oscillateur, lui, est trop rapide pour être lu par quiconque. Deux directions possibles :
soit des constantes de temps par personne de l'ordre de la conversation (minutes/heures),
soit assumer le tag comme source de vérité du tour et l'archiver comme tel.

Deuxième fil : **la frontière de l'intime tient dans `_fetch_person_context` et nulle part
ailleurs** (S11, S12, et le journal en mineur).

Troisième fil : **le registre de dégradations s'arrête au seuil de la psyché** (S13, S16,
S17, S18, M4, B1) — le test « 72 sites câblés » mesure la plomberie, pas les organes.

**Reste à faire** : 7 constats sérieux au statut plausible et 16 vérifications non exécutées
(audit interrompu). Journaux complets de l'audit (constats intégraux, verdicts, méthodes de
repro, scripts dans le scratchpad de la session) :
`~/.claude/projects/-home-Qwartz-Bureau-PROJET-IA-vtuber/b7617e2f-504f-414c-b024-459657bfb28b/subagents/workflows/wf_145d6c48-0c5/journal.jsonl`.

---

# Guide de correction (pour une autre session)

## Avant de toucher quoi que ce soit

1. **Lire `CLAUDE.md`** (racine) en entier : la plupart des mécanismes touchés y sont
   documentés avec leurs raisons. Ne pas défaire un choix documenté sans le comprendre.
2. **Tests** : `python -m pytest backend/tests/` avant/après (python3 système, base en
   mémoire ; exclure les 2 flaky documentés via `--deselect`). Frontend :
   `cd frontend && npx vitest run` + `npm run build` (tsc = gate).
3. **Ne jamais toucher `data/`** (SQLite vivante + ChromaDB de l'installation).
4. **Trois tests pinnent des comportements que certaines corrections changent exprès** —
   les mettre à jour fait partie du correctif, pas le contourner :
   `test_emotion_sync.py` (pin « l'impulsion n'est pas visible dans
   `compute_message_emotion` » → B2/S2), `test_prompt_layers.py` (pin « seule
   `emotion_context` est project-muted » → S8), `test_retention.py` (cohérence des
   politiques → P2).
5. **Les items `design qui se retourne` (B1, B2, S5, S7, S8, S12, P5) demandent un
   arbitrage utilisateur avant correction** — ce sont des choix, pas des fautes de frappe.
   Les items `bug` se corrigent directement.
6. Conventions du dépôt : nouveaux réglages → registre de config (dashboard), jamais
   `.env` ; labels de dégradation = prose courte pour le hot path, `module.function`
   ailleurs ; textes visibles en français ; chaque correctif accompagné d'un test
   non-vacueux (vérifier qu'il rougit sur l'ancien code).

## Pistes par constat

**B1 (gate sommeil)** — Deux corrections cumulables : (a) l'entrée de nuit ne doit pas
dépendre d'un REST volatil : entrer en sommeil sur `nuit + idle ≥ 900s` seuls, REST ne
servant qu'à avancer l'heure d'entrée ; (b) persister l'état des drives (snapshot périodique
+ rechargement au boot, comme `EmotionEngine._save_state`). Corriger aussi l'`except` du
gate : ne pas forcer `rest_tension=0.0` (fail-closed) et compter via
`degradations.record`. Vérif : étendre `test_sleep_rest_recovery.py` (soirée calme → dort
quand même ; reboot 22h50 → dort quand même).

**B2 (échelle de temps PAD)** — Arbitrage requis entre : (a) constantes de temps par
personne de l'ordre de la conversation (minutes — retoucher `_recompute_params`,
`emotion/engine.py:167-174`, pour que ζ/ω₀ donnent un retour en ~10-30 min) ; (b) assumer le
tag `[EMOTION:]` comme vérité du tour : le persister tel quel (snapshot, fiche, frame
speech) et garder l'oscillateur pour la dérive entre tours. (b) est le moins invasif et
règle S2/S7 en même temps. Dans les deux cas, ajouter un cliquet d'escalade (impulsions
répétées de même signe → position qui monte, pas seulement la vélocité).

**S1 (tag absent = impulsion vers zéro)** — `extract_emotion`
(`emotion/types.py:75-85`) doit distinguer « pas de tag » (retour `None`) de « tag
neutral » ; `processor.py:280` saute `process_emotion` sur `None` ; nom inconnu →
`degradations.record("emotion: tag inconnu", ...)` au lieu d'un silencieux NEUTRAL.
Vérif : tour sans tag → oscillateur intouché (position ET vélocité).

**S2 (snapshot pré-impulsion)** — Après (B2-b) : persister l'émotion du tag dans
`EmotionSnapshot`. Sinon : relever la position *projetée* post-impulsion (la dynamique
connaît position+vélocité ; exposer `peak_projection()` dans `dynamics.py`) et poser le
timestamp du throttle à la *dernière* écriture, pas la première (`engine.py:507-512`).

**S3 (« comme d'habitude »)** — `emotion/state.py:173` : supprimer
`or label == default_mood`, ou brancher sur l'intensité : `< 0.1` → « comme d'habitude »,
`> 0.6` → « nettement plus que d'habitude ». Une ligne + un test.

**S4 (débordement global mort)** — `emotion/engine.py:605` : la cible est déjà réduite
par `impulse_gain = global_bleed` dans `_global_params` (`engine.py:180`) — le
`scale(target, global_bleed)` de la ligne 605 double la réduction. Supprimer le scale de la
ligne 605 (garder le gain). Vérif numérique : 20 min d'impulsions I=1.0 doivent pouvoir
franchir 0.7 (Facteur 3 atteignable), test pur sans Django.

**S5 (stance qui s'évapore vers le home global)** — Arbitrage : le home des oscillateurs
*par personne* devrait être un ancrage personnel (EMA des snapshots de cette personne, repli
= home circadien pour un inconnu), et l'enveloppe de retour doit dépendre réellement de
`recovery_speed` (aujourd'hui c/2m est quasi constant — corriger `_recompute_params` pour
que le curseur change l'enveloppe, pas la raideur). Cible : une vexation reste lisible
~10-30 min.

**S6 (palette 7/29)** — `extractor.py:27` : générer la liste depuis `emotion/types.py`
(les 29, ou un sous-ensemble choisi mais incluant scared/anxious/frustrated/lonely…) ;
`consolidator.py:335` : valider avec `Emotion(...)` et replier sur neutral +
`degradations.record` si inconnu. Vérif : intersection non vide avec le set négatif de
`sleep.py:735-736` pour peur/angoisse (cauchemars possibles).

**S7 (gestes jamais synchrones)** — Avec (B2-b) : la frame `speech` porte le tag du LLM →
le seuil des one-shots devient franchissable au moment où elle parle. Garder la porte
`ambient` telle quelle pour `emotion_update`. Vérif : test vitest existant sur
`decideGesture` + un test backend que la frame speech porte l'émotion du tag.

**S8 (mode pro : 1 canal sur 6)** — Étendre `muted_by_project` dans `_LAYERS`
(`prompt.py:111-124`) à : fatigue (`etat_cognitif`), rêve, mood-hint, ruminations (au
choix de l'arbitrage), et nettoyer les tags `[emotion]` du rendu mémoire quand
`emotion_policy=OFF`. Mettre à jour le pin de `test_prompt_layers.py` en conséquence.

**S9 (budget : outils jamais comptés, pas de borne globale)** — (a) Passer `tools_chars`
aux deux appelants de `budget_for` (`ai/budget.py:138`, `retriever.py:205`) — l'estimation
existe côté `module_manager` (déclarations d'outils collectées) ; (b) ajouter une passe
finale d'assemblage : si l'estimation totale du tour dépasse `usable`, tronquer les couches
volatiles dans un ordre déclaré (mémoire en dernier, planchers respectés) et compter la
troncature. Vérif : reproduire l'arithmétique 16 384 → le pire cas doit tenir.

**S10 (speaker perdu)** — `ChatPrompt.chat_messages()` et `legacy_pair()`
(`ai/chat.py`) : préfixer le contenu des tours portant `speaker` par `"<nom>: "`.
Vérif : test qui construit un buffer à deux locuteurs et inspecte le payload provider.

**S11 (outils MCP mémoire sans gate)** — Dans `memory/module.py`, lire
`current_person_id()` (`pipeline/tracing.py:49` — le ContextVar existe pour ça, cf.
`identity/module.py:209`) ; si l'appelant est une personne externe : filtrer
souvenirs/connaissances/engagements au périmètre autorisé par
`may_disclose_private_context` (les internes — conscience, projets — gardent l'accès
complet). Vérif : étendre `test_memory_tools.py` (inconnu → refus poli, interne → accès).

**S12 (préparation : verbatim d'autrui)** — `preparation.py:291-298` : transmettre
l'identité de l'interlocuteur à `execute_plan` ; si `rappel.person` résout vers une autre
identité que la sienne et que l'appelant n'est pas interne, ne pas exécuter
`echanges_passes` (ou le rerouter vers la même politique « own identity only » que la voie
chaude, `episodic/api.py`). Vérif : « qu'est-ce que Thomas t'a dit hier ? » posé par Bob →
zéro chunk de Thomas dans le prompt.

**S13 (checkpoint sur extraction en échec)** — `extractor.analyze_messages` doit
distinguer « échec transport » (retour `None`) de « rien à extraire » (`[]`) ;
`consolidator.py:175-179` : sur `None`, **ne pas** sauver le checkpoint,
`degradations.record`, retenter au tick suivant. Vérif : stub qui timeout → checkpoint
inchangé ; stub qui rend `[]` → checkpoint avancé.

**S14 (narratif toutes-époques)** — `narrative.py:183-189` : échantillonner le vécu
*récent* (fenêtre depuis `last_souvenir_id` ou N jours) en majorité + quelques ancres
top-importance, plutôt que le top-25 absolu. Vérif : une semaine riche à importance 0.5
doit changer le texte d'entrée.

**S15 (decay détruit un boost)** — `consolidator.py:673-697` : mise à jour
conditionnelle — `F('importance')` ou `UPDATE ... WHERE decayed_at = <valeur lue>` — et
relire la ligne juste avant tout `delete()` ; ne supprimer que si la relecture est sous le
seuil. Vérif : test de course simulée (booster entre lecture et écriture).

**S16 (amnésie non comptée)** — `manager.py:318-322` et `:343-345` +
`context.py:172-176` : ajouter `degradations.record("rappel memoire", exc)` (une ligne par
site, motif déjà présent 13 fois dans ces fichiers). Optionnel (arbitrage) : une ligne de
prompt « (ta mémoire longue est indisponible en ce moment) » pour que Mika puisse le dire.

**S17 (boucles sans filet compté ni âge)** — `periodic.py:91-94` :
`degradations.record(f"loop {self.name}", exc)` (module pur → importer utils.degradation,
pur aussi) ; idem `conscience/engine.py:309-310`. Ajouter `last_success_at` par boucle,
exposé sur `/gestion/systeme/sante/` avec l'âge (« consolidateur : dernier tick réussi il y
a 3 j » doit se voir). Vérif : `test_degradation.py` + un test de vue santé.

**S18 (échecs LLM nocturnes non comptés + timeout irréaliste)** —
`sleep.py:613-621`/`:793-801` et `extractor.py:178-189`/`:233-238`/`:292-303` :
`degradations.record` sur chaque chemin transport. `SLEEP_LLM_TIMEOUT` (45 s,
`sleep.py:106`) → réglage du registre de config, défaut ≥ 120 s (aligné sur
`ai.call_timeout_seconds` et les 76–219 s mesurés en local).

**P1 (mood-hint sur l'échafaudage)** — À contre-vérifier d'abord (statut plausible), puis :
garder `user_mood_hint` sur l'intent (`REQUEST_RESPONSE` seulement) — la `Perception` porte
l'intent jusqu'à `gather_context`.

**P2 (rétention mange le checkpoint)** — `retention.py` : les politiques
`ConsolidationLog`/`EpisodicIndexLog` doivent protéger la ligne la plus récente
(`keep_rows=1` en plancher, ou `protect` sur le max id). Le test de cohérence de
`test_retention.py` doit l'imposer pour toute table-checkpoint.

**P3 (souvenir fantôme)** — `retriever.py:445` (`_enrich_souvenirs`) : si le chargement
ORM a *réussi* mais que le pk manque → écarter le hit, planifier `remove_souvenir` (Chroma)
et compter. Ne garder le repli « servir Chroma tel quel » que si `loaded is None`.

**P4 (double extraction jour/nuit)** — `reorg.py` : soit marquer les chunks déjà extraits
au fil de l'eau et n'envoyer à l'extracteur que les manquants, soit réserver la réorg au
clustering/dédup sans ré-extraction. Corriger M6 en même temps (sinon les doublons datés du
jour surclassent les originaux).

**P5 (conscience ignore le sommeil)** — Arbitrage : ajouter un facteur sommeil au scoring
(`DecisionContext` + `scoring.py` : phase ≠ awake → malus fort ou veto des actes non
urgents), et/ou réserver la voix pendant le sommeil au persona INNER dans
`decide_voice`. Vérif : `_score` à 3h en deep_sleep < seuil.

**P6 (réveil = effet de bord du succès)** — Réveiller sur la *perception* : dans
`router.perceive()` (ou au début de `process_message`), sur `REQUEST_RESPONSE` d'une vraie
personne, notifier `conscience`/`sleep_cycle` (maj `_last_activity` / sortie de phase)
*avant* l'appel IA, pour que le broadcast lise une phase éveillée et qu'un tour en échec
réveille quand même.

**P7 (3 semaines = 25 min)** — Injecter le temps : « dernière interaction avec cette
personne » (max `Message.created_at` du handle, ou registre de présence) rendu en prose
dans le bloc personne (« vous ne vous êtes pas parlé depuis trois semaines ») ; horodater
les segments d'historique réhydratés au-delà d'un gap (préfixe « [il y a N jours] ») ;
optionnel : croissance SOCIAL log-temps pour que la ligne des pulsions distingue les
échelles.

**M1 (rêve brûlé)** — Déplacer `mark_dream_recalled` (`context.py:618-620`) après le
succès du tour : le processor connaît `ai_failed` ; marquer dans la branche succès (ou via
`_turn.completed`). Le rêve doit survivre à un fallback.

**M2 (répétition du rappel)** — Mémo par conversation des pks servis récemment (RAM, TTL
quelques tours, dans le retriever ou `ConversationContext`), exclu des sections association
/ intrusion / top souvenirs ; étendre `exclude_pks` au-delà du tour courant.

**M3 (entêtes vides)** — `retriever.py:694/706/724` (`_format_context`) : construire le
corps de section d'abord, n'append l'entête que si le corps est non vide.

**M4 (digestion muette)** — `sleep.py:871-872` et `:921-922` : remplacer par
`degradations.record` / `with degraded("sleep: digestion")`.

**M5 (deux horloges)** — `consolidator.py:822-823` : `timezone.now().date()` →
`date.today()` (l'horloge unique du dépôt). Étendre le test « une horloge » pour couvrir
`timezone.now().date()` en plus de `timezone.localdate()`.

**M6 (occurred_at faux)** — `consolidator.py:338` (`_store_souvenir`) : propager le
`created_at` des messages de la fenêtre (min/max) jusqu'à l'extraction et dater le souvenir
du vécu, pas de l'extraction.

**M7 (résumé écrasé)** — `compaction.py:219` : garde de sanité — refuser un nouveau résumé
plus court que X% de (ancien + matière repliée) ou vide de contenu ; sur refus, garder
l'ancien, ne pas avancer `last_message_id`, compter.

**M8 (rejeu sans horizon)** — `turns.py:263-267` : borner l'âge (réutiliser
`resume_window_minutes`) ; au-delà, nettoyer le flag sans rejouer (la question reste dans
l'historique et sur la fiche).

**M9 (course à l'arrêt)** — `emotion/engine.py:132-135` : annuler `_decay_task` *avant*
`_save_state()`, et itérer `list(self.person_moods.items())`.

**M10 (écritures croisées Rumination)** — Mises à jour conditionnelles : la digestion
relit chaque ligne juste avant son `save` et saute si `status`/`intensity` ont bougé ;
ou `UPDATE ... WHERE intensity = <lu>`. Pas besoin de verrou inter-boucles.

## Ordre suggéré

1. **Lot « compté »** (S16, S17, S18, M4, B1-except, M5) : mécanique, sans arbitrage,
   petit diff, rend toutes les autres pannes visibles — à faire en premier.
2. **Lot « intégrité mémoire »** (S13, S15, P2, P3, M1, M6, M7, M8) : bugs purs, testables
   unitairement.
3. **Lot « frontière »** (S11, S12, S10) : après arbitrage rapide sur la politique exacte.
4. **Lot « affect »** (B2 + S1, S2, S3, S4, S6, S7, S5) : commence par l'arbitrage B2
   (tag-vérité vs constantes lentes) — le choix conditionne S2 et S7.
5. **Lot « rythme de vie »** (B1, P5, P6, P7, S14, S8) : après arbitrage design.
6. Relancer la contre-vérification des 16 constats restants (P1-P7 + mineurs non vérifiés)
   avant de corriger ceux-là — journaux et scripts de repro dans le dossier du workflow
   ci-dessus.
