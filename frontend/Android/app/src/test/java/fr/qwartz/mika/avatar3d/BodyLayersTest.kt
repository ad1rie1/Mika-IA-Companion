package fr.qwartz.mika.avatar3d

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs
import kotlin.math.acos
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.min
import kotlin.math.sign
import kotlin.math.sin
import kotlin.random.Random

/**
 * Les couches du corps, vérifiées par la GÉOMÉTRIE — « l'avant de l'œil pointe sur la caméra », « l'avant de la tête
 * descend » — jamais par une constante de signe : sur le web, c'est un commentaire qui s'était trompé (`sad` levait le
 * menton, la tête qui dort basculait en arrière). Le squelette est un VRM 0.x minimal écrit à la main (le modèle n'est
 * pas versionné) : il regarde −Z, sa gauche est en x < 0, en mètres.
 */
class BodyLayersTest {
    private val doc = VrmDocument.fromJson(RIG_JSON)
    private val dt = 1f / 60f

    private fun newRig() = AvatarRig(doc)

    /** La pose du « clip » : le repos, les hanches à leur place — réécrite à chaque image, comme le ferait un clip. */
    private fun rest(rig: AvatarRig): Pose = rig.newPose().also { it.hips = doc.restWorldPosition(rig.node("hips")!!) }

    private fun forward(pose: Pose, bone: String): Vec3 = pose[bone]!!.rotate(CharacterFrame.FORWARD)

    private fun position(rig: AvatarRig, pose: Pose, bone: String): Vec3 {
        rig.solve(pose)
        return rig.world(bone)!!.second
    }

    private fun dirTo(rig: AvatarRig, pose: Pose, bone: String, target: Vec3) = (target - position(rig, pose, bone)).normalized()

    private fun angleOf(q: Quat): Float = 2 * acos(min(1f, abs(q.normalized().w)))

    private fun angleBetween(a: Vec3, b: Vec3): Float = acos(a.normalized().dot(b.normalized()).coerceIn(-1f, 1f))

    /** Le milieu des yeux au repos. */
    private fun restEyes(): Vec3 {
        val rig = newRig()
        val p = rest(rig)
        return (position(rig, p, "leftEye") + position(rig, p, "rightEye")) * 0.5f
    }

    private val contact = GazeIntent(AttentionState.CONTACT, 1f, GazeAngles.ZERO, GazeAngles.ZERO, 0f)

    // ── Géométrie du regard ─────────────────────────────────────────────

    @Test fun `directionToGaze et gazeToQuaternion sont l'inverse l'un de l'autre`() {
        val targets = listOf(Vec3(0.3f, 0.2f, -1f), Vec3(-0.4f, -0.3f, -1f), Vec3(0.1f, 0.5f, -0.8f))
        for (t in targets) {
            val g = BodyMath.directionToGaze(t)
            val f = BodyMath.gazeToQuaternion(g).rotate(CharacterFrame.FORWARD)
            assertTrue("$t → $g", f.dot(t.normalized()) > 0.9999f)
            // Le sens sémantique ne dépend d'aucune convention : en dessous = pitch > 0, à sa gauche (x < 0) = yaw > 0.
            assertEquals(-sign(t.y), sign(g.pitch))
            assertEquals(-sign(t.x), sign(g.yaw))
        }
    }

    private fun settleGaze(
        rig: AvatarRig,
        gaze: GazeController,
        ctx: BodyContext,
        intent: GazeIntent?,
        frames: Int = 30,
        clip: (Pose) -> Unit = {},
    ): Pose {
        var p = rest(rig)
        repeat(frames) {
            p = rest(rig)
            clip(p)
            gaze.update(dt, ctx, rig, p, intent)
        }
        return p
    }

    @Test fun `les yeux se posent SUR la caméra quand elle est dans leur course`() {
        val rig = newRig()
        val origin = position(rig, rest(rig), "leftEye")
        // 8° en haut et 8° à sa gauche, à 2 m : dans la course de l'œil (10°) sur les deux axes.
        val dir = Vec3(-sin(0.14f), sin(0.14f), -cos(0.14f)).normalized()
        val camera = origin + dir * 2f
        val ctx = BodyContext(viewer = camera)
        val gaze = GazeController()
        val p = settleGaze(rig, gaze, ctx, contact)
        val dot = forward(p, "leftEye").dot(dirTo(rig, p, "leftEye", camera))
        assertTrue("dot=$dot", dot > 0.995f)
        assertTrue("à sa gauche : yaw ${gaze.applied.yaw} > 0", gaze.applied.yaw > 0.1f)
    }

    @Test fun `une caméra au-dessus fait lever les yeux, une en dessous les fait baisser`() {
        val rig = newRig()
        val gaze = GazeController()
        val ctx = BodyContext(viewer = Vec3(0f, 3.0f, -1.5f))
        var p = settleGaze(rig, gaze, ctx, contact)
        assertTrue(forward(p, "rightEye").y > 0.1f)
        ctx.viewer = Vec3(0f, 0.2f, -1.5f)
        p = settleGaze(rig, gaze, ctx, contact)
        assertTrue(forward(p, "rightEye").y < -0.1f)
    }

    @Test fun `une caméra loin sur le côté arrête l'œil au coin, jamais au-delà de sa course`() {
        val rig = newRig()
        val gaze = GazeController()
        // 70° à sa gauche : bien au-delà de ce qu'un os d'œil peut montrer.
        val ctx = BodyContext(viewer = Vec3(-2.7f, 1.66f, -1f))
        val p = settleGaze(rig, gaze, ctx, contact)
        assertTrue(gaze.applied.yaw <= gaze.maxYaw + 1e-6f)
        assertTrue(gaze.applied.yaw > gaze.maxYaw - 0.01f)
        // Et sur l'os lui-même, relatif à la tête : au plus la course du modèle.
        val rel = BodyMath.directionToGaze((p["head"]!!.inverse() * p["leftEye"]!!).rotate(CharacterFrame.FORWARD))
        assertTrue("${rel.yaw}", abs(rel.yaw) <= GazeController.MIKA_EYE_RANGE + 1e-4f)
        // De l'autre côté, l'autre signe.
        ctx.viewer = Vec3(2.7f, 1.66f, -1f)
        settleGaze(rig, gaze, ctx, contact)
        assertTrue(gaze.applied.yaw < -gaze.maxYaw + 0.01f)
    }

    @Test fun `les yeux compensent un tour de tête du clip, le contact tient (réflexe vestibulo-oculaire)`() {
        val rig = newRig()
        val gaze = GazeController()
        val camera = restEyes() + Vec3(0f, 0f, -2f)
        val ctx = BodyContext(viewer = camera)
        var p = settleGaze(rig, gaze, ctx, contact)
        val before = forward(p, "leftEye").dot(dirTo(rig, p, "leftEye", camera))
        // Le clip tourne la tête de 8,6° vers sa gauche (dans la course de 10° de ce modèle) : les yeux doivent
        // contre-tourner vers sa droite.
        val turn = Quat.axisAngle(CharacterFrame.UP, 0.15f)
        p = settleGaze(rig, gaze, ctx, contact) { it["head"] = turn }
        val after = forward(p, "leftEye").dot(dirTo(rig, p, "leftEye", camera))
        assertTrue("avant $before", before > 0.999f)
        assertTrue("après $after", after > 0.999f)
        assertTrue("l'œil a vraiment tourné dans la tête : ${gaze.applied.yaw}", gaze.applied.yaw < -0.1f)
    }

    @Test fun `sans spectateur, un détournement se lit encore dans sa direction`() {
        val rig = newRig()
        val gaze = GazeController()
        val down = contact.copy(contact = 0f, offset = GazeAngles(0.15f, 0f))
        val p = settleGaze(rig, gaze, BodyContext(viewer = null), down)
        assertTrue(forward(p, "leftEye").y < -0.1f)
    }

    @Test fun `endormie, les yeux reposent un peu vers le bas`() {
        val rig = newRig()
        val gaze = GazeController()
        val ctx = BodyContext(sleepPhase = BodyContext.DEEP_SLEEP, viewer = Vec3(0f, 3f, -1f))
        val p = settleGaze(rig, gaze, ctx, contact)
        assertTrue(forward(p, "leftEye").y < -0.03f)
    }

    // ── Le sens des rotations additives ─────────────────────────────────

    @Test fun `addRotation de tête, pitch positif, baisse la tête`() {
        val rig = newRig()
        val p = rest(rig)
        BodyMath.addRotation(rig, p, "head", 0.2f, 0f, 0f)
        assertTrue(forward(p, "head").y < -0.15f)
    }

    @Test fun `le yaw du web tourne vers SA GAUCHE, le roll penche le haut vers sa droite`() {
        val rig = newRig()
        val p = rest(rig)
        BodyMath.addRotation(rig, p, "head", 0f, 0.3f, 0f)
        assertTrue("x=${forward(p, "head").x}", forward(p, "head").x < -0.2f)
        val q = rest(rig)
        BodyMath.addRotation(rig, q, "head", 0f, 0f, 0.3f)
        assertTrue(q["head"]!!.rotate(CharacterFrame.UP).x > 0.2f)
    }

    @Test fun `une poitrine qui bascule emporte la tête et les yeux`() {
        val rig = newRig()
        val p = rest(rig)
        val headBefore = position(rig, p, "head")
        BodyMath.addRotation(rig, p, "chest", 0.2f, 0f, 0f)
        assertTrue(forward(p, "head").y < -0.15f)
        assertTrue(forward(p, "leftEye").y < -0.15f)
        // La tête est portée en avant (−Z) par la poitrine qui se penche.
        assertTrue(position(rig, p, "head").z < headBefore.z - 0.03f)
    }

    @Test fun `l'ordre dans lequel on touche un parent et son enfant n'importe pas, comme sur le web`() {
        val rig = newRig()
        val a = rest(rig)
        BodyMath.addRotation(rig, a, "spine", 0.1f, 0.2f, -0.05f)
        BodyMath.addRotation(rig, a, "neck", -0.15f, 0.1f, 0.2f)
        val b = rest(rig)
        BodyMath.addRotation(rig, b, "neck", -0.15f, 0.1f, 0.2f)
        BodyMath.addRotation(rig, b, "spine", 0.1f, 0.2f, -0.05f)
        assertTrue(abs(a["head"]!!.dot(b["head"]!!)) > 0.99999f)
    }

    private fun runOverlay(rig: AvatarRig, frames: Int, step: (Pose) -> Unit): Pose {
        var p = rest(rig)
        repeat(frames) {
            p = rest(rig)
            step(p)
        }
        return p
    }

    @Test fun `la tête qui dort tombe en avant, jamais en arrière`() {
        val rig = newRig()
        val ctx = BodyContext(sleepPhase = BodyContext.DEEP_SLEEP)
        val overlay = SleepOverlay()
        val p = runOverlay(rig, 240) { overlay.update(dt, ctx, rig, it) }
        assertTrue(forward(p, "head").y < -0.15f)
    }

    @Test fun `triste baisse la tête, fière lève le menton`() {
        val rig = newRig()
        val ctx = BodyContext(emotion = "sad", intensity = 1f)
        val overlay = HeadEmotionOverlay()
        val sad = runOverlay(rig, 240) { overlay.update(dt, ctx, rig, it) }
        assertTrue(forward(sad, "head").y < -0.03f)
        ctx.emotion = "proud"
        val proud = runOverlay(rig, 240) { overlay.update(dt, ctx, rig, it) }
        assertTrue(forward(proud, "head").y > 0.02f)
    }

    @Test fun `endormie, le port de tête de l'émotion s'efface`() {
        val rig = newRig()
        val ctx = BodyContext(emotion = "sad", intensity = 1f)
        val overlay = HeadEmotionOverlay()
        runOverlay(rig, 240) { overlay.update(dt, ctx, rig, it) }
        ctx.sleepPhase = BodyContext.REM
        val p = runOverlay(rig, 600) { overlay.update(dt, ctx, rig, it) }
        assertTrue(angleOf(p["head"]!!) < 0.005f)
    }

    // ── La tête dans le regard ──────────────────────────────────────────

    private fun runHead(rig: AvatarRig, ctx: BodyContext, overlay: HeadAttentionOverlay, seconds: Float, clip: (Pose) -> Unit = {}): Pose =
        runOverlay(rig, (seconds * 60).toInt()) {
            clip(it)
            overlay.update(dt, ctx, rig, it)
        }

    private fun headError(rig: AvatarRig, pose: Pose, camera: Vec3): Float {
        rig.solve(pose)
        val (q, p) = rig.world("head")!!
        return angleBetween(q.rotate(CharacterFrame.FORWARD), camera - p)
    }

    private fun aside(angle: Float, distance: Float = 2f): Vec3 = Vec3(-sin(angle) * distance, restEyes().y, -cos(angle) * distance)

    private fun attending(viewer: Vec3, intent: GazeIntent = contact) = BodyContext(viewer = viewer).also { it.attention = intent }

    @Test fun `la tête prend l'essentiel d'un spectateur à 30° sur le côté`() {
        val rig = newRig()
        val camera = aside(0.52f)
        val ctx = attending(camera)
        val overlay = HeadAttentionOverlay()
        val before = headError(rig, rest(rig), camera)
        val p = runHead(rig, ctx, overlay, 2f)
        val after = headError(rig, p, camera)
        assertTrue("avant $before", before > 0.45f)
        // HEAD_FOLLOW 0,7 au-delà de la zone morte : le reste est pour les yeux.
        assertTrue("après $after", after < before * 0.45f)
        assertTrue("après $after", after > 0.05f)
        assertTrue(ctx.viewerMeasured)
        assertTrue("vers sa gauche", forward(p, "head").x < -0.1f)
    }

    @Test fun `un spectateur droit devant, dans la zone morte, laisse la tête tranquille`() {
        val rig = newRig()
        val ctx = attending(Vec3(-0.05f, restEyes().y, -2f))
        val p = runHead(rig, ctx, HeadAttentionOverlay(), 2f)
        assertTrue(angleOf(p["head"]!!) < 0.01f)
    }

    @Test fun `un spectateur derrière elle est hors de portée - pas de torsion`() {
        val rig = newRig()
        val ctx = attending(Vec3(0.3f, restEyes().y, 2f))
        val p = runHead(rig, ctx, HeadAttentionOverlay(), 2f)
        assertTrue(ctx.viewerMeasured)
        assertFalse(HeadAttentionOverlay.viewerReachable(ctx.viewerYaw, ctx.viewerPitch))
        assertTrue(angleOf(p["head"]!!) < 0.01f)
    }

    @Test fun `le tour est borné par HEAD_MAX_YAW même pour un spectateur à 75°`() {
        val rig = newRig()
        val ctx = attending(aside(1.3f))
        val p = runHead(rig, ctx, HeadAttentionOverlay(), 3f)
        val neck = p["neck"]!!
        val total = angleOf(neck) + angleOf(neck.inverse() * p["head"]!!)
        assertTrue("total $total", total <= HeadAttentionOverlay.HEAD_MAX_YAW + 0.02f)
        assertTrue("total $total", total > 0.3f)
    }

    @Test fun `la mesure se fait dans la pose du clip, pas dans sa propre boucle (pas d'emballement)`() {
        val rig = newRig()
        val camera = aside(0.4f)
        val ctx = attending(camera)
        val overlay = HeadAttentionOverlay()
        val settled = headError(rig, runHead(rig, ctx, overlay, 2f), camera)
        val later = headError(rig, runHead(rig, ctx, overlay, 4f), camera)
        assertTrue("$settled → $later", abs(later - settled) < 0.005f)
    }

    @Test fun `endormie, la tête est laissée au sommeil`() {
        val rig = newRig()
        val ctx = attending(aside(0.5f))
        ctx.sleepPhase = BodyContext.REM
        val p = runHead(rig, ctx, HeadAttentionOverlay(), 2f)
        assertFalse(ctx.viewerMeasured)
        assertTrue(angleOf(p["head"]!!) < 0.01f)
    }

    @Test fun `un détournement tourne un peu la tête même quand le spectateur est hors de portée`() {
        val rig = newRig()
        val ctx = attending(Vec3(0f, restEyes().y, 2f), contact.copy(contact = 0f, offset = GazeAngles(-0.2f, 0f)))
        val p = runHead(rig, ctx, HeadAttentionOverlay(), 2f)
        // Pitch sémantique −0,2 = vers le haut.
        assertTrue(forward(p, "head").y > 0.05f)
    }

    // ── Le souffle ──────────────────────────────────────────────────────

    @Test fun `l'inspiration est plus rapide que l'expiration, puis une pause à vide`() {
        assertEquals(1f, BreathingOverlay.breathWave(0.36f), 1e-5f)
        assertTrue(BreathingOverlay.EXHALE_END - BreathingOverlay.INHALE_END > BreathingOverlay.INHALE_END)
        assertEquals(0f, BreathingOverlay.breathWave(0.9f))
        assertEquals(0f, BreathingOverlay.breathWave(0.99f))
    }

    private class Breath(val rig: AvatarRig, val ctx: BodyContext, val overlay: BreathingOverlay)

    private fun breathe(seconds: Float, random: () -> Float = Random(7)::nextFloat, setup: (BodyContext) -> Unit = {}): Pair<Breath, List<Float>> {
        val rig = newRig()
        val ctx = BodyContext().also(setup)
        val overlay = BreathingOverlay(random)
        val trace = ArrayList<Float>()
        repeat((seconds * 60).toInt()) {
            overlay.update(dt, ctx, rig, rest(rig))
            trace.add(ctx.breath)
        }
        return Breath(rig, ctx, overlay) to trace
    }

    @Test fun `deux souffles jamais pareils - les cycles varient`() {
        val (_, trace) = breathe(40f)
        val peaks = (1 until trace.size - 1).filter { trace[it] > 0.6f && trace[it] >= trace[it - 1] && trace[it] > trace[it + 1] }
        val gaps = peaks.zipWithNext { a, b -> b - a }
        assertTrue("$gaps", gaps.size >= 4)
        assertTrue("$gaps", gaps.map { Math.round(it / 6f) }.toSet().size > 1)
    }

    @Test fun `en parlant, une prise d'air remplit vite, puis les mots vident lentement`() {
        val (b, trace) = breathe(2f) { it.speaking = true }
        val low = trace.last()
        b.ctx.breathRequest = BreathRequest.CATCH
        b.overlay.update(dt, b.ctx, b.rig, rest(b.rig))
        assertNull("la demande est consommée", b.ctx.breathRequest)
        repeat(17) { b.overlay.update(dt, b.ctx, b.rig, rest(b.rig)) }
        assertTrue(b.ctx.breath > low + 0.25f)
        val full = b.ctx.breath
        repeat(60) { b.overlay.update(dt, b.ctx, b.rig, rest(b.rig)) }
        assertTrue(b.ctx.breath < full)
        assertTrue(b.ctx.breath > full - 0.35f)
    }

    @Test fun `un soupir dépasse un souffle normal, passe sous le vide, puis se pose`() {
        val (b, _) = breathe(0.1f)
        b.ctx.breathRequest = BreathRequest.SIGH
        var max = 0f
        var min = 0f
        repeat((4.2f * 60).toInt()) {
            b.overlay.update(dt, b.ctx, b.rig, rest(b.rig))
            max = maxOf(max, b.ctx.breath)
            min = minOf(min, b.ctx.breath)
        }
        assertTrue(max > 1.5f)
        assertTrue(min < -0.1f)
    }

    @Test fun `un souffle plein soulève les épaules et garde le visage posé`() {
        val rig = newRig()
        val ctx = BodyContext()
        val overlay = BreathingOverlay(Random(3)::nextFloat)
        val restPose = rest(rig)
        val leftRest = position(rig, restPose, "leftUpperArm").y
        val rightRest = position(rig, restPose, "rightUpperArm").y
        var liftAtFull = Float.NaN
        var liftAtEmpty = Float.NaN
        var worstHead = 0f
        repeat(10 * 60) {
            val p = rest(rig)
            overlay.update(dt, ctx, rig, p)
            val left = position(rig, p, "leftUpperArm").y - leftRest
            val right = position(rig, p, "rightUpperArm").y - rightRest
            if (ctx.breath > 0.7f) liftAtFull = min(left, right)
            if (ctx.breath < 0.05f) liftAtEmpty = maxOf(left, right)
            worstHead = maxOf(worstHead, abs(forward(p, "head").y))
        }
        assertTrue("à plein : $liftAtFull m", liftAtFull > 0.001f)
        assertTrue("à vide : $liftAtEmpty m", liftAtEmpty < 0.0005f)
        // La nuque rend la moitié du tangage du torse : le visage bouge à peine.
        assertTrue("tête $worstHead", worstHead < 0.03f)
    }

    // ── La vie entre les images ─────────────────────────────────────────

    @Test fun `le bruit reste borné`() {
        var t = 0.0
        while (t < 200) {
            assertTrue(abs(LifeOverlay.lifeNoise(t, 3)) <= 1.0)
            t += 0.37
        }
    }

    private fun lcg(seed0: Long = 1): () -> Float {
        var seed = seed0
        return {
            seed = (seed * 16807) % 2147483647
            (seed.toDouble() / 2147483647).toFloat()
        }
    }

    /** Le roulis de la colonne à chaque image (rad, > 0 vers sa droite). */
    private fun sway(seconds: Float, setup: (BodyContext) -> Unit = {}): List<Float> {
        val rig = newRig()
        val ctx = BodyContext().also(setup)
        val overlay = LifeOverlay(lcg())
        val rolls = ArrayList<Float>()
        repeat((seconds * 30).toInt()) {
            val p = rest(rig)
            overlay.update(1f / 30f, ctx, rig, p)
            val up = p["spine"]!!.rotate(CharacterFrame.UP)
            rolls.add(atan2(up.x, up.y))
        }
        return rolls
    }

    @Test fun `elle change d'appui en moins d'une demi-minute, et reste discrète`() {
        val max = sway(30f).maxOf { abs(it) }
        assertTrue("$max", max > 0.012f)
        assertTrue("$max", max < 0.08f)
    }

    @Test fun `endormie, presque immobile`() {
        val amp = { xs: List<Float> -> xs.drop(200).maxOf { abs(it) } }
        val awake = amp(sway(20f))
        val asleep = amp(sway(20f) { it.sleepPhase = BodyContext.DEEP_SLEEP })
        assertTrue("$asleep vs $awake", asleep < awake * 0.5f)
    }

    @Test fun `la vie reste sous le clip, même survoltée, et ne touche jamais les hanches`() {
        val rig = newRig()
        val ctx = BodyContext(emotion = "excited", intensity = 1f, speaking = true)
        val overlay = LifeOverlay(lcg(5))
        repeat(60 * 30) {
            val p = rest(rig)
            val hips = p.hips
            overlay.update(1f / 30f, ctx, rig, p)
            // Os par os, relativement à son parent : quelques degrés, jamais un geste.
            for ((bone, parent) in PARENTS) {
                val local = angleOf(p[parent]!!.inverse() * p[bone]!!)
                assertTrue("$bone $local", local < 0.2f)
            }
            assertEquals(Quat.IDENTITY, p["hips"])
            assertEquals(hips, p.hips)
        }
    }

    // ── L'attention ─────────────────────────────────────────────────────

    private fun base(
        speaking: Boolean = false,
        replyPending: Boolean = false,
        listening: Boolean = false,
        persona: String? = "speaking",
        emotion: String = "neutral",
        sleepPhase: String = BodyContext.AWAKE,
        reachable: Boolean = true,
        walking: Boolean = false,
    ) = AttentionInput(
        speaking = speaking, replyPending = replyPending, listening = listening, persona = persona, emotion = emotion,
        intensity = 0.5f, sleepPhase = sleepPhase, reachable = reachable, viewerAngle = 0.3f, walking = walking,
    )

    /** Une source constante : chaque tirage tombe à `value` de son intervalle. */
    private fun constant(value: Float): () -> Float = { value }

    private fun advance(d: AttentionDirector, input: AttentionInput, seconds: Float, step: Float = 0.05f): GazeIntent {
        var last = d.update(0f, input)
        var t = 0f
        while (t < seconds - 1e-6f) {
            last = d.update(step, input)
            t += step
        }
        return last
    }

    @Test fun `endormie - ni contact, ni décalage, ni saccade`() {
        val g = AttentionDirector(constant(0f)).update(0.1f, base(sleepPhase = BodyContext.DEEP_SLEEP))
        assertEquals(AttentionState.ASLEEP, g.state)
        assertEquals(0f, g.contact)
        assertEquals(GazeAngles.ZERO, g.offset)
        assertEquals(GazeAngles.ZERO, g.saccade)
    }

    @Test fun `le contact par défaut, éveillée, quelqu'un devant elle`() {
        val g = AttentionDirector(constant(0.99f)).update(0.1f, base())
        assertEquals(AttentionState.CONTACT, g.state)
        assertEquals(1f, g.contact)
        assertEquals(GazeAngles.ZERO, g.offset)
    }

    @Test fun `un murmure intérieur ne vous est pas adressé - peu de contact, les yeux en bas de côté`() {
        val g = AttentionDirector(constant(0.99f)).update(0.1f, base(persona = "inner", speaking = true))
        assertEquals(AttentionState.INNER, g.state)
        assertEquals(AttentionDirector.INNER_CONTACT, g.contact)
        assertTrue(g.offset.pitch > 0f)
        assertTrue(abs(g.offset.yaw) > 0f)
        // La voix intérieure qui se tait, c'est juste elle : le contact revient.
        assertEquals(AttentionState.CONTACT, AttentionDirector(constant(0.99f)).update(0.1f, base(persona = "inner")).state)
    }

    @Test fun `une réponse en attente emporte le regard en haut et de côté, avec des retours`() {
        val d = AttentionDirector(constant(0f))
        val g = d.update(0.1f, base(replyPending = true))
        assertEquals(AttentionState.THINKING, g.state)
        assertEquals(AttentionDirector.THINKING_CONTACT, g.contact)
        assertTrue(g.offset.pitch < 0f)
        assertTrue(abs(g.offset.yaw) > 0.1f)
        // Aléa 0 → un retour au bout de THINKING_CHECKIN_INTERVAL.start, pour THINKING_CHECKIN_DURATION.start.
        val atCheckin = advance(d, base(replyPending = true), AttentionDirector.THINKING_CHECKIN_INTERVAL.start + 0.05f)
        assertEquals(1f, atCheckin.contact)
        assertEquals(GazeAngles.ZERO, atCheckin.offset)
        val after = advance(d, base(replyPending = true), AttentionDirector.THINKING_CHECKIN_DURATION.start + 0.1f)
        assertEquals(AttentionDirector.THINKING_CONTACT, after.contact)
    }

    @Test fun `le côté de la réflexion est tiré une fois par réponse attendue, et tenu`() {
        val d = AttentionDirector(constant(0.7f))
        val a = d.update(0.05f, base(replyPending = true))
        val b = d.update(0.05f, base(replyPending = true))
        assertEquals(a.offset.yaw, b.offset.yaw)
        assertTrue(a.offset.yaw > 0f)
    }

    @Test fun `parler passe avant un message en attente - on finit sa phrase`() {
        val g = AttentionDirector(constant(0.99f)).update(0.1f, base(replyPending = true, speaking = true))
        assertTrue(g.state != AttentionState.THINKING)
        assertEquals(1f, g.contact)
    }

    @Test fun `une réponse qui ne vient jamais cesse d'être réfléchie après THINKING_MAX_S`() {
        val d = AttentionDirector(constant(0.99f))
        assertEquals(AttentionState.THINKING, advance(d, base(replyPending = true), 5f, 0.5f).state)
        assertEquals(AttentionState.CONTACT, advance(d, base(replyPending = true), AttentionDirector.THINKING_MAX_S + 1, 0.5f).state)
    }

    @Test fun `la réponse qui arrive ramène le regard d'un coup (un saut, rendu dans shift)`() {
        val d = AttentionDirector(constant(0.99f))
        d.update(0.1f, base(replyPending = true))
        val g = d.update(0.05f, base(replyPending = false))
        assertEquals(AttentionState.CONTACT, g.state)
        assertEquals(1f, g.contact)
        assertTrue(g.shift > 0.1f)
    }

    @Test fun `hors de portée - contact 0 et regard droit devant, mais une pensée garde son décalage`() {
        val d = AttentionDirector(constant(0.99f))
        val away = d.update(0.1f, base(reachable = false))
        assertEquals(AttentionState.AWAY, away.state)
        assertEquals(0f, away.contact)
        val thinking = d.update(0.1f, base(reachable = false, replyPending = true))
        assertEquals(AttentionState.THINKING, thinking.state)
        assertEquals(0f, thinking.contact)
        assertTrue(thinking.offset.pitch < 0f)
    }

    @Test fun `en marchant, les yeux quelques pas devant au sol`() {
        val g = AttentionDirector(constant(0.99f)).update(0.1f, base(walking = true))
        assertEquals(AttentionState.WALKING, g.state)
        assertEquals(0f, g.contact)
        assertEquals(AttentionDirector.WALKING_OFFSET, g.offset)
    }

    @Test fun `le début d'un énoncé porte un regard de préparation, puis le contact revient`() {
        assertTrue(0.1f < AttentionDirector.ONSET_AVERSION_P)
        val d = AttentionDirector(constant(0.1f))
        d.update(0.05f, base(speaking = false))
        val onset = d.update(0.05f, base(speaking = true))
        assertEquals(AttentionState.AVERT, onset.state)
        assertTrue("en haut : préparer, pas avoir honte", onset.offset.pitch < 0f)
        assertTrue(onset.shift > 0.1f)
        val later = advance(d, base(speaking = true), 1.2f)
        assertEquals(AttentionState.CONTACT, later.state)
        assertEquals(GazeAngles.ZERO, later.offset)
    }

    @Test fun `pas de regard de préparation quand le tirage échoue`() {
        val d = AttentionDirector(constant(0.9f))
        d.update(0.05f, base(speaking = false))
        assertEquals(AttentionState.CONTACT, d.update(0.05f, base(speaking = true)).state)
    }

    @Test fun `gênée, elle détourne vers le BAS à la première échéance - amoureuse, avec les mêmes dés, elle tient le regard`() {
        val roll = 0.2f
        val profile = AttentionDirector.AVERSION_PROFILE
        assertTrue(roll < AttentionDirector.AVERSION_P_IDLE * profile.getValue("embarrassed").p)
        assertTrue(roll > AttentionDirector.AVERSION_P_IDLE * profile.getValue("love").p)
        val at = AttentionDirector.AVERSION_INTERVAL.start + roll * 4.5f + 0.1f
        val shy = advance(AttentionDirector(constant(roll)), base(emotion = "embarrassed"), at)
        assertEquals(AttentionState.AVERT, shy.state)
        assertTrue(shy.offset.pitch > 0f)
        assertEquals(AttentionState.CONTACT, advance(AttentionDirector(constant(roll)), base(emotion = "love"), at).state)
    }

    @Test fun `écoutée (on lui écrit), elle détourne moins`() {
        val roll = 0.3f
        assertTrue(roll < AttentionDirector.AVERSION_P_IDLE)
        assertTrue(roll > AttentionDirector.AVERSION_P_LISTENING)
        val at = AttentionDirector.AVERSION_INTERVAL.start + roll * 4.5f + 0.1f
        assertEquals(AttentionState.AVERT, advance(AttentionDirector(constant(roll)), base(), at).state)
        assertEquals(AttentionState.CONTACT, advance(AttentionDirector(constant(roll)), base(listening = true), at).state)
    }

    @Test fun `chaque profil de détournement nomme une émotion connue et une direction possible`() {
        for ((emotion, profile) in AttentionDirector.AVERSION_PROFILE) {
            assertTrue(emotion, emotion in Affect.AROUSAL.keys)
            assertTrue(profile.p > 0f)
            profile.dir?.let {
                assertTrue(abs(it.pitch) <= 0.25f)
                assertTrue(abs(it.yaw) <= 0.25f)
            }
        }
        for (emotion in GazeController.EMOTION_GAZE_BIAS.keys + HeadEmotionOverlay.EMOTION_HEAD_POSE.keys) {
            assertTrue(emotion, emotion in Affect.AROUSAL.keys)
        }
    }

    @Test fun `les saccades partent au rythme tiré, d'un saut, rendu dans shift`() {
        val d = AttentionDirector(constant(0f))
        val first = advance(d, base(), AttentionDirector.SACCADE_INTERVAL.start - 0.1f)
        assertEquals(GazeAngles.ZERO, first.saccade)
        var jumped = false
        var g = first
        repeat(6) {
            g = d.update(0.05f, base())
            if (g.shift > 0f) jumped = true
        }
        assertTrue(jumped)
        assertTrue(hypot(g.saccade.pitch, g.saccade.yaw) > 0.01f)
    }

    @Test fun `une saccade est un saut - deux images sans saccade gardent la même valeur`() {
        val d = AttentionDirector(constant(0.5f))
        d.update(0.05f, base())
        val a = d.update(0.05f, base())
        val b = d.update(0.05f, base())
        assertEquals(a.saccade, b.saccade)
        assertEquals(0f, b.shift)
    }

    private fun share(d: AttentionDirector, seconds: Float, input: AttentionInput, state: AttentionState): Float {
        var n = 0
        var total = 0
        repeat((seconds * 30).toInt()) {
            if (d.update(1f / 30f, input).state == state) n++
            total++
        }
        return n.toFloat() / total
    }

    private val alone = AttentionInput(intensity = 0.5f, reachable = true, viewerAngle = 0.2f)

    @Test fun `elle n'erre pas tant que quelqu'un est là`() {
        assertEquals(0f, share(AttentionDirector(lcg(7)), AttentionDirector.WANDER_AFTER_S - 1, alone, AttentionState.WANDER))
        assertEquals(0f, share(AttentionDirector(lcg(7)), 120f, alone.copy(listening = true), AttentionState.WANDER))
        assertEquals(0f, share(AttentionDirector(lcg(7)), 120f, alone.copy(speaking = true), AttentionState.WANDER))
    }

    @Test fun `seule un moment, elle regarde la pièce la plupart du temps, avec des coups d'œil`() {
        val d = AttentionDirector(lcg(3))
        share(d, AttentionDirector.WANDER_AFTER_S, alone, AttentionState.WANDER)
        val wander = share(d, 120f, alone, AttentionState.WANDER)
        assertTrue("$wander", wander > 0.35f)
        assertTrue("$wander", wander < 0.85f)
    }

    @Test fun `un regard qui erre regarde la pièce, pas à côté du spectateur`() {
        val d = AttentionDirector(lcg(5))
        repeat(200 * 30) {
            val out = d.update(1f / 30f, alone)
            if (out.state == AttentionState.WANDER) {
                assertEquals(0f, out.contact)
                assertTrue(hypot(out.offset.pitch, out.offset.yaw) > 0.2f)
                return
            }
        }
        throw AssertionError("n'a jamais erré")
    }

    @Test fun `la personne qui écrit ramène ses yeux aussitôt`() {
        val d = AttentionDirector(lcg(11))
        var wandered = false
        for (i in 0 until 300 * 30) {
            if (d.update(1f / 30f, alone).state == AttentionState.WANDER) {
                wandered = true
                break
            }
        }
        assertTrue(wandered)
        val back = d.update(1f / 30f, alone.copy(listening = true))
        assertEquals(AttentionState.CONTACT, back.state)
        assertEquals(1f, back.contact)
        assertTrue("un vrai saut de regard — il peut porter un clignement", back.shift > 0.1f)
    }

    // ── Les couches ensemble ────────────────────────────────────────────

    private fun live(layers: BodyLayers, rig: AvatarRig, ctx: BodyContext, seconds: Float, each: (Pose) -> Unit = {}): Pose {
        var p = rest(rig)
        repeat((seconds * 60).toInt()) {
            p = rest(rig)
            layers.update(dt, p, ctx)
            each(p)
        }
        return p
    }

    private fun eyeContact(rig: AvatarRig, p: Pose, viewer: Vec3): Float =
        minOf(
            forward(p, "leftEye").dot(dirTo(rig, p, "leftEye", viewer)),
            forward(p, "rightEye").dot(dirTo(rig, p, "rightEye", viewer)),
        )

    @Test fun `devant elle, ses deux yeux se posent sur le spectateur malgré le souffle et la vie`() {
        val rig = newRig()
        val viewer = restEyes() + Vec3(0f, 0f, -1.5f)
        val ctx = BodyContext(viewer = viewer)
        val layers = BodyLayers(rig, constant(0.99f))
        val p = live(layers, rig, ctx, 2f)
        assertEquals(AttentionState.CONTACT, layers.attentionState)
        assertTrue("contact ${eyeContact(rig, p, viewer)}", eyeContact(rig, p, viewer) > 0.995f)
        assertTrue("la tête reste à peu près devant : ${angleOf(p["head"]!!)}", angleOf(p["head"]!!) < 0.08f)
    }

    @Test fun `un spectateur à 20° à sa gauche - la tête prend l'essentiel, les yeux le reste`() {
        val rig = newRig()
        val eyes = restEyes()
        val viewer = eyes + Vec3(-sin(0.35f) * 1.5f, 0f, -cos(0.35f) * 1.5f)
        val ctx = BodyContext(viewer = viewer)
        val layers = BodyLayers(rig, constant(0.99f))
        val p = live(layers, rig, ctx, 3f)
        assertTrue("la tête tourne vers sa gauche", forward(p, "head").x < -0.1f)
        assertTrue("contact ${eyeContact(rig, p, viewer)}", eyeContact(rig, p, viewer) > 0.995f)
        assertTrue("les yeux font le reste, du même côté : ${layers.gaze.applied.yaw}", layers.gaze.applied.yaw > 0.05f)
    }

    @Test fun `le regard ne sort jamais de la course de l'œil`() {
        val rig = newRig()
        for (viewer in listOf(Vec3(-2.7f, 1.6f, -1f), Vec3(2.7f, 3.5f, -1f), Vec3(0.4f, -1f, -0.6f))) {
            val ctx = BodyContext(viewer = viewer, emotion = "thinking", intensity = 1f)
            val layers = BodyLayers(rig, Random(1)::nextFloat)
            live(layers, rig, ctx, 6f) { p ->
                val rel = BodyMath.directionToGaze((p["head"]!!.inverse() * p["leftEye"]!!).rotate(CharacterFrame.FORWARD))
                assertTrue("$viewer yaw ${rel.yaw}", abs(rel.yaw) <= GazeController.MIKA_EYE_RANGE + 1e-3f)
                assertTrue("$viewer pitch ${rel.pitch}", abs(rel.pitch) <= GazeController.MIKA_EYE_RANGE + 1e-3f)
            }
        }
    }

    @Test fun `endormie - la tête tombe, les yeux reposent en bas, le regard ne cherche personne`() {
        val rig = newRig()
        val ctx = BodyContext(sleepPhase = BodyContext.DEEP_SLEEP, viewer = restEyes() + Vec3(0f, 0f, -1.5f))
        val layers = BodyLayers(rig, constant(0.5f))
        val p = live(layers, rig, ctx, 3f)
        assertEquals(AttentionState.ASLEEP, layers.attentionState)
        assertFalse(ctx.viewerMeasured)
        assertTrue(forward(p, "head").y < -0.1f)
        assertEquals(GazeController.EYE_SLEEP_PITCH, layers.gaze.applied.pitch, 1e-3f)
    }

    @Test fun `derrière elle - ni contact ni torsion`() {
        val rig = newRig()
        val ctx = BodyContext(viewer = restEyes() + Vec3(0.2f, 0f, 1.5f))
        val layers = BodyLayers(rig, constant(0.99f))
        val p = live(layers, rig, ctx, 2f)
        assertEquals(AttentionState.AWAY, layers.attentionState)
        assertTrue(angleOf(p["neck"]!!.inverse() * p["head"]!!) < 0.06f)
    }

    @Test fun `la demande de souffle est consommée et le remplissage publié`() {
        val rig = newRig()
        val ctx = BodyContext(breathRequest = BreathRequest.SIGH)
        val layers = BodyLayers(rig, constant(0.5f))
        layers.update(dt, rest(rig), ctx)
        assertNull(ctx.breathRequest)
        live(layers, rig, ctx, 1.1f)
        assertTrue("${ctx.breath}", ctx.breath > 1.5f)
    }

    @Test fun `le saut de regard est rendu - la réponse qui arrive ramène les yeux d'un bond`() {
        val rig = newRig()
        val ctx = BodyContext(viewer = restEyes() + Vec3(-0.6f, 0f, -1.5f), replyPending = true)
        val layers = BodyLayers(rig, constant(0.99f))
        live(layers, rig, ctx, 1f)
        assertEquals(AttentionState.THINKING, layers.attentionState)
        ctx.replyPending = false
        val shift = layers.update(dt, rest(rig), ctx)
        assertTrue("$shift", shift > 0.1f)
        assertEquals(shift, ctx.gazeShift)
    }

    @Test fun `un dt aberrant (retour d'onglet) est borné`() {
        val rig = newRig()
        val a = BodyLayers(rig, constant(0.3f))
        val b = BodyLayers(rig, constant(0.3f))
        val viewer = restEyes() + Vec3(-0.5f, 0.2f, -1.5f)
        val ctxA = BodyContext(viewer = viewer)
        val ctxB = BodyContext(viewer = viewer)
        val pa = rest(rig)
        val pb = rest(rig)
        a.update(5f, pa, ctxA)
        b.update(BodyLayers.MAX_DT, pb, ctxB)
        for (bone in pa.bones) assertTrue(bone, abs(pa[bone]!!.dot(pb[bone]!!)) > 0.99999f)
    }

    @Test fun `une phase de sommeil inconnue se lit éveillée`() {
        val rig = newRig()
        val ctx = BodyContext(sleepPhase = "hibernation", viewer = restEyes() + Vec3(0f, 0f, -1.5f))
        val layers = BodyLayers(rig, constant(0.99f))
        live(layers, rig, ctx, 0.5f)
        assertEquals(AttentionState.CONTACT, layers.attentionState)
    }

    companion object {
        private val PARENTS = mapOf(
            "spine" to "hips", "chest" to "spine", "neck" to "chest", "head" to "neck",
            "leftShoulder" to "chest", "leftUpperArm" to "leftShoulder", "leftLowerArm" to "leftUpperArm", "leftHand" to "leftLowerArm",
            "rightShoulder" to "chest", "rightUpperArm" to "rightShoulder", "rightLowerArm" to "rightUpperArm", "rightHand" to "rightLowerArm",
        )

        /** Un VRM 0.x minimal : il regarde −Z, sa gauche est en x < 0 ; les yeux à ~1,58 m. */
        private val RIG_JSON = """
            {
              "nodes": [
                {"name": "Armature", "children": [1]},
                {"name": "Hips", "translation": [0, 0.95, 0], "children": [2]},
                {"name": "Spine", "translation": [0, 0.1, 0], "children": [3]},
                {"name": "Chest", "translation": [0, 0.15, 0], "children": [4, 8, 12]},
                {"name": "Neck", "translation": [0, 0.22, 0], "children": [5]},
                {"name": "Head", "translation": [0, 0.1, 0], "children": [6, 7]},
                {"name": "LeftEye", "translation": [-0.03, 0.06, -0.05]},
                {"name": "RightEye", "translation": [0.03, 0.06, -0.05]},
                {"name": "LeftShoulder", "translation": [-0.04, 0.17, 0], "children": [9]},
                {"name": "LeftUpperArm", "translation": [-0.08, 0, 0], "children": [10]},
                {"name": "LeftLowerArm", "translation": [-0.24, 0, 0], "children": [11]},
                {"name": "LeftHand", "translation": [-0.22, 0, 0]},
                {"name": "RightShoulder", "translation": [0.04, 0.17, 0], "children": [13]},
                {"name": "RightUpperArm", "translation": [0.08, 0, 0], "children": [14]},
                {"name": "RightLowerArm", "translation": [0.24, 0, 0], "children": [15]},
                {"name": "RightHand", "translation": [0.22, 0, 0]}
              ],
              "extensions": {"VRM": {"humanoid": {"humanBones": [
                {"bone": "hips", "node": 1},
                {"bone": "spine", "node": 2},
                {"bone": "chest", "node": 3},
                {"bone": "neck", "node": 4},
                {"bone": "head", "node": 5},
                {"bone": "leftEye", "node": 6},
                {"bone": "rightEye", "node": 7},
                {"bone": "leftShoulder", "node": 8},
                {"bone": "leftUpperArm", "node": 9},
                {"bone": "leftLowerArm", "node": 10},
                {"bone": "leftHand", "node": 11},
                {"bone": "rightShoulder", "node": 12},
                {"bone": "rightUpperArm", "node": 13},
                {"bone": "rightLowerArm", "node": 14},
                {"bone": "rightHand", "node": 15}
              ]}}}
            }
        """.trimIndent()
    }
}
