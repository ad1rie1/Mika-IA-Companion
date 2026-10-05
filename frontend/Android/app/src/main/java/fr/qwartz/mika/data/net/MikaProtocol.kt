package fr.qwartz.mika.data.net

/**
 * Toutes les constantes du protocole, chacune avec sa source : quand le serveur ou le client web
 * change une limite, c'est ici seulement qu'on la suit.
 */
object MikaProtocol {
    // ── Limites du serveur (backendv2/src/mika/adapters/web/protocol.py) ──
    const val MAX_MESSAGE_CHARS = 2000
    const val MAX_ATTACHMENTS = 5
    const val MAX_FILE_BYTES = 5L * 1024 * 1024
    const val MAX_CLIENT_MSG_ID = 64

    /** Le compteur de caractères ne se montre qu'à l'approche de la limite (ChatOverlay.ts). */
    const val COUNTER_FROM = 1800

    // ── Transport (OkHttp RealWebSocket) ──
    /**
     * OkHttp ferme la socket (1001) quand sa file d'envoi dépasse 16 Mio : une trame est donc
     * bornée à 15 Mio, soit ~11 Mio de fichiers une fois en base64. Le serveur, lui, accepte plus.
     */
    const val MAX_FRAME_BYTES = 15L * 1024 * 1024
    /** Au-delà, l'écran demande d'envoyer le reste à part (4/3 du base64 et l'enveloppe JSON). */
    const val MAX_FILES_BYTES_PER_MESSAGE = 11L * 1024 * 1024
    /** Le vidage de la file attend que la file d'OkHttp fasse de la place (sondée toutes les 100 ms). */
    const val QUEUE_POLL_MS = 100L

    // ── File d'envoi (WebSocketClient.ts : MAX_OUTBOX, MAX_OUTBOX_CHARS, MAX_OUTBOX_ATTEMPTS) ──
    const val MAX_OUTBOX = 20
    const val MAX_OUTBOX_BYTES = 48L * 1024 * 1024
    const val MAX_OUTBOX_ATTEMPTS = 5

    // ── Maintien de connexion (WebSocketClient.ts) ──
    const val HEARTBEAT_INTERVAL_MS = 20_000L
    /** Deux pongs manqués, pas un aller-retour lent. */
    const val HEARTBEAT_TIMEOUT_MS = 50_000L
    /**
     * Un battement en retard de plus de 40 s : le processeur dormait (Doze). Le silence mesuré ne
     * prouve alors rien ; on pingue d'abord, et on juge 10 s plus tard.
     */
    const val LATE_TICK_MS = 40_000L
    const val LATE_TICK_JUDGE_MS = 10_000L
    const val RECONNECT_DELAY_MS = 1_000L
    const val MAX_RECONNECT_DELAY_MS = 30_000L
    const val RECONNECT_FACTOR = 1.5

    // ── Fil (ChatOverlay.ts) ──
    /** « Mika écrit… » doit couvrir toute l'attente : appel au modèle, file d'attente, délai. */
    const val TYPING_TIMEOUT_MS = 300_000L
    /** Ce que le téléphone garde du fil ; le reste se relit sur le serveur. */
    const val MAX_LOCAL_MESSAGES = 1000

    // ── Codes de fermeture (adapters/web/hub.py, app.py) ──
    const val CLOSE_NORMAL = 1000
    /** Origine refusée — envoyé avant l'acceptation : OkHttp le voit comme une poignée de main en 403. */
    const val CLOSE_POLICY = 1008
    /** Session absente ou révoquée : permanent, la session doit changer avant qu'un essai diffère. */
    const val CLOSE_UNAUTHORIZED = 4401

    // ── En-têtes et routes (ADR 0051, ADR 0062) ──
    const val HEADER_AUTHORIZATION = "Authorization"
    /** `here` : devant l'écran ; `away` : l'app garde la socket en arrière-plan (pas d'annonce de présence). */
    const val HEADER_PRESENCE = "X-Mika-Presence"
    const val HEADER_USER_AGENT = "User-Agent"
    const val PRESENCE_HERE = "here"
    const val PRESENCE_AWAY = "away"
    const val PATH_WS = "/ws"
    const val PATH_TOKEN = "/auth/token"
    const val PATH_WHOAMI = "/auth/whoami"
    const val PATH_FILES = "/files/"
    /** La nature du client est portée par le jeton : c'est elle qui fait de l'app une messagerie. */
    const val CLIENT_MOBILE = "mobile"

    // ── Types de trames ──
    const val TYPE_SPEECH = "speech"
    const val TYPE_HISTORY = "history"
    const val TYPE_ACK = "ack"
    const val TYPE_EMOTION_UPDATE = "emotion_update"
    const val TYPE_INNER_STATE_UPDATE = "inner_state_update"
    const val TYPE_PONG = "pong"
    const val TYPE_APPROVALS = "approvals"
    const val TYPE_APPROVAL_RESULT = "approval_result"
    const val TYPE_CHAT = "chat"
    const val TYPE_SYNC = "sync"
    const val TYPE_PING = "ping"
    const val TYPE_PRESENCE = "presence"
    const val TYPE_APPROVAL = "approval"

    const val MODE_INITIAL = "initial"
    const val MODE_CATCHUP = "catchup"

    // ── Statuts d'accusé (protocol.py ; les trois derniers sont émis par le client lui-même) ──
    const val ACK_ACCEPTED = "accepted"
    const val ACK_NO_REPLY = "no_reply"
    const val ACK_TOO_LATE = "too_late"
    const val ACK_FRAME_TOO_LARGE = "frame_too_large"
    const val ACK_SEND_ABANDONED = "send_abandoned"
    const val ACK_UNAUTHORIZED = "unauthorized"
    /** Propres à l'app : la connexion refusée (1008/403) et des fichiers disparus du téléphone. */
    const val ACK_CONNECTION_REFUSED = "connection_refused"
    const val ACK_FILES_MISSING = "files_missing"

    // ── Cartes d'accord (ADR 0064 ; app/mindport.py::approval_cards, adapters/web/app.py::approval) ──
    const val DECISION_ACCEPT = "accept"
    const val DECISION_REFUSE = "refuse"
    const val APPROVAL_APPROVED = "approved"
    const val APPROVAL_REJECTED = "rejected"
    const val APPROVAL_UNKNOWN = "unknown"
    const val APPROVAL_CHANGED = "changed"
    const val APPROVAL_BLOCKED = "blocked"
    const val APPROVAL_EXPIRED = "expired"
    const val APPROVAL_FORBIDDEN = "forbidden"
    /** L'empreinte de ce qui partirait : hexadécimale, tronquée à 128 par le serveur. */
    val APPROVAL_DIGEST = Regex("[0-9a-f]{0,128}")
    /**
     * Bornes de lecture, au-dessus de celles du serveur (titre 400, texte 4 000) : un titre ou une raison
     * plus longs sont coupés à l'affichage ; un texte plus long est coupé aussi, et la carte ne peut plus
     * qu'être refusée — on n'accepte pas ce qu'on n'a pas pu lire en entier.
     */
    const val MAX_APPROVAL_TITLE_CHARS = 1_000
    const val MAX_APPROVAL_TEXT_CHARS = 16_000
    const val MAX_APPROVAL_BLOCKED_CHARS = 1_000
    const val MAX_APPROVAL_CARDS = 50

    // ── Voix et sources (protocol.py) ──
    const val VOICE_REASON_ASLEEP = "asleep"
    /** Une trame sans texte : elle a lu et choisi de se taire (ou, suivie d'un `no_reply`, elle n'a pas pu répondre). */
    const val VOICE_REASON_SILENCE = "silence"
    const val PERSONA_INNER = "inner"
    const val PERSONA_SPEAKING = "speaking"
    const val SOURCE_ERROR = "error"

    const val ROLE_USER = "user"
    const val ROLE_ASSISTANT = "assistant"
}
