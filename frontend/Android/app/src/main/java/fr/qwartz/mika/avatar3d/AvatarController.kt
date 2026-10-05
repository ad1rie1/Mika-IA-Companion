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
    val face = FaceDriver(rig.doc.expressions, random)
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

    /** Coucou de la main, quand on la retrouve. */
    fun wave() {
        machine.requestGesture(WAVE_CLIP)
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

    /** Une image : avance tout de `dt` secondes et rend la pose à poser. */
    fun frame(dt: Float): Pose {
        clock += dt
        updateYawn(dt)
        machine.update(dt)
        // Le clip réécrit toute la pose ; les couches (souffle, vie, port de tête, attention, regard) s'y ajoutent.
        val pose = animator.update(dt)
        ctx.listening = clock - lastTypingAt < BodyContext.LISTENING_HOLD_S
        val gazeShift = layers.update(dt, pose, ctx)
        face.noteGazeShift(gazeShift)
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
        const val YAWN_MIN_FATIGUE = 0.55f
        const val WAVE_CLIP = "gesture_wave"
        val YAWN_INTERVAL_S = 120f to 300f
    }
}
