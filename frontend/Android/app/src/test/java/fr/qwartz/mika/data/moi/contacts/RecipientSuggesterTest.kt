package fr.qwartz.mika.data.moi.contacts

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.mail.MailApi
import fr.qwartz.mika.data.moi.mail.MailContact
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * D'où viennent les destinataires proposés : tes contacts d'abord (`/contacts?q=`, ADR 0298) ; l'annuaire absent (pas
 * branché, un serveur d'avant), tes correspondants du courrier ; une autre panne, rien — jamais les correspondants à la
 * place d'un annuaire qui répond.
 */
class RecipientSuggesterTest {
    private val nowhere = MoiApi(OkHttpClient(), { null }, {})

    private class Directory(var answer: MoiApi.Result<ContactsPage>) : ContactsApi(MoiApi(OkHttpClient(), { null }, {})) {
        val asked = mutableListOf<String>()
        override suspend fun page(q: String, kind: String, page: Int, size: Int): MoiApi.Result<ContactsPage> {
            asked += "$q|$kind|$page|$size"
            return answer
        }
    }

    private inner class Mail(val answer: MoiApi.Result<List<MailContact>>) : MailApi(nowhere) {
        val asked = mutableListOf<String>()
        override suspend fun contacts(q: String, size: Int, box: String): MoiApi.Result<List<MailContact>> {
            asked += q
            return answer
        }
    }

    private val claire = ContactLine(id = 12, name = "Claire Dubois", identifiers = listOf(ContactIdent("email", "c.dubois@lumen.fr")))
    private val lea = MailContact("lea@x.fr", "Léa", received = 2)

    @Test fun `tes contacts d'abord, sans demander tes correspondants`() = runBlocking {
        val dir = Directory(MoiApi.Result.Ok(ContactsPage(items = listOf(claire))))
        val mail = Mail(MoiApi.Result.Ok(listOf(lea)))
        val got = RecipientSuggester(dir, mail).lookup("  clai ", emptySet())
        assertEquals(listOf("c.dubois@lumen.fr"), got.map { it.address })
        assertEquals(listOf("clai||1|${RecipientSuggester.LOOKUP}"), dir.asked)
        assertTrue(mail.asked.isEmpty())
    }

    @Test fun `l'annuaire répond qu'il n'y a personne, rien, pas de correspondants à la place`() = runBlocking {
        val mail = Mail(MoiApi.Result.Ok(listOf(lea)))
        val got = RecipientSuggester(Directory(MoiApi.Result.Ok(ContactsPage())), mail).lookup("lé", emptySet())
        assertTrue(got.isEmpty())
        assertTrue(mail.asked.isEmpty())
    }

    @Test fun `l'annuaire pas branché ou absent du serveur, tes correspondants, comme avant`() = runBlocking {
        for (code in listOf(503, 404)) {
            val mail = Mail(MoiApi.Result.Ok(listOf(lea)))
            val got = RecipientSuggester(Directory(MoiApi.Result.Failed(MoiError(code, "L'annuaire n'est pas branché."))), mail).lookup("lé", emptySet())
            assertEquals(listOf("lea@x.fr"), got.map { it.address })
            assertEquals(listOf("lé"), mail.asked)
        }
        // sans annuaire du tout (un écran qui ne le donne pas)
        assertEquals(listOf("lea@x.fr"), RecipientSuggester(null, Mail(MoiApi.Result.Ok(listOf(lea)))).lookup("lé", emptySet()).map { it.address })
    }

    @Test fun `une autre panne ne propose rien, et un texte vide ne demande rien`() = runBlocking {
        val mail = Mail(MoiApi.Result.Ok(listOf(lea)))
        val dir = Directory(MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK)))
        assertTrue(RecipientSuggester(dir, mail).lookup("lé", emptySet()).isEmpty())
        assertTrue(mail.asked.isEmpty())
        assertTrue(RecipientSuggester(dir, mail).lookup("   ", emptySet()).isEmpty())
        assertEquals(1, dir.asked.size)
    }

    @Test fun `ce qui est déjà en puce n'est pas proposé`() = runBlocking {
        val dir = Directory(MoiApi.Result.Ok(ContactsPage(items = listOf(claire))))
        assertTrue(RecipientSuggester(dir, Mail(MoiApi.Result.Ok(emptyList()))).lookup("clai", setOf("c.dubois@lumen.fr")).isEmpty())
    }
}
