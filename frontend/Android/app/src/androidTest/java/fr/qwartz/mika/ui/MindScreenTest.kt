package fr.qwartz.mika.ui

import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import fr.qwartz.mika.data.mind.MindState
import fr.qwartz.mika.data.mind.Mood
import fr.qwartz.mika.data.net.Rumination
import fr.qwartz.mika.ui.mind.MindCards
import fr.qwartz.mika.ui.mind.MindContent
import fr.qwartz.mika.ui.theme.MikaTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.time.ZoneId

/** « Ce qu'elle fait » : les cartes présentes, titrées, et rien pour ce qu'on ne sait pas. */
@RunWith(AndroidJUnit4::class)
class MindScreenTest {
    @get:Rule val rule = createComposeRule()

    private fun show(state: MindState?, updated: String? = null, onBack: () -> Unit = {}) {
        val cards = MindCards.build(state, ZoneId.of("Europe/Paris"))
        rule.setContent { MikaTheme(dynamicColor = false) { MindContent(cards, updated, onBack) } }
    }

    @Test fun lesCartesPresentesSontDesIntitules() {
        show(
            MindState(
                place = "desk",
                energy = 0.7,
                mood = Mood("curious", 0.6),
                ruminations = listOf(Rumination("ce qu'elle a lu ce matin", 0.4)),
            ),
            updated = "Mis à jour il y a 3 min",
        )
        rule.onNodeWithText("Humeur").assertIsDisplayed()
        rule.onNodeWithText("Corps").assertIsDisplayed()
        rule.onNodeWithText("Elle repense à…").assertIsDisplayed()
        rule.onNodeWithText("Curieuse").assertIsDisplayed()
        rule.onNodeWithText("Mis à jour il y a 3 min").assertIsDisplayed()
        rule.onAllNodes(SemanticsMatcher.keyIsDefined(SemanticsProperties.Heading)).fetchSemanticsNodes().let {
            assertTrue(it.size >= 3)
        }
    }

    @Test fun pasDeCarteSansDonnees() {
        show(MindState(mood = Mood("happy", 0.5)))
        rule.onAllNodesWithText("Corps").assertCountEquals(0)
        rule.onAllNodesWithText("Projets en cours").assertCountEquals(0)
        rule.onAllNodesWithText("Rêve de cette nuit").assertCountEquals(0)
    }

    @Test fun rienDeConnu() {
        show(null)
        rule.onNodeWithText("Rien de connu pour l'instant", substring = true).assertIsDisplayed()
    }

    @Test fun retour() {
        var back = false
        show(null, onBack = { back = true })
        rule.onNodeWithContentDescription("Retour").performClick()
        assertTrue(back)
    }
}
