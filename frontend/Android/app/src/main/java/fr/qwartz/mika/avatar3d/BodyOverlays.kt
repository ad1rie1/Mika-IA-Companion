package fr.qwartz.mika.avatar3d

import fr.qwartz.mika.avatar3d.BodyMath.addRotation
import fr.qwartz.mika.avatar3d.BodyMath.smooth
import kotlin.math.abs
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
