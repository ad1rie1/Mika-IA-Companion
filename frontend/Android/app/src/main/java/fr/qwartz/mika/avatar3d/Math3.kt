package fr.qwartz.mika.avatar3d

import kotlin.math.acos
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

/** Un vecteur 3D (repère glTF : Y en haut, le VRM 0.x regarde vers −Z). */
data class Vec3(val x: Float, val y: Float, val z: Float) {
    operator fun plus(o: Vec3) = Vec3(x + o.x, y + o.y, z + o.z)
    operator fun minus(o: Vec3) = Vec3(x - o.x, y - o.y, z - o.z)
    operator fun times(s: Float) = Vec3(x * s, y * s, z * s)
    operator fun times(o: Vec3) = Vec3(x * o.x, y * o.y, z * o.z)
    fun dot(o: Vec3) = x * o.x + y * o.y + z * o.z
    fun cross(o: Vec3) = Vec3(y * o.z - z * o.y, z * o.x - x * o.z, x * o.y - y * o.x)
    fun length() = sqrt(dot(this))
    fun normalized(): Vec3 = length().let { if (it < 1e-9f) this else this * (1f / it) }
    fun lerp(o: Vec3, t: Float) = Vec3(x + (o.x - x) * t, y + (o.y - y) * t, z + (o.z - z) * t)

    companion object {
        val ZERO = Vec3(0f, 0f, 0f)
        val ONE = Vec3(1f, 1f, 1f)
    }
}

/** Un quaternion (x, y, z, w), comme glTF l'écrit. */
data class Quat(val x: Float, val y: Float, val z: Float, val w: Float) {
    /** Produit de Hamilton : `a * b` applique b puis a. */
    operator fun times(o: Quat) = Quat(
        w * o.x + x * o.w + y * o.z - z * o.y,
        w * o.y - x * o.z + y * o.w + z * o.x,
        w * o.z + x * o.y - y * o.x + z * o.w,
        w * o.w - x * o.x - y * o.y - z * o.z,
    )

    fun conjugate() = Quat(-x, -y, -z, w)

    /** L'inverse d'un quaternion unitaire. */
    fun inverse() = conjugate()

    fun normalized(): Quat {
        val n = sqrt(x * x + y * y + z * z + w * w)
        return if (n < 1e-9f) IDENTITY else Quat(x / n, y / n, z / n, w / n)
    }

    fun rotate(v: Vec3): Vec3 {
        val u = Vec3(x, y, z)
        val t = u.cross(v) * 2f
        return v + t * w + u.cross(t)
    }

    fun dot(o: Quat) = x * o.x + y * o.y + z * o.z + w * o.w

    /** Interpolation sphérique, par le plus court chemin. */
    fun slerp(o: Quat, t: Float): Quat {
        var b = o
        var d = dot(o)
        if (d < 0f) {
            b = Quat(-o.x, -o.y, -o.z, -o.w)
            d = -d
        }
        if (d > 0.9995f) {
            return Quat(x + (b.x - x) * t, y + (b.y - y) * t, z + (b.z - z) * t, w + (b.w - w) * t).normalized()
        }
        val theta = acos(d.coerceIn(-1f, 1f))
        val s = sin(theta)
        val wa = sin((1 - t) * theta) / s
        val wb = sin(t * theta) / s
        return Quat(x * wa + b.x * wb, y * wa + b.y * wb, z * wa + b.z * wb, w * wa + b.w * wb)
    }

    /** Une fraction `t` de cette rotation (depuis l'identité). */
    fun scaled(t: Float): Quat = IDENTITY.slerp(this, t)

    companion object {
        val IDENTITY = Quat(0f, 0f, 0f, 1f)

        fun axisAngle(axis: Vec3, radians: Float): Quat {
            val a = axis.normalized()
            val s = sin(radians / 2)
            return Quat(a.x * s, a.y * s, a.z * s, cos(radians / 2))
        }

        /** La rotation la plus courte qui amène la direction `from` sur `to`. */
        fun between(from: Vec3, to: Vec3): Quat {
            val a = from.normalized()
            val b = to.normalized()
            val d = a.dot(b)
            if (d > 0.999999f) return IDENTITY
            if (d < -0.999999f) {
                var axis = Vec3(1f, 0f, 0f).cross(a)
                if (axis.length() < 1e-6f) axis = Vec3(0f, 1f, 0f).cross(a)
                return axisAngle(axis, Math.PI.toFloat())
            }
            val c = a.cross(b)
            return Quat(c.x, c.y, c.z, 1f + d).normalized()
        }
    }
}

/** Une matrice 4×4 colonne par colonne (l'ordre de Filament) : translation, rotation, échelle. */
fun trs(t: Vec3, r: Quat, s: Vec3, out: FloatArray = FloatArray(16)): FloatArray {
    val (x, y, z, w) = r
    val xx = x * x
    val yy = y * y
    val zz = z * z
    val xy = x * y
    val xz = x * z
    val yz = y * z
    val wx = w * x
    val wy = w * y
    val wz = w * z
    out[0] = (1 - 2 * (yy + zz)) * s.x
    out[1] = 2 * (xy + wz) * s.x
    out[2] = 2 * (xz - wy) * s.x
    out[3] = 0f
    out[4] = 2 * (xy - wz) * s.y
    out[5] = (1 - 2 * (xx + zz)) * s.y
    out[6] = 2 * (yz + wx) * s.y
    out[7] = 0f
    out[8] = 2 * (xz + wy) * s.z
    out[9] = 2 * (yz - wx) * s.z
    out[10] = (1 - 2 * (xx + yy)) * s.z
    out[11] = 0f
    out[12] = t.x
    out[13] = t.y
    out[14] = t.z
    out[15] = 1f
    return out
}
