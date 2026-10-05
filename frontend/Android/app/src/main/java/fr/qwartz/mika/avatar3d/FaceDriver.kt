package fr.qwartz.mika.avatar3d

import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.random.Random

/**
 * Le visage de Mika, image par image — port pur des quatre couches du client web (`frontend/Web/src/vtuber/`), qui
 * composent sans arbitrage parce qu'elles écrivent des groupes disjoints :
 *
 *  - l'émotion (`EmotionController.ts`) : les groupes du modèle (`Smile1`, `Sad1`…) dans leur copie « propre »
 *    (`faceRig.ts` : sans les symboles manga ni les morphoses du regard), l'apparition à la vitesse propre de
 *    l'émotion, la disparition plus lente, l'émotion secondaire du mélange à une part de son poids, une respiration
 *    de quelques pour cent qui empêche un visage tenu de se figer, et les paupières lourdes de la fatigue (`Sleepy`) ;
 *  - la physiologie (`FacePhysiology.ts`) : rougeur, larmes, pupilles, sur leurs propres horloges, lentes ;
 *  - le clignement (`BlinkController.ts`) : cadence irrégulière modulée par l'émotion, la parole et la fatigue,
 *    clignements évoqués par un saut du regard, yeux fermés pendant le sommeil et frémissement du sommeil paradoxal ;
 *  - les micro-mouvements (`FaceIdleController.ts`) : dérive continue et asymétrique des formes ARKit du modèle,
 *    accents par émotion, sourcils levés par les temps forts de la parole ;
 *  - la bouche qui parle (`LipSyncController.ts`, voir [LipSync]) : les visèmes `vrc.v_*` du texte de sa réponse,
 *    au rythme où la bulle l'affiche ([startSpeech], [seekSpeech]), sous un plafond qui laisse la place à la bouche
 *    que l'émotion dessine déjà.
 *
 * Sort des poids par NOM de morphose (le moteur les retrouve dans chaque maillage : le visage est découpé par
 * matériau). Comme three-vrm, chaque groupe est d'abord borné à 0…1 puis ses liens s'additionnent (`+=`) ; la somme
 * est ensuite bornée à 0…1 (three.js ne la borne pas, mais un poids au-delà de 1 déforme). Une morphose à 0 est
 * omise : [AvatarSurface.setMorphs] remet à zéro ce qui n'est pas nommé.
 *
 * Pur : ni Android ni Filament, testé sur la JVM ; le hasard (cadence des clignements) est injecté.
 *
 * Ce qui n'est pas porté : la table de repli sur les préréglages standard (`STANDARD_EMOTION_MAP`, pour un modèle
 * sans les groupes de Perula — une recette incomplète ne montre ici rien, comme `neutral`), et la source des temps
 * forts de la parole (`SpeechBodyOverlay`, qui suit le curseur du lip-sync) : [setSpeechBeat] en attend la valeur.
 *
 * `morphNames` : les morphoses que porte le modèle (`VrmDocument.morphNames`), pour que la bouche se replie sur les
 * préréglages a/i/u/e/o d'un modèle sans visèmes VRChat. Sans elles, les visèmes sont supposés présents — c'est le
 * cas du modèle de Mika ; un nom absent du maillage serait de toute façon ignoré par [AvatarSurface.setMorphs].
 */
class FaceDriver(
    expressions: Map<String, VrmDocument.Expression>,
    private val random: Random = Random.Default,
    morphNames: Set<String>? = null,
) {
    /**
     * Un groupe résolu en ses liens ; un groupe binaire est tout ou rien, comme `VRMExpression.outputWeight`.
     * `mouth` : ce qu'il fait à la bouche quand il est plein ([LipSync.mouthInvolvement]) — la parole lui laisse la
     * place.
     */
    private class Group(val binds: List<VrmDocument.Bind>, val binary: Boolean) {
        val mouth: Float = LipSync.mouthInvolvement(binds)
    }

    /** Les groupes des recettes et de la fatigue, sans symboles ni regard (les copies `clean:` du web). */
    private val cleanGroups: Map<String, Group>
    /** Recette par émotion, réduite à rien quand le modèle n'a pas tous ses groupes (une recette amputée serait une
     * autre expression que celle que l'auteur a réglée). */
    private val recipes: Map<String, Map<String, Float>>
    private val tiredAvailable: Boolean
    private val blinkGroup: Group?
    /** Les formes ARKit que le modèle expose, telles quelles (le web ne les nettoie pas). */
    private val idleGroups: Map<String, Group>
    /** La bouche qui parle : ses propres morphoses (`vrc.v_*`), qu'aucune autre couche n'écrit. */
    private val lip = LipSync(morphNames)
    /** Les préréglages de bouche du repli, par nom three-vrm (`aa`…) : un VRM 0.x les range sous a, i, u, e, o. */
    private val presetGroups: Map<String, Group>

    init {
        val wanted = LinkedHashSet<String>()
        EMOTION_RECIPES.values.forEach { wanted.addAll(it.keys) }
        wanted.add(TIRED_GROUP)
        cleanGroups = wanted.mapNotNull { name ->
            expressions[name]?.let { e -> name to Group(e.binds.filterNot { isStripped(it.name) }, e.binary) }
        }.toMap()
        recipes = EMOTION_RECIPES.mapValues { (_, recipe) ->
            if (recipe.isNotEmpty() && recipe.keys.all { it in cleanGroups }) recipe else emptyMap()
        }
        tiredAvailable = TIRED_GROUP in cleanGroups
        // Le web écrit le préréglage `blink` (three-vrm range un groupe VRM 0.x à préréglage sous ce nom), pas le
        // groupe nommé « Blink » : le modèle en a deux, le préréglage (`まばたき`) et un groupe maison qui baisse aussi
        // les sourcils. Le nom ne vient qu'en repli.
        blinkGroup = (expressions.values.firstOrNull { it.preset.equals(BLINK_PRESET, ignoreCase = true) }
            ?: expressions[BLINK_GROUP])?.let { Group(it.binds, it.binary) }
        val idleNames = LinkedHashSet<String>()
        MICRO_CHANNELS.forEach { idleNames.add(it.name) }
        idleNames.addAll(SPEECH_BROWS.keys)
        EMOTION_ACCENT.values.forEach { idleNames.addAll(it.keys) }
        idleGroups = idleNames.mapNotNull { name -> expressions[name]?.let { name to Group(it.binds, it.binary) } }.toMap()
        presetGroups = LipSync.MOUTH_PRESETS.mapNotNull { preset ->
            (expressions[preset] ?: expressions[VRM0_MOUTH_PRESET.getValue(preset)])
                ?.let { preset to Group(it.binds, it.binary) }
        }.toMap()
    }

    // --- Entrées ---

    private var emotion = NEUTRAL
    private var intensity = 0.5f
    private var blendKey = ""
    private var sleepPhase = AWAKE
    private var speaking = false
    /** Fatigue 0 (fraîche) … 1 (épuisée), tirée de l'énergie du serveur. */
    private var fatigue = 0f
    /** Le saut du regard noté depuis la dernière image ; consommé par elle. */
    private var gazeShift = 0f
    private var speechEmphasis = 0f
    private var speechQuestion = 0f

    /** Une horloge en double : des heures de session en `Float` hacheraient les sinus de la respiration. */
    private var time = 0.0
    /** Ce que les expressions écrites cette image laissent de la bouche intacte (« ou » probabiliste de leurs
     * charges : deux demi-sourires ne comptent pas double). */
    private var mouthUntouched = 1f

    /** Elle parle : l'appelant le dit ([setSpeaking]), ou sa bouche joue le texte d'une réponse. */
    private val talking: Boolean get() = speaking || lip.isSpeaking

    // --- Émotion ---

    private val targetWeights = LinkedHashMap<String, Float>()
    private val currentWeights = LinkedHashMap<String, Float>()
    /** Paupières lourdes d'un visage fatigué (`Sleepy`), 0…[TIRED_MAX]. */
    private var tiredTarget = 0f

    // --- Physiologie ---

    private var blush = 0f
    private var watery = 0f
    private var tear = 0f
    private var pupil = 0f
    /** La charge de larmes : monte avec une tristesse forte, se vide lentement. */
    private var tearLoad = 0f

    // --- Clignement ---

    private var blinkTimer = 0f
    private var nextBlinkAt = 3f + random.nextFloat() * 2f
    private var eyeClosure = 0f
    private var remFlickerTimer = 0.0
    private var blinking = false
    private var elapsed = 0f
    private var shape = QUICK
    /** Un second clignement rapide suit celui-ci (le double clignement humain). */
    private var doublePending = false
    /** Le clignement qui va partir EST ce second temps : il ne se re-tire jamais. */
    private var secondBeatArmed = false
    /** Le poids du groupe de clignement : il ne change que là où le web l'écrit (`setValue`), et garde sinon sa
     * dernière valeur, comme une expression three-vrm. */
    private var blinkWeight = 0f

    // --- Micro-mouvements ---

    /** Accents adoucis, par forme. */
    private val accent = LinkedHashMap<String, Float>()

    /** L'émotion que le visage montre (un nom inconnu est devenu `neutral`). */
    val currentEmotion: String get() = emotion
    val currentIntensity: Float get() = intensity

    /**
     * L'émotion d'une réplique ou de la dérive de l'humeur. `blend` est le mélange du serveur (émotion, poids), du
     * plus fort au plus faible : la plus forte autre que la principale se montre à une part de son poids. Un nom hors
     * des 29 retombe sur `neutral`.
     */
    fun setEmotion(emotion: String, intensity: Float = 0.7f, blend: List<Pair<String, Float>> = emptyList()) {
        val name = if (emotion in EMOTION_SET) emotion else NEUTRAL
        val clamped = if (intensity.isNaN()) 0f else intensity.coerceIn(0f, 1f)
        val secondary = secondaryOf(name, blend)
        val key = secondary?.let { "${it.emotion}:${(it.ratio * 100).roundToInt()}" } ?: ""
        if (name == this.emotion && clamped == this.intensity && key == blendKey) return

        this.emotion = name
        this.intensity = clamped
        blendKey = key

        // La bouche articule à la mesure de ce qu'elle ressent (`affect.articulationFor`), comme le web l'applique à
        // chaque émotion que le visage reçoit.
        lip.setArticulation(LipSync.articulationFor(name, clamped, fatigue))

        // La secondaire se montre à une part de son poids et fait de la place dans la principale.
        val primaryScale = if (secondary != null) 1f - 0.25f * secondary.ratio else 1f
        targetWeights.clear()
        for ((group, w) in recipes[name].orEmpty()) targetWeights[group] = w * clamped * primaryScale
        if (secondary != null) {
            val share = clamped * secondary.ratio * SECONDARY_SHARE
            for ((group, w) in recipes[secondary.emotion].orEmpty()) {
                targetWeights[group] = min(1f, (targetWeights[group] ?: 0f) + w * share)
            }
        }
    }

    /** Énergie 0…1 : passé ~0,55 de fatigue, les paupières s'alourdissent — lentement, ce n'est pas une expression —
     * et les clignements ralentissent. */
    fun setEnergy(energy: Float) {
        if (energy.isNaN()) return
        fatigue = ((0.55f - energy) / 0.4f).coerceIn(0f, 1f)
        tiredTarget = TIRED_MAX * fatigue
        // Le web ne relit la fatigue qu'à l'émotion suivante ; ici elle compte tout de suite — une bouche lasse ne
        // l'est pas qu'à partir de la prochaine réplique.
        lip.setArticulation(LipSync.articulationFor(emotion, intensity, fatigue))
    }

    /** « awake », « light_sleep », « rem », « deep_sleep » ; une phase inconnue vaut l'éveil (`resolveSleepPhase`). */
    fun setSleepPhase(phase: String) {
        sleepPhase = if (phase in PHASE_EYE_CLOSURE) phase else AWAKE
    }

    fun setSpeaking(speaking: Boolean) {
        this.speaking = speaking
    }

    /** Le saut que les yeux viennent de faire (rad) : un grand saut entraîne parfois un clignement. Plusieurs sauts
     * entre deux images comptent pour le plus grand. */
    fun noteGazeShift(magnitude: Float) {
        if (magnitude > gazeShift) gazeShift = magnitude
    }

    /** Les temps forts de la parole, 0…1 et décroissants : un mot appuyé fait lever les sourcils, une question les
     * tient levés. Publiés par la couche de parole du corps (`SpeechBodyOverlay`, dans [BodyLayers]). */
    fun setSpeechBeat(emphasis: Float, question: Float) {
        speechEmphasis = if (emphasis.isNaN()) 0f else emphasis.coerceIn(0f, 1f)
        speechQuestion = if (question.isNaN()) 0f else question.coerceIn(0f, 1f)
    }

    /**
     * Elle commence à dire `text` — sa réponse telle qu'elle s'affiche, Markdown léger et jetons de prosodie compris :
     * `[PAUSE:ms]`, `[SIGH]`, `[LAUGH]`, `[BREATH]` sont des silences de leur durée (la bouche se ferme), un `*` ne
     * se dit pas (la bouche glisse dessus comme sur un blanc). `msPerChar` : la cadence d'affichage, en ms par
     * caractère. Un nouveau texte remplace le précédent sans que la bouche saute : elle part de sa forme du moment.
     */
    fun startSpeech(text: String, msPerChar: Float) {
        val ms = if (msPerChar.isFinite() && msPerChar > 0f) msPerChar.toDouble() else LipSync.DEFAULT_MS_PER_CHAR
        lip.startFromPlan(LipSync.speechPlan(text), ms)
    }

    /**
     * Où en est l'affichage : `charIndex` est l'indice, dans le texte passé à [startSpeech], du caractère qui apparaît
     * (le nombre de caractères déjà affichés). Fait pour être appelé à CHAQUE image : tant que la bouche suit le
     * texte, la lecture n'est pas touchée ; si elle s'en écarte, elle rattrape en douceur ; un vrai saut (toute la
     * réponse affichée d'un coup) la fait taire proprement ([LipSync.trackChar]).
     */
    fun seekSpeech(charIndex: Int) {
        lip.trackChar(charIndex)
    }

    /** Elle se tait : la bouche se referme en douceur, à la vitesse d'une bouche qui se détend. */
    fun stopSpeech() {
        lip.stop()
    }

    /** Sa bouche joue encore le texte d'une réponse. */
    val isSpeechPlaying: Boolean get() = lip.isSpeaking

    /** Avance de `dt` secondes ; rend le poids (0…1) de chaque morphose pilotée cette image. */
    fun update(dt: Float): Map<String, Float> {
        // Un pas invalide empoisonnerait l'état pour toujours (un NaN ne se résorbe pas).
        val step = if (dt > 0f && dt.isFinite()) dt else 0f
        time += step
        val out = HashMap<String, Float>()
        mouthUntouched = 1f
        updateEmotion(step, out)
        updatePhysiology(step, out)
        updateBlink(step)
        gazeShift = 0f
        blinkGroup?.let { addGroup(it, blinkWeight, out) }
        updateIdle(step, out)
        updateSpeech(step, out)
        val entries = out.entries.iterator()
        while (entries.hasNext()) {
            val e = entries.next()
            if (!(e.value > 0f)) entries.remove() else if (e.value > 1f) e.setValue(1f)
        }
        return out
    }

    // --- Émotion ---

    private fun updateEmotion(dt: Float, out: MutableMap<String, Float>) {
        // Apparition à la vitesse de l'émotion, disparition plus lente — par forme, car celle qui part (l'émotion
        // d'avant) et celle qui arrive coexistent.
        val onset = min(1f, dt * onsetSpeedFor(emotion))
        val offset = min(1f, dt * offsetSpeedFor(emotion))
        val names = LinkedHashSet<String>(targetWeights.keys)
        names.addAll(currentWeights.keys)
        if (tiredAvailable && tiredTarget > 0f) names.add(TIRED_GROUP)

        var seed = 0
        for (name in names) {
            seed++
            val tired = if (tiredAvailable && name == TIRED_GROUP) tiredTarget else 0f
            val target = (targetWeights[name] ?: 0f) + tired
            val current = currentWeights[name] ?: 0f
            val lerp = if (target > current) onset else offset
            val value = current + (target - current) * lerp
            if (target == 0f && value < 0.001f) {
                // Tout à fait éteinte : plus suivie (son 0 est l'absence de la sortie).
                currentWeights.remove(name)
                continue
            }
            // On suit la valeur adoucie nette ; la respiration ne teinte que ce qui sort, elle ne s'accumule pas.
            currentWeights[name] = value
            val shaded = value * (1f + pulse(time, seed) * PULSE_AMPLITUDE)
            cleanGroups[name]?.let { addGroup(it, shaded, out) }
        }
    }

    // --- Physiologie ---

    private fun updatePhysiology(dt: Float, out: MutableMap<String, Float>) {
        val i = intensity.coerceIn(0f, 1f)

        val blushTarget = (BLUSH[emotion] ?: 0f) * smoothstep(0.2f, 0.9f, i)
        blush = approach(blush, blushTarget, dt, BLUSH_RISE_S, BLUSH_FALL_S)

        var drive = max(0f, (TEARS[emotion] ?: 0f) * i - TEAR_THRESHOLD)
        if (emotion == "amused" || emotion == "playful") drive = max(drive, (i - LAUGH_TEAR_FROM) * 2.5f)
        tearLoad = max(0f, tearLoad + (drive - TEAR_DECAY * tearLoad) * dt)
        watery = smoothstep(WATERY_FROM, WATERY_TO, tearLoad)
        tear = smoothstep(TEAR_FROM, TEAR_TO, tearLoad) * 0.9f

        val pupilTarget = (PUPIL[emotion] ?: 0f) * i
        val pupilTau = if (pupilTarget > pupil) PUPIL_WIDEN_S else PUPIL_NARROW_S
        pupil = approach(pupil, pupilTarget, dt, pupilTau, pupilTau)

        addRaw("FaceRed", blush, out)
        addRaw("EyeWatery", watery * 0.8f, out)
        addRaw("Tear", tear, out)
        val dilate = max(0f, pupil)
        val narrow = max(0f, -pupil)
        addRaw("EyeDilationLeft", dilate * 0.6f, out)
        addRaw("EyeDilationRight", dilate * 0.6f, out)
        addRaw("EyeConstrictLeft", narrow * 0.6f, out)
        addRaw("EyeConstrictRight", narrow * 0.6f, out)
    }

    // --- Clignement ---

    private fun updateBlink(dt: Float) {
        // Vers la fermeture de la phase : l'éveil laisse le cycle piloter, le sommeil tient les yeux presque clos.
        val target = PHASE_EYE_CLOSURE.getValue(sleepPhase)
        val rate = min(1f, dt / EASE_SECONDS * 4f)
        val diff = target - eyeClosure
        eyeClosure = if (abs(diff) < 0.0005f) target else eyeClosure + diff * rate

        if (sleepPhase == AWAKE) {
            // Fermeture résiduelle juste après le réveil : elle redescend avant que le cycle reprenne.
            if (eyeClosure > 0.02f) {
                blinkWeight = eyeClosure
                return
            }
            blinkCycle(dt)
            return
        }

        var value = eyeClosure
        // Le frémissement attend que les paupières soient vraiment près de la fermeture du sommeil paradoxal : son
        // plancher de 0,7 claquerait sinon les yeux d'un coup sur un passage direct éveil → rem.
        if (sleepPhase == REM && eyeClosure > 0.75f) {
            remFlickerTimer += dt
            value += (sin(remFlickerTimer * 8.0) * 0.04).toFloat()
            value = value.coerceIn(0.7f, 1f)
        }
        blinkWeight = value
    }

    private fun blinkCycle(dt: Float) {
        if (!blinking) {
            blinkTimer += dt
            val gazeEvoked = gazeShift >= GAZE_BLINK_MIN_SHIFT &&
                blinkTimer >= GAZE_BLINK_REFRACTORY_S &&
                random.nextFloat() < GAZE_BLINK_P
            when {
                blinkTimer >= nextBlinkAt -> startBlink(forcedQuick = false)
                gazeEvoked -> startBlink(forcedQuick = true)
                else -> return
            }
        }

        elapsed += dt
        val s = shape
        val total = s.close + s.hold + s.open
        val value = when {
            elapsed < s.close -> elapsed / s.close
            elapsed < s.close + s.hold -> 1f
            elapsed < total -> 1f - (elapsed - s.close - s.hold) / s.open
            else -> {
                blinking = false
                blinkTimer = 0f
                if (doublePending) {
                    // Second temps d'un double clignement : un court écart, puis un autre rapide. Le drapeau passe à
                    // `secondBeatArmed` plutôt que d'être consommé : startBlink part 70 ms plus tard et doit savoir que
                    // ce clignement est le second temps, pas un nouveau tirage.
                    doublePending = false
                    secondBeatArmed = true
                    nextBlinkAt = 0.07f
                } else {
                    nextBlinkAt = sampleInterval()
                }
                0f
            }
        }
        blinkWeight = value.coerceIn(0f, 1f)
    }

    private fun startBlink(forcedQuick: Boolean) {
        blinking = true
        elapsed = 0f
        blinkTimer = 0f
        if (forcedQuick) {
            // Un clignement qui accompagne un saut du regard est rapide et ne se double jamais.
            shape = QUICK
            doublePending = false
            return
        }
        if (secondBeatArmed) {
            // Rapide d'office, et sans nouveau tirage : un lent 70 ms après un rapide se lit comme un accroc, pas
            // comme un tic, et un tirage pourrait armer encore un double.
            secondBeatArmed = false
            shape = QUICK
            return
        }
        val heavy = emotion in HEAVY || fatigue > 0.5f
        val roll = random.nextFloat()
        if (roll < (if (heavy) 0.45f else 0.15f)) {
            shape = SOFT
        } else {
            shape = QUICK
            // Doubles seulement sur un rapide, et jamais paupières lourdes.
            doublePending = !heavy && roll > 0.85f
        }
    }

    private fun sampleInterval(): Float {
        var base = 2.5f + random.nextFloat() * 3f
        if (emotion in RESTLESS) base *= 0.65f else if (emotion in HEAVY) base *= 1.3f
        base *= 1f + 0.3f * fatigue // des paupières fatiguées clignent plus lentement et plus longtemps
        if (talking) base *= 0.85f // on cligne davantage en parlant
        return base
    }

    // --- Micro-mouvements ---

    private fun updateIdle(dt: Float, out: MutableMap<String, Float>) {
        if (idleGroups.isEmpty()) return
        val asleep = sleepPhase != AWAKE

        // Les accents vont vers ceux de l'émotion du moment.
        val target = if (asleep) null else EMOTION_ACCENT[emotion]
        val scale = 0.35f + intensity * 0.65f
        val ease = min(1f, dt * ACCENT_EASE)
        val names = LinkedHashSet<String>(accent.keys)
        target?.let { names.addAll(it.keys) }
        for (name in names) {
            val want = (target?.get(name) ?: 0f) * scale
            val current = accent[name] ?: 0f
            val next = current + (want - current) * ease
            if (want == 0f && next < 0.001f) accent.remove(name) else accent[name] = next
        }

        // Dérive + accent + temps forts, une valeur par forme.
        val values = LinkedHashMap<String, Float>()
        val microScale = if (asleep) SLEEP_MICRO_SCALE else 1f
        for (c in MICRO_CHANNELS) {
            if (c.name !in idleGroups) continue
            val boost = if (talking && c.talkBoost != null) c.talkBoost else 1f
            values[c.name] = (c.bias + noise(time * c.rate, c.seed) * c.amp * boost) * microScale
        }
        for ((name, w) in accent) {
            if (name !in idleGroups) continue
            values[name] = (values[name] ?: 0f) + w
        }
        // Ponctuation de la parole : les sourcils montent sur un mot appuyé et restent levés pendant une question.
        if (!asleep) {
            for ((name, b) in SPEECH_BROWS) {
                if (name !in idleGroups) continue
                val v = b.emphasis * speechEmphasis + b.question * speechQuestion
                if (v > 0.001f) values[name] = (values[name] ?: 0f) + v
            }
        }
        for ((name, v) in values) addGroup(idleGroups.getValue(name), v, out)
    }

    // --- Parole ---

    /**
     * Les visèmes, écrits en dernier comme sur le web (le lip-sync y lit les poids de cette image des autres
     * couches) : ses morphoses `vrc.v_*` ne sont écrites par personne d'autre, et leur somme cède la place à la
     * bouche que l'émotion et les micro-mouvements dessinent déjà. Sur un modèle sans visèmes, ce sont les
     * préréglages a/i/u/e/o — qui ne comptent pas dans la charge : c'est la parole elle-même.
     */
    private fun updateSpeech(dt: Float, out: MutableMap<String, Float>) {
        lip.update(dt)
        val load = 1f - mouthUntouched
        lip.forEachOutput(load) { name, w ->
            val preset = presetGroups[name]
            if (preset != null) addGroup(preset, w, out, countsForMouth = false) else addRaw(name, w, out)
        }
    }

    // --- Composition ---

    private fun addGroup(group: Group, weight: Float, out: MutableMap<String, Float>, countsForMouth: Boolean = true) {
        var w = weight.coerceIn(0f, 1f)
        if (group.binary) w = if (w > 0.5f) 1f else 0f
        if (!(w > 0f)) return
        for (b in group.binds) out[b.name] = (out[b.name] ?: 0f) + b.weight * w
        if (countsForMouth && group.mouth > 0f && w > 0.001f) mouthUntouched *= 1f - min(1f, w * group.mouth)
    }

    private fun addRaw(morph: String, weight: Float, out: MutableMap<String, Float>) {
        val w = weight.coerceIn(0f, 1f)
        if (w > 0f) out[morph] = (out[morph] ?: 0f) + w
    }

    /** Ce que le mélange donne de plus fort hors la principale, avec son poids relatif à elle. */
    internal data class Secondary(val emotion: String, val ratio: Float)

    /** La durée d'un clignement, en secondes : un vrai se ferme vite et se rouvre plus lentement ; un seul timing pour
     * tous est ce qui fait lire un métronome. */
    private class BlinkShape(val close: Float, val hold: Float, val open: Float)

    /** Un canal de dérive : amplitude, repos autour duquel il module (il reste continu plutôt que de toucher 0 la
     * moitié du temps), vitesse (différente à gauche et à droite) et surcroît en parlant. */
    internal class MicroChannel(
        val name: String,
        val amp: Float,
        val bias: Float,
        val rate: Float,
        val seed: Int,
        val talkBoost: Float? = null,
    )

    internal class SpeechBrow(val emphasis: Float, val question: Float)

    companion object {
        const val NEUTRAL = "neutral"
        const val AWAKE = "awake"
        private const val REM = "rem"

        /** Les 29 émotions du serveur (`emotion/types.py::Emotion`), dans l'ordre du web (`types/emotions.ts`). */
        val EMOTION_NAMES: List<String> = listOf(
            "neutral",
            "happy", "excited", "love", "proud", "grateful", "playful", "amused", "hopeful", "relieved",
            "sad", "angry", "scared", "disgusted", "frustrated", "lonely", "anxious", "bored", "jealous",
            "surprised", "thinking", "confused", "embarrassed", "nostalgic", "dreamy", "determined", "mischievous",
            "curious", "melancholic",
        )
        private val EMOTION_SET: Set<String> = EMOTION_NAMES.toSet()

        // --- Émotion (EmotionController.ts) ---

        /**
         * Recettes du modèle Perula (`PERULA_EMOTION_MAP`), poids à l'intensité 1. Les noms sont les groupes du modèle
         * (sensibles à la casse), joués dans leur copie propre : les sourcils, paupières et bouche de l'auteur, SANS
         * les symboles qu'il y a joints — `Shocked` dessinait des yeux en spirale et une goutte de sueur à chaque
         * surprise, `Sad1`/`Sad3`/`Angry1`/`LMAO` une larme à toute intensité, `Healthy` (déterminée) des cernes,
         * `BadSmile2` (jalouse) des yeux noirs, `Numbly` (réfléchit) des spirales, `Hau` (confuse) des yeux en ><. La
         * rougeur et les larmes viennent de la physiologie, sur leur propre horloge. Le standard `angry` du modèle est
         * vide : la colère passe forcément par ces groupes.
         */
        internal val EMOTION_RECIPES: Map<String, Map<String, Float>> = mapOf(
            "neutral" to emptyMap(),

            "happy" to mapOf("Smile1" to 1.0f),
            "excited" to mapOf("Joy2" to 0.9f, "InWonder" to 0.2f),
            "love" to mapOf("Love1" to 0.9f),
            "proud" to mapOf("Prond" to 0.9f), // sic — l'auteur du modèle écrit « proud » ainsi
            "grateful" to mapOf("Smile2" to 0.8f, "Relaxy" to 0.15f),
            "playful" to mapOf("Smile4" to 0.7f, "Wink1" to 0.25f),
            "amused" to mapOf("LMAO" to 0.8f),
            "hopeful" to mapOf("Smile3" to 0.5f, "InWonder" to 0.35f),
            "relieved" to mapOf("Relaxy" to 0.7f, "Smile2" to 0.2f),

            "sad" to mapOf("Sad1" to 0.85f),
            "angry" to mapOf("Angry4" to 0.7f, "Angry1" to 0.3f),
            "scared" to mapOf("Shocked2" to 0.7f, "Pain" to 0.25f),
            "disgusted" to mapOf("Disgust" to 0.85f),
            "frustrated" to mapOf("Angry2" to 0.6f, "GiveUp" to 0.25f),
            "lonely" to mapOf("Sad3" to 0.8f),
            "anxious" to mapOf("Pain" to 0.45f, "Sad1" to 0.25f),
            "bored" to mapOf("Boring" to 0.85f),
            "jealous" to mapOf("BadSmile2" to 0.5f, "Angry2" to 0.35f),

            "surprised" to mapOf("Shocked" to 0.9f),
            "thinking" to mapOf("Numbly" to 0.35f, "Interesting" to 0.15f),
            "confused" to mapOf("Hau" to 0.55f),
            "embarrassed" to mapOf("Shy" to 0.85f),
            "nostalgic" to mapOf("Sad2" to 0.3f, "Smile2" to 0.35f, "Relaxy" to 0.2f),
            "dreamy" to mapOf("InWonder" to 0.55f, "Relaxy" to 0.3f),
            "determined" to mapOf("Healthy" to 0.6f, "Angry4" to 0.2f),
            "mischievous" to mapOf("BadSmile1" to 0.65f, "Taunt1" to 0.2f),
            "curious" to mapOf("Interesting" to 0.75f),
            "melancholic" to mapOf("Sad2" to 0.55f, "Relaxy" to 0.2f),
        )

        /** Part d'une émotion secondaire montrée sur le visage, relative à son poids dans le mélange. Un vrai visage
         * est rarement une seule émotion : un sourire à travers la tristesse, l'inquiétude sous un rire. */
        const val SECONDARY_SHARE = 0.45f
        /** Sous ce rapport de poids, la secondaire est du bruit, pas un sentiment. */
        const val SECONDARY_MIN_RATIO = 0.3f

        /** Le visage ensommeillé du modèle (paupières lourdes, lèvres entrouvertes), nettoyé, au plus ceci sur un
         * visage éveillé fatigué. */
        const val TIRED_GROUP = "Sleepy"
        const val TIRED_MAX = 0.32f

        /** Respiration d'une expression tenue : quelques pour cent, pour qu'un visage ne soit jamais identique au bit
         * près d'une image à l'autre. */
        const val PULSE_AMPLITUDE = 0.05f

        /**
         * Vitesse d'apparition par émotion (1/s de l'approche exponentielle). Les expressions n'arrivent pas toutes à
         * la même vitesse : un sursaut en ~100–200 ms, un sourire en ~300–500 ms, la tristesse et la rêverie sur
         * presque une seconde. Et chacune REPART plus lentement qu'elle n'est venue ([OFFSET_RATIO]) — un visage qui
         * revient au neutre aussi vite qu'il s'est allumé est l'un des signes les plus sûrs d'un masque.
         */
        internal val ONSET_SPEED: Map<String, Float> = mapOf(
            "surprised" to 9f,
            "scared" to 8f,
            "excited" to 6f,
            "angry" to 5f,
            "amused" to 5f,
            "playful" to 5f,
            "disgusted" to 4.5f,
            "frustrated" to 4f,
            "curious" to 4f,
            "happy" to 3.5f,
            "sad" to 1.8f,
            "lonely" to 1.8f,
            "melancholic" to 1.6f,
            "nostalgic" to 1.6f,
            "dreamy" to 1.6f,
            "relieved" to 2.2f,
            "bored" to 2.0f,
            "love" to 2.2f,
            "grateful" to 2.5f,
            "hopeful" to 2.5f,
        )
        const val DEFAULT_ONSET_SPEED = 3.0f
        const val OFFSET_RATIO = 0.6f
        /** Une expression ne s'attarde jamais au-delà de ~0,8 s de constante de temps. */
        const val MIN_OFFSET_SPEED = 1.2f

        fun onsetSpeedFor(emotion: String): Float = ONSET_SPEED[emotion] ?: DEFAULT_ONSET_SPEED

        fun offsetSpeedFor(emotion: String): Float = max(MIN_OFFSET_SPEED, onsetSpeedFor(emotion) * OFFSET_RATIO)

        /** La plus forte du mélange hors la principale, avec son poids relatif ; `null` quand rien ne vaut d'être
         * montré. Seule la première candidate compte : sous le seuil, on ne cherche pas plus loin. */
        internal fun secondaryOf(primary: String, blend: List<Pair<String, Float>>): Secondary? {
            if (blend.size < 2) return null
            val top = blend.firstOrNull { it.first == primary }?.second ?: blend[0].second
            if (!(top > 0f)) return null
            for ((name, weight) in blend) {
                if (name == primary || name == NEUTRAL) continue
                if (name !in EMOTION_SET) continue
                val ratio = min(1f, weight / top)
                return if (ratio >= SECONDARY_MIN_RATIO) Secondary(name, ratio) else null
            }
            return null
        }

        /** Sinus lents et incommensurables : une expression tenue respire au lieu de se figer. */
        private fun pulse(t: Double, seed: Int): Float =
            ((sin(t * 0.43 + seed * 2.1) + sin(t * 0.79 + seed * 4.3) * 0.5) / 1.5).toFloat()

        // --- Groupes nettoyés (faceRig.ts) ---

        /**
         * Morphoses qui dessinent un SYMBOLE manga au lieu de bouger un visage : larmes et rougeur (à la physiologie,
         * qui leur donne leur horloge lente), gouttes de sueur, ombres, yeux en spirale / cœur / étoile / ><, yeux
         * noirs ou blancs, pupilles en tête d'épingle, reflets géants. Les groupes du modèle les mêlent au vrai
         * mouvement du visage ; on les retire des copies jouées par l'émotion.
         */
        internal val SYMBOL_MORPHS: Set<String> = setOf(
            "Tear", "Tear2", "TearFlow", "EyeWatery",
            "FaceRed", "FaceRed2", "FaceRed3",
            "FaceSweat", "FaceSweat2", "FaceShadow", "FaceShadow2", "FaceShadow3",
            "FaceSnot", "FaceSnotLong", "FaceSnotBubbles", "FaceSnotBubblesBig", "FaceSnotBubblesSmall",
            "Eye@@", "EyeStar", "EyeHeart", "EyeHeartSmall", "Eye><", "Eye0 0", "Eye0 0VSmall", "Eye0 0USmall",
            "EyeBlack", "EyeWhite", "EyeStare", "EyeHide", "EyeBlackCircles",
            "EyeIrisWhite", "EyeIrisClear", "EyeIrisSmall", "EyeIrisBig",
            "EyePupilBlackLine", "EyePupilCircle", "EyePupilSmall",
            "EyeHighlightHide", "EyeHighlightBig", "EyeHighlightDown", "EyeHighlightStar", "EyeHighlightHeart",
            "Mouth△", "Mouth^", "Mouthω", "Mouth□",
        )

        /** Morphoses de direction des yeux : le regard (os, saccades, évitements) décide où ils pointent — une
         * expression qui roule aussi les iris vers le haut (`Shy`, `Disgust`) se battrait avec lui. */
        internal fun isGazeMorph(morph: String): Boolean = morph.startsWith("eyeLook", ignoreCase = true)

        internal fun isStripped(morph: String): Boolean = morph in SYMBOL_MORPHS || isGazeMorph(morph)

        // --- Physiologie (FacePhysiology.ts) ---

        /** Ce que chaque émotion fait monter aux joues. */
        internal val BLUSH: Map<String, Float> = mapOf(
            "embarrassed" to 0.95f,
            "love" to 0.75f,
            "excited" to 0.3f,
            "amused" to 0.3f,
            "angry" to 0.35f,
            "grateful" to 0.25f,
            "playful" to 0.2f,
            "proud" to 0.15f,
            "jealous" to 0.2f,
            "frustrated" to 0.18f,
            "dreamy" to 0.2f,
            "happy" to 0.12f,
            "hopeful" to 0.1f,
        )

        /** La force avec laquelle chaque émotion pousse vers les larmes (le chagrin, ou être ému). */
        internal val TEARS: Map<String, Float> = mapOf(
            "sad" to 1f,
            "lonely" to 0.9f,
            "melancholic" to 0.75f,
            "nostalgic" to 0.45f,
            "anxious" to 0.3f,
            "scared" to 0.35f,
            "frustrated" to 0.2f,
            "grateful" to 0.45f,
            "relieved" to 0.35f,
            "love" to 0.3f,
        )
        /** Sous ceci (poids × intensité), rien ne monte. */
        const val TEAR_THRESHOLD = 0.45f
        /** Rire aux larmes n'arrive qu'en haut de l'échelle. */
        const val LAUGH_TEAR_FROM = 0.82f
        /** Fuite de la charge (1/s) : règle à la fois la montée des larmes et la lenteur à sécher. */
        const val TEAR_DECAY = 0.08f
        private const val WATERY_FROM = 0.15f
        private const val WATERY_TO = 1.2f
        private const val TEAR_FROM = 1.2f
        private const val TEAR_TO = 3.2f

        /** Taille des pupilles : > 0 dilate, < 0 contracte. */
        internal val PUPIL: Map<String, Float> = mapOf(
            "love" to 0.6f,
            "scared" to 0.7f,
            "excited" to 0.5f,
            "surprised" to 0.5f,
            "curious" to 0.45f,
            "dreamy" to 0.3f,
            "hopeful" to 0.25f,
            "happy" to 0.2f,
            "thinking" to 0.15f,
            "angry" to -0.5f,
            "disgusted" to -0.5f,
            "frustrated" to -0.3f,
            "bored" to -0.2f,
        )

        const val BLUSH_RISE_S = 1.6f
        const val BLUSH_FALL_S = 9f
        const val PUPIL_WIDEN_S = 0.9f
        const val PUPIL_NARROW_S = 0.45f

        /** Les morphoses brutes de la physiologie (hors de tout groupe). */
        val PHYSIOLOGY_MORPHS: List<String> = listOf(
            "FaceRed", "EyeWatery", "Tear",
            "EyeDilationLeft", "EyeDilationRight", "EyeConstrictLeft", "EyeConstrictRight",
        )

        private fun smoothstep(lo: Float, hi: Float, x: Float): Float {
            val t = ((x - lo) / (hi - lo)).coerceIn(0f, 1f)
            return t * t * (3f - 2f * t)
        }

        /** Approche exponentielle avec des constantes de temps distinctes à la montée et à la descente. */
        private fun approach(current: Float, target: Float, dt: Float, riseS: Float, fallS: Float): Float {
            val tau = if (target > current) riseS else fallS
            return current + (target - current) * (1f - exp(-dt / tau))
        }

        // --- Clignement (BlinkController.ts) ---

        /** Le préréglage VRM du clignement, et le nom du groupe en repli. */
        const val BLINK_PRESET = "blink"
        const val BLINK_GROUP = "Blink"

        /** Fermeture des yeux visée par phase : l'éveil laisse le cycle de clignement piloter, le sommeil les tient
         * presque clos en continu. */
        internal val PHASE_EYE_CLOSURE: Map<String, Float> = mapOf(
            "awake" to 0f,
            "light_sleep" to 0.85f,
            "rem" to 0.95f, // clos, mais les paupières « frémissent »
            "deep_sleep" to 1.0f,
        )

        const val EASE_SECONDS = 1.2f

        private val QUICK = BlinkShape(close = 0.055f, hold = 0.02f, open = 0.09f)
        private val SOFT = BlinkShape(close = 0.13f, hold = 0.07f, open = 0.2f)

        /** Clignements évoqués par le regard : un grand saut s'accompagne d'un clignement environ une fois sur trois
         * (les paupières suivent le saut) ; un petit saut de fixation, jamais. */
        const val GAZE_BLINK_MIN_SHIFT = 0.12f
        const val GAZE_BLINK_P = 0.35f
        /** Pas de clignement évoqué sur les talons d'un autre clignement. */
        const val GAZE_BLINK_REFRACTORY_S = 0.6f

        /** Les émotions en alerte clignent plus souvent ; celles de basse énergie plus lentement, et préfèrent le
         * clignement long, paupières lourdes. */
        internal val RESTLESS: Set<String> = setOf("excited", "scared", "anxious", "surprised", "angry", "frustrated")
        internal val HEAVY: Set<String> = setOf("bored", "dreamy", "melancholic", "sad", "lonely", "relieved", "nostalgic")

        // --- Micro-mouvements (FaceIdleController.ts) ---

        /** Bruit organique bon marché : trois sinus incommensurables, qui ne se répètent jamais visiblement. */
        private fun noise(t: Double, seed: Int): Float =
            ((sin(t * 0.37 + seed * 1.7) + sin(t * 0.91 + seed * 3.1) * 0.5 + sin(t * 1.53 + seed * 5.3) * 0.25) / 1.75)
                .toFloat()

        /** La dérive continue. Les paires gauche/droite ont des vitesses différentes : un visage parfaitement
         * symétrique est le signe le plus sûr d'une marionnette. */
        internal val MICRO_CHANNELS: List<MicroChannel> = listOf(
            MicroChannel("BrowInnerUp", amp = 0.07f, bias = 0.05f, rate = 0.55f, seed = 1, talkBoost = 1.5f),
            MicroChannel("BrowOuterUpLeft", amp = 0.06f, bias = 0.04f, rate = 0.47f, seed = 2, talkBoost = 1.4f),
            MicroChannel("BrowOuterUpRight", amp = 0.06f, bias = 0.04f, rate = 0.53f, seed = 3, talkBoost = 1.4f),
            MicroChannel("EyeSquintLeft", amp = 0.05f, bias = 0.03f, rate = 0.61f, seed = 4),
            MicroChannel("EyeSquintRight", amp = 0.05f, bias = 0.03f, rate = 0.67f, seed = 5),
            MicroChannel("MouthDimpleLeft", amp = 0.06f, bias = 0.05f, rate = 0.42f, seed = 6, talkBoost = 1.6f),
            MicroChannel("MouthDimpleRight", amp = 0.06f, bias = 0.05f, rate = 0.38f, seed = 7, talkBoost = 1.6f),
            MicroChannel("MouthPressLeft", amp = 0.04f, bias = 0.02f, rate = 0.35f, seed = 8),
            MicroChannel("MouthPressRight", amp = 0.04f, bias = 0.02f, rate = 0.31f, seed = 9),
            MicroChannel("MouthShrugUpper", amp = 0.04f, bias = 0.03f, rate = 0.29f, seed = 10),
            MicroChannel("CheekSquintLeft", amp = 0.035f, bias = 0.02f, rate = 0.44f, seed = 11),
            MicroChannel("CheekSquintRight", amp = 0.035f, bias = 0.02f, rate = 0.48f, seed = 12),
        )

        /**
         * Accents ARKit par émotion, à l'intensité 1, tenus ≤ 0,45 pour se lire comme une nuance sur la forme de
         * l'émotion, pas comme une seconde expression concurrente. Ils font lire l'émotion avant même que la forme
         * principale arrive, et donnent quelque chose à faire à `neutral` (vide sur ce modèle).
         */
        internal val EMOTION_ACCENT: Map<String, Map<String, Float>> = mapOf(
            // Positives — les joues montent, les sourcils externes se lèvent, les yeux se plissent dans le sourire
            "happy" to mapOf("MouthSmileLeft" to 0.3f, "MouthSmileRight" to 0.3f, "CheekSquintLeft" to 0.25f, "CheekSquintRight" to 0.25f),
            "excited" to mapOf("EyeWideLeft" to 0.35f, "EyeWideRight" to 0.35f, "BrowOuterUpLeft" to 0.3f, "BrowOuterUpRight" to 0.3f, "MouthSmileLeft" to 0.25f, "MouthSmileRight" to 0.25f),
            "love" to mapOf("CheekSquintLeft" to 0.3f, "CheekSquintRight" to 0.3f, "BrowInnerUp" to 0.2f, "MouthSmileLeft" to 0.2f, "MouthSmileRight" to 0.2f),
            "proud" to mapOf("BrowOuterUpLeft" to 0.2f, "BrowOuterUpRight" to 0.2f, "MouthSmileLeft" to 0.22f, "MouthSmileRight" to 0.22f),
            "grateful" to mapOf("BrowInnerUp" to 0.25f, "MouthSmileLeft" to 0.25f, "MouthSmileRight" to 0.25f, "CheekSquintLeft" to 0.2f, "CheekSquintRight" to 0.2f),
            "playful" to mapOf("MouthSmileLeft" to 0.35f, "MouthSmileRight" to 0.15f, "EyeSquintLeft" to 0.2f, "BrowOuterUpRight" to 0.25f),
            "amused" to mapOf("MouthSmileLeft" to 0.3f, "MouthSmileRight" to 0.3f, "CheekSquintLeft" to 0.3f, "CheekSquintRight" to 0.3f, "EyeSquintLeft" to 0.25f, "EyeSquintRight" to 0.25f),
            "hopeful" to mapOf("BrowInnerUp" to 0.3f, "BrowOuterUpLeft" to 0.2f, "BrowOuterUpRight" to 0.2f, "MouthSmileLeft" to 0.15f, "MouthSmileRight" to 0.15f),
            "relieved" to mapOf("BrowInnerUp" to 0.2f, "MouthShrugUpper" to 0.2f, "EyeSquintLeft" to 0.2f, "EyeSquintRight" to 0.2f),

            // Négatives — le sourcil interne est le muscle de la tristesse, le sourcil bas celui de la colère
            "sad" to mapOf("BrowInnerUp" to 0.45f, "MouthFrownLeft" to 0.3f, "MouthFrownRight" to 0.3f),
            "angry" to mapOf("BrowDownLeft" to 0.45f, "BrowDownRight" to 0.45f, "NoseSneerLeft" to 0.2f, "NoseSneerRight" to 0.2f, "MouthPressLeft" to 0.25f, "MouthPressRight" to 0.25f),
            "scared" to mapOf("BrowInnerUp" to 0.4f, "EyeWideLeft" to 0.4f, "EyeWideRight" to 0.4f, "MouthStretchLeft" to 0.2f, "MouthStretchRight" to 0.2f),
            "disgusted" to mapOf("NoseSneerLeft" to 0.45f, "NoseSneerRight" to 0.45f, "BrowDownLeft" to 0.25f, "BrowDownRight" to 0.25f, "MouthFrownLeft" to 0.2f, "MouthFrownRight" to 0.2f),
            "frustrated" to mapOf("BrowDownLeft" to 0.35f, "BrowDownRight" to 0.35f, "MouthPressLeft" to 0.3f, "MouthPressRight" to 0.3f),
            "lonely" to mapOf("BrowInnerUp" to 0.35f, "MouthFrownLeft" to 0.2f, "MouthFrownRight" to 0.2f, "EyeSquintLeft" to 0.15f, "EyeSquintRight" to 0.15f),
            "anxious" to mapOf("BrowInnerUp" to 0.4f, "MouthPressLeft" to 0.3f, "MouthPressRight" to 0.3f, "EyeWideLeft" to 0.2f, "EyeWideRight" to 0.2f),
            "bored" to mapOf("BrowDownLeft" to 0.15f, "BrowDownRight" to 0.15f, "EyeSquintLeft" to 0.3f, "EyeSquintRight" to 0.3f, "MouthShrugLower" to 0.2f),
            "jealous" to mapOf("BrowDownLeft" to 0.3f, "BrowDownRight" to 0.2f, "MouthPressLeft" to 0.3f, "EyeSquintRight" to 0.2f),

            // Complexes — l'asymétrie est ce qui se lit « réfléchit » plutôt que « pose »
            "surprised" to mapOf("BrowInnerUp" to 0.45f, "BrowOuterUpLeft" to 0.4f, "BrowOuterUpRight" to 0.4f, "EyeWideLeft" to 0.45f, "EyeWideRight" to 0.45f),
            "thinking" to mapOf("BrowDownLeft" to 0.3f, "BrowInnerUp" to 0.2f, "MouthPressLeft" to 0.3f, "EyeSquintLeft" to 0.2f),
            "confused" to mapOf("BrowInnerUp" to 0.3f, "BrowDownRight" to 0.3f, "BrowOuterUpLeft" to 0.25f, "MouthShrugUpper" to 0.2f),
            "embarrassed" to mapOf("BrowInnerUp" to 0.3f, "EyeSquintLeft" to 0.25f, "EyeSquintRight" to 0.25f, "MouthShrugUpper" to 0.25f, "CheekSquintLeft" to 0.2f, "CheekSquintRight" to 0.2f),
            "nostalgic" to mapOf("BrowInnerUp" to 0.3f, "MouthSmileLeft" to 0.15f, "MouthSmileRight" to 0.15f, "EyeSquintLeft" to 0.15f, "EyeSquintRight" to 0.15f),
            "dreamy" to mapOf("BrowOuterUpLeft" to 0.2f, "BrowOuterUpRight" to 0.2f, "EyeSquintLeft" to 0.25f, "EyeSquintRight" to 0.25f),
            "determined" to mapOf("BrowDownLeft" to 0.3f, "BrowDownRight" to 0.3f, "MouthPressLeft" to 0.25f, "MouthPressRight" to 0.25f),
            "mischievous" to mapOf("MouthSmileLeft" to 0.35f, "EyeSquintLeft" to 0.3f, "BrowDownLeft" to 0.2f, "BrowOuterUpRight" to 0.25f),
            "curious" to mapOf("BrowInnerUp" to 0.25f, "BrowOuterUpLeft" to 0.3f, "EyeWideLeft" to 0.2f, "EyeWideRight" to 0.2f),
            "melancholic" to mapOf("BrowInnerUp" to 0.4f, "MouthFrownLeft" to 0.25f, "MouthFrownRight" to 0.25f, "EyeSquintLeft" to 0.15f, "EyeSquintRight" to 0.15f),
        )

        /** Réponse des sourcils et paupières aux temps forts de la parole, à emphase = 1 / question = 1. */
        internal val SPEECH_BROWS: Map<String, SpeechBrow> = mapOf(
            "BrowInnerUp" to SpeechBrow(emphasis = 0.28f, question = 0.22f),
            "BrowOuterUpLeft" to SpeechBrow(emphasis = 0.32f, question = 0.3f),
            "BrowOuterUpRight" to SpeechBrow(emphasis = 0.3f, question = 0.26f),
            "EyeWideLeft" to SpeechBrow(emphasis = 0.12f, question = 0.08f),
            "EyeWideRight" to SpeechBrow(emphasis = 0.12f, question = 0.08f),
        )

        /** Vitesse à laquelle les accents suivent un changement d'émotion. */
        const val ACCENT_EASE = 2.5f
        /** Amplitude de dérive gardée en dormant — un visage endormi respire encore. */
        const val SLEEP_MICRO_SCALE = 0.18f

        // --- Parole (LipSyncController.ts) ---

        /** Les préréglages de bouche sous leur nom VRM 0.x : `VrmDocument` range un préréglage sous son nom, et un
         * VRM 0.x appelle a, i, u, e, o ce que three-vrm nomme aa, ih, ou, ee, oh. */
        private val VRM0_MOUTH_PRESET: Map<String, String> =
            mapOf("aa" to "a", "ih" to "i", "ou" to "u", "ee" to "e", "oh" to "o")
    }
}
