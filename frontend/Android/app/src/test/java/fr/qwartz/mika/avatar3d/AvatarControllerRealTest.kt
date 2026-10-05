package fr.qwartz.mika.avatar3d

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import kotlin.random.Random

/**
 * Mika entière (machine à états, couches, visage) sur les vrais fichiers, quand ils sont là : la conversation du fil
 * — une réplique qu'elle dit, un message qu'elle lit — passe bien jusqu'au corps.
 */
class AvatarControllerRealTest {
    private val glb = File("src/main/assets/avatar3d/mika.glb")
    private val motions = File("../../Unity/ArtSource/atelier/motions")
    private val manifestFile = File("../../Web/public/animations/manifest.json")

    private fun controller(): AvatarController {
        val rig = AvatarRig(VrmDocument.fromGlb(ByteBuffer.wrap(glb.readBytes())))
        val manifest = ClipManifest.parse(manifestFile.readText())
        val clips = HashMap<String, MotionClip>()
        for (name in manifest.clips.keys + manifest.sleep.values.map { it.clip }) {
            val f = File(motions, "$name.json.gz")
            if (!f.exists() || name in clips) continue
            val clip = f.inputStream().use { MotionClip.read(it) }
            clips[name] = clip
            clips[name + MotionClip.MIRROR_SUFFIX] = clip.mirrored()
        }
        return AvatarController(rig, manifest, clips, Random(1)).also {
            it.setViewer(Vec3(0f, 1.19f, -2.2f))
            it.start()
        }
    }

    /** Fait tourner `seconds` à 60 images/s sur l'horloge `now` ; rend l'horloge à la fin. */
    private fun AvatarController.run(seconds: Float, from: Long, each: (Long) -> Unit = {}): Long {
        var now = from
        repeat((seconds * 60).toInt()) {
            now += 16_666_667L
            frame(1f / 60f, now)
            each(now)
        }
        return now
    }

    @Test fun `une réplique la fait parler le temps qu'elle s'écrit, puis elle se tait`() {
        assumeTrue(glb.exists() && motions.isDirectory && manifestFile.exists())
        val c = controller()
        var now = c.run(1f, 1_000_000_000L)
        val line = Utterance("m1", "Oh, vraiment ? C'est **génial**, raconte-moi tout !", now, 16f)
        c.setUtterances(listOf(line))
        var talked = false
        var mouthMoved = false
        now = c.run(line.length / 16f * 0.9f, now) {
            if (c.machine.state == BodyStateMachine.State.TALKING) talked = true
            if (c.morphs().any { (k, v) -> k.startsWith("vrc.v_") && v > 0.05f }) mouthMoved = true
            assertTrue(c.morphs().values.all { it.isFinite() && it in 0f..1f })
        }
        assertTrue("elle parle pendant que sa réponse s'écrit", talked)
        assertTrue("sa bouche dit le texte", mouthMoved)
        c.run(line.length / 16f * 0.1f + 2f, now)
        assertNotEquals(BodyStateMachine.State.TALKING, c.machine.state)
        assertTrue("la bouche se referme", c.morphs().filterKeys { it.startsWith("vrc.v_") }.values.all { it < 0.02f })
    }

    @Test fun `un message envoyé, elle le lit, puis revient à la personne`() {
        assumeTrue(glb.exists() && motions.isDirectory && manifestFile.exists())
        val c = controller()
        var now = c.run(1f, 1_000_000_000L)
        c.noteUserMessage(1.5f)
        var read = false
        now = c.run(1.2f, now) { if (c.layers.attentionState == AttentionState.READING) read = true }
        assertTrue("elle lit", read)
        c.run(1f, now)
        assertNotEquals(AttentionState.READING, c.layers.attentionState)
    }

    @Test fun `toucher la bulle la fait taire tout de suite`() {
        assumeTrue(glb.exists() && motions.isDirectory && manifestFile.exists())
        val c = controller()
        var now = c.run(0.5f, 1_000_000_000L)
        val line = Utterance("m1", "x".repeat(160), now, 16f)
        c.setUtterances(listOf(line))
        now = c.run(1f, now)
        assertEquals(BodyStateMachine.State.TALKING, c.machine.state)
        c.setUtterances(listOf(line.copy(skippedAtNanos = now)))
        c.run(1.5f, now)
        assertNotEquals(BodyStateMachine.State.TALKING, c.machine.state)
    }
}
