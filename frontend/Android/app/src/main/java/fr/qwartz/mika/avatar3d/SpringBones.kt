package fr.qwartz.mika.avatar3d

import kotlin.math.ceil
import kotlin.math.min

/**
 * Les cheveux et les vêtements qui bougent : les « ressorts » du VRM 0.x (`secondaryAnimation`), simulés comme
 * three-vrm le fait (`VRMSpringBoneJoint.update`) — chaque articulation garde la position de sa pointe ; à chaque
 * pas, l'inertie (amortie), le rappel vers sa forme de repos, la gravité, puis la longueur conservée et les
 * sphères du corps qu'elle ne traverse pas.
 *
 * Le modèle livre ses ressorts sans gravité (rigidité 1, gravité 0) : au repos les couettes gardent leur forme,
 * mais dès qu'elle bouge plus rien ne les retient, elles flottent comme dans l'eau. Les réglages par famille sont
 * donc ceux qu'Unity leur a rendus (`frontend/Unity/Mika/Assets/Mika/Editor/Animation/SpringTuning.cs`), pour que
 * les deux clients aient les mêmes cheveux. Pur : testé sur la JVM.
 */
class SpringBones(private val doc: VrmDocument, private val rig: AvatarRig, tuning: Map<String, Tuning> = UNITY_TUNING) {

    /** Rigidité, gravité, amortissement d'une famille (le `comment` de son groupe dans le VRM). */
    data class Tuning(val stiffness: Float, val gravity: Float, val drag: Float)

    private class Settings(val stiffness: Float, val gravityPower: Float, val gravityDir: Vec3, val drag: Float, val hitRadius: Float)

    private class Joint(
        val node: Int,
        val parent: Int,
        val settings: Settings,
        val colliders: List<VrmDocument.ColliderGroup>,
        val initialLocalRotation: Quat,
        val translation: Vec3,
        /** La pointe dans le repère de l'os : la position de son premier enfant (ou 7 cm dans son prolongement). */
        val childLocal: Vec3,
    ) {
        val boneAxis = childLocal.normalized()
        val length = childLocal.length()
        var prevTail = Vec3.ZERO
        var currentTail = Vec3.ZERO
        var localRotation = initialLocalRotation
    }

    private val joints: List<Joint>
    private val jointOf = HashMap<Int, Joint>()
    private val worldRot = HashMap<Int, Quat>()
    private val worldPos = HashMap<Int, Vec3>()
    private var initialized = false

    init {
        val list = ArrayList<Joint>()
        for (group in doc.springGroups) {
            val t = tuning[group.comment]
            val settings = Settings(
                stiffness = t?.stiffness ?: group.stiffness,
                gravityPower = t?.gravity ?: group.gravityPower,
                gravityDir = group.gravityDir,
                drag = t?.drag ?: group.dragForce,
                hitRadius = group.hitRadius,
            )
            val colliders = group.colliderGroups.mapNotNull { doc.colliderGroups.getOrNull(it) }
            for (root in group.roots) {
                // Toute la descendance de la racine, parents d'abord (comme `root.traverse`).
                val stack = ArrayDeque(listOf(root))
                while (stack.isNotEmpty()) {
                    val n = stack.removeFirst()
                    val node = doc.nodes[n]
                    val parent = node.parent ?: continue
                    val child = doc.children[n]?.firstOrNull()
                    val childLocal = child?.let { doc.nodes[it].translation } ?: node.translation.normalized() * 0.07f
                    if (childLocal.length() > 1e-6f && n !in jointOf) {
                        val j = Joint(n, parent, settings, colliders, node.rotation, node.translation, childLocal)
                        jointOf[n] = j
                        list.add(j)
                    }
                    doc.children[n]?.let { stack.addAll(it) }
                }
            }
        }
        joints = list
    }

    val jointCount: Int get() = joints.size

    /** Les rotations locales calculées au dernier [update] : nœud → rotation. */
    fun forEachLocal(block: (node: Int, translation: Vec3, rotation: Quat) -> Unit) {
        for (j in joints) block(j.node, j.translation, j.localRotation)
    }

    /**
     * Avance la simulation de `dt` secondes, une fois le squelette posé ([AvatarRig.solve] déjà appelé pour cette
     * image). Par pas de 1/60 s au plus : un téléphone qui saute des images ne fait pas exploser les mèches.
     */
    fun update(dt: Float) {
        if (dt <= 0f) return
        worldRot.clear()
        worldPos.clear()
        if (!initialized) {
            reset()
            initialized = true
        }
        val steps = ceil(min(dt, MAX_DT) / STEP).toInt().coerceAtLeast(1)
        val h = min(dt, MAX_DT) / steps
        repeat(steps) {
            worldRot.clear()
            worldPos.clear()
            for (j in joints) step(j, h)
        }
    }

    /** Remet chaque mèche dans sa forme de repos, à la pose actuelle (au chargement, après un saut de pose). */
    fun reset() {
        worldRot.clear()
        worldPos.clear()
        for (j in joints) {
            j.localRotation = j.initialLocalRotation
            val (r, p) = world(j.node)
            j.currentTail = p + r.rotate(j.childLocal)
            j.prevTail = j.currentTail
        }
        worldRot.clear()
        worldPos.clear()
    }

    private fun step(j: Joint, dt: Float) {
        val (parentRot, parentPos) = world(j.parent)
        val position = parentPos + parentRot.rotate(j.translation)
        val restRot = parentRot * j.initialLocalRotation
        val axisWorld = restRot.rotate(j.boneAxis)
        val s = j.settings
        var next = j.currentTail + (j.currentTail - j.prevTail) * (1f - s.drag) +
            axisWorld * (s.stiffness * dt) + s.gravityDir * (s.gravityPower * dt)
        next = position + (next - position).normalized() * j.length
        // Les sphères du corps : la pointe ne les traverse pas.
        for (group in j.colliders) {
            val (cr, cp) = world(group.node)
            for ((offset, radius) in group.spheres) {
                val center = cp + cr.rotate(offset)
                val d = next - center
                val dist = d.length() - (radius + s.hitRadius)
                if (dist < 0f) {
                    next = next + d.normalized() * (-dist)
                    next = position + (next - position).normalized() * j.length
                }
            }
        }
        j.prevTail = j.currentTail
        j.currentTail = next
        // La rotation qui amène l'axe de repos sur la nouvelle pointe, exprimée dans le repère de repos de l'os.
        val toLocal = restRot.inverse().rotate(next - position).normalized()
        j.localRotation = (j.initialLocalRotation * Quat.between(j.boneAxis, toLocal)).normalized()
        worldRot[j.node] = parentRot * j.localRotation
        worldPos[j.node] = position
    }

    /** L'orientation et la position monde d'un nœud : le squelette, une mèche déjà simulée, ou le repos sous son parent. */
    private fun world(node: Int): Pair<Quat, Vec3> {
        worldRot[node]?.let { r -> return r to worldPos.getValue(node) }
        rig.nodeWorld(node)?.let { return it }
        val n = doc.nodes[node]
        val local = jointOf[node]?.localRotation ?: n.rotation
        val result = n.parent?.let { p ->
            val (pr, pp) = world(p)
            (pr * local) to (pp + pr.rotate(n.translation))
        } ?: (local to n.translation)
        worldRot[node] = result.first
        worldPos[node] = result.second
        return result
    }

    companion object {
        const val STEP = 1f / 60f
        const val MAX_DT = 0.1f

        /** `SpringTuning.cs` (Unity) : rigidité, gravité, amortissement par famille. */
        val UNITY_TUNING: Map<String, Tuning> = mapOf(
            "HairTail" to Tuning(1.6f, 0.6f, 0.85f),
            "HairFront" to Tuning(2.2f, 0.12f, 0.8f),
            "HairSide" to Tuning(1.8f, 0.3f, 0.82f),
            "HairOthers" to Tuning(2.0f, 0.1f, 0.75f),
            "HairRibbon" to Tuning(1.6f, 0.15f, 0.72f),
            "Generated by VRMSkirtTool 1.1.2" to Tuning(1.4f, 0.15f, 0.65f),
            "Cloth" to Tuning(1.3f, 0.2f, 0.65f),
            "Cable" to Tuning(1.2f, 0.25f, 0.7f),
        )
    }
}
