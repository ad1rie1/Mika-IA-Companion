package fr.qwartz.mika.core

import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import fr.qwartz.mika.service.NotificationPolicy
import fr.qwartz.mika.ui.BackStack
import fr.qwartz.mika.ui.Route
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * « La conversation est à l'écran » (R1-01) : l'app au premier plan **et** le chat au sommet de la pile. Avec le tiroir,
 * l'app ouverte peut montrer Mail pendant des minutes : une parole de Mika s'y notifie.
 */
class AppForegroundTest {
    private val owner = object : LifecycleOwner {
        override val lifecycle: Lifecycle get() = error("le premier plan ne lit pas son propriétaire")
    }
    private val parole = StoredMessage("coucou", Sender.MIKA, 0, id = 13)

    private fun notified(fg: AppForeground): Boolean = NotificationPolicy.shouldNotify(
        parole,
        NotificationPolicy.Context(fg.chatOnScreen, lastReadId = 10, lastNotifiedId = 12, cursorBefore = 12),
    )

    @Test fun `l'app ouverte sur Mail - la conversation n'est pas à l'écran, sa parole se notifie`() {
        val fg = AppForeground()
        fg.onStart(owner)
        fg.onTop(chat = BackStack().open(Route.Mail).showsChat)
        assertTrue(fg.visible.value)
        assertFalse(fg.chatOnScreen)
        assertTrue(notified(fg))
    }

    @Test fun `l'app ouverte sur le chat - à l'écran, rien ne se notifie`() {
        val fg = AppForeground()
        fg.onStart(owner)
        fg.onTop(chat = BackStack().showsChat)
        assertTrue(fg.chatOnScreen)
        assertFalse(notified(fg))
    }

    @Test fun `le chat au sommet mais l'app quittée - pas à l'écran`() {
        val fg = AppForeground()
        fg.onStart(owner)
        fg.onTop(chat = true)
        fg.onStop(owner)
        assertFalse(fg.chatOnScreen)
        assertTrue(notified(fg))
    }

    @Test fun `hors session, le cadre parti - pas à l'écran`() {
        val fg = AppForeground()
        fg.onStart(owner)
        fg.onTop(chat = true)
        fg.onTop(chat = false)
        assertFalse(fg.chatOnScreen)
    }
}
