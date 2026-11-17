package fr.qwartz.mika.ui.chat

import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import fr.qwartz.mika.data.net.MessageNote
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

/** Ses notes de carte (ADR 0196), lues comme `frontendv2/src/map/notes.ts` et posées sous ses bulles. */
class MapNotesTest {
    private val raw = listOf(
        MessageNote("location", "rue Nationale, Lille", 1_790_601_490_000),
        MessageNote("look", "Dormir · près de Talloires", 1_790_601_500_000, "812"),
        MessageNote("map", "Trois campings au bord du lac", 1_790_601_510_000, "815"),
        MessageNote("trip", "Les Alpes en cinq jours", 1_790_601_520_000, "640"),
        MessageNote("meteo", "Soleil", 1, "9"), // une sorte inconnue
        MessageNote("trip", "", 0), // un voyage supprimé : vidé, rien à ouvrir
        MessageNote("look", "Oublié", 5), // pas de ref : rien à ouvrir
        MessageNote("look", "illisible", 5, "../../x"),
    )

    @Test fun `garde look, map et trip avec ce qu'ils ouvrent, ignore une sorte inconnue et une note vidée`() {
        val notes = MapNotes.read(raw)
        assertEquals(listOf("look" to "812", "map" to "815", "trip" to "640"), notes.map { it.kind to it.ref })
        assertEquals(MapNote("look", "Dormir · près de Talloires", 1_790_601_500_000, "812"), notes[0])
        assertEquals("trip:640", notes[2].id)
    }

    @Test fun `une liste vide ou absente ne montre rien, une redite une fois, six au plus, le texte sur une ligne`() {
        assertEquals(emptyList<MapNote>(), MapNotes.read(null))
        assertEquals(emptyList<MapNote>(), MapNotes.read(emptyList()))
        assertEquals(1, MapNotes.read(listOf(raw[1], raw[1])).size)
        val many = (1..9).map { MessageNote("look", "regard $it", 0, "$it") }
        assertEquals(MapNotes.MAX, MapNotes.read(many).size)
        val long = MapNotes.read(listOf(MessageNote("map", "  Le\n tour   du lac " + "x".repeat(400), -3, "7"))).single()
        assertTrue(long.text.startsWith("Le tour du lac x"))
        assertTrue(long.text.length <= MapNotes.MAX_TEXT)
        assertEquals(0L, long.at) // un instant illisible vaut 0
    }

    @Test fun `sous sa dernière bulle, une miniature par note, la bulle 📍 ne change pas`() {
        val zone = ZoneId.of("Europe/Paris")
        val now = LocalDateTime.of(2026, 11, 17, 14, 18).atZone(zone).toInstant().toEpochMilli()
        val asked = StoredMessage("un road trip ?", Sender.USER, now, id = 1, localId = 1)
        val reply = StoredMessage("première version\n\nj'ai ajouté quatre arrêts", Sender.MIKA, now, id = 2, localId = 2, notes = raw)
        val items = ChatItems.build(listOf(asked, reply), nowMs = now, zone = zone).filter { it !is ChatItem.DateSeparator }
        assertEquals(
            listOf("Bubble", "Looked", "Bubble", "Bubble", "MapCard", "MapCard", "MapCard"),
            items.map { it::class.simpleName },
        )
        val cards = items.filterIsInstance<ChatItem.MapCard>()
        assertEquals(listOf("look", "map", "trip"), cards.map { it.note.kind })
        // elle attend sa dernière bulle ; le message qui la porte lui donne sa place
        assertTrue(cards.all { it.after == "m2.1" && it.owner == "m2" })
        assertEquals(items.size, items.map { it.key }.toSet().size)

        // une pensée à voix haute n'en montre pas ; la personne non plus
        val thought = StoredMessage("hmm", Sender.MIKA, now, after = 2, inner = true, notes = raw)
        val mine = StoredMessage("tiens", Sender.USER, now, id = 3, localId = 3, notes = raw)
        assertTrue(ChatItems.build(listOf(thought, mine), nowMs = now, zone = zone).none { it is ChatItem.MapCard })
    }
}
