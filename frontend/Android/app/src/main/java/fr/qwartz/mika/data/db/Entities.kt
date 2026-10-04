package fr.qwartz.mika.data.db

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * Un message du fil. `server_id` est le curseur (unique), `client_msg_id` corrèle nos propres bulles
 * (unique). Aucun octet de fichier ici : une fenêtre de curseur SQLite fait 2 Mio, les fichiers
 * vivent sur le disque (`OutboxFiles`) et la ligne ne garde que leurs noms.
 */
@Entity(
    tableName = "messages",
    indices = [Index(value = ["server_id"], unique = true), Index(value = ["client_msg_id"], unique = true)],
)
data class MessageEntity(
    @PrimaryKey(autoGenerate = true) @ColumnInfo(name = "local_id") val localId: Long = 0,
    @ColumnInfo(name = "server_id") val serverId: Long?,
    @ColumnInfo(name = "client_msg_id") val clientMsgId: String?,
    /** `user` | `mika` */
    val sender: String,
    val text: String,
    @ColumnInfo(name = "match_text") val matchText: String?,
    /** `List<MessageAttachment>` en JSON. */
    val attachments: String,
    /** Millisecondes. */
    val ts: Long,
    /** `pending` | `sent` | `failed` (messages de la personne seulement). */
    val status: String?,
    val reason: String?,
    val note: String?,
    @ColumnInfo(name = "reply_note") val replyNote: String?,
    @ColumnInfo(name = "reply_href") val replyHref: String?,
    /** `asleep` : sa réponse attend son réveil. */
    val waiting: String?,
    @ColumnInfo(name = "after_cursor") val afterCursor: Long?,
    val source: String?,
    val emotion: String?,
    @ColumnInfo(name = "emotion_intensity") val emotionIntensity: Double?,
)

/**
 * Ce qui reste à envoyer — écrit dans la même transaction que la bulle : un message tapé hors ligne
 * survit à la mort du processus. Les fichiers sont dans `filesDir/outbox/<client_msg_id>/`.
 */
@Entity(tableName = "outbox")
data class OutboxEntity(
    @PrimaryKey @ColumnInfo(name = "client_msg_id") val clientMsgId: String,
    /** Ce qui a été tapé (sans les noms de fichiers). */
    val message: String,
    /** `List<OutboxFile>` en JSON. */
    val attachments: String,
    @ColumnInfo(name = "frame_bytes") val frameBytes: Long,
    @ColumnInfo(name = "created_at") val createdAt: Long,
    val attempts: Int = 0,
    @ColumnInfo(name = "in_flight") val inFlight: Boolean = false,
)

/** De petites valeurs : la vie du fil, son propriétaire, la troncature, le lu, l'état mental… */
@Entity(tableName = "kv")
data class KvEntity(
    @PrimaryKey val key: String,
    val value: String,
)
