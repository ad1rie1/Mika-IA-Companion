package fr.qwartz.mika.avatar3d

import kotlin.random.Random

/**
 * Mika en 3D, de bout en bout — l'équivalent de `AnimationSystem` du client web. Une image :
 *   1. la machine à états choisit et enchaîne les mouvements de l'atelier ([BodyStateMachine], [AvatarAnimator]) ;
 *   2. les couches procédurales s'y ajoutent ([BodyLayers] : souffle, vie, port de tête, attention, regard) ;
 *   3. le squelette pose le corps ([AvatarRig]) ;
 *   4. les mèches et les vêtements suivent ([SpringBones]) ;
 *   5. le visage ([FaceDriver] : expressions, physiologie, clignements, micro-expressions).
 * Ce qu'elle ressent arrive par [setEmotion] : une parole peut déclencher un geste, une humeur qui dérive change
 * seulement la posture — les portes de `gestures.ts`, dans le même ordre.
 */
class AvatarController(
    private val rig: AvatarRig,
    manifest: ClipManifest,
    clips: Map<String, MotionClip>,
    private val random: Random = Random.Default,
) {
    val animator = AvatarAnimator(rig)
    val machine = BodyStateMachine(manifest, { clips[it] }, animator, random)
    val springs = SpringBones(rig.doc, rig)
    val face = FaceDriver(rig.doc.expressions, random, rig.doc.morphNames.values.flatten().toSet())
    val layers = BodyLayers(rig, { random.nextFloat() })
    private val ctx = BodyContext()
    private var lastTypingAt = Float.NEGATIVE_INFINITY
    private var morphs: Map<String, Float> = emptyMap()

    private var clock = 0f
    private var lastOneshotAt: Float? = null
    private var emotion = "neutral"
    private var intensity = 0f
    private var blend: List<Pair<String, Float>> = emptyList()
    private var sleepPhase = "awake"
    private var fatigue = 0f
    private var yawnIn: Float? = null
    private val hasYawn = clips.containsKey(BodyStateMachine.SLEEP_YAWN_CLIP)
    private var replyPending = false

    fun start() = machine.start()

    /** Les transformations locales du squelette, calculées par la dernière [frame]. */
    fun rigLocals(): Array<AvatarRig.Local> = rig.locals

    /**
     * Ce qu'elle ressent. `ambient` : une dérive de l'humeur entre deux tours (aucun geste, la posture suit) ;
     * sinon l'émotion de ce qu'elle vient de dire.
     */
    fun setEmotion(emotion: String, intensity: Float, blend: List<Pair<String, Float>> = emptyList(), ambient: Boolean = false) {
        this.emotion = emotion
        this.intensity = intensity.coerceIn(0f, 1f)
        this.blend = blend
        face.setEmotion(emotion, this.intensity, blend)
        ctx.emotion = emotion
        ctx.intensity = this.intensity
        machine.setAffect(emotion, this.intensity)
        val decision = Gestures.decide(
            Gestures.Input(
                emotion = emotion,
                intensity = this.intensity,
                blend = blend,
                sleepPhase = sleepPhase,
                nowSeconds = clock,
                lastOneshotAt = lastOneshotAt,
                ambient = ambient,
                activeVariant = machine.idleVariant,
            ),
        )
        when (decision) {
            is Gestures.Decision.IdleVariant -> machine.setIdleVariant(decision.clip)
            is Gestures.Decision.Oneshot -> {
                machine.setIdleVariant(null)
                if (machine.requestGesture(decision.clip)) lastOneshotAt = clock
            }
            is Gestures.Decision.None -> machine.setIdleVariant(null)
        }
    }

    /** Coucou de la main, quand on la retrouve après une vraie absence. */
    fun wave() {
        machine.requestGesture(WAVE_CLIP)
    }

    /** Un hochement de tête, quand on revient après un moment : elle lève les yeux, sans grand salut. */
    fun nod() {
        machine.requestGesture(NOD_CLIP)
    }

    /** Elle compose sa réponse (« Mika écrit… ») : le regard d'une réflexion — porté par les couches du corps. */
    fun setReplyPending(pending: Boolean) {
        replyPending = pending
        ctx.replyPending = pending
    }

    /** La personne écrit : regard posé sur elle, peu d'évitements, pendant 2,5 s après la dernière frappe. */
    fun noteUserTyping() {
        lastTypingAt = clock
    }

    /** Où est la personne qui la regarde (la caméra, en monde) : ce que ses yeux et sa tête cherchent. */
    fun setViewer(position: Vec3) {
        ctx.viewer = position
    }

    /** Les poids des morphoses du visage pour cette image. */
    fun morphs(): Map<String, Float> = morphs

    fun setSleepPhase(phase: String) {
        sleepPhase = phase
        machine.setSleepPhase(phase)
        face.setSleepPhase(phase)
        ctx.sleepPhase = phase
    }

    /** L'énergie (0…1) : sous ~0,55 elle se fatigue, et de temps en temps — seule, éveillée — elle bâille. */
    fun setEnergy(energy: Float) {
        fatigue = ((0.55f - energy) / 0.4f).coerceIn(0f, 1f)
        face.setEnergy(energy)
        ctx.fatigue = fatigue
        if (fatigue < YAWN_MIN_FATIGUE) yawnIn = null else if (yawnIn == null) yawnIn = sampleYawnDelay()
    }

    // ── La conversation ──────────────────────────────────────────────────────

    private var utterances: List<Utterance> = emptyList()
    /** La réplique qu'elle dit en ce moment (sa dernière version : la personne a pu tout afficher). */
    private var spoken: Utterance? = null
    private var readingLeft = 0f

    /** Les répliques qu'elle dit, sur l'horloge des bulles ([Utterance]) : la bouche suit le texte qui s'écrit. */
    fun setUtterances(list: List<Utterance>) {
        utterances = list
    }

    /**
     * La personne vient d'envoyer un message : elle le lit `seconds`, puis hoche la tête. Ce qu'elle disait encore
     * s'est déjà affiché d'un coup (la bulle l'a sautée) : elle se tait pour lire.
     */
    fun noteUserMessage(seconds: Float) {
        if (sleepPhase != "awake") return
        readingLeft = seconds.coerceAtLeast(0f)
    }

    /** Les rires écrits dans la réplique en cours (`[LAUGH]`) : le corps rit quand le texte y arrive. */
    private var laughs: List<SpeechCue> = emptyList()
    private var lastCursor = -1

    /** Lit l'horloge des répliques : commence, suit et termine ce qu'elle dit. */
    private fun updateSpeech(now: Long) {
        val active = utterances.firstOrNull { it.started(now) && !it.finished(now) }
        val current = spoken
        if (active?.key != current?.key) {
            if (current != null) endSpeech()
            if (active != null) beginSpeech(active)
        } else if (active != null) {
            spoken = active
        }
        val u = spoken ?: return
        val cursor = u.cursorAt(now)
        // La bouche et le corps suivent le texte qui s'écrit : le même curseur, à la même image.
        face.seekSpeech(cursor)
        layers.setSpeechCursor(cursor)
        // Un rire franchi pas à pas (pas sauté parce que la personne a tout affiché d'un coup).
        if (cursor - lastCursor in 1..MAX_CUE_STEP) {
            if (laughs.any { it.at in (lastCursor + 1)..cursor }) machine.requestGesture(LAUGH_CLIP)
        }
        lastCursor = cursor
    }

    private fun beginSpeech(u: Utterance) {
        spoken = u
        lastCursor = -1
        laughs = SpeechBeats.cues(u.text).filter { it.kind == SpeechCueKind.LAUGH }
        // Elle se taisait pour lire : sa réponse arrive, elle relève les yeux.
        readingLeft = 0f
        ctx.reading = false
        machine.setSpeaking(true)
        face.setSpeaking(true)
        face.startSpeech(u.text, msPerChar = 1000f / u.charsPerSecond)
        layers.beginUtterance(u.text)
        ctx.speaking = true
        ctx.persona = "speaking"
    }

    private fun endSpeech() {
        spoken = null
        laughs = emptyList()
        lastCursor = -1
        face.stopSpeech()
        layers.setSpeechCursor(-1)
        layers.endUtterance()
        machine.setSpeaking(false)
        face.setSpeaking(false)
        ctx.speaking = false
        ctx.persona = null
    }

    /** Elle lit le message qu'on vient d'envoyer ; à la fin, un petit hochement : « j'ai lu ». */
    private fun updateReading(dt: Float) {
        if (readingLeft <= 0f) {
            ctx.reading = false
            return
        }
        ctx.reading = sleepPhase == "awake"
        readingLeft -= dt
        if (readingLeft <= 0f) {
            readingLeft = 0f
            ctx.reading = false
            layers.acknowledge()
        }
    }

    /** Une image : avance tout de `dt` secondes et rend la pose à poser. `now` : l'horloge des répliques. */
    fun frame(dt: Float, now: Long = System.nanoTime()): Pose {
        clock += dt
        updateSpeech(now)
        updateReading(dt)
        updateYawn(dt)
        machine.update(dt)
        // Le clip réécrit toute la pose ; les couches (souffle, vie, port de tête, attention, regard) s'y ajoutent.
        val pose = animator.update(dt)
        ctx.listening = clock - lastTypingAt < BodyContext.LISTENING_HOLD_S
        val gazeShift = layers.update(dt, pose, ctx)
        face.noteGazeShift(gazeShift)
        // Les mots appuyés lèvent les sourcils, une question les tient levés.
        face.setSpeechBeat(ctx.speechEmphasis, ctx.speechQuestion)
        rig.solve(pose)
        springs.update(dt)
        morphs = face.update(dt)
        return pose
    }

    private fun sampleYawnDelay(): Float {
        val (lo, hi) = YAWN_INTERVAL_S
        return (lo + random.nextFloat() * (hi - lo)) / maxOf(0.3f, fatigue)
    }

    private fun updateYawn(dt: Float) {
        val left = yawnIn ?: return
        if (!hasYawn || sleepPhase != "awake" || machine.state != BodyStateMachine.State.IDLE) return
        val next = left - dt
        if (next > 0f) {
            yawnIn = next
            return
        }
        yawnIn = sampleYawnDelay()
        machine.requestGesture(BodyStateMachine.SLEEP_YAWN_CLIP)
    }

    companion object {
        const val LAUGH_CLIP = "gesture_laugh"

        /** Au-delà, le curseur a sauté (tout affiché d'un coup) : les rires franchis ne partent pas. */
        const val MAX_CUE_STEP = 20
        const val YAWN_MIN_FATIGUE = 0.55f
        const val WAVE_CLIP = "gesture_wave"
        const val NOD_CLIP = "gesture_nod"
        val YAWN_INTERVAL_S = 120f to 300f
    }
}
