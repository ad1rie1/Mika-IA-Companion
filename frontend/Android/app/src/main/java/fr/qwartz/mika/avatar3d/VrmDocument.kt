package fr.qwartz.mika.avatar3d

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Ce que l'app lit du VRM 0.x de Mika (le JSON du GLB) : ce que le moteur glTF ignore et dont l'avatar a besoin —
 * les os humanoïdes, les groupes d'expressions et leurs morphoses, les maillages, la pose de repos. Pur : testé
 * sur la JVM, sans Filament.
 */
class VrmDocument private constructor(private val root: JsonObject) {

    /** Un nœud du glTF : son nom, son parent, sa pose de repos locale. */
    class Node(
        val index: Int,
        val name: String,
        val parent: Int?,
        val translation: Vec3,
        val rotation: Quat,
        val scale: Vec3,
        val mesh: Int?,
    )

    /**
     * Un lien d'expression : la morphose `name` (portée par un ou plusieurs maillages : le visage est découpé par
     * matériau), au poids `weight` (0…1).
     */
    data class Bind(val name: String, val weight: Float)

    class Expression(val name: String, val preset: String, val binds: List<Bind>, val binary: Boolean)

    /** Une famille de ressorts (cheveux, jupe…) : ses racines, ses réglages, les colliders qu'elle évite. */
    class SpringGroup(
        val comment: String,
        val stiffness: Float,
        val gravityPower: Float,
        val gravityDir: Vec3,
        val dragForce: Float,
        val hitRadius: Float,
        val roots: List<Int>,
        val colliderGroups: List<Int>,
    )

    /** Des sphères attachées à un nœud (décalage dans le repère du nœud, rayon). */
    class ColliderGroup(val node: Int, val spheres: List<Pair<Vec3, Float>>)

    val nodes: List<Node>
    /** Os humanoïde VRM (« hips », « leftUpperArm »…) → index du nœud. */
    val humanoid: Map<String, Int>
    /** Groupes d'expressions : les presets sous leur preset (« blink », « joy »…), les autres sous leur nom (« Smile1 »). */
    val expressions: Map<String, Expression>
    /** Nom des morphoses de chaque maillage (`extras.targetNames`). */
    val morphNames: Map<Int, List<String>>
    val springGroups: List<SpringGroup>
    val colliderGroups: List<ColliderGroup>

    /** Les enfants de chaque nœud, dans l'ordre du glTF. */
    val children: Map<Int, List<Int>>

    init {
        val jsonNodes = root["nodes"]?.jsonArray ?: JsonArray(emptyList())
        val parents = HashMap<Int, Int>()
        jsonNodes.forEachIndexed { i, n ->
            n.jsonObject["children"]?.jsonArray?.forEach { c -> parents[c.jsonPrimitive.int] = i }
        }
        nodes = jsonNodes.mapIndexed { i, n ->
            val o = n.jsonObject
            Node(
                index = i,
                name = o["name"]?.jsonPrimitive?.content ?: "node$i",
                parent = parents[i],
                translation = o["translation"]?.floats()?.let { Vec3(it[0], it[1], it[2]) } ?: Vec3.ZERO,
                rotation = o["rotation"]?.floats()?.let { Quat(it[0], it[1], it[2], it[3]) } ?: Quat.IDENTITY,
                scale = o["scale"]?.floats()?.let { Vec3(it[0], it[1], it[2]) } ?: Vec3.ONE,
                mesh = o["mesh"]?.jsonPrimitive?.int,
            )
        }
        morphNames = root["meshes"]?.jsonArray?.mapIndexed { i, m ->
            i to (m.jsonObject["extras"]?.jsonObject?.get("targetNames")?.jsonArray?.map { it.jsonPrimitive.content }.orEmpty())
        }?.toMap() ?: emptyMap()
        children = jsonNodes.mapIndexed { i, n ->
            i to (n.jsonObject["children"]?.jsonArray?.map { it.jsonPrimitive.int }.orEmpty())
        }.toMap()
        val vrm = root["extensions"]?.jsonObject?.get("VRM")?.jsonObject
        val secondary = vrm?.get("secondaryAnimation")?.jsonObject
        fun vec(o: JsonObject?, default: Vec3) = o?.let {
            Vec3(
                it["x"]?.jsonPrimitive?.double?.toFloat() ?: 0f,
                it["y"]?.jsonPrimitive?.double?.toFloat() ?: 0f,
                it["z"]?.jsonPrimitive?.double?.toFloat() ?: 0f,
            )
        } ?: default
        springGroups = secondary?.get("boneGroups")?.jsonArray?.map { g ->
            val o = g.jsonObject
            SpringGroup(
                comment = o["comment"]?.jsonPrimitive?.content.orEmpty(),
                stiffness = o["stiffiness"]?.jsonPrimitive?.double?.toFloat() ?: 1f,
                gravityPower = o["gravityPower"]?.jsonPrimitive?.double?.toFloat() ?: 0f,
                gravityDir = vec(o["gravityDir"]?.jsonObject, Vec3(0f, -1f, 0f)),
                dragForce = o["dragForce"]?.jsonPrimitive?.double?.toFloat() ?: 0.4f,
                hitRadius = o["hitRadius"]?.jsonPrimitive?.double?.toFloat() ?: 0.02f,
                roots = o["bones"]?.jsonArray?.map { it.jsonPrimitive.int }.orEmpty(),
                colliderGroups = o["colliderGroups"]?.jsonArray?.map { it.jsonPrimitive.int }.orEmpty(),
            )
        }.orEmpty()
        // Le z des colliders est inversé dans un VRM 0.x (comme three-vrm le lit).
        colliderGroups = secondary?.get("colliderGroups")?.jsonArray?.map { g ->
            val o = g.jsonObject
            ColliderGroup(
                node = o["node"]!!.jsonPrimitive.int,
                spheres = o["colliders"]?.jsonArray?.map { c ->
                    val co = c.jsonObject
                    val off = vec(co["offset"]?.jsonObject, Vec3.ZERO)
                    Vec3(off.x, off.y, -off.z) to (co["radius"]?.jsonPrimitive?.double?.toFloat() ?: 0f)
                }.orEmpty(),
            )
        }.orEmpty()
        humanoid = vrm?.get("humanoid")?.jsonObject?.get("humanBones")?.jsonArray
            ?.associate { b -> b.jsonObject["bone"]!!.jsonPrimitive.content to b.jsonObject["node"]!!.jsonPrimitive.int }
            ?: emptyMap()
        expressions = vrm?.get("blendShapeMaster")?.jsonObject?.get("blendShapeGroups")?.jsonArray
            ?.map { g ->
                val o = g.jsonObject
                Expression(
                    name = o["name"]?.jsonPrimitive?.content.orEmpty(),
                    preset = o["presetName"]?.jsonPrimitive?.content.orEmpty(),
                    binds = o["binds"]?.jsonArray?.mapNotNull { b ->
                        val bo = b.jsonObject
                        // `morphName` est écrit par vrm_mobile.py ; un VRM brut n'a que le maillage et l'indice.
                        val name = bo["morphName"]?.jsonPrimitive?.content
                            ?: morphNameAt(bo["mesh"]?.jsonPrimitive?.int, bo["index"]?.jsonPrimitive?.int)
                            ?: return@mapNotNull null
                        // VRM 0.x écrit les poids de 0 à 100.
                        Bind(name, (bo["weight"]?.jsonPrimitive?.double ?: 100.0).toFloat() / 100f)
                    }.orEmpty(),
                    binary = o["isBinary"]?.jsonPrimitive?.content == "true",
                )
            }
            // Un groupe preset (« blink », « joy »…) est rangé sous son preset, comme three-vrm : ce modèle a deux
            // groupes nommés « Blink », le preset (les paupières seules) et un groupe maison qui baisse aussi les
            // sourcils — rangés par nom, le second écrasait le premier.
            ?.associateBy { if (it.preset.isNotBlank() && it.preset != "unknown") it.preset.lowercase() else it.name }
            ?: emptyMap()
    }

    private fun morphNameAt(mesh: Int?, index: Int?): String? =
        if (mesh == null || index == null) null else morphNames[mesh]?.getOrNull(index)

    /** Les nœuds qui portent le maillage `mesh` (gltfio en fait une entité chacun). */
    fun nodesOfMesh(mesh: Int): List<Node> = nodes.filter { it.mesh == mesh }

    /** La rotation monde de repos d'un nœud (le produit des rotations locales, de la racine à lui). */
    fun restWorldRotation(index: Int): Quat {
        var q = Quat.IDENTITY
        var n: Int? = index
        val chain = ArrayList<Int>()
        while (n != null) {
            chain.add(n)
            n = nodes[n].parent
        }
        for (i in chain.asReversed()) q = q * nodes[i].rotation
        return q
    }

    /** La position monde de repos d'un nœud. */
    fun restWorldPosition(index: Int): Vec3 {
        val chain = ArrayList<Int>()
        var n: Int? = index
        while (n != null) {
            chain.add(n)
            n = nodes[n].parent
        }
        var pos = Vec3.ZERO
        var rot = Quat.IDENTITY
        var scale = Vec3.ONE
        for (i in chain.asReversed()) {
            val node = nodes[i]
            pos = pos + rot.rotate(node.translation * scale)
            rot = rot * node.rotation
            scale = Vec3(scale.x * node.scale.x, scale.y * node.scale.y, scale.z * node.scale.z)
        }
        return pos
    }

    private fun kotlinx.serialization.json.JsonElement.floats(): FloatArray =
        jsonArray.map { it.jsonPrimitive.double.toFloat() }.toFloatArray()

    companion object {
        private val JSON = Json { ignoreUnknownKeys = true }

        /** Le JSON d'un GLB (premier bloc). Lève une [IllegalArgumentException] sur un fichier qui n'en est pas un. */
        fun fromGlb(bytes: ByteBuffer): VrmDocument {
            val b = bytes.duplicate().order(ByteOrder.LITTLE_ENDIAN)
            require(b.remaining() >= 20 && b.getInt(0) == 0x46546C67) { "pas un GLB" }
            val length = b.getInt(12)
            require(b.getInt(16) == 0x4E4F534A) { "GLB sans bloc JSON" }
            val raw = ByteArray(length)
            b.position(20)
            b.get(raw)
            return VrmDocument(JSON.parseToJsonElement(raw.decodeToString()).jsonObject)
        }

        fun fromJson(text: String): VrmDocument = VrmDocument(JSON.parseToJsonElement(text).jsonObject)
    }
}
