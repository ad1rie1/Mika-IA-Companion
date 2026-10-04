package fr.qwartz.mika.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import fr.qwartz.mika.ui.login.LoginForm
import fr.qwartz.mika.ui.theme.MikaTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Le formulaire de connexion, sans graphe : avertissements, bouton, compte à rebours, raison. */
@RunWith(AndroidJUnit4::class)
class LoginScreenTest {
    @get:Rule val rule = createComposeRule()

    private fun show(
        server: String,
        canSubmit: Boolean = true,
        cooldown: Long = 0,
        reason: String? = null,
        error: String? = null,
        onSubmit: () -> Unit = {},
    ) {
        rule.setContent {
            var s by remember { mutableStateOf(server) }
            MikaTheme(dynamicColor = false) {
                LoginForm(
                    server = s, onServer = { s = it },
                    username = "bea", onUsername = {},
                    password = "secret", onPassword = {},
                    reason = reason, error = error, busy = false, cooldown = cooldown,
                    canSubmit = canSubmit, onSubmit = onSubmit,
                )
            }
        }
    }

    @Test fun httpSurLeReseauPrevientQueCeNEstPasChiffre() {
        show("192.168.1.20:8001")
        rule.onNodeWithText("Connexion non chiffrée", substring = true).assertIsDisplayed()
    }

    @Test fun tailscaleChiffreDeja() {
        show("http://mika.tail1234.ts.net:8001")
        rule.onNodeWithText("le tunnel chiffre déjà", substring = true).assertIsDisplayed()
    }

    @Test fun seConnecter() {
        var submitted = false
        show("https://mika.example.org", onSubmit = { submitted = true })
        rule.onNodeWithText("Se connecter").assertIsEnabled().performClick()
        assertTrue(submitted)
    }

    @Test fun troisTentativesDeTropUnCompteARebours() {
        show("https://mika.example.org", canSubmit = false, cooldown = 42, error = "Trop de tentatives. Réessaie dans 42 s.")
        rule.onNodeWithText("Réessaie dans 42 s").assertIsNotEnabled()
        rule.onNodeWithText("Trop de tentatives. Réessaie dans 42 s.").assertIsDisplayed()
    }

    @Test fun laRaisonDUneSessionFermeeEstDite() {
        show("https://mika.example.org", reason = "Ta session a expiré ou a été révoquée — reconnecte-toi.")
        rule.onNodeWithText("Ta session a expiré", substring = true).assertIsDisplayed()
    }
}
