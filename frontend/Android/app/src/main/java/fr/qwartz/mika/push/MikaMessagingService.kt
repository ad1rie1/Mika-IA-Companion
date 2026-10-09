package fr.qwartz.mika.push

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import fr.qwartz.mika.graph
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Ce que Firebase apporte app fermée (ADR 0077) : un message de Mika scellé pour ce téléphone. On l'ouvre avec la
 * clé gardée par le Keystore et on l'affiche comme une parole reçue par la connexion (`MessageNotifier`). Aucune
 * connexion n'est ouverte : le fil se rattrape à la prochaine ouverture de l'app.
 *
 * `onMessageReceived` tourne sur un fil de Firebase, qui laisse quelques secondes à un message de priorité haute :
 * on attend le graphe et la notification, bornés.
 */
class MikaMessagingService : FirebaseMessagingService() {

    override fun onMessageReceived(message: RemoteMessage) {
        val graph = applicationContext.graph
        runBlocking {
            try {
                withTimeoutOrNull(HANDLE_MS) {
                    graph.ready.await()
                    graph.onPushed(message.data)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                graph.logger.e(TAG, "notification non affichée", e)
            }
        }
    }

    /**
     * Un jeton neuf (rotation par Google) : le serveur doit l'apprendre. App ouverte, tout de suite ; fermée, à la
     * prochaine ouverture (l'empreinte de ce qui a été dit change avec le jeton) — jamais un essai en 4G vers un
     * serveur de la maison, app fermée.
     */
    override fun onNewToken(token: String) {
        val graph = applicationContext.graph
        graph.scope.launch {
            graph.ready.await()
            if (graph.foreground.visible.value) graph.push.sync()
        }
    }

    private companion object {
        const val TAG = "Messaging"
        const val HANDLE_MS = 8_000L
    }
}
