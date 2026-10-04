package fr.qwartz.mika.data.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface MessageDao {
    @Query("SELECT * FROM messages")
    suspend fun all(): List<MessageEntity>

    @Query("SELECT * FROM messages")
    fun observeAll(): Flow<List<MessageEntity>>

    @Query("SELECT * FROM messages WHERE local_id = :localId")
    suspend fun byLocalId(localId: Long): MessageEntity?

    @Query("SELECT COALESCE(MAX(server_id), 0) FROM messages")
    suspend fun maxServerId(): Long

    @Query("SELECT client_msg_id FROM messages WHERE client_msg_id IS NOT NULL")
    suspend fun clientMsgIds(): List<String>

    @Insert
    suspend fun insert(row: MessageEntity): Long

    @Update
    suspend fun update(row: MessageEntity)

    @Query("DELETE FROM messages WHERE local_id IN (:ids)")
    suspend fun deleteByLocalIds(ids: List<Long>)

    @Query("DELETE FROM messages")
    suspend fun deleteAll()
}

@Dao
interface OutboxDao {
    @Query("SELECT * FROM outbox ORDER BY created_at, client_msg_id")
    suspend fun all(): List<OutboxEntity>

    @Query("SELECT * FROM outbox WHERE client_msg_id = :cid")
    suspend fun get(cid: String): OutboxEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(row: OutboxEntity)

    @Query("DELETE FROM outbox WHERE client_msg_id = :cid")
    suspend fun delete(cid: String)

    @Query("DELETE FROM outbox")
    suspend fun deleteAll()
}

@Dao
interface KvDao {
    @Query("SELECT value FROM kv WHERE `key` = :key")
    suspend fun get(key: String): String?

    @Query("SELECT value FROM kv WHERE `key` = :key")
    fun observe(key: String): Flow<String?>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(row: KvEntity)

    @Query("DELETE FROM kv WHERE `key` = :key")
    suspend fun delete(key: String)

    @Query("DELETE FROM kv")
    suspend fun deleteAll()
}
