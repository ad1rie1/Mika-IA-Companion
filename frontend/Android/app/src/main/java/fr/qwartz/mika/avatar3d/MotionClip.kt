package fr.qwartz.mika.avatar3d

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.InputStream
import java.util.zip.GZIPInputStream
import kotlin.math.floor

/**
 * La pose du corps : pour chaque os humanoïde, son changement d'orientation depuis la T-pose de repos, en repère
 * monde glTF ; plus la position des hanches. C'est la forme des mouvements de l'atelier, ramenée dans le repère du
 * VRM — et ce que les couches procédurales (souffle, regard, port de tête) modifient avant le squelette.
 */
class Pose(val bones: Array<String>) {
    val rotations: Array<Quat> = Array(bones.size) { Quat.IDENTITY }
    var hips: Vec3 = Vec3.ZERO
    private val index = bones.withIndex().associate { (i, b) -> b to i }

    fun indexOf(bone: String): Int = index[bone] ?: -1
    operator fun get(bone: String): Quat? = index[bone]?.let { rotations[it] }
    operator fun set(bone: String, q: Quat) {
        index[bone]?.let { rotations[it] = q }
    }

    /** Applique une rotation monde supplémentaire à `bone` (et à lui seul : le squelette fera suivre ses enfants). */
    fun rotateWorld(bone: String, q: Quat) {
        val i = index[bone] ?: return
        rotations[i] = (q * rotations[i]).normalized()
    }

    fun copyFrom(o: Pose) {
        for (i in bones.indices) rotations[i] = o.rotations[o.indexOf(bones[i])]
        hips = o.hips
    }

    /** Fond `o` dans cette pose, à la part `t` (0 : celle-ci, 1 : `o`). */
    fun blendTowards(o: Pose, t: Float) {
        for (i in bones.indices) {
            val j = o.indexOf(bones[i])
            if (j >= 0) rotations[i] = rotations[i].slerp(o.rotations[j], t)
        }
        hips = hips.lerp(o.hips, t)
    }
}

/**
 * Un mouvement de l'atelier (`frontend/Unity/ArtSource/atelier/motions/<nom>.json.gz`, ce qu'Unity importe aussi) :
 * pour chaque image, la position des hanches et l'orientation monde de chaque os humanoïde, en repère Blender
 * (Z en haut, le personnage regarde −Y), quaternions écrits (w, x, y, z).
 *
 * Le VRM a pour repos une T-pose aux rotations nulles : l'orientation d'un os dans le VRM est donc exactement son
 * changement depuis le repos de l'atelier, ramené en glTF par (x, y, z) → (−x, z, y) — vérifié sur les positions
 * de repos des os (hanches, tête, mains, pieds) à 0,1 mm près.
 */
class MotionClip private constructor(
    val name: String,
    val fps: Float,
    val loop: Boolean,
    val bones: Array<String>,
    /** Par image : hanches (3) puis, par os, le changement depuis le repos en glTF (x, y, z, w). */
    private val frames: Array<FloatArray>,
) {
    val frameCount: Int get() = frames.size
    val duration: Float get() = (frames.size - 1).coerceAtLeast(1) / fps

    /** La pose au temps `t` (secondes) : bouclée ou bornée, interpolée entre les deux images voisines. */
    fun sample(t: Float, out: Pose, loop: Boolean = this.loop) {
        val n = frames.size
        var pos = t * fps
        if (loop) {
            pos %= n.toFloat()
            if (pos < 0) pos += n
        } else {
            pos = pos.coerceIn(0f, (n - 1).toFloat())
        }
        val i = floor(pos).toInt().coerceIn(0, n - 1)
        val j = if (loop) (i + 1) % n else (i + 1).coerceAtMost(n - 1)
        val f = pos - i
        val a = frames[i]
        val b = frames[j]
        out.hips = Vec3(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)
        for (k in bones.indices) {
            val o = 3 + 4 * k
            val qa = Quat(a[o], a[o + 1], a[o + 2], a[o + 3])
            val qb = Quat(b[o], b[o + 1], b[o + 2], b[o + 3])
            out[bones[k]] = qa.slerp(qb, f)
        }
    }

    /**
     * Le jumeau en miroir (gauche ↔ droite), comme `clipMirror.ts` le fait sur le web : un clip qui revient toujours du
     * même côté se reconnaît ; son miroir double chaque attente pour rien. Le plan de symétrie est x = 0 (sa droite
     * est +X) : une rotation (x, y, z, w) devient (x, −y, −z, w), l'os gauche prend la rotation de l'os droit, les
     * hanches passent de l'autre côté.
     */
    fun mirrored(): MotionClip {
        val twin = IntArray(bones.size) { k -> bones.indexOf(mirrorBone(bones[k])).takeIf { it >= 0 } ?: k }
        val out = frames.map { f ->
            val m = FloatArray(f.size)
            m[0] = -f[0]
            m[1] = f[1]
            m[2] = f[2]
            for (k in bones.indices) {
                val src = 3 + 4 * twin[k]
                val dst = 3 + 4 * k
                m[dst] = f[src]
                m[dst + 1] = -f[src + 1]
                m[dst + 2] = -f[src + 2]
                m[dst + 3] = f[src + 3]
            }
            m
        }.toTypedArray()
        return MotionClip(name + MIRROR_SUFFIX, fps, loop, bones, out)
    }

    companion object {
        private val JSON = Json { ignoreUnknownKeys = true }
        const val MIRROR_SUFFIX = "~m"

        fun mirrorBone(bone: String): String = when {
            bone.startsWith("left") -> "right" + bone.removePrefix("left")
            bone.startsWith("right") -> "left" + bone.removePrefix("right")
            else -> bone
        }

        /** Le nom du clip du manifeste dont `name` est issu (lui-même, ou le jumeau en miroir). */
        fun baseName(name: String): String = name.removeSuffix(MIRROR_SUFFIX)

        /** Blender (x, y, z) → glTF (−x, z, y) : une rotation propre, qui change aussi les axes des quaternions. */
        fun toGltf(v: Vec3) = Vec3(-v.x, v.z, v.y)

        fun toGltf(q: Quat) = Quat(-q.x, q.z, q.y, q.w)

        fun read(input: InputStream, gzipped: Boolean = true): MotionClip {
            val text = (if (gzipped) GZIPInputStream(input) else input).bufferedReader().use { it.readText() }
            return parse(text)
        }

        fun parse(text: String): MotionClip {
            val o = JSON.parseToJsonElement(text).jsonObject
            val bones = o["bones"]!!.jsonArray.map { it.jsonPrimitive.content }.toTypedArray()
            val rest = o["rest"]!!.jsonObject
            // Le repos de chaque os en Blender, inversé une fois.
            val restInv = bones.map { b ->
                val q = rest[b]!!.jsonObject["q"]!!.jsonArray.map { it.jsonPrimitive.double.toFloat() }
                Quat(q[1], q[2], q[3], q[0]).normalized().inverse()
            }
            val frames = o["frames"]!!.jsonArray.map { row ->
                val v = row.jsonArray.map { it.jsonPrimitive.double.toFloat() }
                val out = FloatArray(3 + 4 * bones.size)
                val hips = toGltf(Vec3(v[0], v[1], v[2]))
                out[0] = hips.x
                out[1] = hips.y
                out[2] = hips.z
                for (k in bones.indices) {
                    val s = 3 + 4 * k
                    val world = Quat(v[s + 1], v[s + 2], v[s + 3], v[s])
                    val delta = toGltf((world * restInv[k]).normalized())
                    out[3 + 4 * k] = delta.x
                    out[4 + 4 * k] = delta.y
                    out[5 + 4 * k] = delta.z
                    out[6 + 4 * k] = delta.w
                }
                out
            }.toTypedArray()
            return MotionClip(
                name = o["name"]?.jsonPrimitive?.content.orEmpty(),
                fps = o["fps"]?.jsonPrimitive?.int?.toFloat() ?: 30f,
                loop = o["loop"]?.jsonPrimitive?.boolean ?: false,
                bones = bones,
                frames = frames,
            )
        }
    }
}
