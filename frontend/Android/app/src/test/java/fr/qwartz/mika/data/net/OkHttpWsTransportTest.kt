package fr.qwartz.mika.data.net

import fr.qwartz.mika.core.Clock
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** Le vrai OkHttp contre un vrai serveur local : en-têtes, trames, 4401, poignée de main refusée. */
class OkHttpWsTransportTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().readTimeout(0, TimeUnit.MILLISECONDS).build()

    @Before fun setUp() = server.start()

    @After fun tearDown() {
        server.close()
        client.dispatcher.executorService.shutdown()
        client.connectionPool.evictAll()
    }

    private class Recorder : WsListener {
        val events = LinkedBlockingQueue<String>()
        override fun onOpen() { events += "open" }
        override fun onMessage(text: String) { events += "msg:$text" }
        override fun onClosed(code: Int, reason: String) { events += "closed:$code" }
        override fun onFailure(error: Throwable, httpCode: Int?) { events += "failure:$httpCode" }
        fun next(): String? = events.poll(5, TimeUnit.SECONDS)
    }

    private fun wsUrl() = "ws" + server.url("/ws").toString().removePrefix("http")

    private val headers = mapOf(
        MikaProtocol.HEADER_AUTHORIZATION to "Bearer mw_x",
        MikaProtocol.HEADER_PRESENCE to MikaProtocol.PRESENCE_AWAY,
        MikaProtocol.HEADER_USER_AGENT to "Mika-Test/1",
    )

    @Test fun `vrais en-têtes, jamais d'Origin, une trame dans chaque sens`() {
        val received = LinkedBlockingQueue<String>()
        server.enqueue(
            MockResponse.Builder().webSocketUpgrade(object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    webSocket.send("""{"type":"pong","t":1}""")
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    received += text
                }

                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    webSocket.close(code, null)
                }
            }).build(),
        )
        val rec = Recorder()
        val socket = OkHttpWsTransport(client).open(wsUrl(), headers, rec)
        assertEquals("open", rec.next())
        assertEquals("""msg:{"type":"pong","t":1}""", rec.next())
        assertTrue(socket.send("""{"type":"ping","t":2}"""))
        assertEquals("""{"type":"ping","t":2}""", received.poll(5, TimeUnit.SECONDS))

        val request = server.takeRequest(5, TimeUnit.SECONDS)
        assertNotNull(request)
        assertEquals("Bearer mw_x", request!!.headers["Authorization"])
        assertEquals("away", request.headers["X-Mika-Presence"])
        assertEquals("Mika-Test/1", request.headers["User-Agent"])
        assertNull(request.headers["Origin"])
        socket.close(MikaProtocol.CLOSE_NORMAL, null)
        assertEquals("closed:1000", rec.next())
    }

    @Test fun `un 4401 du serveur est annoncé une seule fois`() {
        server.enqueue(
            MockResponse.Builder().webSocketUpgrade(object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    webSocket.close(MikaProtocol.CLOSE_UNAUTHORIZED, "session révoquée")
                }
            }).build(),
        )
        val rec = Recorder()
        OkHttpWsTransport(client).open(wsUrl(), headers, rec)
        assertEquals("open", rec.next())
        assertEquals("closed:4401", rec.next())
        assertNull(rec.events.poll(500, TimeUnit.MILLISECONDS))
    }

    @Test fun `une poignée de main refusée en 403 arrive comme un échec avec son statut`() {
        server.enqueue(MockResponse.Builder().code(403).build())
        val rec = Recorder()
        OkHttpWsTransport(client).open(wsUrl(), headers, rec)
        assertEquals("failure:403", rec.next())
    }

    @Test fun `avec MikaSocket — une poignée de main en 403 rend la connexion refusée`() {
        server.enqueue(MockResponse.Builder().code(403).build())
        val posted = LinkedBlockingQueue<() -> Unit>()
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        val clock = object : Clock {
            override fun wallMs() = System.currentTimeMillis()
            override fun elapsedMs() = System.nanoTime() / 1_000_000
        }
        val socket = MikaSocket(
            transport = OkHttpWsTransport(client),
            scope = scope,
            clock = clock,
            listener = object : MikaSocket.Listener {
                override fun onFrame(frame: ServerFrame) = Unit
            },
            cursor = { 0 },
            post = { posted += it },
        )
        socket.start(MikaSocket.Endpoint(wsUrl(), "mw_x", "Mika-Test/1"))
        // Les rappels d'OkHttp sont rapatriés : on joue ici le contexte sérialisé de l'app.
        requireNotNull(posted.poll(5, TimeUnit.SECONDS)).invoke()
        assertEquals(LinkState.Refused(403), socket.state.value)
        assertTrue(socket.isTerminal)
        scope.cancel()
    }
}
