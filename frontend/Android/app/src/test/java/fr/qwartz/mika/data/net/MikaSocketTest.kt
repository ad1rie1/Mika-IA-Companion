package fr.qwartz.mika.data.net

import fr.qwartz.mika.data.net.MikaSocket.ConnectionStatus
import fr.qwartz.mika.data.net.MikaSocket.ConnectionStatus.Connected
import fr.qwartz.mika.data.net.MikaSocket.ConnectionStatus.Disconnected
import fr.qwartz.mika.data.net.MikaSocket.ConnectionStatus.Reconnecting
import fr.qwartz.mika.data.net.MikaSocket.ConnectionStatus.Unauthorized
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.coroutines.EmptyCoroutineContext

/**
 * Portage de `frontend/Web/src/network/__tests__/WebSocketClient.test.ts`, contre un faux transport
 * ([FakeWsTransport]) et l'horloge virtuelle des coroutines. Écarts : « focus » et « online »
 * deviennent `ensureAlive()` (retour au premier plan) ; il n'y a plus d'`identify` (le jeton lie la
 * session) ; un 4401 refuse ce qui attendait au lieu de le taire. Les noms gardent le français, les
 * « : » devenus « — » (interdits dans un nom de méthode).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MikaSocketTest {

    private class Harness(scope: TestScope, var cursor: Long = 0) {
        private val scheduler = scope.testScheduler
        val transport = FakeWsTransport()
        val clock = FakeClock(scheduler)
        val statuses = mutableListOf<ConnectionStatus>()
        val acks = mutableListOf<ServerFrame.Ack>()
        val frames = mutableListOf<ServerFrame>()
        var throwOnFrame = false
        var throwOnStatus = false
        val endpoint = MikaSocket.Endpoint("ws://test/ws", "mw_secret", "Mika-Test/1")
        val socket = MikaSocket(
            transport = transport,
            scope = scope.backgroundScope,
            clock = clock,
            listener = object : MikaSocket.Listener {
                override fun onFrame(frame: ServerFrame) {
                    if (frame is ServerFrame.Ack) acks += frame
                    frames += frame
                    if (throwOnFrame) error("boom")
                }

                override fun onStatus(status: ConnectionStatus) {
                    statuses += status
                    if (throwOnStatus) error("boom")
                }
            },
            cursor = { cursor },
            io = EmptyCoroutineContext,
            post = { it() },
        )

        fun connect() = socket.start(endpoint)
        fun sockets() = transport.sockets
        fun last() = transport.sockets.last()
        fun advance(ms: Long) {
            scheduler.advanceTimeBy(ms)
            scheduler.runCurrent()
        }

        fun chat(text: String, cid: String): Boolean = socket.offer(
            MikaSocket.OutboundChat(cid, ChatFrameWriter.frameBytes(text, cid, emptyList())) {
                ChatFrameWriter.render(text, cid, emptyList())
            },
        )

        fun ack(cid: String, status: String) = ServerFrame.Ack(clientMsgId = cid, status = status)
    }

    private fun test(cursor: Long = 0, body: Harness.() -> Unit) = runTest {
        Harness(this, cursor).body()
    }

    // ── Reconnexion ──────────────────────────────────────────────────────────────────────

    @Test fun `backoff exponentiel ×1,5 depuis 1 s, borné à 30 s, remis à 1 s par une ouverture`() = test {
        connect()
        val announced = mutableListOf<Long>()
        repeat(12) {
            last().fail()
            val s = statuses.last() as Disconnected
            announced += s.retryInMs
            // Le socket suivant n'existe qu'à l'échéance du délai annoncé.
            val before = sockets().size
            advance(s.retryInMs - 2)
            assertEquals(before, sockets().size)
            advance(2)
            assertEquals(before + 1, sockets().size)
            assertEquals(Reconnecting, statuses.last())
        }
        assertEquals(listOf(1000L, 1500L, 2250L, 3375L), announced.take(4))
        assertEquals(30000L, announced.max())
        assertEquals(listOf(30000L, 30000L), announced.takeLast(2))

        // Une ouverture réussie repart du délai initial.
        last().open()
        assertEquals(Connected, statuses.last())
        last().fail()
        assertEquals(Disconnected(1000), statuses.last())
    }

    @Test fun `une fermeture n'arme qu'un seul timer, même annoncée deux fois`() = test {
        connect()
        val first = last()
        first.fail()
        first.fail()
        advance(60000)
        assertEquals(2, sockets().size)
    }

    @Test fun `reconnectNow (focus sur un socket mort) — un seul nouveau socket, l'ancien fermé et détaché`() = test {
        connect()
        val first = last()
        first.open()
        first.die()

        socket.ensureAlive()
        assertEquals(2, sockets().size)
        assertEquals(1, first.closeCalls)
        // Détaché : un événement tardif de l'ancien ne relance rien.
        val seen = statuses.size
        first.fail()
        assertEquals(seen, statuses.size)
        // « reconnecting » suit l'ouverture du nouveau socket, « connected » vient après.
        assertEquals(Reconnecting, statuses.last())
        last().open()
        assertEquals(Connected, statuses.last())
        // Rien d'autre ne se déclenche derrière (sous les 50 s du chien de garde).
        advance(45000)
        assertEquals(2, sockets().size)
    }

    @Test fun `reconnectNow annule le backoff en cours — pas de troisième socket à son échéance`() = test {
        connect()
        last().fail() // attente de 1 s armée
        socket.ensureAlive() // reconnexion immédiate
        assertEquals(2, sockets().size)
        advance(60000)
        assertEquals(2, sockets().size)
    }

    @Test fun `un socket encore en CONNECTING n'est pas remplacé`() = test {
        connect()
        socket.ensureAlive()
        socket.ensureAlive()
        assertEquals(1, sockets().size)
    }

    @Test fun `le passage en arrière-plan ne vérifie rien, le retour au premier plan si`() = test {
        connect()
        last().open()
        last().die()
        socket.setPresence(false)
        assertEquals(1, sockets().size)
        socket.setPresence(true)
        socket.ensureAlive()
        assertEquals(2, sockets().size)
    }

    @Test fun `sur un socket OPEN, un réveil envoie un ping et laisse le chien de garde juger`() = test {
        connect()
        last().open()
        val before = last().sent.size
        socket.ensureAlive()
        assertEquals(1, sockets().size)
        assertEquals(listOf("ping"), last().types().drop(before))
    }

    @Test fun `silence passé 50 s SANS trame en vol — un réveil pingue seulement`() = test {
        connect()
        last().open()
        clock.jump(60000)
        socket.ensureAlive()
        assertEquals(1, sockets().size)
        assertEquals("ping", last().types().last())
    }

    @Test fun `silence passé 50 s AVEC un message sans ack — un réveil reconnecte tout de suite`() = test {
        connect()
        last().open()
        assertTrue(chat("t'es là ?", "c1"))
        clock.jump(60000)
        socket.ensureAlive()
        assertEquals(2, sockets().size)
        // Et le message reparti sur le nouveau socket, après le sync.
        last().open()
        assertEquals(listOf("sync", "chat"), last().types())
    }

    // ── Battement ────────────────────────────────────────────────────────────────────────

    @Test fun `un ping toutes les 20 s, portant l'heure d'envoi`() = test {
        connect()
        last().open()
        val base = last().sent.size
        advance(19999)
        assertEquals(base, last().sent.size)
        advance(1)
        assertEquals(listOf("ping"), last().types().drop(base))
        assertEquals(clock.wallMs(), last().frames().last()["t"]!!.jsonPrimitive.long)
        advance(20000)
        assertEquals(listOf("ping", "ping"), last().types().drop(base))
    }

    @Test fun `50 s sans aucune trame reçue — reconnexion forcée au tick suivant`() = test {
        connect()
        val first = last()
        first.open()
        advance(40000)
        assertEquals(1, sockets().size)
        assertEquals(2, first.types().count { it == "ping" })
        advance(20000) // 60 s de silence au tick
        assertEquals(2, sockets().size)
        assertEquals(1, first.closeCalls)
        // Le nouveau socket repart avec son propre battement.
        last().open()
        advance(20000)
        assertTrue(last().types().contains("ping"))
    }

    @Test fun `n'importe quelle trame reçue — même un pong — remet le compteur de silence à zéro`() = test {
        connect()
        val first = last()
        first.open()
        advance(40000)
        first.receive("""{"type":"pong","t":0}""")
        advance(40000) // 80 s après l'ouverture, 40 s après le pong
        assertEquals(1, sockets().size)
        advance(20000) // 60 s après le pong
        assertEquals(2, sockets().size)
    }

    @Test fun `le keepalive s'arrête avec le socket`() = test {
        connect()
        val first = last()
        first.open()
        first.fail()
        val sentAtClose = first.sent.size
        advance(500) // avant la reconnexion (1 s)
        assertEquals(sentAtClose, first.sent.size)
        assertEquals(1, socket.activeTimers()) // la seule minuterie restante est l'attente
    }

    @Test fun `un battement très en retard pingue d'abord et juge dix secondes plus tard`() = test {
        connect()
        last().open()
        clock.jump(120_000) // le processeur dormait : l'horloge a avancé, pas les minuteries
        advance(20000)
        assertEquals(1, sockets().size)
        assertEquals("ping", last().types().last())
        advance(10000) // aucun pong depuis le ping : morte
        assertEquals(2, sockets().size)
    }

    @Test fun `un battement en retard suivi d'un pong ne reconnecte pas`() = test {
        connect()
        last().open()
        clock.jump(120_000)
        advance(20000)
        advance(3000)
        last().receive("""{"type":"pong","t":1}""")
        advance(7000)
        assertEquals(1, sockets().size)
    }

    // ── File d'envoi et accusés ──────────────────────────────────────────────────────────

    @Test fun `à l'ouverture — sync sur le curseur, puis la file dans l'ordre, puis « connected »`() = test(cursor = 42) {
        assertFalse(chat("un", "c1"))
        assertFalse(chat("deux", "c2"))
        connect()
        assertEquals(emptyList<String>(), last().sent)
        last().open()
        assertEquals(
            listOf(
                """{"type":"sync","after_id":42}""",
                """{"type":"chat","message":"un","client_msg_id":"c1"}""",
                """{"type":"chat","message":"deux","client_msg_id":"c2"}""",
            ),
            last().sent,
        )
        assertEquals(listOf(Connected), statuses)
    }

    @Test fun `socket ouvert — envoi immédiat — l'ack purge le suivi, rien n'est rejoué ensuite`() = test {
        connect()
        last().open()
        assertTrue(chat("salut", "c1"))
        assertEquals("chat", last().types().last())
        last().receive("""{"type":"ack","client_msg_id":"c1","status":"accepted"}""")
        assertEquals(listOf(ack("c1", "accepted")), acks)
        last().fail()
        advance(1000)
        last().open()
        assertEquals(listOf("sync"), last().types())
    }

    @Test fun `un message parti sans ack revient en tête, devant ce qui a été tapé pendant la coupure`() = test {
        connect()
        last().open()
        chat("A", "a")
        last().fail()
        assertFalse(chat("B", "b"))
        advance(1000)
        last().open()
        assertEquals(
            listOf("A", "B"),
            last().frames().filter { it["type"]!!.jsonPrimitive.content == "chat" }.map { it["message"]!!.jsonPrimitive.content },
        )
    }

    @Test fun `les trames de contrôle ne sont jamais mises en file`() = test(cursor = 5) {
        socket.requestSync()
        socket.setPresence(true)
        socket.setPresence(false)
        connect()
        last().open()
        assertEquals(listOf("sync"), last().types())
    }

    @Test fun `MAX_OUTBOX = 20 — la 21e évince la plus ancienne, refusée à voix haute`() = test {
        for (i in 1..21) chat("m$i", "c$i")
        assertEquals(listOf(ack("c1", "send_abandoned")), acks)
        connect()
        last().open()
        val sent = last().frames().filter { it["type"]!!.jsonPrimitive.content == "chat" }
            .map { it["client_msg_id"]!!.jsonPrimitive.content }
        assertEquals(20, sent.size)
        assertEquals("c2", sent.first())
        assertEquals("c21", sent.last())
    }

    @Test fun `une trame au-delà de la taille du transport est refusée, jamais mise en file`() = test {
        val huge = MikaSocket.OutboundChat("big", MikaProtocol.MAX_FRAME_BYTES + 1) { error("jamais écrite") }
        assertFalse(socket.offer(huge))
        assertEquals(listOf(ack("big", "frame_too_large")), acks)
        connect()
        last().open()
        assertEquals(listOf("sync"), last().types())
    }

    @Test fun `une trame que 5 réouvertures n'ont pas réussi à faire partir est abandonnée`() = test {
        chat("tenace", "t")
        chat("suivante", "s")
        connect()
        // Chaque socket meurt sur le `sync` (son premier envoi) : la file est retrouvée morte au moment
        // de la rejouer, et chaque réouverture compte une tentative.
        for (attempt in 1..6) {
            val s = last()
            s.dieAfterSends = 1
            s.open()
            assertEquals(listOf("sync"), s.types())
            if (attempt < 6) {
                assertEquals(emptyList<ServerFrame.Ack>(), acks)
                s.fail()
                advance(30000)
            }
        }
        assertEquals(listOf(ack("t", "send_abandoned"), ack("s", "send_abandoned")), acks)
    }

    @Test fun `une trame impossible à écrire (fichier disparu) est refusée, la suivante part`() = test {
        connect()
        last().open()
        socket.offer(MikaSocket.OutboundChat("gone", 10) { throw java.io.FileNotFoundException("photo.jpg") })
        assertTrue(chat("après", "c2"))
        assertEquals(listOf(ack("gone", "files_missing")), acks)
        assertEquals(listOf("sync", "chat"), last().types())
    }

    @Test fun `le vidage attend la place dans la file d'OkHttp`() = test {
        connect()
        last().open()
        last().queued = MikaProtocol.MAX_FRAME_BYTES - 10
        assertTrue(chat("patience", "c1"))
        assertEquals(listOf("sync"), last().types())
        advance(500)
        assertEquals(listOf("sync"), last().types())
        last().queued = 0
        advance(100)
        assertEquals(listOf("sync", "chat"), last().types())
    }

    // ── Refus terminaux ──────────────────────────────────────────────────────────────────

    @Test fun `4401 — ne réessaie plus, refuse la file, annonce « unauthorized », ignore les réveils`() = test {
        chat("avant", "c0")
        connect()
        last().fail(4401)
        assertEquals(listOf<ConnectionStatus>(Unauthorized), statuses)
        assertEquals(listOf(ack("c0", "unauthorized")), acks)
        assertEquals(LinkState.SessionExpired, socket.state.value)
        advance(120000)
        socket.ensureAlive()
        socket.onNetworkChanged(true)
        assertEquals(1, sockets().size)
        connect()
        assertEquals(1, sockets().size)
    }

    @Test fun `un envoi APRÈS le 4401 est refusé à voix haute, pas mis en file pour toujours`() = test {
        connect()
        last().fail(4401)
        assertFalse(chat("après", "c1"))
        assertEquals(listOf(ack("c1", "unauthorized")), acks)
    }

    @Test fun `un 4401 sur une socket déjà ouverte refuse aussi ce qui était en vol`() = test {
        connect()
        last().open()
        chat("en vol", "c1")
        last().fail(4401)
        assertEquals(listOf(ack("c1", "unauthorized")), acks)
    }

    @Test fun `1008 et une poignée de main en 401 ou 403 sont terminaux aussi`() = test {
        connect()
        last().fail(1008)
        assertEquals(LinkState.Refused(1008), socket.state.value)
        assertEquals(ConnectionStatus.Refused(1008), statuses.last())
        assertFalse(chat("x", "c1"))
        assertEquals(listOf(ack("c1", "connection_refused")), acks)
        advance(120000)
        assertEquals(1, sockets().size)

        socket.retry()
        assertEquals(2, sockets().size)
        last().failHandshake(403)
        assertEquals(LinkState.Refused(403), socket.state.value)

        socket.retry()
        last().failHandshake(401)
        assertEquals(LinkState.SessionExpired, socket.state.value)
        assertEquals(Unauthorized, statuses.last())
        advance(120000)
        assertEquals(3, sockets().size)
    }

    @Test fun `un nouveau jeton lève le refus terminal`() = test {
        connect()
        last().fail(4401)
        socket.start(endpoint.copy(token = "mw_neuf"))
        assertEquals(2, sockets().size)
        assertEquals("Bearer mw_neuf", last().headers[MikaProtocol.HEADER_AUTHORIZATION])
    }

    // ── Présence, en-têtes, réseau ───────────────────────────────────────────────────────

    @Test fun `en-têtes — un jeton, la présence, jamais d'Origin`() = test {
        connect()
        val h = last().headers
        assertEquals("Bearer mw_secret", h["Authorization"])
        assertEquals("away", h["X-Mika-Presence"])
        assertEquals("Mika-Test/1", h["User-Agent"])
        assertNull(h.keys.firstOrNull { it.equals("origin", ignoreCase = true) })
        assertEquals("ws://test/ws", last().url)
        assertFalse(endpoint.toString().contains("mw_secret"))
    }

    @Test fun `l'en-tête de présence suit le premier plan au moment de la connexion`() = test {
        socket.setPresence(true)
        connect()
        assertEquals("here", last().headers["X-Mika-Presence"])
        socket.setPresence(false)
        last().fail()
        advance(1000)
        assertEquals("away", last().headers["X-Mika-Presence"])
    }

    @Test fun `présente — pas de sync sans curseur — absente — toujours un sync`() = test {
        socket.setPresence(true)
        connect()
        last().open()
        assertEquals(emptyList<String>(), last().types())
        cursor = 7
        last().fail()
        advance(1000)
        last().open()
        assertEquals(listOf("""{"type":"sync","after_id":7}"""), last().sent)
        cursor = 0
        socket.setPresence(false)
        last().fail()
        advance(1000)
        last().open()
        assertEquals(listOf("""{"type":"sync","after_id":0}"""), last().sent)
    }

    @Test fun `la présence change pendant l'ouverture — annoncée une fois ouverte, après la file`() = test {
        socket.setPresence(true)
        chat("hop", "c1")
        connect()
        socket.setPresence(false) // en cours d'ouverture : rien n'est envoyé ni mis en file
        last().open()
        // Présente à l'en-tête et sans curseur : le fil initial arrive seul, pas de `sync`.
        assertEquals(listOf("chat", "presence"), last().types())
        assertEquals(false, last().frames().last()["here"]!!.jsonPrimitive.content.toBooleanStrict())
        socket.setPresence(true)
        assertEquals("""{"type":"presence","here":true}""", last().sent.last())
    }

    @Test fun `un changement de réseau reconnecte tout de suite, même ouverte`() = test {
        connect()
        val first = last()
        first.open()
        socket.onNetworkChanged(true)
        assertEquals(2, sockets().size)
        assertEquals(1, first.closeCalls)
    }

    @Test fun `sans réseau, l'attente ne dépense aucun essai`() = test {
        connect()
        last().fail()
        socket.onNetworkChanged(false)
        advance(1000)
        assertEquals(1, sockets().size)
        assertEquals(LinkState.NoNetwork, socket.state.value)
        assertEquals(ConnectionStatus.WaitingNetwork, statuses.last())
        socket.onNetworkChanged(true)
        assertEquals(2, sockets().size)
        assertEquals(LinkState.Connecting, socket.state.value)
    }

    @Test fun `une socket remplacée ne parle plus (numéro de génération)`() = test {
        connect()
        val first = last()
        first.open()
        socket.onNetworkChanged(true)
        val before = frames.size
        first.receive("""{"type":"speech","text":"fantôme"}""")
        first.open()
        first.fail()
        assertEquals(before, frames.size)
        assertEquals(Reconnecting, statuses.last())
        assertEquals(LinkState.Connecting, socket.state.value)
    }

    @Test fun `stop ferme proprement et garde la file — start rouvre et rejoue`() = test {
        socket.setPresence(true)
        connect()
        last().open()
        chat("pas encore accusé", "c1")
        socket.setPresence(false)
        val first = last()
        socket.stop()
        assertEquals(1, first.closeCalls)
        assertEquals("presence", first.types().last())
        assertEquals(LinkState.Idle, socket.state.value)
        advance(60000)
        assertEquals(1, sockets().size)
        connect()
        last().open()
        assertEquals(listOf("sync", "chat"), last().types())
    }

    @Test fun `reset oublie tout sans rien annoncer`() = test {
        connect()
        last().open()
        chat("x", "c1")
        socket.reset()
        assertEquals(emptyList<ServerFrame.Ack>(), acks)
        connect()
        last().open()
        assertEquals(listOf("sync"), last().types())
    }

    // ── Diffusion ────────────────────────────────────────────────────────────────────────

    @Test fun `un abonné qui lève n'empêche ni les trames suivantes ni la relance`() = test {
        throwOnFrame = true
        throwOnStatus = true
        connect()
        last().open()
        last().receive("""{"type":"speech","text":"coucou"}""")
        last().receive("""{"type":"speech","text":"encore"}""")
        assertEquals(listOf("coucou", "encore"), frames.filterIsInstance<ServerFrame.Speech>().map { it.text })
        last().fail()
        advance(1000)
        assertEquals(2, sockets().size)
    }

    @Test fun `une trame illisible ou sans type est ignorée mais compte comme signe de vie`() = test {
        connect()
        last().open()
        advance(40000)
        last().receive("{pas du json")
        advance(40000)
        assertEquals(1, sockets().size)
        assertTrue(frames.isEmpty())
    }
}
