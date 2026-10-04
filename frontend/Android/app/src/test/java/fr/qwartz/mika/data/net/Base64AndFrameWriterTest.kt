package fr.qwartz.mika.data.net

import fr.qwartz.mika.core.MikaJson
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64
import kotlin.random.Random

class Base64AndFrameWriterTest {
    private val base64 = Regex("^[A-Za-z0-9+/]*={0,2}$")

    private fun file(name: String, bytes: ByteArray, mime: String = "application/octet-stream") =
        OutgoingFile(name, mime, bytes.size.toLong()) { bytes.inputStream() }

    private fun parse(frame: String) = MikaJson.parseToJsonElement(frame) as JsonObject

    @Test fun `le base64 n'a aucun retour à la ligne, quelle que soit la taille`() {
        val sizes = listOf(0, 1, 2, 3, 57, 58, 76, 77, 1000, 10 * 1024, 1024 * 1024 + 7)
        val random = Random(42)
        for (size in sizes) {
            val bytes = random.nextBytes(size)
            val frame = ChatFrameWriter.render("", "c1", listOf(file("f.bin", bytes)))
            val data = ((parse(frame)["attachments"] as JsonArray)[0] as JsonObject)["data"]!!.jsonPrimitive.content
            assertFalse("taille $size", data.contains('\n') || data.contains('\r'))
            assertTrue("taille $size", base64.matches(data))
            assertArrayEquals("taille $size", bytes, Base64.getDecoder().decode(data))
            assertEquals("taille $size", ChatFrameWriter.base64Length(size.toLong()), data.length.toLong())
        }
    }

    @Test fun `la taille annoncée est la taille écrite, au caractère près`() {
        val random = Random(7)
        val cases = listOf(
            Triple("salut", emptyList<OutgoingFile>(), "c1"),
            Triple("« Ça va ? » \"guillemets\" \\ \n nouvelle ligne \t tab 😀 漢字", emptyList(), "cé-2"),
            Triple("", listOf(file("photo été.jpg", random.nextBytes(4097), "image/jpeg")), "c3"),
            Triple("deux", listOf(file("a.txt", random.nextBytes(10)), file("b\"c.pdf", random.nextBytes(77))), "c4"),
        )
        for ((message, files, cid) in cases) {
            val frame = ChatFrameWriter.render(message, cid, files)
            assertEquals(frame, frame.toByteArray(Charsets.UTF_8).size.toLong(), ChatFrameWriter.frameBytes(message, cid, files))
        }
    }

    @Test fun `sans fichier, pas de clé attachments`() {
        assertEquals(
            """{"type":"chat","message":"salut","client_msg_id":"c1"}""",
            ChatFrameWriter.render("salut", "c1", emptyList()),
        )
    }

    @Test fun `une trame avec fichiers relit chaque champ échappé`() {
        val frame = parse(
            ChatFrameWriter.render(
                "regarde \"ça\"", "c9",
                listOf(file("a\nb.png", byteArrayOf(1, 2, 3), "image/png")),
            ),
        )
        assertEquals("chat", frame["type"]!!.jsonPrimitive.content)
        assertEquals("regarde \"ça\"", frame["message"]!!.jsonPrimitive.content)
        assertEquals("c9", frame["client_msg_id"]!!.jsonPrimitive.content)
        val att = (frame["attachments"] as JsonArray)[0] as JsonObject
        assertEquals("a\nb.png", att["name"]!!.jsonPrimitive.content)
        assertEquals("image/png", att["type"]!!.jsonPrimitive.content)
        assertEquals("AQID", att["data"]!!.jsonPrimitive.content)
    }
}
