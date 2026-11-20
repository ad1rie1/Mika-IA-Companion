package fr.qwartz.mika.ui.mail

import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.mail.MailFramePage
import fr.qwartz.mika.data.moi.mail.MailFull
import fr.qwartz.mika.data.moi.mail.MailImages
import fr.qwartz.mika.data.moi.mail.MailPerson
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * La mise en page d'un mail HTML dans la liseuse (ADR 0242) : demandée pour un mail HTML seulement, pas relue tant que
 * la règle de ses images ne change pas, ses images « cette fois » relues avec `images=1`, « toujours » décidé par le
 * serveur, un refus qui laisse réessayer, et une réponse tardive qui ne se pose pas sur un autre mail.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MailReaderFrameTest {
    @get:Rule val main = MainDispatcherRule()

    private val a = "pro:<a@x>"
    private val b = "pro:<b@x>"
    private val t = "pro:<t@x>"
    private val api = FakeMailApi().apply {
        mails[a] = MailFull(ref = a, box = "pro", from = MailPerson("Léa", "lea@x.fr"), subject = "La lettre", html = true, images = MailImages(remote = true))
        mails[b] = MailFull(ref = b, box = "pro", from = MailPerson("Paul", "paul@x.fr"), subject = "La facture", html = true)
        mails[t] = MailFull(ref = t, box = "pro", from = MailPerson("Zoé", "zoe@x.fr"), subject = "Un mot", body = "Un mot de Zoé.")
    }
    private val reader by lazy { main.model { MailReaderViewModel(MailDeps(api)) } }

    private val ready: MailHtml get() = (reader.frame as Load.Ready).value

    @Test fun `un mail HTML se lit dans sa mise en page, sous la politique du cadre, sans images distantes`() = runTest {
        reader.open(a, "v1")
        advanceUntilIdle()
        assertEquals(listOf("frame:$a"), api.calls.filter { it.startsWith("frame") })
        assertEquals(a, ready.ref)
        assertFalse(ready.remote)
        assertTrue(ready.page.contains(MailFramePage.CSP))
        assertTrue(ready.page.contains("<p>La lettre</p>"))
    }

    @Test fun `un mail sans HTML ne demande pas de cadre`() = runTest {
        reader.open(t, "v1")
        advanceUntilIdle()
        assertNull(reader.frame)
        assertTrue(api.calls.none { it.startsWith("frame") })
    }

    @Test fun `rouvert sous la même règle, le cadre ne se relit pas`() = runTest {
        reader.open(a, "v1")
        advanceUntilIdle()
        reader.open(a, "v2")
        advanceUntilIdle()
        assertEquals(1, api.calls.count { it.startsWith("frame") })
    }

    @Test fun `ses images « cette fois » relisent le cadre avec images=1, sans rien décider pour l'expéditeur`() = runTest {
        reader.open(a, "v1")
        advanceUntilIdle()
        reader.images(ImagesGesture.ONCE) { "" }
        advanceUntilIdle()
        assertEquals(listOf("frame:$a", "frame:$a:images"), api.calls.filter { it.startsWith("frame") || it.startsWith("images") })
        assertTrue(ready.remote)
        assertTrue(ready.page.contains(MailFramePage.CSP_REMOTE))
        assertTrue(a in reader.imagesOnce)
    }

    @Test fun `« toujours pour cet expéditeur » se décide au serveur, puis le cadre se relit avec ses images`() = runTest {
        reader.open(a, "v1")
        advanceUntilIdle()
        reader.images(ImagesGesture.ALWAYS) { if (it) "toujours" else "jamais" }
        val said = withTimeoutOrNull(1_000) { reader.said.first() }
        advanceUntilIdle()
        assertEquals("toujours", said)
        assertEquals(listOf("frame:$a", "images:$a:true", "frame:$a"), api.calls.filter { it.startsWith("frame") || it.startsWith("images") })
        assertTrue((reader.mail as Load.Ready).value.images.shown)
        assertTrue(ready.remote)
    }

    @Test fun `un cadre refusé se dit, et « Réessayer » le redemande`() = runTest {
        api.frameFail = MoiError(0, MoiError.NETWORK)
        reader.open(a, "v1")
        advanceUntilIdle()
        assertTrue(reader.frame is Load.Failed)
        api.frameFail = null
        reader.retryFrame()
        advanceUntilIdle()
        assertEquals(a, ready.ref)
        assertEquals(2, api.calls.count { it.startsWith("frame") })
    }

    @Test fun `un cadre qui répond après qu'on est passé à un autre mail ne se pose pas sur lui`() = runTest {
        api.hold("frame")
        reader.open(a, "v1")
        advanceUntilIdle()
        reader.open(t, "v2")
        advanceUntilIdle()
        api.release("frame")
        advanceUntilIdle()
        assertNull(reader.frame)
        assertEquals(t, (reader.mail as Load.Ready).value.ref)
    }
}
