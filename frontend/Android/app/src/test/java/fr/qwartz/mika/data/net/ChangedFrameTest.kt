package fr.qwartz.mika.data.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * La trame `changed` (ADR 0308, `docs/protocole-moi.md` § 2 bis), telle que `protocol.py::changed` l'écrit : chaque
 * sujet connu et ce qu'il nomme ; un sujet inconnu se tait ; une clé inconnue, une liste vide ou illisible valent
 * « tout le domaine » ; deux entrées d'un même sujet se réunissent ; les numéros de projet se lisent comme du texte.
 */
class ChangedFrameTest {
    private fun changed(json: String): Map<String, Set<String>?> {
        val frame = FrameCodec.decode(json)
        assertTrue("$json → $frame", frame is ServerFrame.Changed)
        return (frame as ServerFrame.Changed).changes
    }

    @Test fun `l'exemple du contrat se lit tel quel`() {
        val got = changed("""{"type": "changed", "changes": [{"topic": "mail", "boxes": ["pro"]}, {"topic": "mail.drafts"}, {"topic": "me"}]}""")
        assertEquals(mapOf("mail" to setOf("pro"), "mail.drafts" to null, "me" to null), got)
    }

    @Test fun `chaque sujet du contrat est connu, avec sa clé`() {
        assertEquals(
            listOf("me", "mail", "mail.drafts", "mail.work", "teams", "teams.replies", "teams.work", "phone",
                "phone.position", "phone.phones", "contacts", "agenda", "projects", "trips", "settings"),
            Topics.ALL,
        )
        val got = changed(
            """{"type":"changed","changes":[
                {"topic":"mail.work","refs":["pro:<a@x>"]},
                {"topic":"teams","conversations":["pro~19:marc"]},
                {"topic":"teams.work","conversations":["pro~19:marc"]},
                {"topic":"phone","conversations":["whatsapp|t1"]},
                {"topic":"agenda","calendars":["moi:user_1~mon-agenda"]},
                {"topic":"projects","projects":[12, "7"]}]}""",
        )
        assertEquals(setOf("moi:user_1~mon-agenda"), got["agenda"])
        assertEquals(setOf("pro:<a@x>"), got["mail.work"])
        assertEquals(setOf("pro~19:marc"), got["teams"])
        assertEquals(setOf("pro~19:marc"), got["teams.work"])
        assertEquals(setOf("whatsapp|t1"), got["phone"])
        // les numéros de projet, entiers ou textes, se lisent en texte
        assertEquals(setOf("12", "7"), got["projects"])
    }

    @Test fun `un sujet inconnu se tait, les autres passent`() {
        val got = changed("""{"type":"changed","changes":[{"topic":"meteo","days":["lundi"]},{"topic":"trips"},{"topic":7},{"nope":1},"cassé"]}""")
        assertEquals(mapOf("trips" to null), got)
        // aucun sujet connu : rien à dire, mais une trame lue
        assertEquals(emptyMap<String, Set<String>?>(), changed("""{"type":"changed","changes":[{"topic":"meteo"}]}"""))
    }

    @Test fun `une clé inconnue, une liste vide ou illisible - tout le domaine`() {
        // une clé que le contrat ne connaît pas pour ce sujet
        assertEquals(null, changed("""{"type":"changed","changes":[{"topic":"mail","boxes":["pro"],"folders":["INBOX"]}]}""")["mail"])
        assertEquals(null, changed("""{"type":"changed","changes":[{"topic":"teams","boxes":["pro"]}]}""")["teams"])
        // un sujet sans clé qui en porte une quand même
        assertEquals(null, changed("""{"type":"changed","changes":[{"topic":"me","boxes":["pro"]}]}""")["me"])
        // vide, pas une liste, un nom vide, un nom qui n'est ni texte ni entier
        for (raw in listOf("[]", "\"pro\"", "[\"\"]", "[null]", "[true]", "[1.5]", "[[\"pro\"]]")) {
            val got = changed("""{"type":"changed","changes":[{"topic":"mail","boxes":$raw}]}""")
            assertTrue("$raw : le sujet reste", "mail" in got)
            assertEquals("$raw : tout le domaine", null, got["mail"])
        }
    }

    @Test fun `deux entrées d'un même sujet se réunissent - tout le domaine l'emporte`() {
        assertEquals(
            setOf("pro", "perso"),
            changed("""{"type":"changed","changes":[{"topic":"mail","boxes":["pro"]},{"topic":"mail","boxes":["perso","pro"]}]}""")["mail"],
        )
        val whole = changed("""{"type":"changed","changes":[{"topic":"mail","boxes":["pro"]},{"topic":"mail"},{"topic":"mail","boxes":["perso"]}]}""")
        assertTrue("mail" in whole)
        assertEquals(null, whole["mail"])
    }

    @Test fun `sans liste de changements, la trame est inconnue - jamais fatale`() {
        assertEquals(ServerFrame.Unknown(MikaProtocol.TYPE_CHANGED), FrameCodec.decode("""{"type":"changed"}"""))
        assertEquals(ServerFrame.Unknown(MikaProtocol.TYPE_CHANGED), FrameCodec.decode("""{"type":"changed","changes":{"topic":"me"}}"""))
    }
}
