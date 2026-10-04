package fr.qwartz.mika.ui

import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import fr.qwartz.mika.data.chat.MessageStatus
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import fr.qwartz.mika.ui.chat.ChatActions
import fr.qwartz.mika.ui.chat.ChatConversation
import fr.qwartz.mika.ui.chat.ChatItems
import fr.qwartz.mika.ui.theme.MikaTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.time.LocalDateTime
import java.time.ZoneId

/** Le fil à l'écran, sans graphe : une bulle = un nœud décrit, « Réessayer », « Mika écrit… ». */
@RunWith(AndroidJUnit4::class)
class ChatScreenTest {
    @get:Rule val rule = createComposeRule()
    private val zone = ZoneId.of("Europe/Paris")
    private val at = LocalDateTime.of(2026, 10, 4, 21, 4).atZone(zone).toInstant().toEpochMilli()

    private fun show(messages: List<StoredMessage>, typing: Boolean = false, actions: ChatActions = ChatActions()) {
        val items = ChatItems.build(messages, typing = typing, nowMs = at, zone = zone)
        rule.setContent {
            MikaTheme(dynamicColor = false) {
                ChatConversation(items, zone, operator = false, busyFileId = null, actions = actions)
            }
        }
    }

    @Test fun uneBulleEstUnNoeudDecrit() {
        show(
            listOf(
                StoredMessage("salut", Sender.USER, at, id = 1, localId = 1, status = MessageStatus.SENT),
                StoredMessage("coucou **toi**", Sender.MIKA, at, id = 2, localId = 2),
            ),
        )
        rule.onNodeWithContentDescription("Toi, 21 h 04, lu : salut").assertIsDisplayed()
        rule.onNodeWithContentDescription("Mika, 21 h 04 : coucou toi").assertIsDisplayed()
        rule.onNodeWithText("Aujourd'hui").assertIsDisplayed()
    }

    @Test fun uneBulleRefuseeProposeReessayer() {
        var retried = -1L
        show(
            listOf(StoredMessage("trop", Sender.USER, at, localId = 5, cid = "c5", status = MessageStatus.FAILED, reason = "message trop long")),
            actions = ChatActions(retry = { retried = it }),
        )
        rule.onNodeWithText("Réessayer").performClick()
        assertEquals(5L, retried)
        // L'action est aussi offerte au lecteur d'écran, sur la bulle elle-même.
        rule.onNode(SemanticsMatcher.keyIsDefined(SemanticsActions.CustomActions)).assertIsDisplayed()
    }

    @Test fun mikaEcritEstAnnonce() {
        show(listOf(StoredMessage("salut", Sender.USER, at, id = 1, localId = 1, status = MessageStatus.SENT)), typing = true)
        rule.onNodeWithText("Mika écrit…").assertIsDisplayed()
    }

    @Test fun unFilVideInviteADireBonjour() {
        rule.setContent {
            MikaTheme(dynamicColor = false) {
                ChatConversation(emptyList(), zone, operator = false, busyFileId = null, actions = ChatActions())
            }
        }
        rule.onNodeWithText("Dis bonjour à Mika.").assertIsDisplayed()
    }
}
