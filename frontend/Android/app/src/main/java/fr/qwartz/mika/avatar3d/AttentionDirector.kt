package fr.qwartz.mika.avatar3d

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.random.Random

/**
 * Des angles de regard sémantiques, en radians, ceux du web (`gazeMath.ts`) : `pitch` > 0 vers le BAS, `yaw` > 0 vers
 * SA GAUCHE (la droite de qui la regarde). Attention : c'est l'inverse du `yaw` de [CharacterFrame] (> 0 vers sa
 * droite). Les tables du web sont gardées telles quelles dans cette convention, et la conversion se fait en un seul
 * endroit, [BodyMath] — recopier une table en changeant ses signes à la main, c'est ainsi qu'un geste part du mauvais
 * côté sans que rien ne le dise.
 */
data class GazeAngles(val pitch: Float, val yaw: Float) {
    companion object {
        val ZERO = GazeAngles(0f, 0f)
    }
}

/** Où est son attention (le `AttentionState` du web). */
enum class AttentionState {
    /** Les yeux sur qui la regarde. */
    CONTACT,

    /** Un court détournement, puis retour. */
    AVERT,

    /** Seule avec ses pensées : elle regarde la pièce. */
    WANDER,

    /** Elle traverse la pièce : les yeux sur le chemin, un coup d'œil de temps en temps. */
    WALKING,

    /** Une réponse se compose : absorbée, en haut et de côté. */
    THINKING,

    /**
     * Elle lit le message qu'on vient de lui envoyer (propre à l'app) : les yeux baissés sur la bulle, des saccades
     * de lecture le long des lignes.
     */
    READING,

    /** Elle se murmure quelque chose : pas à vous. */
    INNER,

    /** Personne à portée d'un tour de tête (derrière elle) : regard droit devant. */
    AWAY,

    ASLEEP,
}

/** Ce que le directeur lit à chaque image. */
data class AttentionInput(
    val speaking: Boolean = false,
    /** Un message a été accepté et rien n'y a encore répondu. */
    val replyPending: Boolean = false,
    /** La personne en face est en train d'écrire. */
    val listening: Boolean = false,
    /** La voix de la réponse en cours : `"inner"` = elle se murmure à elle-même. */
    val persona: String? = null,
    val emotion: String = "neutral",
    val intensity: Float = 0.5f,
    val sleepPhase: String = BodyContext.AWAKE,
    /**
     * Le spectateur est à portée d'un tour de tête (false : derrière elle, ou pas de caméra). Ne règle que le terme
     * de contact : une pensée détourne encore le regard par rapport à son avant quand personne n'est là.
     */
    val reachable: Boolean = false,
    /** Distance angulaire au spectateur (rad) : la taille du saut quand le contact bascule, pour les clignements. */
    val viewerAngle: Float = 0f,
    val walking: Boolean = false,
    /** Elle lit le message qu'on vient de lui envoyer, dans la bulle sous son visage. */
    val reading: Boolean = false,
)

/** L'intention de regard de l'image. */
data class GazeIntent(
    val state: AttentionState,
    /** La part de la direction du spectateur dans la cible des yeux, 0…1. */
    val contact: Float,
    /** Ajouté au regard : un détournement, une pose de réflexion, le murmure. */
    val offset: GazeAngles,
    /** Le bougé de fixation en cours, changé au rythme des saccades. */
    val saccade: GazeAngles,
    /** Le saut décidé à CETTE image (rad) ; 0 quand les yeux n'ont pas bougé. */
    val shift: Float,
)

/**
 * Où est l'attention de Mika — la décision derrière les yeux et la tête, portée de `attention.ts`. Pur : pas de
 * moteur, une source d'aléa injectable, et le temps n'entre que par `dt`, si bien que chaque branche se teste image
 * par image.
 *
 * Le modèle est le regard conversationnel tel que la littérature le décrit (Kendon 1967, Argyle & Cook 1976) : qui
 * écoute garde les yeux sur qui parle ; qui parle détourne le regard au DÉBUT d'un énoncé (il prépare ce qu'il va
 * dire) et revient vers la fin ; qui cherche une pensée regarde en haut et de côté, avec de brefs retours ; la honte,
 * la tristesse et l'anxiété détournent vers le bas, l'amour et la gratitude presque jamais. Et qui se murmure quelque
 * chose ne vous regarde pas.
 *
 * L'app ajoute un mode que le web n'a pas : la lecture. La personne écrit sur son téléphone, et sa bulle s'affiche
 * sous le visage de Mika ; elle la lit — les yeux baissés sur le texte, qui avancent par petits sauts le long des
 * lignes. Priorités : marcher > se murmurer quelque chose > lire > composer une réponse > la conversation ordinaire.
 *
 * Chaque CHANGEMENT de regard est ici un saut, jamais un glissement : les mouvements des yeux sont des saccades —
 * un bond balistique puis une fixation — et un œil qui glisse vers sa cible a l'air ivre. La tête, qui elle bouge
 * lentement, s'adoucit dans sa propre couche. `shift` donne la taille du saut de l'image, pour que les paupières
 * fassent ce qu'elles font sur un grand changement de regard (un tiers environ porte un clignement).
 */
class AttentionDirector(private val random: () -> Float = { Random.nextFloat() }) {
    var currentState: AttentionState = AttentionState.CONTACT
        private set

    private var contact = 1f
    private var offPitch = 0f
    private var offYaw = 0f
    private var sacPitch = 0f
    private var sacYaw = 0f

    // Dans l'ordre du constructeur web (détournement, saccade, retour) : la même suite d'aléa donne les mêmes tirages.
    private var aversionTimer = 0f
    private var nextAversionAt = sample(AVERSION_INTERVAL)
    private var aversionRemaining = 0f

    private var saccadeTimer = 0f
    private var nextSaccadeAt = sample(SACCADE_INTERVAL)

    private var thinkingElapsed = 0f
    private var thinkingSide = 1f
    private var checkinTimer = 0f
    private var nextCheckinAt = sample(THINKING_CHECKIN_INTERVAL)
    private var checkinRemaining = 0f

    private var innerSide = 1f

    // La lecture : la demi-largeur de la ligne en cours, son rang, et l'horloge de la fixation. Tirés en entrant en
    // lecture, jamais à la construction — la suite d'aléa du constructeur reste celle du web.
    private var readingSpan = 0f
    private var readingLine = 0
    private var fixationTimer = 0f
    private var fixationFor = 0f

    private var wasSpeaking = false
    private var wasPending = false

    /** Secondes sans personne à qui prêter attention (ni parole, ni frappe, ni réponse attendue). */
    private var idleFor = 0f
    private var wandering = false

    fun update(dt: Float, input: AttentionInput): GazeIntent {
        val prevContact = contact
        val prevPitch = offPitch
        val prevYaw = offYaw

        val speakingStarted = input.speaking && !wasSpeaking
        val pendingStarted = input.replyPending && !wasPending
        wasSpeaking = input.speaking
        wasPending = input.replyPending

        if (input.sleepPhase != BodyContext.AWAKE) {
            currentState = AttentionState.ASLEEP
            contact = 0f
            offPitch = 0f
            offYaw = 0f
            sacPitch = 0f
            sacYaw = 0f
            aversionRemaining = 0f
            checkinRemaining = 0f
            thinkingElapsed = 0f
            return emit(0f)
        }

        if (pendingStarted) {
            thinkingElapsed = 0f
            thinkingSide = if (random() < 0.5f) -1f else 1f
            checkinTimer = 0f
            nextCheckinAt = sample(THINKING_CHECKIN_INTERVAL)
            checkinRemaining = 0f
        }
        thinkingElapsed = if (input.replyPending) thinkingElapsed + dt else 0f
        // Lire ce qu'on vient de lui écrire, c'est être en conversation : pas d'errance, et l'horloge repart.
        val engaged = input.speaking || input.replyPending || input.listening || input.reading
        idleFor = if (engaged) 0f else idleFor + dt
        if (engaged && wandering) {
            // Quelqu'un est de nouveau là : le regard ailleurs s'arrête maintenant, pas à son terme — et le prochain
            // détournement est un détournement de conversation ordinaire.
            wandering = false
            aversionRemaining = 0f
            offPitch = 0f
            offYaw = 0f
            aversionTimer = 0f
            nextAversionAt = sample(AVERSION_INTERVAL)
        }

        var mode = when {
            input.walking -> AttentionState.WALKING
            input.persona == INNER_PERSONA && input.speaking -> AttentionState.INNER
            // Lire passe avant de composer : on lit le message avant d'y réfléchir — et avant ce qu'elle disait
            // encore, puisque c'est la personne qui vient de parler.
            input.reading -> AttentionState.READING
            // Un message en attente pendant qu'elle dit encore la réponse précédente n'emporte pas son regard : on
            // finit sa phrase d'abord.
            input.replyPending && !input.speaking && thinkingElapsed <= THINKING_MAX_S -> AttentionState.THINKING
            else -> AttentionState.CONTACT
        }

        when (mode) {
            AttentionState.WALKING -> {
                // Les yeux quelques pas devant, au sol ; un détournement n'a pas de sens ici.
                aversionRemaining = 0f
                wandering = false
                contact = if (input.speaking) 0.35f else 0f
                offPitch = WALKING_OFFSET.pitch
                offYaw = 0f
            }
            AttentionState.INNER -> {
                if (currentState != AttentionState.INNER) innerSide = if (random() < 0.5f) -1f else 1f
                aversionRemaining = 0f
                contact = INNER_CONTACT
                offPitch = INNER_OFFSET.pitch
                offYaw = INNER_OFFSET.yaw * innerSide
            }
            AttentionState.READING -> {
                // Les yeux sur la bulle : vers la personne (la bulle est entre elles deux, sur l'écran), mais plus bas.
                // Le contact reste partiel — elle regarde le texte, pas vous — et le balayage des lignes passe par
                // les saccades, que la tête ne suit pas.
                aversionRemaining = 0f
                contact = READING_CONTACT
                offPitch = READING_OFFSET.pitch
                offYaw = READING_OFFSET.yaw
            }
            AttentionState.THINKING -> {
                aversionRemaining = 0f
                if (checkinRemaining > 0f) {
                    // Un coup d'œil vers vous entre deux moments d'absorption.
                    checkinRemaining -= dt
                    contact = 1f
                    offPitch = 0f
                    offYaw = 0f
                } else {
                    checkinTimer += dt
                    if (checkinTimer >= nextCheckinAt) {
                        checkinTimer = 0f
                        nextCheckinAt = sample(THINKING_CHECKIN_INTERVAL)
                        checkinRemaining = sample(THINKING_CHECKIN_DURATION)
                        contact = 1f
                        offPitch = 0f
                        offYaw = 0f
                    } else {
                        contact = THINKING_CONTACT
                        offPitch = THINKING_OFFSET.pitch
                        offYaw = THINKING_OFFSET.yaw * thinkingSide
                    }
                }
            }
            else -> mode = conversation(dt, input, speakingStarted)
        }

        if (!input.reachable) {
            // Personne devant elle vers qui la tête pourrait tourner : le terme de contact n'a pas de sens. Une pensée
            // ou un murmure garde son décalage — il est relatif à son avant, pas à un spectateur.
            contact = 0f
            if (mode == AttentionState.CONTACT || mode == AttentionState.AVERT) mode = AttentionState.AWAY
        }

        val saccadeJump = when {
            mode == AttentionState.READING -> readingScan(dt, entering = currentState != AttentionState.READING)
            currentState == AttentionState.READING -> endReading()
            else -> updateSaccade(dt, input, mode)
        }
        currentState = mode

        val offsetJump = hypot(offPitch - prevPitch, offYaw - prevYaw)
        val contactJump = abs(contact - prevContact) * min(abs(input.viewerAngle), 0.5f)
        return emit(offsetJump + contactJump + saccadeJump)
    }

    /** Le cas ordinaire : contact, détournements de conversation, et regard qui erre quand elle est seule. */
    private fun conversation(dt: Float, input: AttentionInput, speakingStarted: Boolean): AttentionState {
        if (currentState == AttentionState.THINKING || currentState == AttentionState.INNER ||
            currentState == AttentionState.READING
        ) {
            // Retour vers vous : l'horloge des détournements repart, pour que le retour ne soit pas aussitôt suivi
            // d'un regard ailleurs.
            aversionTimer = 0f
            nextAversionAt = sample(AVERSION_INTERVAL)
        }
        if (speakingStarted && aversionRemaining <= 0f && random() < ONSET_AVERSION_P) {
            // Le regard de préparation : le détournement qui ouvre un énoncé.
            aversionRemaining = sample(ONSET_AVERSION_DURATION)
            val side = if (random() < 0.5f) -1f else 1f
            offPitch = PLANNING_OFFSET.pitch
            offYaw = PLANNING_OFFSET.yaw * side
        }
        val alone = idleFor >= WANDER_AFTER_S
        if (aversionRemaining > 0f) {
            aversionRemaining -= dt
            if (aversionRemaining <= 0f) {
                aversionRemaining = 0f
                wandering = false
                offPitch = 0f
                offYaw = 0f
                aversionTimer = 0f
                nextAversionAt = if (alone) sample(WANDER_INTERVAL) else sample(AVERSION_INTERVAL) * intervalScale(input)
            }
        } else if (alone) {
            offPitch = 0f
            offYaw = 0f
            aversionTimer += dt
            if (aversionTimer >= nextAversionAt) {
                aversionTimer = 0f
                nextAversionAt = sample(WANDER_INTERVAL)
                if (random() < WANDER_P) {
                    wandering = true
                    aversionRemaining = sample(WANDER_DURATION)
                    val point = WANDER_POINTS[pick(WANDER_POINTS.size)]
                    offPitch = point.pitch
                    offYaw = point.yaw
                }
            }
        } else {
            offPitch = 0f
            offYaw = 0f
            aversionTimer += dt
            if (aversionTimer >= nextAversionAt) {
                aversionTimer = 0f
                nextAversionAt = sample(AVERSION_INTERVAL) * intervalScale(input)
                val profile = AVERSION_PROFILE[input.emotion]
                val p = baseAversionP(input) * (profile?.p ?: 1f)
                if (random() < p) {
                    aversionRemaining = sample(AVERSION_DURATION)
                    val dir = profile?.dir ?: AVERSION_DIRS[pick(AVERSION_DIRS.size)]
                    offPitch = dir.pitch
                    offYaw = dir.yaw
                }
            }
        }
        // Errer, c'est regarder la pièce elle-même (par rapport à son avant), pas un point à côté du spectateur.
        contact = if (wandering) 0f else 1f
        return when {
            wandering -> AttentionState.WANDER
            aversionRemaining > 0f -> AttentionState.AVERT
            else -> AttentionState.CONTACT
        }
    }

    private fun emit(shift: Float) = GazeIntent(
        state = currentState,
        contact = contact,
        offset = GazeAngles(offPitch, offYaw),
        saccade = GazeAngles(sacPitch, sacYaw),
        shift = shift,
    )

    private fun baseAversionP(input: AttentionInput): Float = when {
        input.listening -> AVERSION_P_LISTENING
        input.speaking -> AVERSION_P_SPEAKING
        else -> AVERSION_P_IDLE
    }

    private fun intervalScale(input: AttentionInput): Float = when {
        input.listening -> 1.8f
        input.speaking -> 0.8f
        else -> 1f
    }

    /** L'amplitude du saut quand une saccade part, 0 sinon. */
    private fun updateSaccade(dt: Float, input: AttentionInput, mode: AttentionState): Float {
        saccadeTimer += dt
        if (saccadeTimer < nextSaccadeAt) return 0f
        saccadeTimer = 0f

        val focused = input.emotion in FOCUSED_EMOTIONS
        val restless = input.emotion in RESTLESS_EMOTIONS
        var amp = sample(if (mode == AttentionState.CONTACT) SACCADE_AMPLITUDE_CONTACT else SACCADE_AMPLITUDE_FREE)
        if (focused) amp *= 0.5f
        if (restless) amp *= 1.4f
        if (input.listening) amp *= 0.6f

        val angle = random() * PI.toFloat() * 2f
        val pitch = sin(angle) * amp
        val yaw = cos(angle) * amp
        val jump = hypot(pitch - sacPitch, yaw - sacYaw)
        sacPitch = pitch
        sacYaw = yaw

        var interval = sample(SACCADE_INTERVAL)
        if (focused) interval *= 1.4f
        if (restless) interval *= 0.55f
        if (input.listening) interval *= 1.5f
        nextSaccadeAt = interval
        return jump
    }

    /**
     * Les saccades de lecture : des fixations de ~¼ s, chacune un petit saut le long de la ligne, puis un grand saut
     * de retour au début de la suivante — et de temps en temps une ligne plus bas. L'amplitude du saut, rendue.
     *
     * Le sens : elle suit le texte tel que la personne le voit, de la gauche de l'écran vers sa droite. Face à la
     * caméra, la gauche de l'écran est SA droite : le lacet sémantique (> 0 vers sa gauche) va donc du négatif au
     * positif. Lire la bulle « de son côté », en miroir, serait juste et se lirait à l'envers.
     */
    private fun readingScan(dt: Float, entering: Boolean): Float {
        if (entering) {
            readingLine = 0
            readingSpan = sample(READING_SPAN)
            fixationTimer = 0f
            fixationFor = sample(READING_FIXATION)
            return jumpTo(0f, -readingSpan)
        }
        fixationTimer += dt
        if (fixationTimer < fixationFor) return 0f
        fixationTimer = 0f
        fixationFor = sample(READING_FIXATION)
        val next = sacYaw + sample(READING_STEP)
        if (next <= readingSpan) return jumpTo(sacPitch, next)
        // Le retour à la ligne : un seul grand saut vers le début. Une ligne plus bas, souvent ; au bas d'une bulle
        // courte, elle reste sur la dernière (elle relit la fin).
        if (readingLine < READING_MAX_LINES - 1 && random() < READING_LINE_DROP_P) readingLine++
        readingSpan = sample(READING_SPAN)
        return jumpTo(readingLine * READING_LINE_STEP, -readingSpan)
    }

    /**
     * La lecture finie, les yeux quittent la ligne d'un saut — un reste de balayage tenu des secondes pendant le
     * contact se lirait comme un regard de travers — et l'horloge des saccades ordinaires repart de zéro.
     */
    private fun endReading(): Float {
        saccadeTimer = 0f
        nextSaccadeAt = sample(SACCADE_INTERVAL)
        return jumpTo(0f, 0f)
    }

    private fun jumpTo(pitch: Float, yaw: Float): Float {
        val jump = hypot(pitch - sacPitch, yaw - sacYaw)
        sacPitch = pitch
        sacYaw = yaw
        return jump
    }

    private fun sample(range: ClosedFloatingPointRange<Float>): Float =
        range.start + random() * max(0f, range.endInclusive - range.start)

    private fun pick(size: Int): Int = min(size - 1, floor(random() * size).toInt())

    /** La tendance d'une émotion à détourner le regard : `p` multiplie la probabilité de base, `dir` est sa direction. */
    data class AversionProfile(val p: Float, val dir: GazeAngles? = null)

    companion object {
        const val INNER_PERSONA = "inner"

        val AVERSION_PROFILE: Map<String, AversionProfile> = mapOf(
            // La honte et la tristesse détournent vers le BAS — l'indice le plus fort, le plus lisible.
            "embarrassed" to AversionProfile(2.2f, GazeAngles(0.18f, -0.16f)),
            "anxious" to AversionProfile(1.8f, GazeAngles(0.12f, 0.14f)),
            "scared" to AversionProfile(1.4f, GazeAngles(0.1f, 0.18f)),
            "sad" to AversionProfile(1.6f, GazeAngles(0.2f, 0.0f)),
            "lonely" to AversionProfile(1.6f, GazeAngles(0.18f, -0.05f)),
            "melancholic" to AversionProfile(1.5f, GazeAngles(0.16f, -0.1f)),
            "jealous" to AversionProfile(1.4f, GazeAngles(0.06f, -0.2f)),
            "disgusted" to AversionProfile(1.2f, GazeAngles(0.04f, -0.18f)),
            // Le souvenir et la rêverie vont en HAUT et de côté.
            "thinking" to AversionProfile(1.8f, GazeAngles(-0.16f, 0.18f)),
            "confused" to AversionProfile(1.5f, GazeAngles(-0.1f, -0.14f)),
            "dreamy" to AversionProfile(1.5f, GazeAngles(-0.18f, 0.04f)),
            "nostalgic" to AversionProfile(1.4f, GazeAngles(-0.12f, 0.12f)),
            "hopeful" to AversionProfile(0.9f, GazeAngles(-0.12f, 0.06f)),
            "frustrated" to AversionProfile(1.1f, GazeAngles(-0.08f, 0.16f)),
            "bored" to AversionProfile(1.7f, GazeAngles(-0.04f, 0.22f)),
            "proud" to AversionProfile(0.7f, GazeAngles(-0.1f, 0.1f)),
            // Le regard tenu : les émotions d'attachement, et celles qui fixent.
            "love" to AversionProfile(0.35f),
            "grateful" to AversionProfile(0.5f),
            "determined" to AversionProfile(0.4f),
            "angry" to AversionProfile(0.6f),
            "curious" to AversionProfile(0.8f),
            "surprised" to AversionProfile(0.3f),
        )

        /** Des saccades plus petites et plus rares pour un regard concentré, plus larges et nerveuses s'il est alarmé. */
        val FOCUSED_EMOTIONS: Set<String> = setOf("love", "grateful", "proud", "determined")
        val RESTLESS_EMOTIONS: Set<String> = setOf("scared", "anxious", "surprised", "excited")

        // ── Durées (secondes) et amplitudes (radians) ──────────────────────
        val AVERSION_INTERVAL = 3.5f..8f
        val AVERSION_DURATION = 0.7f..2.0f
        const val AVERSION_P_IDLE = 0.4f
        const val AVERSION_P_SPEAKING = 0.55f
        const val AVERSION_P_LISTENING = 0.18f

        /** Le regard de préparation au début d'un énoncé. */
        const val ONSET_AVERSION_P = 0.45f
        val ONSET_AVERSION_DURATION = 0.9f..1.6f
        val PLANNING_OFFSET = GazeAngles(-0.12f, 0.16f)
        const val THINKING_CONTACT = 0.15f
        val THINKING_OFFSET = GazeAngles(-0.14f, 0.2f)
        val THINKING_CHECKIN_INTERVAL = 2.5f..5f
        val THINKING_CHECKIN_DURATION = 0.5f..0.9f

        /** Une réponse qui ne vient jamais cesse d'être « réfléchie » au bout de ce temps. */
        const val THINKING_MAX_S = 90f
        const val INNER_CONTACT = 0.1f
        val INNER_OFFSET = GazeAngles(0.14f, 0.12f)

        /**
         * La lecture (propre à l'app). La bulle s'affiche sous son visage, entre elle et la personne : vue de ses
         * yeux, elle est dans la direction de la caméra, plus bas. D'où un contact partiel — l'ancrage sur la
         * personne, qui suit la caméra quand on tourne autour d'elle — plus un tangage vers le bas : 0,22 rad, dont
         * la tête prend sa part ([HeadAttentionOverlay.HEAD_OFFSET_SHARE]) et les yeux le reste, soit ~0,25 rad sous
         * le spectateur une fois la tête posée, sans sortir de la course de l'œil (10° sur ce modèle).
         */
        const val READING_CONTACT = 0.8f
        val READING_OFFSET = GazeAngles(0.22f, 0f)

        /** La demi-largeur d'une ligne (rad) : la bulle est petite à cette distance, le balayage aussi. */
        val READING_SPAN = 0.05f..0.07f

        /** Un saut le long de la ligne (rad) : quatre ou cinq fixations par ligne. */
        val READING_STEP = 0.022f..0.034f

        /** Une fixation de lecture (s), la durée que la littérature donne (~200–280 ms). */
        val READING_FIXATION = 0.2f..0.28f

        /** Une ligne plus bas (rad) ; la chance de descendre à chaque retour à la ligne, et combien de lignes au plus. */
        const val READING_LINE_STEP = 0.018f
        const val READING_LINE_DROP_P = 0.6f
        const val READING_MAX_LINES = 3
        val SACCADE_INTERVAL = 1.8f..4.5f

        /** En contact, les yeux parcourent le visage (yeux ↔ bouche, 1–4°) ; hors du spectateur, ils errent plus large. */
        val SACCADE_AMPLITUDE_CONTACT = 0.02f..0.07f
        val SACCADE_AMPLITUDE_FREE = 0.04f..0.1f

        /**
         * Laissée seule, on ne fixe pas l'endroit où quelqu'un était. Après un moment sans personne qui parle ni
         * écrive, son attention glisse vers la pièce — la porte, le lit, ses mains, le sol, la lumière de la fenêtre,
         * le vague — en longs regards, avec des coups d'œil vers le spectateur entre eux. Tout signe de la personne
         * (une frappe, un message, sa propre réponse) ramène les yeux aussitôt : être remarqué, c'est le but.
         */
        val WALKING_OFFSET = GazeAngles(0.16f, 0f)
        const val WANDER_AFTER_S = 25f
        const val WANDER_P = 0.75f
        val WANDER_DURATION = 2.5f..7f
        val WANDER_INTERVAL = 2f..6f

        /** Les points d'intérêt, dans son repère de regard sémantique, d'après la pièce (`Environment.ts`). */
        val WANDER_POINTS: List<GazeAngles> = listOf(
            GazeAngles(0.04f, 0.55f), // la porte, devant à gauche
            GazeAngles(0.24f, -0.5f), // le lit, devant à droite
            GazeAngles(0.34f, 0.08f), // le sol devant elle
            GazeAngles(0.3f, -0.14f), // ses mains
            GazeAngles(-0.12f, -0.72f), // la lumière de la fenêtre
            GazeAngles(-0.2f, 0.32f), // en haut, ailleurs — la rêverie
            GazeAngles(0.02f, -0.38f), // la plante près du lit
        )

        private val AVERSION_DIRS: List<GazeAngles> = listOf(
            GazeAngles(0.14f, 0.16f),
            GazeAngles(0.14f, -0.16f),
            GazeAngles(-0.12f, 0.18f),
            GazeAngles(-0.12f, -0.18f),
            GazeAngles(0.02f, 0.22f),
            GazeAngles(0.02f, -0.22f),
        )
    }
}
