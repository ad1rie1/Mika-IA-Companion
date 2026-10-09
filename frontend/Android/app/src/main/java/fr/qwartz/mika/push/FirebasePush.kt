package fr.qwartz.mika.push

import android.content.Context
import com.google.android.gms.tasks.Task
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import fr.qwartz.mika.data.push.PushPort
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Firebase Cloud Messaging (ADR 0077). Présent seulement si l'app a été construite avec `google-services.json` :
 * sans lui, `FirebaseInitProvider` n'initialise rien, et [available] le dit. Le jeton ne naît qu'avec une session
 * (l'initialisation automatique est coupée au manifeste) et meurt à la déconnexion.
 */
class FirebasePush(private val context: Context) : PushPort {
    override val available: Boolean
        get() = FirebaseApp.getApps(context).isNotEmpty()

    override suspend fun token(): String? {
        val messaging = FirebaseMessaging.getInstance()
        messaging.isAutoInitEnabled = true
        return messaging.token.await()
    }

    override suspend fun forget() {
        val messaging = FirebaseMessaging.getInstance()
        messaging.isAutoInitEnabled = false
        messaging.deleteToken().await()
    }
}

/**
 * Attendre une tâche des services Google sans bloquer de fil. Une tâche annulée par Google est une erreur, pas une
 * annulation de la coroutine : sinon elle arrêterait l'appelant (l'inscription à chaque ouverture, la déconnexion).
 */
private suspend fun <T> Task<T>.await(): T? = suspendCancellableCoroutine { cont ->
    addOnCompleteListener { task ->
        val error = task.exception
        when {
            error != null -> cont.resumeWithException(error)
            task.isCanceled -> cont.resumeWithException(IllegalStateException("tâche Firebase annulée"))
            else -> cont.resume(task.result)
        }
    }
}
