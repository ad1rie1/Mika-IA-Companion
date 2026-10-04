package fr.qwartz.mika.data.files

import kotlinx.serialization.Serializable
import java.io.File
import java.io.IOException

/** Un fichier prêt à joindre, déjà copié dans l'espace de l'app (le sélecteur ne garde pas ses droits). */
@Serializable
data class StagedFile(val name: String, val mime: String, val path: String, val size: Long)

/** Un fichier d'un message en partance, tel que la ligne `outbox` le décrit. */
@Serializable
data class OutboxFile(
    val name: String,
    val mime: String,
    val size: Long,
    /** Son nom sur le disque, dans le dossier du message. */
    val file: String,
)

/**
 * Les fichiers des messages, sur le disque — jamais en base. `outbox/<cid>/` tant que le message n'a
 * pas d'accusé ; `sent/<cid>/` ensuite (vignettes de ses propres photos, renvoi d'un message refusé),
 * gardé dans un budget de [sentBudgetBytes], les plus anciens partant les premiers.
 */
class OutboxFiles(
    private val root: File,
    private val sentBudgetBytes: Long = 100L * 1024 * 1024,
) {
    private val outbox = File(root, "outbox")
    private val sent = File(root, "sent")
    val staging = File(root, "staging")

    /** Ranger les fichiers préparés dans le dossier du message ; ils quittent la préparation. */
    fun adopt(cid: String, staged: List<StagedFile>): List<OutboxFile> {
        if (staged.isEmpty()) return emptyList()
        val dir = File(outbox, safe(cid)).apply { mkdirs() }
        val taken = HashSet<String>()
        return staged.map { s ->
            val name = unique(sanitize(s.name), taken)
            val target = File(dir, name)
            val source = File(s.path)
            if (!source.renameTo(target)) {
                source.copyTo(target, overwrite = true)
                source.delete()
            }
            OutboxFile(s.name, s.mime, target.length(), name)
        }
    }

    /** Où lire un fichier d'un message : encore en partance, ou déjà accusé. */
    fun locate(cid: String, file: String): File? {
        val name = sanitize(file)
        return listOf(File(File(outbox, safe(cid)), name), File(File(sent, safe(cid)), name)).firstOrNull { it.isFile }
    }

    /** Ouvrir les fichiers d'un message pour écrire sa trame ; un fichier disparu lève. */
    fun open(cid: String, file: String): java.io.InputStream =
        (locate(cid, file) ?: throw IOException("fichier introuvable : $file")).inputStream()

    /** L'accusé est arrivé : le dossier passe dans `sent/`, et le budget est tenu. */
    fun release(cid: String) {
        val from = File(outbox, safe(cid))
        if (!from.isDirectory) return
        sent.mkdirs()
        val to = File(sent, safe(cid))
        to.deleteRecursively()
        if (!from.renameTo(to)) {
            from.copyRecursively(to, overwrite = true)
            from.deleteRecursively()
        }
        to.setLastModified(System.currentTimeMillis())
        trimSent()
    }

    /**
     * Pour renvoyer un message refusé : ses fichiers repassent en préparation (sous de nouveaux noms
     * de disque), dans l'ordre donné. Ceux qui ont disparu sont omis.
     */
    fun restage(cid: String, files: List<Pair<String, String>>, mimeOf: (String) -> String): List<StagedFile> {
        staging.mkdirs()
        return files.mapNotNull { (name, disk) ->
            val source = locate(cid, disk) ?: return@mapNotNull null
            val target = File.createTempFile("retry-", ".bin", staging)
            source.copyTo(target, overwrite = true)
            StagedFile(name, mimeOf(name), target.absolutePath, target.length())
        }
    }

    fun forget(cid: String) {
        File(outbox, safe(cid)).deleteRecursively()
        File(sent, safe(cid)).deleteRecursively()
    }

    /**
     * Déconnexion : plus aucun fichier de cette conversation sur le téléphone. [keepStaging] : ce qui
     * attend dans la barre de saisie (un partage reçu hors session) reste pour la session qui s'ouvre.
     */
    fun wipe(keepStaging: Boolean = false) {
        outbox.deleteRecursively()
        sent.deleteRecursively()
        if (!keepStaging) staging.deleteRecursively()
    }

    /** Un nouveau fichier vide dans la préparation, où copier ce qu'un sélecteur ou un partage donne. */
    fun newStagingFile(suffix: String = ".bin"): File {
        staging.mkdirs()
        return File.createTempFile("stage-", suffix, staging)
    }

    /** Retirer un fichier préparé (✕ sur sa puce) : seulement s'il est bien dans la préparation. */
    fun discardStaged(path: String) {
        val file = File(path)
        if (file.parentFile?.canonicalPath == staging.canonicalPath) file.delete()
    }

    /**
     * Ranger la préparation : ce qu'aucun brouillon ne cite plus (un envoi annulé, une app tuée au
     * milieu d'une copie) n'a rien à faire là. Seulement ce qui a plus de [minAgeMs] : un partage peut
     * être en train d'y copier ses fichiers.
     */
    fun pruneStaging(keep: Set<String>, nowMs: Long, minAgeMs: Long = 10 * 60_000L) {
        val kept = keep.mapTo(HashSet()) { File(it).canonicalPath }
        staging.listFiles()?.forEach {
            if (it.canonicalPath !in kept && nowMs - it.lastModified() > minAgeMs) it.deleteRecursively()
        }
    }

    private fun trimSent() {
        val dirs = sent.listFiles { f -> f.isDirectory }?.toMutableList() ?: return
        var total = dirs.sumOf { size(it) }
        dirs.sortBy { it.lastModified() }
        for (dir in dirs) {
            if (total <= sentBudgetBytes) break
            total -= size(dir)
            dir.deleteRecursively()
        }
    }

    private fun size(dir: File): Long = dir.walkBottomUp().filter { it.isFile }.sumOf { it.length() }

    companion object {
        private val UNSAFE = Regex("""[^\p{L}\p{N}._\- ]""")

        /** Un nom de disque sans chemin ni caractère douteux, jamais vide, jamais caché. */
        fun sanitize(name: String): String {
            val base = name.substringAfterLast('/').substringAfterLast('\\')
            val cleaned = UNSAFE.replace(base, "_").trim().trimStart('.').take(80)
            return cleaned.ifEmpty { "fichier" }
        }

        private fun safe(cid: String) = sanitize(cid)

        private fun unique(name: String, taken: MutableSet<String>): String {
            var candidate = name
            var n = 2
            while (!taken.add(candidate)) {
                val dot = name.lastIndexOf('.')
                candidate = if (dot > 0) "${name.substring(0, dot)} ($n)${name.substring(dot)}" else "$name ($n)"
                n++
            }
            return candidate
        }
    }
}
