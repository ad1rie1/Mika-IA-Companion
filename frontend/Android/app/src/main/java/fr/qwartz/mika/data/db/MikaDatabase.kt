package fr.qwartz.mika.data.db

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

/** La base locale : un cache du fil et de sa file d'envoi, jamais la référence (c'est le serveur). */
@Database(entities = [MessageEntity::class, OutboxEntity::class, KvEntity::class], version = 1, exportSchema = true)
abstract class MikaDatabase : RoomDatabase() {
    abstract fun messages(): MessageDao
    abstract fun outbox(): OutboxDao
    abstract fun kv(): KvDao

    companion object {
        const val NAME = "mika.db"

        fun open(context: Context): MikaDatabase =
            Room.databaseBuilder(context, MikaDatabase::class.java, NAME).build()
    }
}

/** Les clés de la table `kv`. */
object Kv {
    /** L'empreinte de la vie du fil (ADR 0056). */
    const val LIFE = "life"
    /** `<adresse>|<person_id>` : un autre compte ou un autre serveur vide le cache. */
    const val OWNER = "owner"
    const val TRUNCATED = "truncated"
    /** Le plus petit identifiant du dernier lot tronqué : au-dessous, un trou. */
    const val GAP_BEFORE_ID = "gap_before_id"
    const val LAST_READ_ID = "last_read_id"
    const val LAST_NOTIFIED_ID = "last_notified_id"
    const val MIND_STATE = "mind_state"
    /** Le brouillon de la barre de saisie (texte, fichiers en attente). */
    const val DRAFT = "draft"
    /** Un partage reçu (« Partager vers Mika ») pas encore pris par la barre de saisie. */
    const val SHARED_INBOX = "shared_inbox"
    /** Les lignes de la notification de messages (JSON), pour qu'un processus tué ne la vide pas. */
    const val NOTIFIED_LINES = "notified_lines"
    /** Quand on a quitté la conversation pour la dernière fois (heure murale, ms) : l'horloge des retrouvailles. */
    const val LAST_SEEN_WALL = "last_seen_wall"
}
