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
    /**
     * Au plus, un fichier qu'elle envoie et que `/files/…` sert (ports/shares.py `MAX_SHARE_BYTES`) :
     * le double de ce qu'on lui envoie. C'est lui que les téléchargements doivent pouvoir porter.
     */
    const val MAX_SHARE_BYTES = 10L * 1024 * 1024
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
    /**
     * Au plus tant de messages partis sans accusé : le serveur refuse (`overloaded`) au-delà de 8 en
     * attente sur une connexion (adapters/web/app.py `MAX_QUEUED_CHATS`), et une file rejouée d'un
     * bloc au retour du réseau les dépassait. Chaque accusé fait partir le suivant.
     */
    const val MAX_IN_FLIGHT = 4

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
    /**
     * Sans frappe depuis tant, la personne n'écrit plus (trame `composing`, WebSocketClient.ts
     * `COMPOSING_IDLE_MS`) : la réponse à son message d'avant n'attend pas une suite qui ne vient pas.
     */
    const val COMPOSING_IDLE_MS = 6_000L

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
    /** Où notifier le téléphone fermé (ADR 0077) : `POST` son jeton Firebase et sa clé, `DELETE` pour ne plus l'être. */
    const val PATH_PUSH = "/auth/push"
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
    const val TYPE_VERDICT_RESULT = "verdict_result"
    const val TYPE_VERDICT = "verdict"

    /** L'avis de l'opératrice sur une de ses réponses (ADR 0113) : adaptée, ou pas. */
    const val VERDICT_OK = "ok"
    const val VERDICT_KO = "ko"
    const val VERDICT_STATUS_OK = "ok"
    /** Ses outils en direct, pendant une réponse pro (ADR 0116) : jamais dans l'historique, jamais gardés. */
    const val TYPE_TOOL = "tool"
    const val TYPE_CHAT = "chat"
    const val TYPE_SYNC = "sync"
    const val TYPE_PING = "ping"
    const val TYPE_PRESENCE = "presence"
    const val TYPE_COMPOSING = "composing"
    const val TYPE_APPROVAL = "approval"
    const val TYPE_READ = "read"
    /** Où est la personne (« Lui dire où je suis », ADR 0119) : sa position, ou `off` pour l'effacer. */
    const val TYPE_WHERE = "where"

    // ── Sa position (ADR 0119 ; adapters/web/protocol.py `WHERE_*`, `note_item`) ──
    /** Le nom du lieu tient sur une ligne, borné par le serveur : au-delà, il est coupé avant de partir. */
    const val MAX_WHERE_LABEL_CHARS = 200
    /** La sorte d'une petite bulle (`notes` d'une `speech` ou d'une ligne d'`history`) : elle a regardé où tu es. */
    const val NOTE_LOCATION = "location"
    /** Bornes de lecture des petites bulles, au-dessus de celles du serveur (le lieu, 200 caractères). */
    const val MAX_NOTE_TEXT_CHARS = 400
    const val MAX_MESSAGE_NOTES = 8

    const val MODE_INITIAL = "initial"
    const val MODE_CATCHUP = "catchup"
    /** La réponse à `strand_history` (ADR 0164) : les messages d'un fil de travail ; son `last_id` n'est pas un curseur. */
    const val MODE_STRAND = "strand"

    // ── Le mode pro (ADR 0116) : un message de travail, pour une opératrice seulement ──
    /** Le `mode` d'un `chat`, d'une `speech` ou d'une ligne d'`history` ; toute autre valeur vaut « ordinaire ». */
    const val CHAT_MODE_PRO = "pro"
    /** Les phases d'une trame `tool` : un outil part, il a fini, ce qu'elle écrit entre deux, l'épisode est fini. */
    const val TOOL_START = "start"
    const val TOOL_END = "end"
    const val TOOL_NOTE = "note"
    const val TOOL_DONE = "done"
    /** L'issue d'un épisode qui a répondu ; les autres (`failed`, `timeout`, `superseded`…) se disent. */
    const val TOOL_OUTCOME_DONE = "done"
    /**
     * Bornes de lecture d'une trame `tool`, au-dessus de celles du serveur (arguments et résultat ~2 000
     * caractères) : au-delà, le texte est coupé à l'affichage.
     */
    const val MAX_TOOL_TEXT_CHARS = 4_000
    const val MAX_TOOL_NAME_CHARS = 128
    const val MAX_TOOL_ID_CHARS = 128
    /** Ce qu'une ligne d'historique peut dire de ses outils, au plus. */
    const val MAX_HISTORY_TOOLS = 100
    /** Les cartes de travail gardées en mémoire, et les étapes d'une carte, au plus. */
    const val MAX_WORK_CARDS = 20
    const val MAX_WORK_STEPS = 200

    // ── Les fils de travail du mode pro (ADR 0164 ; adapters/web/protocol.py `strand_id`, transcript/actions.py) ──
    /** Ses fils de travail, la liste entière (opératrice seulement). */
    const val TYPE_STRANDS = "strands"
    /** Le sort d'un réglage de fil : `ok`, `invalid`, `forbidden`, `failed`. */
    const val TYPE_STRAND_RESULT = "strand_result"
    /** Client → serveur : le réglage entier d'un fil (titre, description, archivé). */
    const val TYPE_STRAND = "strand"
    /** Client → serveur : les messages d'un fil (les 200 derniers avant `before`). */
    const val TYPE_STRAND_HISTORY = "strand_history"
    const val STRAND_STATUS_OK = "ok"
    /** Un identifiant de fil : choisi par le client, 1 à 40 lettres, chiffres, `_` ou `-`. */
    val STRAND_ID = Regex("[A-Za-z0-9_-]{1,40}")
    const val MAX_STRAND_TITLE_CHARS = 120
    const val MAX_STRAND_DESCRIPTION_CHARS = 2000
    /** Le début du premier message d'un fil, tel que le serveur le donne (120) ; borne de lecture au-dessus. */
    const val MAX_STRAND_OPENER_CHARS = 200
    /** Les fils lus d'une trame `strands`, au plus. */
    const val MAX_STRANDS = 500

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
    /** Une réponse pro ne se lit pas à voix haute (ADR 0116). */
    const val VOICE_REASON_PRO = "pro"
    const val PERSONA_INNER = "inner"
    const val PERSONA_SPEAKING = "speaking"
    const val SOURCE_ERROR = "error"

    const val ROLE_USER = "user"
    const val ROLE_ASSISTANT = "assistant"
}
