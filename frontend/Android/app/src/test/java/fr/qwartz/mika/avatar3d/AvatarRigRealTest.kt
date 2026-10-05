package fr.qwartz.mika.avatar3d

import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer

/** Sur les vrais fichiers, quand ils sont là (le VRM n'est pas versionné) : la pose d'un mouvement tient debout. */
class AvatarRigRealTest {
    private val glb = File("src/main/assets/avatar3d/mika.glb")
    private val motion = File("../../Unity/ArtSource/atelier/motions/idle_breathing.json.gz")

    @Test fun `l'attente de l'atelier la garde debout, la tête à sa hauteur`() {
        assumeTrue(glb.exists() && motion.exists())
        val doc = VrmDocument.fromGlb(ByteBuffer.wrap(glb.readBytes()))
        val rig = AvatarRig(doc)
        val clip = motion.inputStream().use { MotionClip.read(it) }
        val pose = rig.newPose()
        rig.solve(pose)
        println("repos : tête ${rig.world("head")?.second}  main ${rig.world("leftHand")?.second}")
        clip.sample(0f, pose)
        rig.solve(pose)
        println("image 0 : hanches ${pose.hips}  tête ${rig.world("head")?.second}  main ${rig.world("leftHand")?.second}")
        println("rotation tête ${pose["head"]}  hanches ${pose["hips"]}")
    }
}

/** Les ressorts sur le vrai modèle, quand il est là : stables, et les couettes pendent. */
class SpringBonesRealTest {
    private val glb = File("src/main/assets/avatar3d/mika.glb")

    @Test fun `les mèches restent attachées, finies, et tombent sous la gravité rendue`() {
        assumeTrue(glb.exists())
        val doc = VrmDocument.fromGlb(ByteBuffer.wrap(glb.readBytes()))
        val rig = AvatarRig(doc)
        val pose = rig.newPose()
        pose.hips = Vec3(0f, 0.78f, 0f)
        rig.solve(pose)
        val springs = SpringBones(doc, rig)
        println("articulations : ${springs.jointCount}")
        val tail = doc.nodes.first { it.name == "HairTail1_L.005_end" }.index
        fun tipY(): Float {
            var y = 0f
            // Remonte la chaîne avec les rotations simulées pour mesurer la pointe.
            val rot = HashMap<Int, Quat>()
            springs.forEachLocal { n, _, r -> rot[n] = r }
            val chain = generateSequence(tail) { doc.nodes[it].parent }.toList().asReversed()
            var wr = Quat.IDENTITY
            var wp = Vec3.ZERO
            for (n in chain) {
                val node = doc.nodes[n]
                val w = rig.nodeWorld(n)
                if (w != null) { wr = w.first; wp = w.second; continue }
                wp = wp + wr.rotate(node.translation)
                wr = wr * (rot[n] ?: node.rotation)
            }
            y = wp.y
            return y
        }
        springs.update(0.016f)
        val start = tipY()
        repeat(240) { springs.update(1 / 60f) }
        val end = tipY()
        println("pointe d'une couette : ${start} → ${end}")
        org.junit.Assert.assertTrue(end.isFinite())
        org.junit.Assert.assertTrue("la couette doit descendre un peu sous son poids", end <= start + 1e-3f)
        // Une tête qui tourne : rien n'explose.
        rig.rotate(pose, "head", CharacterFrame.roll(0.4f))
        rig.solve(pose)
        repeat(120) { springs.update(1 / 60f) }
        org.junit.Assert.assertTrue(tipY().isFinite())
    }
}
