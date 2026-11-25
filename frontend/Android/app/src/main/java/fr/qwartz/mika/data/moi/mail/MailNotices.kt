package fr.qwartz.mika.data.moi.mail

import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow

/**
 * Le sort d'un geste de Mail à dire où qu'on soit : un envoi qui finit après qu'on a quitté « Écrire » (←, une
 * notification touchée) se dit quand même. Le cadre de la session le montre en toast ; ce que personne n'a encore lu
 * (une rotation) attend, et tout s'efface à la déconnexion : le compte suivant n'en hérite pas.
 */
class MailNotices {
    private val channel = Channel<String>(Channel.BUFFERED)
    val flow: Flow<String> = channel.receiveAsFlow()

    fun say(text: String) {
        if (text.isNotBlank()) channel.trySend(text)
    }

    fun clear() {
        while (channel.tryReceive().isSuccess) Unit
    }
}
