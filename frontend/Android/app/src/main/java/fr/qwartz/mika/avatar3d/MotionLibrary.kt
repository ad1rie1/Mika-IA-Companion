package fr.qwartz.mika.avatar3d

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.IOException

/** Les mouvements de l'atelier embarqués (`avatar3d/motions/<nom>.json.gz`), lus à la demande et gardés. */
class MotionLibrary(private val context: Context) {
    private val mutex = Mutex()
    private val clips = HashMap<String, MotionClip>()

    suspend fun get(name: String): MotionClip? = mutex.withLock {
        clips[name] ?: withContext(Dispatchers.IO) { open(name) }?.also { clips[name] = it }
    }

    /**
     * La construction Android décompresse les `.gz` des assets et retire l'extension : le fichier arrive en `.json`.
     * Les deux formes sont lues, au cas où un réglage d'empaquetage les garderait compressés.
     */
    private fun open(name: String): MotionClip? {
        for ((file, gzipped) in listOf("$name.json" to false, "$name.json.gz" to true)) {
            try {
                return context.assets.open("$DIR/$file").use { MotionClip.read(it, gzipped) }
            } catch (_: IOException) {
            }
        }
        return null
    }

    /** Le manifeste des animations du web, embarqué ; null s'il manque. */
    suspend fun manifest(): ClipManifest? = withContext(Dispatchers.IO) {
        try {
            context.assets.open(ClipManifest.PATH).bufferedReader().use { ClipManifest.parse(it.readText()) }
        } catch (_: IOException) {
            null
        }
    }

    /**
     * Tous les mouvements que le manifeste cite, lus en parallèle, avec leurs jumeaux en miroir (sauf `mirror:
     * false`). Les absents sont simplement omis : la machine à états fait avec ce qu'elle a.
     */
    suspend fun loadAll(manifest: ClipManifest): Map<String, MotionClip> = coroutineScope {
        val loaded = manifest.clips.keys.map { name -> async(Dispatchers.Default) { name to open(name) } }.awaitAll()
        buildMap {
            for ((name, clip) in loaded) {
                if (clip == null) continue
                put(name, clip)
                if (manifest.clips[name]?.mirror != false) {
                    val twin = clip.mirrored()
                    put(twin.name, twin)
                }
            }
        }
    }

    /** Les noms disponibles. */
    fun names(): List<String> = context.assets.list(DIR).orEmpty()
        .filter { it.endsWith(".json") || it.endsWith(".json.gz") }
        .map { it.removeSuffix(".gz").removeSuffix(".json") }
        .distinct()
        .sorted()

    companion object {
        const val DIR = "avatar3d/motions"
    }
}
