package fr.qwartz.mika.data.net

import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json
import okio.Buffer
import okio.BufferedSink
import java.io.FilterOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.util.Base64

/** Un fichier à joindre : ses octets sont relus du disque au moment d'écrire la trame, jamais gardés. */
class OutgoingFile(
    val name: String,
    val mime: String,
    val size: Long,
    val open: () -> InputStream,
)

/**
 * La trame `chat`, écrite en flux : `{"type":"chat","message":…,"client_msg_id":…,"attachments":[…]}`
 * (la clé `attachments` est omise sans fichier).
 *
 * Le base64 vient de `java.util.Base64` : sans retour à la ligne, contrairement à
 * `android.util.Base64.DEFAULT` que le serveur refuserait (`b64decode(validate=True)`). Il est écrit
 * par morceaux de 48 Kio dans un tampon okio : cinq fichiers de 5 Mio ne sont jamais tous en mémoire
 * deux fois.
 */
object ChatFrameWriter {
    private const val CHUNK = 48 * 1024

    /** La taille exacte, en octets UTF-8, de la trame que [write] produira pour ces tailles de fichiers. */
    fun frameBytes(message: String, clientMsgId: String, files: List<OutgoingFile>): Long {
        var total = utf8(head(message, clientMsgId)).toLong()
        if (files.isEmpty()) return total + 1 // "}"
        total += utf8(",\"attachments\":[").toLong()
        files.forEachIndexed { i, f ->
            if (i > 0) total += 1
            total += utf8(fileHead(f)).toLong() + base64Length(f.size) + 2 // "\"}"
        }
        return total + 2 // "]}"
    }

    fun write(sink: BufferedSink, message: String, clientMsgId: String, files: List<OutgoingFile>) {
        sink.writeUtf8(head(message, clientMsgId))
        if (files.isEmpty()) {
            sink.writeUtf8("}")
            return
        }
        sink.writeUtf8(",\"attachments\":[")
        files.forEachIndexed { i, f ->
            if (i > 0) sink.writeUtf8(",")
            sink.writeUtf8(fileHead(f))
            // Le flux base64 doit être fermé pour écrire son remplissage, sans fermer le puits.
            val encoder = Base64.getEncoder().wrap(object : FilterOutputStream(sink.outputStream()) {
                override fun write(b: ByteArray, off: Int, len: Int) = out.write(b, off, len)
                override fun close() = flush()
            })
            f.open().use { input -> copy(input, encoder) }
            encoder.close()
            sink.writeUtf8("\"}")
        }
        sink.writeUtf8("]}")
    }

    /** La trame entière en texte : OkHttp n'envoie de trame texte que depuis une `String`. */
    fun render(message: String, clientMsgId: String, files: List<OutgoingFile>): String {
        val buffer = Buffer()
        write(buffer, message, clientMsgId, files)
        return buffer.readUtf8()
    }

    fun base64Length(bytes: Long): Long = 4 * ((bytes + 2) / 3)

    private fun head(message: String, clientMsgId: String): String =
        "{\"type\":\"${MikaProtocol.TYPE_CHAT}\",\"message\":${quote(message)},\"client_msg_id\":${quote(clientMsgId)}"

    private fun fileHead(f: OutgoingFile): String =
        "{\"name\":${quote(f.name)},\"type\":${quote(f.mime)},\"data\":\""

    private fun quote(s: String): String = Json.encodeToString(String.serializer(), s)

    private fun utf8(s: String): Int {
        var n = 0
        var i = 0
        while (i < s.length) {
            val c = s[i]
            n += when {
                c.code < 0x80 -> 1
                c.code < 0x800 -> 2
                Character.isHighSurrogate(c) && i + 1 < s.length && Character.isLowSurrogate(s[i + 1]) -> {
                    i++
                    4
                }
                else -> 3
            }
            i++
        }
        return n
    }

    private fun copy(input: InputStream, output: OutputStream) {
        val buf = ByteArray(CHUNK)
        while (true) {
            val n = input.read(buf)
            if (n < 0) break
            output.write(buf, 0, n)
        }
    }
}
