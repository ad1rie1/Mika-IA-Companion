package fr.qwartz.mika.data.net

/**
 * Le transport WebSocket, réduit à ce dont [MikaSocket] a besoin — de quoi lui substituer un faux
 * dans les tests (le navigateur, joué à la main) et OkHttp dans l'app.
 */
interface WsTransport {
    fun open(url: String, headers: Map<String, String>, listener: WsListener): WsSocket
}

interface WsSocket {
    /** `false` quand la socket n'accepte plus rien (fermée, ou en train de se fermer). */
    fun send(text: String): Boolean
    /** Octets mis en file par le transport et pas encore partis (OkHttp ferme au-delà de 16 Mio). */
    fun queueSize(): Long
    fun close(code: Int, reason: String?): Boolean
    /** Abandonner sans politesse : une socket qu'on croit morte ne mérite pas d'attendre sa fermeture. */
    fun cancel()
}

/** Les événements d'une socket, depuis le fil du transport : [MikaSocket] les rapatrie sur le sien. */
interface WsListener {
    fun onOpen()
    fun onMessage(text: String)
    /** La socket s'est fermée (appelé une fois, que la fermeture vienne du serveur ou du réseau). */
    fun onClosed(code: Int, reason: String)
    /** Échec ; [httpCode] est le statut de la poignée de main quand elle a été refusée (401, 403…). */
    fun onFailure(error: Throwable, httpCode: Int?)
}
