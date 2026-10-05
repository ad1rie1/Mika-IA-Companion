package fr.qwartz.mika.avatar3d

import kotlin.random.Random

/**
 * La machine à états du corps — `frontend/Web/src/vtuber/animation/AnimationStateMachine.ts`, portée sur
 * [AvatarAnimator] (sans la marche ni les postures assise/couchée : l'app n'a pas de pièce).
 *
 * États : attente (un tirage pondéré parmi les clips « idle », chacun tenu un moment), parole (le même tirage
 * parmi les clips « talk »), geste (joué une fois, il rend la main avant sa fin), sommeil. Le tirage tient compte
 * de l'humeur ([Affect]) ; chaque choix repart d'une image au hasard, à une vitesse tirée à ±7 %, et un clip sur
 * deux est son jumeau en miroir : la même attente ne revient jamais tout à fait pareille. Une émotion peut
 * remplacer l'attente par une posture (épaules tombantes pour la tristesse…). On s'endort par un bâillement, on se
 * réveille par un étirement, quand le manifeste les a.
 */
class BodyStateMachine(
    private val manifest: ClipManifest,
    private val clips: (String) -> MotionClip?,
    private val animator: AvatarAnimator,
    private val random: Random = Random.Default,
) {
    enum class State { IDLE, TALKING, GESTURE, SLEEPING }

    var state = State.IDLE
        private set
    private var started = false
    private var speaking = false
    private var sleepPhase = "awake"

    private var currentName: String? = null
    private var currentTimeScale = 1f
    private var holdTimer = 0f
    private var holdDuration = 10f

    private var gestureFadeOut = FADE_GESTURE_OUT
    private var gestureHoldRemaining: Float? = null
    private var queuedGesture: String? = null
    private var sleepAfterGesture = false

    /** La posture d'émotion en cours, telle qu'elle a été résolue (un clip absent vaut null). */
    var idleVariant: String? = null
        private set

    private var affectEmotion = "neutral"
    private var affectIntensity = 0.5f
    private var tempoTarget = 1f
    private var tempo = 1f
    private var pickTempo = 1f
    private var settleRemaining: Float? = null

    val currentClip: String? get() = currentName

    fun start() {
        if (started) return
        started = true
        if (sleepPhase != "awake") enterSleeping(FADE_START) else enterBase(if (speaking) State.TALKING else State.IDLE, FADE_START)
    }

    fun update(dt: Float) {
        if (!started) return
        when (state) {
            State.IDLE, State.TALKING -> {
                settleRemaining?.let { s ->
                    val left = s - dt
                    settleRemaining = if (left <= 0f) null else left
                    if (left <= 0f && !speaking && state == State.TALKING) {
                        enterBase(State.IDLE, FADE_TO_IDLE)
                        updateTempo(dt)
                        return
                    }
                }
                holdTimer += dt
                if (holdTimer >= holdDuration) enterBase(state, FADE_VARIATION)
                updateTempo(dt)
            }
            State.GESTURE -> updateGesture(dt)
            State.SLEEPING -> Unit
        }
    }

    fun setSpeaking(on: Boolean) {
        if (on == speaking) return
        speaking = on
        if (!started || state == State.SLEEPING || state == State.GESTURE) return
        if (on) {
            settleRemaining = null
            if (state != State.TALKING) enterBase(State.TALKING, FADE_TO_TALKING)
            return
        }
        settleRemaining = SPEECH_SETTLE_S
    }

    fun setSleepPhase(phase: String) {
        if (phase == sleepPhase) return
        val prev = sleepPhase
        sleepPhase = phase
        if (!started) return
        if (phase == "awake") {
            if (state == State.GESTURE) {
                sleepAfterGesture = false
                return
            }
            val stretch = variant(WAKE_STRETCH_CLIP)
            if (stretch != null && !speaking) {
                sleepAfterGesture = false
                startGesture(stretch, FADE_WAKE)
                return
            }
            enterBase(if (speaking) State.TALKING else State.IDLE, FADE_WAKE)
            return
        }
        queuedGesture = null
        if (prev == "awake" && (state == State.IDLE || state == State.TALKING)) {
            val yawn = variant(SLEEP_YAWN_CLIP)
            if (yawn != null && !speaking) {
                settleRemaining = null
                sleepAfterGesture = true
                startGesture(yawn, entry(yawn)?.fadeIn ?: FADE_GESTURE_IN)
                return
            }
        }
        gestureHoldRemaining = null
        sleepAfterGesture = false
        enterSleeping(if (prev == "awake") FADE_TO_SLEEP else FADE_SLEEP_SWAP)
    }

    /** Remplace l'attente par une posture d'émotion ; null rend l'attente normale. */
    fun setIdleVariant(name: String?) {
        val resolved = name?.takeIf { clips(it) != null }
        if (resolved == idleVariant) return
        idleVariant = resolved
        if (started && state == State.IDLE) enterBase(State.IDLE, FADE_VARIATION)
    }

    /** L'humeur : pèse les tirages, règle le tempo et la tenue. Ne provoque jamais de transition à elle seule. */
    fun setAffect(emotion: String, intensity: Float) {
        affectEmotion = emotion
        affectIntensity = intensity.coerceIn(0f, 1f)
        tempoTarget = Affect.timeScale(emotion, affectIntensity)
    }

    /** Joue un geste (une fois, ou tenu un moment s'il boucle). Faux quand l'état l'interdit (sommeil…). */
    fun requestGesture(name: String): Boolean {
        if (!started || state == State.SLEEPING) return false
        val chosen = variant(name) ?: return false
        if (state == State.GESTURE) {
            if (currentName?.let { MotionClip.baseName(it) } == name) return true
            val progressed = if (animator.duration > 0f) animator.time / animator.duration else 1f
            if (progressed >= 0.25f) startGesture(chosen, FADE_GESTURE_INTERRUPT) else queuedGesture = chosen
            return true
        }
        settleRemaining = null
        startGesture(chosen, entry(chosen)?.fadeIn ?: FADE_GESTURE_IN)
        return true
    }

    // ── interne ──────────────────────────────────────────────────────────────────────────────────────────────

    private fun entry(name: String) = manifest.clips[MotionClip.baseName(name)]

    /** Le clip ou son jumeau en miroir, à pile ou face (sauf `mirror: false`). */
    private fun variant(name: String): String? {
        if (clips(name) == null) return null
        val twin = name + MotionClip.MIRROR_SUFFIX
        return if (entry(name)?.mirror != false && clips(twin) != null && random.nextFloat() < 0.5f) twin else name
    }

    private fun updateTempo(dt: Float) {
        tempo += (tempoTarget - tempo) * minOf(1f, dt * TEMPO_EASE)
        animator.timeScale = currentTimeScale * tempo * pickTempo
    }

    private fun updateGesture(dt: Float) {
        if (currentName == null) {
            finishGesture()
            return
        }
        gestureHoldRemaining?.let {
            val left = it - dt
            gestureHoldRemaining = left
            if (left <= 0f) finishGesture()
            return
        }
        if (animator.remaining <= gestureFadeOut || animator.finished) finishGesture()
    }

    private fun finishGesture() {
        if (sleepAfterGesture) {
            sleepAfterGesture = false
            if (sleepPhase != "awake") {
                queuedGesture = null
                gestureHoldRemaining = null
                enterSleeping(FADE_TO_SLEEP)
                return
            }
        }
        val queued = queuedGesture
        queuedGesture = null
        if (queued != null) {
            startGesture(queued, entry(queued)?.fadeIn ?: FADE_GESTURE_IN)
            return
        }
        enterBase(if (speaking) State.TALKING else State.IDLE, gestureFadeOut)
    }

    private fun startGesture(name: String, fadeIn: Float) {
        state = State.GESTURE
        val e = entry(name)
        gestureFadeOut = e?.fadeOut ?: FADE_GESTURE_OUT
        val loops = e?.loop == true
        play(name, fadeIn, once = !loops, timeScale = (e?.timeScale ?: 1f) * jitter(GESTURE_TEMPO_JITTER))
        gestureHoldRemaining = if (loops) sample(e?.hold ?: listOf(3.5f, 5.5f)) else null
    }

    private fun enterBase(target: State, fade: Float) {
        state = target
        gestureHoldRemaining = null
        settleRemaining = null
        val name = pickBaseClip(target) ?: return
        pickTempo = jitter(BASE_TEMPO_JITTER)
        play(name, fade, randomPhase = true)
        updateTempo(0f)
        holdTimer = 0f
        val default = if (target == State.TALKING) DEFAULT_HOLD_TALKING else DEFAULT_HOLD_IDLE
        holdDuration = sample(entry(name)?.hold ?: default) * Affect.holdScale(affectEmotion, affectIntensity)
    }

    private fun enterSleeping(fade: Float) {
        if (sleepPhase == "awake") return
        state = State.SLEEPING
        settleRemaining = null
        pickTempo = 1f
        val cfg = manifest.sleep[sleepPhase]
        val name = cfg?.clip?.takeIf { clips(it) != null } ?: manifest.byCategory("idle").firstOrNull { clips(it) != null } ?: return
        play(name, fade, timeScale = cfg?.timeScale ?: SLEEP_TIMESCALE[sleepPhase] ?: 1f)
    }

    /** Le poids de tirage d'un clip sous l'humeur du moment. */
    fun poolWeight(name: String): Float {
        val e = entry(name) ?: return 1f
        return e.weight * Affect.clipAffinity(e, affectEmotion, affectIntensity)
    }

    private fun pickBaseClip(target: State): String? {
        if (target == State.IDLE) idleVariant?.let { v -> variant(v)?.let { return it } }
        var pool = if (target == State.TALKING) manifest.byCategory("talk") else manifest.byCategory("idle")
        if (pool.isEmpty() && target == State.TALKING) pool = manifest.byCategory("idle")
        pool = pool.filter { clips(it) != null }
        val spontaneous = pool.filter { (entry(it)?.weight ?: 1f) > 0f }
        if (spontaneous.isEmpty()) return currentName ?: pool.firstOrNull()
        val current = currentName?.let { MotionClip.baseName(it) }
        val usable = spontaneous.filter { it != current }.ifEmpty { spontaneous }
        val weights = usable.map { poolWeight(it) }
        var r = random.nextFloat() * weights.sum()
        for (i in usable.indices) {
            r -= weights[i]
            if (r <= 0f) return variant(usable[i])
        }
        return variant(usable.last())
    }

    private fun play(name: String, fade: Float, once: Boolean = false, timeScale: Float = 1f, randomPhase: Boolean = false) {
        val clip = clips(name) ?: return
        currentTimeScale = timeScale
        val loop = !once && (clip.loop || entry(name)?.category != "gesture" || entry(name)?.loop == true)
        val at = if (randomPhase && loop) random.nextFloat() * clip.duration else 0f
        animator.play(clip, fade, at = at, loop = loop, timeScale = timeScale)
        currentName = name
    }

    private fun sample(range: List<Float>): Float = range[0] + random.nextFloat() * maxOf(0f, range.getOrElse(1) { range[0] } - range[0])

    /** 1 ± amount, centré. */
    private fun jitter(amount: Float): Float = 1 + amount * (2 * random.nextFloat() - 1)

    companion object {
        const val FADE_VARIATION = 0.6f
        const val FADE_TO_TALKING = 0.4f
        const val FADE_TO_IDLE = 0.5f
        const val FADE_GESTURE_IN = 0.25f
        const val FADE_GESTURE_OUT = 0.45f
        const val FADE_GESTURE_INTERRUPT = 0.2f
        const val FADE_TO_SLEEP = 1.2f
        const val FADE_SLEEP_SWAP = 1.0f
        const val FADE_WAKE = 1.0f
        const val FADE_START = 0.5f
        val DEFAULT_HOLD_IDLE = listOf(8f, 16f)
        val DEFAULT_HOLD_TALKING = listOf(4f, 9f)
        const val SPEECH_SETTLE_S = 0.7f
        const val SLEEP_YAWN_CLIP = "gesture_yawn"
        const val WAKE_STRETCH_CLIP = "gesture_stretch"
        const val TEMPO_EASE = 2.0f
        const val BASE_TEMPO_JITTER = 0.07f
        const val GESTURE_TEMPO_JITTER = 0.1f
        val SLEEP_TIMESCALE = mapOf("light_sleep" to 1.0f, "rem" to 0.85f, "deep_sleep" to 0.6f)
    }
}
