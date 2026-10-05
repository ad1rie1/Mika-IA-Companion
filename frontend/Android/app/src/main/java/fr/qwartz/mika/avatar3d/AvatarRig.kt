package fr.qwartz.mika.avatar3d

/**
 * Le squelette du VRM vu par l'animation : de la [Pose] (orientations monde des os humanoïdes) aux transformations
 * locales des nœuds, que le moteur pose. Le repos est une T-pose aux rotations nulles : un os humanoïde prend
 * l'orientation de la pose, un nœud qui n'en est pas un (racine, os de torsion, mèches) garde sa rotation de repos
 * et suit son parent. Pur : testé sur la JVM.
 */
class AvatarRig(val doc: VrmDocument) {
    /** Os humanoïde → nœud, et l'inverse. */
    private val nodeOf: Map<String, Int> = doc.humanoid
    private val boneOf: Map<Int, String> = doc.humanoid.entries.associate { (b, n) -> n to b }

    /** Les nœuds humanoïdes et leurs ancêtres, parents d'abord : l'ordre dans lequel les poser. */
    val order: IntArray

    /** Les os que l'animation pose (ceux du VRM), dans l'ordre de la pose. */
    val bones: Array<String> = doc.humanoid.keys.sorted().toTypedArray()

    init {
        val needed = LinkedHashSet<Int>()
        for (n in nodeOf.values) {
            val chain = ArrayList<Int>()
            var i: Int? = n
            while (i != null) {
                chain.add(i)
                i = doc.nodes[i].parent
            }
            needed.addAll(chain.asReversed())
        }
        order = needed.sortedBy { depth(it) }.toIntArray()
    }

    private fun depth(i: Int): Int {
        var d = 0
        var n = doc.nodes[i].parent
        while (n != null) {
            d++
            n = doc.nodes[n].parent
        }
        return d
    }

    fun newPose() = Pose(bones)

    /** Pour chaque os humanoïde, ses descendants humanoïdes (une rotation de l'os les emporte). */
    private val descendants: Map<String, List<String>> = bones.associateWith { b ->
        val start = nodeOf.getValue(b)
        boneOf.filter { (n, _) -> n != start && isAncestor(start, n) }.values.toList()
    }

    private fun isAncestor(ancestor: Int, node: Int): Boolean {
        var n = doc.nodes[node].parent
        while (n != null) {
            if (n == ancestor) return true
            n = doc.nodes[n].parent
        }
        return false
    }

    /**
     * Tourne `bone` de `q` (rotation monde, autour de l'os) et emporte tout ce qu'il porte : une poitrine qui
     * respire soulève les bras, une tête qui penche emporte les yeux. C'est l'équivalent, sur une pose en
     * orientations monde, des rotations additives du client web.
     */
    fun rotate(pose: Pose, bone: String, q: Quat) {
        pose.rotateWorld(bone, q)
        descendants[bone]?.forEach { pose.rotateWorld(it, q) }
    }

    /** Une transformation locale à poser : nœud, translation, rotation, échelle. */
    class Local(val node: Int, var translation: Vec3, var rotation: Quat, val scale: Vec3)

    private val worldRot = arrayOfNulls<Quat>(doc.nodes.size)
    private val worldPos = arrayOfNulls<Vec3>(doc.nodes.size)
    val locals: Array<Local> = order.map { n -> Local(n, doc.nodes[n].translation, doc.nodes[n].rotation, doc.nodes[n].scale) }
        .toTypedArray()

    /**
     * Les transformations locales de [locals] pour la pose `pose`. Les hanches portent leur position (le mouvement
     * de l'atelier) ; les autres os gardent la longueur de leur repos.
     */
    fun solve(pose: Pose): Array<Local> {
        for (local in locals) {
            val node = doc.nodes[local.node]
            val parent = node.parent
            val pRot = if (parent != null) worldRot[parent] ?: Quat.IDENTITY else Quat.IDENTITY
            val pPos = if (parent != null) worldPos[parent] ?: Vec3.ZERO else Vec3.ZERO
            val bone = boneOf[local.node]
            val world = if (bone != null) pose[bone] ?: Quat.IDENTITY else (pRot * node.rotation)
            local.rotation = (pRot.inverse() * world).normalized()
            local.translation = if (bone == "hips") pRot.inverse().rotate(pose.hips - pPos) else node.translation
            worldRot[local.node] = world
            worldPos[local.node] = pPos + pRot.rotate(local.translation)
        }
        return locals
    }

    /** L'orientation et la position monde d'un os après le dernier [solve]. */
    fun world(bone: String): Pair<Quat, Vec3>? {
        val n = nodeOf[bone] ?: return null
        return (worldRot[n] ?: return null) to (worldPos[n] ?: return null)
    }

    fun node(bone: String): Int? = nodeOf[bone]

    /** L'orientation et la position monde d'un nœud que le squelette pose (os humanoïde ou ancêtre), ou null. */
    fun nodeWorld(node: Int): Pair<Quat, Vec3>? {
        val r = worldRot[node] ?: return null
        val p = worldPos[node] ?: return null
        return r to p
    }
}
