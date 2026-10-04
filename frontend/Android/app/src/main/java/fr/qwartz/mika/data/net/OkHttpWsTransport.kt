package fr.qwartz.mika.data.net

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.util.concurrent.atomic.AtomicBoolean

/**
 * [WsTransport] sur OkHttp. Aucun en-tête `Origin` n'est posé (OkHttp n'en pose pas) : c'est ce qui
 * fait lire le jeton par le serveur — avec une `Origin`, seule une session de navigateur compte.
 */
class OkHttpWsTransport(private val client: OkHttpClient) : WsTransport {

    override fun open(url: String, headers: Map<String, String>, listener: WsListener): WsSocket {
        val request = Request.Builder().url(url).apply {
            for ((name, value) in headers) header(name, value)
        }.build()
        // Une seule fin annoncée : OkHttp peut dire `onClosing` puis `onClosed`, ou échouer pendant.
        val ended = AtomicBoolean(false)
        val ws = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) = listener.onOpen()

            override fun onMessage(webSocket: WebSocket, text: String) = listener.onMessage(text)

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) = listener.onMessage(bytes.utf8())

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                // Le serveur ferme (4401 compris) : on répond, et on l'annonce sans attendre `onClosed`.
                webSocket.close(MikaProtocol.CLOSE_NORMAL, null)
                if (ended.compareAndSet(false, true)) listener.onClosed(code, reason)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (ended.compareAndSet(false, true)) listener.onClosed(code, reason)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                val code = response?.code
                response?.close()
                if (ended.compareAndSet(false, true)) listener.onFailure(t, code)
            }
        })
        return object : WsSocket {
            override fun send(text: String): Boolean = ws.send(text)
            override fun queueSize(): Long = ws.queueSize()
            override fun close(code: Int, reason: String?): Boolean = ws.close(code, reason)
            override fun cancel() = ws.cancel()
        }
    }
}
