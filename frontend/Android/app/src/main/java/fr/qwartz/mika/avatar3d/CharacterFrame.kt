package fr.qwartz.mika.avatar3d

/**
 * Le repère du personnage dans le glTF du VRM 0.x : elle regarde vers −Z, sa droite est +X (sa main gauche est
 * en x < 0), le haut est +Y. Ici, géométriquement : `pitch` > 0 baisse le menton, `yaw` > 0 tourne vers sa droite,
 * `roll` > 0 penche le haut de la tête vers sa droite. Radians.
 *
 * Attention : le `yaw` du client web va dans l'autre sens (> 0 vers sa gauche, vérifié par la géométrie) ; ses tables
 * sont recopiées telles quelles et [BodyMath] fait la conversion, en un seul endroit.
 */
object CharacterFrame {
    val FORWARD = Vec3(0f, 0f, -1f)
    val RIGHT = Vec3(1f, 0f, 0f)
    val UP = Vec3(0f, 1f, 0f)

    /** Baisse (pitch > 0) ou lève le menton : rotation autour de son axe latéral. */
    fun pitch(radians: Float): Quat = Quat.axisAngle(RIGHT, -radians)

    /** Tourne vers sa droite (yaw > 0) : rotation autour de la verticale. */
    fun yaw(radians: Float): Quat = Quat.axisAngle(UP, -radians)

    /** Penche le haut vers sa droite (roll > 0) : rotation autour de l'axe avant. */
    fun roll(radians: Float): Quat = Quat.axisAngle(FORWARD, radians)

    /** pitch puis yaw puis roll, composés comme le web les ajoute. */
    fun euler(pitch: Float, yaw: Float, roll: Float): Quat = (yaw(yaw) * pitch(pitch) * roll(roll)).normalized()
}
