package fr.qwartz.mika.service

import android.content.Context
import androidx.core.app.NotificationChannelCompat
import androidx.core.app.NotificationManagerCompat
import fr.qwartz.mika.R

/** Les deux canaux de l'app, créés au démarrage (recréer un canal existant ne change rien). */
object NotificationChannels {
    const val MESSAGES = "messages"
    const val CONNECTION = "connection"

    /** Les identifiants des notifications : une seule conversation, une seule notification de messages. */
    const val ID_CONNECTION = 1
    const val ID_MESSAGES = 2

    fun create(context: Context) {
        val manager = NotificationManagerCompat.from(context)
        manager.createNotificationChannelsCompat(
            listOf(
                NotificationChannelCompat.Builder(MESSAGES, NotificationManagerCompat.IMPORTANCE_HIGH)
                    .setName(context.getString(R.string.channel_messages_name))
                    .setDescription(context.getString(R.string.channel_messages_desc))
                    .build(),
                // Minimale : présente dans le volet, jamais dans la barre d'état ni sonore.
                NotificationChannelCompat.Builder(CONNECTION, NotificationManagerCompat.IMPORTANCE_MIN)
                    .setName(context.getString(R.string.channel_connection_name))
                    .setDescription(context.getString(R.string.channel_connection_desc))
                    .setShowBadge(false)
                    .build(),
            ),
        )
    }
}
