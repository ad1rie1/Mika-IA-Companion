package fr.qwartz.mika.data.net

import fr.qwartz.mika.core.Clock
import fr.qwartz.mika.core.MikaJson
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.IOException

/**
 * Un faux transport qui ne fait rien tout seul : chaque test joue le réseau — l'ouverture, une trame
 * reçue, la fermeture annoncée, ou la mort silencieuse (plus rien ne passe, aucun événement), celle
 * d'un téléphone qui dormait ou d'un mandataire qui a coupé.
 */
class FakeWsTransport : WsTransport {
    val sockets = mutableListOf<FakeWsSocket>()

    override fun open(url: String, headers: Map<String, String>, listener: WsListener): WsSocket =
        FakeWsSocket(url, headers, listener).also { sockets += it }
}

class FakeWsSocket(
    val url: String,
    val headers: Map<String, String>,
    private val listener: WsListener,
) : WsSocket {
    enum class St { CONNECTING, OPEN, CLOSED }

    var state = St.CONNECTING
    val sent = mutableListOf<String>()
    var closeCalls = 0
    /** Après ce nombre d'envois, la socket meurt sans prévenir (0 = jamais). */
    var dieAfterSends = 0
    /** Ce que la file du transport porte encore (OkHttp `queueSize()`). */
    var queued = 0L

    override fun send(text: String): Boolean {
        if (state != St.OPEN) return false
        sent += text
        if (dieAfterSends > 0 && sent.size >= dieAfterSends) state = St.CLOSED
        return true
    }

    override fun queueSize(): Long = queued

    override fun close(code: Int, reason: String?): Boolean {
        closeCalls++
        state = St.CLOSED
        return true
    }

    override fun cancel() {
        closeCalls++
        state = St.CLOSED
    }

    // ── Le réseau, joué à la main ──
    fun open() {
        state = St.OPEN
        listener.onOpen()
    }

    fun receive(json: String) = listener.onMessage(json)

    /** Fermeture annoncée. */
    fun fail(code: Int = 1006) {
        state = St.CLOSED
        listener.onClosed(code, "")
    }

    /** Poignée de main refusée (401, 403). */
    fun failHandshake(httpCode: Int) {
        state = St.CLOSED
        listener.onFailure(IOException("HTTP $httpCode"), httpCode)
    }

    /** Mort silencieuse : plus rien ne passe, aucun événement. */
    fun die() {
        state = St.CLOSED
    }

    fun frames(): List<JsonObject> = sent.map { MikaJson.parseToJsonElement(it) as JsonObject }
    fun types(): List<String> = frames().map { it["type"]!!.jsonPrimitive.content }
}

/** Le temps des tests : celui de l'ordonnanceur, plus des sauts qui ne déclenchent aucune minuterie. */
@OptIn(ExperimentalCoroutinesApi::class)
class FakeClock(private val scheduler: TestCoroutineScheduler) : Clock {
    private var offset = 0L
    override fun elapsedMs(): Long = scheduler.currentTime + offset
    override fun wallMs(): Long = WALL_BASE + elapsedMs()

    /** Comme `vi.setSystemTime(Date.now() + ms)` : l'horloge saute, les minuteries ne bougent pas. */
    fun jump(ms: Long) {
        offset += ms
    }

    companion object {
        const val WALL_BASE = 1_759_572_000_000L
    }
}
