package fr.qwartz.mika.data.db

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/** La base locale : un cache du fil et de sa file d'envoi, jamais la référence (c'est le serveur). */
@Database(entities = [MessageEntity::class, OutboxEntity::class, KvEntity::class], version = 4, exportSchema = true)
abstract class MikaDatabase : RoomDatabase() {
    abstract fun messages(): MessageDao
    abstract fun outbox(): OutboxDao
    abstract fun kv(): KvDao

    companion object {
        const val NAME = "mika.db"

        /** Version 2 : l'avis de l'opératrice sur ses réponses (ADR 0113). Le cache garde son fil. */
        val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE messages ADD COLUMN verdict TEXT")
                db.execSQL("ALTER TABLE messages ADD COLUMN verdict_note TEXT")
            }
        }

        /**
         * Version 3 : le mode pro (ADR 0116) — le mode d'un message et ses outils (noms et réussites), et le mode
         * d'un message en partance. Le cache garde son fil ; ses outils reviennent avec le prochain historique.
         */
        val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE messages ADD COLUMN mode TEXT")
                db.execSQL("ALTER TABLE messages ADD COLUMN tools TEXT")
                db.execSQL("ALTER TABLE outbox ADD COLUMN mode TEXT")
            }
        }

        /** Version 4 : ses petites bulles (ADR 0119 : elle a regardé où tu es), jointes à ses réponses. Le cache garde son fil. */
        val MIGRATION_3_4 = object : Migration(3, 4) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE messages ADD COLUMN notes TEXT")
            }
        }

        fun open(context: Context): MikaDatabase =
            Room.databaseBuilder(context, MikaDatabase::class.java, NAME)
                .addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4)
                .build()
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
    /** Les derniers messages reçus par Firebase et notifiés (JSON) : Firebase n'en garantit pas l'ordre (ADR 0077). */
    const val PUSHED_IDS = "pushed_ids"
    /** Quand on a quitté la conversation pour la dernière fois (heure murale, ms) : l'horloge des retrouvailles. */
    const val LAST_SEEN_WALL = "last_seen_wall"
    /**
     * Les messages lus sur le téléphone qui attendent le serveur, et le sort des réponses proposées (JSON, ADR 0120) :
     * en 4G, ils attendent le Wi-Fi de la maison. Effacés avec la session : un autre compte n'en hérite jamais.
     */
    const val PHONE_QUEUE = "phone_queue"
    /** Les réponses proposées qui attendent un geste, le temps de leur échéance (JSON, ADR 0120). */
    const val PHONE_DRAFTS = "phone_drafts"
}
