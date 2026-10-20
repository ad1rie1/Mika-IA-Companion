package fr.qwartz.mika.data.phone

import java.security.MessageDigest

/**
 * Les clés opaques d'un message lu sur le téléphone (ADR 0120) : le serveur ne reçoit jamais l'identifiant que la
 * notification donne à une conversation ou à un contact (un numéro, un identifiant WhatsApp), seulement son empreinte —
 * les 16 premiers octets de SHA-256, en hexadécimal minuscule (32 caractères). Les mêmes entrées donnent toujours la
 * même clé : une conversation garde sa clé d'une notification à l'autre, et un message qui revient à chaque mise à jour
 * de la notification garde son identifiant (le serveur ne l'écrit qu'une fois).
 */
object PhoneKeys {
    const val LENGTH = 32
    private const val BYTES = LENGTH / 2

    fun hash(value: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
        val out = StringBuilder(LENGTH)
        for (i in 0 until BYTES) {
            val b = digest[i].toInt() and 0xff
            out.append(HEX[b ushr 4]).append(HEX[b and 0x0f])
        }
        return out.toString()
    }

    /** La conversation : l'appli et l'identifiant qu'elle donne à la conversation. */
    fun thread(packageName: String, conversation: String): String = hash("$packageName|$conversation")

    /** L'expéditeur : l'appli et sa clé (`person.key`, sinon `uri`, sinon le nom). Vide quand c'est la personne. */
    fun sender(packageName: String, senderKey: String): String = hash("$packageName|$senderKey")

    /** Le message : tout ce qui le distingue, pour qu'une notification mise à jour ne le fasse pas compter deux fois. */
    fun id(packageName: String, thread: String, sender: String, time: Long, text: String): String =
        hash("$packageName|$thread|$sender|$time|$text")

    /** Une clé telle que le serveur l'attend (une conversation d'une proposition de réponse, par exemple). */
    fun isKey(value: String): Boolean = value.length == LENGTH && value.all { it in '0'..'9' || it in 'a'..'f' }

    private val HEX = "0123456789abcdef".toCharArray()
}
