package fr.qwartz.mika.avatar3d

import fr.qwartz.mika.avatar3d.BodyMath.addRotation
import fr.qwartz.mika.avatar3d.BodyMath.smooth
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.exp
import kotlin.math.min
import kotlin.math.sign
import kotlin.math.sin
import kotlin.random.Random

/**
 * Le souffle — le mouvement qu'un corps vivant ne cesse jamais de faire (`BreathingOverlay.ts`).
 *
 * L'ancienne couche du web était un sinus de 0,005 rad sur la colonne : un métronome sous le souffle (enregistré, en
 * boucle) du clip. Une respiration humaine n'est rien de cela : l'inspiration est plus rapide que l'expiration et
 * suivie d'une courte pause, deux cycles n'ont jamais la même longueur ni la même profondeur, le rythme s'accélère
 * avec l'arousal et ralentit dans le sommeil, de temps en temps un souffle est plus profond que les autres, et en
 * parlant le régime change tout à fait — une inspiration rapide avant chaque proposition, puis une longue expiration
 * lente qui porte les mots. Un soupir, c'est une grande inspiration et un long relâchement, les épaules qui tombent.
 *
 * Le remplissage (0 = vides, 1 = pleins) soulève la poitrine et la colonne en une légère extension et monte les
 * épaules ; la nuque reprend la moitié du tangage, pour que le visage reste posé sur qui elle regarde. Il est publié
 * dans le contexte ([BodyContext.breath]) pour qui veut le suivre.
 */
class BreathingOverlay(private val random: () -> Float = { Random.nextFloat() }) {
    private var phase = random()
    private var cycleScale = 1f
    private var depthScale = 1f
    private var fill = 0f
    private var catchRemaining = 0f

    /** Le temps écoulé dans un soupir, ou −1 hors soupir. */
    private var sighTime = -1f
    private var wasSpeaking = false

    fun update(dt: Float, ctx: BodyContext, rig: AvatarRig, pose: Pose) {
        val request = ctx.breathRequest
        ctx.breathRequest = null
        if (request == BreathRequest.SIGH && ctx.awake) sighTime = 0f
        else if (request == BreathRequest.CATCH) catchRemaining = CATCH_SECONDS

        val a = if (ctx.awake) ctx.arousal else 0f
        val depth = PHASE_DEPTH.getValue(ctx.phase) * (1 - 0.15f * a)

        if (sighTime >= 0f) {
            sighTime += dt
            fill = sampleKeys(SIGH, sighTime)
            if (sighTime >= SIGH.last().first) {
                sighTime = -1f
                phase = EXHALE_END // reprendre après le relâchement, dans la pause
            }
        } else if (ctx.speaking && ctx.awake) {
            // Le souffle de la parole : une prise rapide, puis les mots emportent l'air lentement. Jamais le sinus
            // du repos en parlant.
            if (catchRemaining > 0f) {
                catchRemaining -= dt
                fill += (CATCH_FILL * depth - fill) * min(1f, dt * CATCH_RATE)
            } else {
                fill += (SPEECH_FLOOR - fill) * min(1f, dt * SPEECH_EXHALE_RATE)
            }
            wasSpeaking = true
        } else {
            if (wasSpeaking) {
                // Retour au souffle de repos d'où la parole a laissé les poumons : on entre dans le cycle par son
                // expiration, au remplissage correspondant.
                wasSpeaking = false
                phase = INHALE_END + (1 - min(1f, fill)) * (EXHALE_END - INHALE_END) * 0.5f
            }
            val rate = PHASE_RATE_HZ.getValue(ctx.phase) * (1 + 0.4f * a).coerceIn(0.75f, 1.5f) * (1 - 0.2f * ctx.fatigue)
            phase += dt * rate / cycleScale
            if (phase >= 1f) {
                phase -= 1f
                // Deux souffles jamais pareils : chaque cycle tire sa longueur et sa profondeur.
                cycleScale = 0.85f + random() * 0.35f
                depthScale = if (ctx.awake && random() < DEEP_BREATH_P) 1.7f else 0.8f + random() * 0.35f
            }
            val target = breathWave(phase) * depth * depthScale
            // Adouci plutôt qu'affecté : un passage parole → repos, un changement de phase ne fait jamais sauter la
            // poitrine.
            fill += (target - fill) * min(1f, dt * 8)
        }

        ctx.breath = fill
        val f = fill
        addRotation(rig, pose, "spine", BREATH_SPINE_PITCH * f, 0f, 0f)
        addRotation(rig, pose, "chest", BREATH_CHEST_PITCH * f, 0f, 0f)
        addRotation(rig, pose, "neck", -(BREATH_SPINE_PITCH + BREATH_CHEST_PITCH) * NECK_COMPENSATION * f, 0f, 0f)
        // Un roulis positif lève l'épaule gauche (elle pointe vers sa gauche) ; la droite pointe de l'autre côté,
        // son lever est le roulis opposé.
        addRotation(rig, pose, "leftShoulder", 0f, 0f, BREATH_SHOULDER_LIFT * f)
        addRotation(rig, pose, "rightShoulder", 0f, 0f, -BREATH_SHOULDER_LIFT * f)
    }

    companion object {
        /** Cycles par seconde au repos, avant l'arousal. ~15/min éveillée. */
        val PHASE_RATE_HZ: Map<String, Float> = mapOf(
            BodyContext.AWAKE to 0.25f,
            BodyContext.LIGHT_SLEEP to 0.2f,
            BodyContext.REM to 0.23f,
            BodyContext.DEEP_SLEEP to 0.16f,
        )
        val PHASE_DEPTH: Map<String, Float> = mapOf(
            BodyContext.AWAKE to 1.0f,
            BodyContext.LIGHT_SLEEP to 1.3f,
            BodyContext.REM to 1.15f,
            BodyContext.DEEP_SLEEP to 1.5f,
        )

        /** La part du cycle passée à inspirer / où finit l'expiration (le reste est la pause après l'expiration). */
        const val INHALE_END = 0.36f
        const val EXHALE_END = 0.86f

        /** Un souffle augmenté, rare (« soupir physiologique »), par cycle de repos. */
        const val DEEP_BREATH_P = 0.07f

        /** Les deltas des os à remplissage 1 (rad). */
        const val BREATH_SPINE_PITCH = -0.011f
        const val BREATH_CHEST_PITCH = -0.016f
        const val BREATH_SHOULDER_LIFT = 0.032f

        /** La part du tangage du torse que la nuque rend. */
        const val NECK_COMPENSATION = 0.5f

        /** Le régime de la parole : vitesse d'une prise (1/s), vitesse d'expiration en parlant, et jusqu'où une prise remplit. */
        const val CATCH_RATE = 9f
        const val CATCH_SECONDS = 0.32f
        const val CATCH_FILL = 0.8f
        const val SPEECH_EXHALE_RATE = 0.28f
        const val SPEECH_FLOOR = 0.12f

        /** Un soupir, écrit en clés (temps s, remplissage). */
        val SIGH: List<Pair<Float, Float>> = listOf(
            0f to 0f,
            1.0f to 1.75f,
            1.3f to 1.8f,
            3.2f to -0.3f,
            4.0f to 0f,
        )

        /** La forme du souffle de repos sur un cycle, p ∈ [0, 1). */
        fun breathWave(p: Float): Float = when {
            p < INHALE_END -> smooth(p / INHALE_END)
            p < EXHALE_END -> 1 - smooth((p - INHALE_END) / (EXHALE_END - INHALE_END))
            else -> 0f
        }

        private fun sampleKeys(keys: List<Pair<Float, Float>>, t: Float): Float {
            for (i in 1 until keys.size) {
                val (t1, v1) = keys[i]
                if (t <= t1) {
                    val (t0, v0) = keys[i - 1]
                    return v0 + (v1 - v0) * smooth((t - t0) / maxOf(1e-6f, t1 - t0))
                }
            }
            return keys.last().second
        }
    }
}

/**
 * La vie entre les images enregistrées (`LifeOverlay.ts`).
 *
 * Une attente enregistrée, ce sont quelques secondes de capture en boucle : à la troisième répétition, l'œil sait
 * exactement quand l'épaule va plonger. Quelqu'un debout n'est jamais en boucle — le torse oscille un peu, la tête
 * dérive et se recentre, les poignets tournent, et toutes les quelques secondes le poids passe d'une jambe à l'autre
 * et la posture se réinstalle. Cette couche ajoute exactement cela, sur ce que fait le clip :
 *
 *   1. un micro-mouvement continu — par os et par axe, une somme de sinus incommensurables (jamais visiblement
 *      périodique), assez petit pour rester sous le clip ;
 *   2. des transferts de poids — à intervalles irréguliers, le torse penche d'un côté en une seconde ou deux et y
 *      reste, la poitrine et la nuque en reprenant une part pour que la tête reste droite (on garde les yeux à
 *      l'horizontale) ;
 *   3. des réinstallations — de temps en temps un petit ajustement rapide de la nuque et des épaules, le « tic » qui
 *      signe un corps vivant.
 *
 * L'arousal règle le tout : un corps anxieux ou excité est plus affairé, un triste ou ennuyé plus immobile ; dans le
 * sommeil il n'en reste qu'une trace. Les hanches ne sont pas touchées, exprès : les tourner ferait glisser les pieds.
 */
class LifeOverlay(private val random: () -> Float = { Random.nextFloat() }) {
    /** Le temps du bruit, en Double : au bout de quelques heures, un Float quantifierait les sinus. */
    private var time: Double = random() * 1000.0

    /** Le gain global, adouci — un changement d'humeur règle le corps en ~1 s. */
    private var gain = 1f
    private var talkGain = 0f

    private var lean = 0f
    private var leanFrom = 0f
    private var leanTo = 0f
    private var shiftT = 1f
    private var shiftDur = 1.8f
    private var nextShift = sample(SHIFT_INTERVAL)

    private var settle = Settle()
    private var settleFrom = Settle()
    private var settleTo = Settle()
    private var settleT = 1f
    private var nextSettle = sample(SETTLE_INTERVAL)

    private data class Settle(val neckX: Float = 0f, val neckY: Float = 0f, val neckZ: Float = 0f, val shoulders: Float = 0f)

    /** Par os, le delta (tangage, lacet, roulis) de l'image — dans l'ordre d'insertion, comme le `Map` du web. */
    private val rot = LinkedHashMap<String, FloatArray>()

    fun update(dt: Float, ctx: BodyContext, rig: AvatarRig, pose: Pose) {
        time += dt
        val awake = ctx.awake
        val a = if (awake) ctx.arousal else 0f
        // Plus affairée quand elle est survoltée, plus immobile quand elle est vidée ; une trace dans le sommeil.
        val target = if (awake) (1 + 0.6f * a).coerceIn(0.5f, 1.6f) * (1 - 0.35f * ctx.fatigue) else 0.15f
        val ease = min(1f, dt * AMP_EASE)
        gain += (target - gain) * ease
        talkGain += ((if (ctx.speaking) 1f else 0f) - talkGain) * ease
        // La marche porte son propre mouvement : seule une trace du balancement debout.
        if (ctx.walking) gain = min(gain, 0.35f)
        // Un corps anxieux bouge plus vite, un triste plus lentement.
        val tempo = 1 + 0.35f * a

        rot.clear()
        for (c in LIFE_CHANNELS) {
            val talk = 1 + (c.talk - 1) * talkGain
            add(c.bone, c.axis, lifeNoise(time * c.rate * tempo, c.seed).toFloat() * c.amp * gain * talk)
        }

        if (awake && !ctx.walking) {
            updateShift(dt)
            updateSettle(dt, a)
        } else {
            // Endormie : l'inclinaison revient au centre, rien de nouveau ne commence.
            lean += (0 - lean) * ease
            nextShift = maxOf(nextShift, 2f)
        }
        add("spine", 2, lean)
        add("chest", 2, -lean * SHIFT_CHEST_BACK)
        add("neck", 2, -lean * SHIFT_NECK_BACK)

        val s = settle
        add("neck", 0, s.neckX)
        add("neck", 1, s.neckY)
        add("neck", 2, s.neckZ)
        add("leftShoulder", 2, s.shoulders)
        add("rightShoulder", 2, -s.shoulders)

        for ((bone, r) in rot) addRotation(rig, pose, bone, r[0], r[1], r[2])
    }

    private fun add(bone: String, axis: Int, v: Float) {
        rot.getOrPut(bone) { FloatArray(3) }[axis] += v
    }

    private fun updateShift(dt: Float) {
        if (shiftT < 1f) {
            shiftT = min(1f, shiftT + dt / shiftDur)
            lean = leanFrom + (leanTo - leanFrom) * smooth(shiftT)
            return
        }
        nextShift -= dt
        if (nextShift > 0f) return
        // Le plus souvent de l'autre côté ; parfois juste vers le milieu.
        val side = when {
            leanTo > 0f -> -1f
            leanTo < 0f -> 1f
            random() < 0.5f -> -1f
            else -> 1f
        }
        val amount = if (random() < 0.25f) 0.2f else 0.6f + random() * 0.4f
        leanFrom = lean
        leanTo = side * SHIFT_LEAN * amount
        shiftT = 0f
        shiftDur = sample(SHIFT_SECONDS)
        nextShift = sample(SHIFT_INTERVAL)
    }

    private fun updateSettle(dt: Float, arousal: Float) {
        if (settleT < 1f) {
            settleT = min(1f, settleT + dt / SETTLE_SECONDS)
            val k = smooth(settleT)
            val f = settleFrom
            val t = settleTo
            settle = Settle(
                neckX = f.neckX + (t.neckX - f.neckX) * k,
                neckY = f.neckY + (t.neckY - f.neckY) * k,
                neckZ = f.neckZ + (t.neckZ - f.neckZ) * k,
                shoulders = f.shoulders + (t.shoulders - f.shoulders) * k,
            )
            return
        }
        // Les humeurs agitées se réinstallent plus souvent.
        nextSettle -= dt * (1 + maxOf(0f, arousal))
        if (nextSettle > 0f) return
        val r = { (random() * 2 - 1) * SETTLE_AMP }
        settleFrom = settle
        settleTo = Settle(neckX = r() * 0.6f, neckY = r(), neckZ = r() * 0.7f, shoulders = r() * 0.5f)
        settleT = 0f
        nextSettle = sample(SETTLE_INTERVAL)
    }

    private fun sample(range: ClosedFloatingPointRange<Float>): Float =
        range.start + random() * (range.endInclusive - range.start)

    /** Un canal de bruit : l'os, l'axe (0 tangage, 1 lacet, 2 roulis), l'amplitude à arousal 0 et le rythme. */
    data class LifeChannel(
        val bone: String,
        val axis: Int,
        /** L'amplitude (rad) à arousal 0. */
        val amp: Float,
        /** L'échelle de temps du bruit (≈ Hz de sa composante la plus lente). */
        val rate: Float,
        val seed: Int,
        /** L'amplitude en plus quand elle parle (le haut du corps anime la parole). */
        val talk: Float = 1f,
    )

    companion object {
        /** Trois sinus incommensurables, ramenés à ~[−1, 1]. */
        fun lifeNoise(t: Double, seed: Int): Double =
            (sin(t * 6.283 + seed * 1.7) +
                sin(t * 6.283 * 2.31 + seed * 3.9) * 0.55 +
                sin(t * 6.283 * 3.73 + seed * 5.3) * 0.3) / 1.85

        val LIFE_CHANNELS: List<LifeChannel> = listOf(
            LifeChannel("spine", 0, 0.008f, 0.11f, 1),
            LifeChannel("spine", 1, 0.012f, 0.07f, 2),
            LifeChannel("spine", 2, 0.01f, 0.09f, 3),
            LifeChannel("chest", 0, 0.006f, 0.13f, 4),
            LifeChannel("chest", 1, 0.012f, 0.1f, 5, talk = 1.6f),
            LifeChannel("chest", 2, 0.007f, 0.08f, 6),
            LifeChannel("neck", 0, 0.012f, 0.19f, 7, talk = 1.4f),
            LifeChannel("neck", 1, 0.016f, 0.15f, 8, talk = 1.3f),
            LifeChannel("neck", 2, 0.012f, 0.13f, 9),
            LifeChannel("leftShoulder", 2, 0.014f, 0.17f, 10, talk = 1.5f),
            LifeChannel("rightShoulder", 2, 0.014f, 0.21f, 11, talk = 1.5f),
            LifeChannel("leftUpperArm", 0, 0.014f, 0.09f, 12),
            LifeChannel("leftUpperArm", 2, 0.016f, 0.12f, 13),
            LifeChannel("rightUpperArm", 0, 0.014f, 0.1f, 14),
            LifeChannel("rightUpperArm", 2, 0.016f, 0.14f, 15),
            LifeChannel("leftHand", 0, 0.05f, 0.23f, 16, talk = 1.6f),
            LifeChannel("leftHand", 2, 0.04f, 0.29f, 17),
            LifeChannel("rightHand", 0, 0.05f, 0.27f, 18, talk = 1.6f),
            LifeChannel("rightHand", 2, 0.04f, 0.31f, 19),
        )

        /** Le transfert de poids : l'inclinaison de la colonne (rad), et ce que la poitrine / la nuque rendent pour garder les yeux droits. */
        const val SHIFT_LEAN = 0.03f
        const val SHIFT_CHEST_BACK = 0.45f
        const val SHIFT_NECK_BACK = 0.4f
        val SHIFT_INTERVAL = 6f..17f
        val SHIFT_SECONDS = 1.3f..2.4f

        /** La réinstallation : un petit ajustement rapide de la nuque et des épaules. */
        val SETTLE_INTERVAL = 11f..30f
        const val SETTLE_SECONDS = 0.55f
        const val SETTLE_AMP = 0.035f

        const val AMP_EASE = 1.5f
    }
}

/**
 * La tête qui tombe en avant pendant le sommeil — l'avatar « pique du nez » (`SleepOverlay.ts`). Additive : elle n'a
 * besoin d'aucune remise à zéro au réveil, ne pas contribuer, c'est zéro.
 */
class SleepOverlay {
    private var tilt = 0f

    fun update(dt: Float, ctx: BodyContext, rig: AvatarRig, pose: Pose) {
        val target = PHASE_HEAD_TILT.getValue(ctx.phase)
        val rate = min(1f, dt / EASE_SECONDS * 4)
        tilt += (target - tilt) * rate
        if (abs(tilt) < 0.0005f) {
            tilt = if (target == 0f) 0f else tilt
            if (tilt == 0f) return
        }
        addRotation(rig, pose, "neck", tilt, 0f, 0f)
    }

    companion object {
        val PHASE_HEAD_TILT: Map<String, Float> = mapOf(
            BodyContext.AWAKE to 0f,
            BodyContext.LIGHT_SLEEP to 0.12f,
            BodyContext.REM to 0.18f,
            BodyContext.DEEP_SLEEP to 0.25f,
        )
        const val EASE_SECONDS = 1.2f
    }
}

/**
 * Le port de tête de l'émotion (`HeadEmotionOverlay.ts`), composé SUR ce que le clip fait de la tête. Retenu
 * (ramené doucement à zéro, jamais figé) pendant le sommeil, pour ne pas s'empiler sur la tête qui tombe.
 */
class HeadEmotionOverlay {
    private var pitch = 0f
    private var roll = 0f
    private var yaw = 0f

    fun update(dt: Float, ctx: BodyContext, rig: AvatarRig, pose: Pose) {
        var tp = 0f
        var tr = 0f
        var ty = 0f
        if (ctx.awake) {
            val p = EMOTION_HEAD_POSE[ctx.emotion]
            if (p != null) {
                val scale = 0.3f + ctx.intensity * 0.7f
                tp = p.pitch * scale
                tr = p.roll * scale
                ty = p.yaw * scale
            }
        }
        val ease = min(1f, dt * EASE_SPEED)
        pitch += (tp - pitch) * ease
        roll += (tr - roll) * ease
        yaw += (ty - yaw) * ease
        addRotation(rig, pose, "head", pitch, yaw, roll)
    }

    /**
     * Un port de tête (rad) : `pitch` > 0 baisse le menton ; `roll` > 0 penche vers sa droite ; `yaw` > 0 tourne vers
     * SA GAUCHE (la droite de qui la regarde — le « turn right » du commentaire web ; les yeux de [GazeController]
     * partent du même côté pour la même émotion).
     */
    data class HeadPose(val pitch: Float, val roll: Float, val yaw: Float)

    companion object {
        val EMOTION_HEAD_POSE: Map<String, HeadPose> = mapOf(
            // Curiosité et réflexion → la tête penchée d'un côté.
            "curious" to HeadPose(-0.04f, 0.10f, 0f),
            "thinking" to HeadPose(-0.02f, 0.08f, 0.03f),
            "confused" to HeadPose(0.0f, -0.10f, 0f),
            // L'embarras → la tête tourne en bas, ailleurs.
            "embarrassed" to HeadPose(0.08f, -0.05f, -0.05f),
            // La fierté → le menton un peu levé.
            "proud" to HeadPose(-0.06f, 0.0f, 0f),
            "determined" to HeadPose(-0.03f, 0.0f, 0f),
            // La famille de la tristesse → la tête basse.
            "sad" to HeadPose(0.08f, 0.0f, 0f),
            "lonely" to HeadPose(0.06f, 0.0f, 0f),
            "melancholic" to HeadPose(0.06f, 0.03f, 0f),
            // La surprise → la tête un peu en arrière.
            "surprised" to HeadPose(-0.05f, 0.0f, 0f),
            "scared" to HeadPose(-0.03f, 0.04f, 0f),
            // La rêverie, l'amour → une inclinaison douce.
            "dreamy" to HeadPose(-0.02f, 0.05f, 0f),
            "love" to HeadPose(0.0f, 0.04f, 0f),
            // La malice → une légère inclinaison, en complément d'un regard de côté.
            "mischievous" to HeadPose(-0.02f, 0.06f, 0.05f),
            // Tout le reste garde la tête au repos.
        )

        /** Plus lent que les expressions — ça se lit naturel. */
        const val EASE_SPEED = 2.0f
    }
}

/**
 * La part de la tête dans un regard (`HeadAttentionOverlay.ts`) — additive sur la nuque et la tête, SUR ce que le
 * clip en fait.
 *
 * La coordination tête–yeux humaine : pour une cible à quelques degrés, les yeux seuls bougent ; au-delà, la tête
 * tourne vers elle et couvre l'essentiel de l'angle, les yeux mènent puis contre-tournent pendant que la tête rattrape
 * (le réflexe vestibulo-oculaire). Ici ce partage découle de l'ordre de l'image : cette couche mesure le spectateur
 * dans la tête TELLE QUE LE CLIP (et les couches d'avant) L'A POSÉE, adoucit une fraction de cet angle sur la nuque et
 * la tête, et [GazeController], qui passe après, pointe les yeux sur le reste. Quand un clip balance la tête, les
 * yeux restent sur le spectateur au lieu de le balayer.
 *
 * Mesurer avant d'ajouter son propre delta garde la boucle ouverte : à chaque image le clip réécrit les os, la mesure
 * est celle du clip seul, et l'état adouci se referme vers la cible — pas de rétroaction, pas de dérive.
 */
class HeadAttentionOverlay {
    private var yaw = 0f
    private var pitch = 0f

    fun update(dt: Float, ctx: BodyContext, rig: AvatarRig, pose: Pose) {
        var targetYaw = 0f
        var targetPitch = 0f
        val viewer = ctx.viewer
        val intent = ctx.attention

        ctx.viewerMeasured = false
        if (viewer != null && ctx.awake) {
            val d = BodyMath.viewerInHead(rig, pose, viewer)
            if (d != null) {
                val g = BodyMath.directionToGaze(d)
                ctx.viewerYaw = g.yaw
                ctx.viewerPitch = g.pitch
                ctx.viewerMeasured = true

                if (intent != null && viewerReachable(g.yaw, g.pitch)) {
                    targetYaw = intent.contact * follow(g.yaw) + intent.offset.yaw * HEAD_OFFSET_SHARE
                    targetPitch = intent.contact * follow(g.pitch) + intent.offset.pitch * HEAD_OFFSET_SHARE
                } else if (intent != null) {
                    // Hors de portée : une pensée tourne encore un peu la tête hors de son avant, le terme du
                    // spectateur a disparu.
                    targetYaw = intent.offset.yaw * HEAD_OFFSET_SHARE
                    targetPitch = intent.offset.pitch * HEAD_OFFSET_SHARE
                }
                targetYaw = targetYaw.coerceIn(-HEAD_MAX_YAW, HEAD_MAX_YAW)
                targetPitch = targetPitch.coerceIn(-HEAD_MAX_PITCH, HEAD_MAX_PITCH)
            }
        }

        val k = 1 - exp(-dt / HEAD_TAU)
        yaw += (targetYaw - yaw) * k
        pitch += (targetPitch - pitch) * k
        if (abs(yaw) + abs(pitch) < 1e-4f) return

        // La nuque est facultative dans la norme VRM : sans elle, la tête porte tout le tour plutôt que de perdre
        // la part de la nuque.
        val neckShare = if (pose["neck"] != null) NECK_SHARE else 0f
        if (neckShare > 0f) addRotation(rig, pose, "neck", pitch * neckShare, yaw * neckShare, 0f)
        addRotation(rig, pose, "head", pitch * (1 - neckShare), yaw * (1 - neckShare), 0f)
    }

    companion object {
        /** La part de l'angle restant que prend la tête (les yeux gardent le reste). */
        const val HEAD_FOLLOW = 0.7f

        /** En dessous, la tête ne se dérange pas — les petits écarts sont pour les yeux. */
        const val HEAD_DEAD_ZONE = 0.06f
        const val HEAD_MAX_YAW = 0.6f
        const val HEAD_MAX_PITCH = 0.32f

        /** La part d'un détournement / d'une pose de réflexion que suit la tête. */
        const val HEAD_OFFSET_SHARE = 0.55f

        /** La constante de temps de la tête — plus lente que les yeux, exprès. */
        const val HEAD_TAU = 0.28f

        /** Le partage du tour entre nuque et tête. */
        const val NECK_SHARE = 0.35f

        /** Au-delà, le spectateur est derrière elle : pas de torsion, regard droit devant. */
        const val HEAD_REACH_YAW = 1.35f
        const val HEAD_REACH_PITCH = 1.0f

        fun viewerReachable(yaw: Float, pitch: Float): Boolean =
            abs(yaw) <= HEAD_REACH_YAW && abs(pitch) <= HEAD_REACH_PITCH

        internal fun follow(angle: Float): Float {
            val mag = abs(angle)
            if (mag < HEAD_DEAD_ZONE) return 0f
            return sign(angle) * (mag - HEAD_DEAD_ZONE) * HEAD_FOLLOW
        }
    }
}

/**
 * Un ressort amorti sur un axe — un peu sous-amorti : une vraie nuque dépasse d'un cheveu, puis se pose. Euler
 * semi-implicite en sous-pas de 1/120 s : stable à toute durée d'image qu'on lui donne.
 */
internal class DampedSpring(private val omega: Float, private val zeta: Float) {
    var x = 0f
        private set
    var v = 0f
        private set

    fun step(dt: Float, target: Float): Float {
        val n = maxOf(1, ceil(dt / SUBSTEP).toInt())
        val h = dt / n
        repeat(n) {
            val a = -omega * omega * (x - target) - 2 * zeta * omega * v
            v += a * h
            x += v * h
        }
        return x
    }

    /** Une impulsion de vitesse dimensionnée pour que la réponse libre culmine à ≈ `peak`. */
    fun kick(peak: Float) {
        v += peak * omega * 1.7f
    }

    private companion object {
        const val SUBSTEP = 1f / 120f
    }
}

/**
 * La tête et les sourcils qui ponctuent la parole (`SpeechBodyOverlay.ts`).
 *
 * Les clips de parole tournent toutes les quelques secondes, mais rien en eux ne sait ce qui se dit : la tête d'un
 * clip enregistré hoche à son propre rythme. Cette couche part sur les temps forts de la réplique en cours
 * ([SpeechBeats]), quand le curseur les atteint :
 *
 *   STRESS        un petit hochement sur le mot ;
 *   EMPHASIS      un hochement plus franc, un léger tour, les sourcils qui sautent ;
 *   QUESTION      le menton levé et la tête penchée sur le dernier mot, les sourcils tenus levés ;
 *   FINAL         le hochement qui ferme une affirmation ;
 *   PAUSE         la tête se réoriente un peu ; une prise d'air ;
 *   TRAIL         une inclinaison douce, la phrase qui traîne ;
 *   PHRASE_START  la tête se relève d'un rien sur une prise d'air.
 *
 * Chaque axe est un ressort amorti, frappé par les temps forts et tiré vers des cibles tenues (l'inclinaison d'une
 * question). S'y ajoute, tant qu'elle parle, un mouvement continu au rythme de la parole — une tête n'est jamais
 * immobile chez quelqu'un qui parle.
 *
 * Elle passe APRÈS le tour de tête de l'attention : un hochement est un geste, pas un changement de ce qu'elle
 * regarde — le regard ([GazeController], après toutes les têtes) garde les yeux sur le spectateur à travers lui.
 *
 * Ce qui diffère du web, et pourquoi :
 *  - l'app n'a pas de voix : sa réponse s'écrit progressivement dans la bulle, et c'est l'énoncé ouvert
 *    ([begin] → [end]) qui tient lieu de voix — les temps forts partent même si l'appelant ne lève pas
 *    [BodyContext.speaking] ;
 *  - un bond du curseur (la personne touche la bulle et tout s'affiche) ne déclenche RIEN : le web ne sautait que
 *    les temps forts à plus de [STALE_CHARS] derrière le curseur, si bien qu'un bond jusqu'à la fin faisait encore
 *    partir ensemble ceux des derniers mots ;
 *  - les jetons `[SIGH]` / `[BREATH]` demandent leur souffle quand le curseur les atteint — la moitié de `playCue`
 *    du web qui revient au corps (le rire, un clip, revient à la machine à états) ;
 *  - le hochement « j'ai lu » ([acknowledge]) attend l'image suivante et tombe en dormant, au lieu de compter sur
 *    l'appelant pour vérifier l'éveil.
 */
class SpeechBodyOverlay(private val random: () -> Float = { Random.nextFloat() }) {
    private var beats: List<SpeechBeat> = emptyList()
    private var cues: List<SpeechCue> = emptyList()
    private var nextBeat = 0
    private var nextCue = 0
    private var lastCursor = -1
    private var open = false
    private var ackPending = false

    /** On ne commence pas à parler les poumons vides : le premier temps fort d'un énoncé prend une inspiration, quel qu'il soit. */
    private var firstBreath = false

    /** Le caractère atteint dans le texte de la réplique (celui que la bulle affiche) ; −1 : aucun. */
    var cursor: Int = -1

    /** Un énoncé est en cours : entre [begin] et [end]. */
    val uttering: Boolean get() = open

    private val pitch = DampedSpring(11f, 0.5f)
    private val yaw = DampedSpring(8f, 0.6f)
    private val roll = DampedSpring(5f, 0.75f)
    private var pitchHold = 0f
    private var yawHold = 0f
    private var rollHold = 0f
    private var holdRemaining = 0f
    private var holdKind: BeatKind? = null
    private var questionSide = 1f

    private var emphasis = 0f
    private var question = 0f

    /** Le temps du bruit de parole, en Double comme celui de [LifeOverlay]. */
    private var time = 0.0
    private var talk = 0f

    /** Un nouvel énoncé commence : ses temps forts remplacent ce qui restait du précédent. */
    fun begin(text: String) {
        beats = SpeechBeats.plan(text)
        cues = SpeechBeats.cues(text)
        nextBeat = 0
        nextCue = 0
        lastCursor = -1
        cursor = -1
        firstBreath = true
        open = true
    }

    /**
     * L'énoncé est fini (ou abandonné) : plus rien ne part. Les ressorts se posent d'eux-mêmes, et une question
     * garde son menton levé le temps de sa tenue — elle attend la réponse, la bulle finie.
     */
    fun end() {
        open = false
        beats = emptyList()
        cues = emptyList()
        cursor = -1
        lastCursor = -1
    }

    /**
     * « Bien reçu » : le petit hochement, les sourcils qui se lèvent, de qui reçoit un message auquel il va répondre.
     * Pas un temps fort de la parole — il part en silence, à l'image suivante, et jamais en dormant.
     */
    fun acknowledge() {
        ackPending = true
    }

    fun update(dt: Float, ctx: BodyContext, rig: AvatarRig, pose: Pose) {
        time += dt
        val awake = ctx.awake
        val voiced = awake && (open || ctx.speaking)
        val inner = ctx.persona == AttentionDirector.INNER_PERSONA
        // Un murmure à elle-même ne s'adresse à personne : à peine un battement.
        val scale = (if (inner) 0.35f else 1f) * (1 + 0.45f * ctx.arousal).coerceIn(0.55f, 1.4f)

        if (ackPending) {
            ackPending = false
            if (awake) {
                pitch.kick(ACK_NOD)
                emphasis = maxOf(emphasis, ACK_BROW)
            }
        }
        if (voiced && open) consume(ctx, scale, inner)

        if (holdRemaining > 0f) {
            holdRemaining -= dt
            if (holdRemaining <= 0f) {
                pitchHold = 0f
                rollHold = 0f
                yawHold *= 0.5f
                holdKind = null
            }
        }
        if (!voiced) yawHold += (0 - yawHold) * min(1f, dt * 0.8f)

        talk += ((if (voiced) 1f else 0f) - talk) * min(1f, dt * 3)
        val p0 = pitch.step(dt, pitchHold)
        val y0 = yaw.step(dt, yawHold)
        val r0 = roll.step(dt, rollHold)

        // Le mouvement continu de la parole : plus rapide et plus petit que la dérive de la couche de vie, seulement
        // tant qu'elle parle.
        val k = talk * scale
        val p = p0 + LifeOverlay.lifeNoise(time * 0.9, 31).toFloat() * 0.012f * k
        val y = y0 + LifeOverlay.lifeNoise(time * 0.7, 37).toFloat() * 0.016f * k
        val r = r0 + LifeOverlay.lifeNoise(time * 0.6, 41).toFloat() * 0.01f * k
        // Comme [HeadAttentionOverlay] : sans nuque (facultative dans la norme VRM), la tête porte tout le geste.
        val neckShare = if (pose["neck"] != null) NECK_SHARE else 0f
        if (neckShare > 0f) addRotation(rig, pose, "neck", p * neckShare, y * neckShare, r * neckShare)
        addRotation(rig, pose, "head", p * (1 - neckShare), y * (1 - neckShare), r * (1 - neckShare))

        val questionTarget = if (holdKind == BeatKind.QUESTION) 1f else 0f
        question += (questionTarget - question) * min(1f, dt * 5)
        emphasis = maxOf(0f, emphasis - dt * BROW_DECAY * maxOf(0.2f, emphasis))
        ctx.speechEmphasis = emphasis
        ctx.speechQuestion = question
    }

    private fun consume(ctx: BodyContext, scale: Float, inner: Boolean) {
        val c = cursor
        if (c < 0) return
        val rewound = c < lastCursor - REWIND_CHARS
        if (rewound) {
            // Le curseur est revenu en arrière : on réarme à partir de là.
            nextBeat = beats.indexOfFirst { it.at >= c }.let { if (it < 0) beats.size else it }
            nextCue = cues.indexOfFirst { it.at >= c }.let { if (it < 0) cues.size else it }
        }
        // Un bond en avant n'est pas de la parole : la personne a tout affiché d'un coup. Ce qui a été sauté est
        // consommé sans partir — une rafale de hochements sur un texte qu'elle n'a pas « dit » se lirait comme un tic.
        val leapt = !rewound && c - lastCursor > LEAP_CHARS
        lastCursor = c
        while (nextBeat < beats.size && beats[nextBeat].at <= c) {
            val beat = beats[nextBeat++]
            if (!leapt && c - beat.at <= STALE_CHARS) fire(beat, ctx, scale)
        }
        while (nextCue < cues.size && cues[nextCue].at <= c) {
            val cue = cues[nextCue++]
            if (!leapt && !inner && c - cue.at <= STALE_CHARS) play(cue, ctx)
        }
    }

    private fun fire(beat: SpeechBeat, ctx: BodyContext, scale: Float) {
        val s = beat.strength * scale
        pitch.kick(NOD.getValue(beat.kind) * s)
        emphasis = minOf(1f, maxOf(emphasis, (BROW[beat.kind] ?: 0f) * s))
        if ((beat.kind in CATCH || firstBreath) && ctx.breathRequest == null) ctx.breathRequest = BreathRequest.CATCH
        firstBreath = false

        when (beat.kind) {
            BeatKind.EMPHASIS -> yaw.kick((if (random() < 0.5f) -1f else 1f) * 0.02f * s)
            // Entre deux idées, on réoriente un peu la tête.
            BeatKind.PAUSE -> yawHold = (random() * 2 - 1) * 0.03f * scale
            BeatKind.QUESTION -> {
                questionSide = if (random() < 0.7f) questionSide else -questionSide
                rollHold = questionSide * QUESTION_TILT * s
                pitchHold = QUESTION_LIFT * s
                holdRemaining = QUESTION_HOLD_S
                holdKind = BeatKind.QUESTION
            }
            BeatKind.TRAIL -> {
                rollHold = (if (random() < 0.5f) -1f else 1f) * TRAIL_TILT * s
                pitchHold = 0.015f * s
                holdRemaining = TRAIL_HOLD_S
                holdKind = BeatKind.TRAIL
            }
            BeatKind.FINAL -> {
                pitchHold = 0f
                rollHold = 0f
                holdKind = null
            }
            BeatKind.STRESS, BeatKind.PHRASE_START -> Unit
        }
    }

    /** Le souffle d'un jeton de prosodie : un soupir l'emporte sur tout, une inspiration n'écrase pas un soupir. */
    private fun play(cue: SpeechCue, ctx: BodyContext) {
        when (cue.kind) {
            SpeechCueKind.SIGH -> ctx.breathRequest = BreathRequest.SIGH
            SpeechCueKind.BREATH -> if (ctx.breathRequest != BreathRequest.SIGH) ctx.breathRequest = BreathRequest.CATCH
            SpeechCueKind.LAUGH -> Unit
        }
    }

    companion object {
        /** Le pic du hochement par temps fort (rad, > 0 = tête en bas). */
        val NOD: Map<BeatKind, Float> = mapOf(
            BeatKind.PHRASE_START to -0.025f,
            BeatKind.STRESS to 0.045f,
            BeatKind.EMPHASIS to 0.075f,
            BeatKind.PAUSE to 0.02f,
            BeatKind.TRAIL to 0.016f,
            BeatKind.QUESTION to 0f,
            BeatKind.FINAL to 0.055f,
        )

        /** L'éclair de sourcils par temps fort, 0…1. */
        val BROW: Map<BeatKind, Float> = mapOf(
            BeatKind.PHRASE_START to 0.3f,
            BeatKind.STRESS to 0.35f,
            BeatKind.EMPHASIS to 1f,
            BeatKind.QUESTION to 0.6f,
            BeatKind.TRAIL to 0.25f,
        )

        /** Les temps forts qui viennent avec une prise d'air. */
        val CATCH: Set<BeatKind> = setOf(BeatKind.PHRASE_START, BeatKind.PAUSE)

        const val QUESTION_TILT = 0.075f
        const val QUESTION_LIFT = -0.035f
        const val QUESTION_HOLD_S = 1.3f
        const val TRAIL_TILT = 0.04f
        const val TRAIL_HOLD_S = 1.2f

        /** Un temps fort que le curseur a dépassé de plus de tant de caractères est sauté, pas lancé en retard. */
        const val STALE_CHARS = 12

        /**
         * Au-delà de tant de caractères d'un coup, le curseur a bondi (tout affiché) : rien de ce qu'il franchit ne
         * part. La bulle avance de 16 à 34 caractères par seconde : même un accroc d'un tiers de seconde reste loin
         * en dessous, et un affichage mot par mot aussi.
         */
        const val LEAP_CHARS = 20

        /** Un recul de quelques caractères est du bruit ; au-delà, le curseur est vraiment revenu en arrière. */
        const val REWIND_CHARS = 3
        const val BROW_DECAY = 3.2f
        const val NECK_SHARE = 0.4f

        /** Le hochement « j'ai lu » et ses sourcils. */
        const val ACK_NOD = 0.04f
        const val ACK_BROW = 0.35f
    }
}
