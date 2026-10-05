package fr.qwartz.mika.avatar3d

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

class BodyStateMachineTest {
    /** Un squelette d'un seul os : la machine à états ne regarde que les noms et les durées des clips. */
    private val doc = VrmDocument.fromJson(
        """{"nodes":[{"name":"Hips","translation":[0,0.8,0]}],
           "extensions":{"VRM":{"humanoid":{"humanBones":[{"bone":"hips","node":0}]}}}}""",
    )

    private fun clip(name: String, seconds: Float, loop: Boolean): MotionClip {
        val frames = (0 until (seconds * 30).toInt()).joinToString(",") { "[0,0,0.8,1,0,0,0]" }
        return MotionClip.parse(
            """{"name":"$name","fps":30,"loop":$loop,"bones":["hips"],
               "rest":{"hips":{"p":[0,0,0.8],"q":[1,0,0,0]}},"frames":[$frames]}""",
        )
    }

    private val manifest = ClipManifest.parse(
        """{"clips":{
             "idle_breathing":{"category":"idle","weight":3,"hold":[8,16]},
             "idle_happy":{"category":"idle","weight":2,"hold":[7,14],"valence":0.7,"arousal":0.2},
             "idle_sad":{"category":"idle","weight":0,"hold":[8,14]},
             "talk_main":{"category":"talk","weight":2,"hold":[4,9]},
             "gesture_wave":{"category":"gesture","fadeIn":0.25,"fadeOut":0.45},
             "gesture_think":{"category":"gesture","loop":true,"hold":[3.5,5.5]},
             "gesture_yawn":{"category":"gesture"},
             "gesture_stretch":{"category":"gesture"}},
           "sleep":{"deep_sleep":{"clip":"idle_breathing","timeScale":0.6}}}""",
    )

    private val library: Map<String, MotionClip> = buildMap {
        for ((name, e) in manifest.clips) {
            val c = clip(name, if (e.category == "gesture") 2f else 3f, loop = e.category != "gesture")
            put(name, c)
            put(c.mirrored().name, c.mirrored())
        }
    }

    private fun machine(seed: Int = 1): Pair<BodyStateMachine, AvatarAnimator> {
        val animator = AvatarAnimator(AvatarRig(doc))
        val m = BodyStateMachine(manifest, { library[it] }, animator, Random(seed))
        m.start()
        return m to animator
    }

    private fun run(m: BodyStateMachine, a: AvatarAnimator, seconds: Float) {
        var t = 0f
        while (t < seconds) {
            m.update(1 / 30f)
            a.update(1 / 30f)
            t += 1 / 30f
        }
    }

    @Test fun `l'attente part d'un clip qui se tire de lui-même, jamais d'une posture à poids nul`() {
        repeat(20) { seed ->
            val (m, _) = machine(seed)
            assertEquals(BodyStateMachine.State.IDLE, m.state)
            assertNotEquals("idle_sad", MotionClip.baseName(m.currentClip!!))
        }
    }

    @Test fun `une attente tenue jusqu'au bout cède la place à une autre`() {
        val (m, a) = machine(3)
        val first = MotionClip.baseName(m.currentClip!!)
        run(m, a, 20f)
        assertNotEquals(first, MotionClip.baseName(m.currentClip!!))
    }

    @Test fun `l'humeur ne provoque aucune transition par elle-même`() {
        val (m, a) = machine(4)
        val clip = m.currentClip
        m.setAffect("angry", 0.9f)
        run(m, a, 1f)
        assertEquals(clip, m.currentClip)
    }

    @Test fun `un clip qui déclare une humeur joyeuse est favorisé pour une réponse joyeuse`() {
        val (m, _) = machine()
        m.setAffect("happy", 1f)
        val happy = m.poolWeight("idle_happy")
        m.setAffect("sad", 1f)
        assertTrue(happy > m.poolWeight("idle_happy"))
    }

    @Test fun `un geste se joue une fois puis rend la main à l'attente`() {
        val (m, a) = machine()
        assertTrue(m.requestGesture("gesture_wave"))
        assertEquals(BodyStateMachine.State.GESTURE, m.state)
        run(m, a, 2.5f)
        assertEquals(BodyStateMachine.State.IDLE, m.state)
    }

    @Test fun `un geste qui boucle est tenu quelques secondes`() {
        val (m, a) = machine()
        m.requestGesture("gesture_think")
        run(m, a, 3f)
        assertEquals(BodyStateMachine.State.GESTURE, m.state)
        run(m, a, 3f)
        assertEquals(BodyStateMachine.State.IDLE, m.state)
    }

    @Test fun `elle bâille avant de s'endormir et s'étire au réveil`() {
        val (m, a) = machine()
        m.setSleepPhase("deep_sleep")
        assertEquals("gesture_yawn", MotionClip.baseName(m.currentClip!!))
        run(m, a, 2.5f)
        assertEquals(BodyStateMachine.State.SLEEPING, m.state)
        assertFalse(m.requestGesture("gesture_wave"))
        m.setSleepPhase("awake")
        assertEquals("gesture_stretch", MotionClip.baseName(m.currentClip!!))
        run(m, a, 2.5f)
        assertEquals(BodyStateMachine.State.IDLE, m.state)
    }

    @Test fun `une posture d'émotion remplace l'attente, et la parole se tient un instant après la voix`() {
        val (m, a) = machine()
        m.setIdleVariant("idle_sad")
        assertEquals("idle_sad", MotionClip.baseName(m.currentClip!!))
        m.setSpeaking(true)
        assertEquals(BodyStateMachine.State.TALKING, m.state)
        m.setSpeaking(false)
        run(m, a, 0.4f)
        assertEquals(BodyStateMachine.State.TALKING, m.state)
        run(m, a, 0.5f)
        assertEquals(BodyStateMachine.State.IDLE, m.state)
    }

    @Test fun `le miroir échange gauche et droite et retourne les hanches`() {
        val c = MotionClip.parse(
            """{"name":"m","fps":30,"loop":true,"bones":["leftHand","rightHand"],
               "rest":{"leftHand":{"p":[0,0,0],"q":[1,0,0,0]},"rightHand":{"p":[0,0,0],"q":[1,0,0,0]}},
               "frames":[[0.1,0,0.8, 0.9238795,0.3826834,0,0, 1,0,0,0]]}""",
        )
        val pose = Pose(arrayOf("leftHand", "rightHand"))
        c.mirrored().sample(0f, pose)
        assertEquals(Quat.IDENTITY.w, pose["leftHand"]!!.w, 1e-5f)
        assertTrue(pose["rightHand"]!!.w < 0.99f)
        assertEquals(-c.let { val p = Pose(arrayOf("leftHand")); it.sample(0f, p); p.hips.x }, pose.hips.x, 1e-6f)
    }
}
