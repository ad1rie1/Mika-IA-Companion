package fr.qwartz.mika.ui.contacts

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.contacts.ContactKinds
import fr.qwartz.mika.data.moi.contacts.ContactLine
import fr.qwartz.mika.data.moi.contacts.ContactSheet
import fr.qwartz.mika.data.moi.contacts.ContactsApi
import fr.qwartz.mika.data.moi.contacts.ContactsCounts
import fr.qwartz.mika.data.moi.contacts.ContactsDone
import fr.qwartz.mika.data.moi.contacts.ContactsPage
import kotlinx.coroutines.CompletableDeferred
import okhttp3.OkHttpClient

/**
 * Une fausse API de Contacts pour les écrans : un petit annuaire en mémoire (ses contacts dans l'ordre du serveur, ses
 * fiches), une recherche naïve (le nom ou une adresse contient ce qu'on cherche), des pages, et des barrières — un appel
 * retenu ne répond que quand le test le lâche, avec ce qu'il avait lu au moment de la demande.
 */
class FakeContactsApi : ContactsApi(MoiApi(OkHttpClient(), { null }, {})) {
    var contacts: MutableList<ContactLine> = mutableListOf()
    val sheets = HashMap<Int, ContactSheet>()

    /** Ce qu'une lecture ou un oubli rend, si le test l'impose (sinon ce que le faux annuaire sait). */
    var pageFail: MoiError? = null
    var sheetFail: MoiError? = null
    var forgetFail: MoiError? = null
    var factFail: MoiError? = null

    /** Les appels, dans l'ordre (« page:cla:org:1 », « sheet:12 », « forget:12 », « fact:41 »). */
    val calls = mutableListOf<String>()

    private val gates = HashMap<String, CompletableDeferred<Unit>>()

    /** Retenir le prochain appel de ce nom (`page`, `sheet`, `forget`, `fact`). */
    fun hold(name: String) {
        gates[name] = CompletableDeferred()
    }

    fun release(name: String) {
        gates.remove(name)?.complete(Unit)
    }

    private suspend fun <T> answer(name: String, value: T): T {
        gates[name]?.await()
        return value
    }

    private fun counts() = ContactsCounts(
        all = contacts.size,
        person = contacts.count { it.kind == ContactKinds.PERSON },
        org = contacts.count { it.kind == ContactKinds.ORG },
    )

    override suspend fun page(q: String, kind: String, page: Int, size: Int): MoiApi.Result<ContactsPage> {
        calls += "page:$q:$kind:$page"
        pageFail?.let { return answer("page", MoiApi.Result.Failed(it)) }
        val text = q.trim().lowercase()
        val found = contacts.filter { c ->
            (kind.isEmpty() || c.kind == kind) &&
                (text.isEmpty() || c.name.lowercase().contains(text) || c.identifiers.any { it.value.lowercase().contains(text) })
        }
        val items = found.drop((page - 1) * size).take(size)
        return answer("page", MoiApi.Result.Ok(ContactsPage(total = found.size, page = page, size = size, counts = counts(), items = items)))
    }

    override suspend fun sheet(id: Int): MoiApi.Result<ContactSheet> {
        calls += "sheet:$id"
        val got = sheetFail?.let { MoiApi.Result.Failed(it) }
            ?: sheets[id]?.let { MoiApi.Result.Ok(it) }
            ?: MoiApi.Result.Failed(MoiError(404, "Introuvable : ce n'est plus là."))
        return answer("sheet", got)
    }

    override suspend fun forget(id: Int, key: String?): MoiApi.Result<ContactsDone> {
        calls += "forget:$id"
        forgetFail?.let { return answer("forget", MoiApi.Result.Failed(it)) }
        val name = sheets.remove(id)?.name ?: return answer("forget", MoiApi.Result.Failed(MoiError(404, "Introuvable : ce n'est plus là.")))
        contacts.removeAll { it.id == id }
        return answer("forget", MoiApi.Result.Ok(ContactsDone(ok = true, message = "« $name » est oublié·e : ce n'est plus un de tes contacts.")))
    }

    override suspend fun forgetFact(id: Int, key: String?): MoiApi.Result<ContactsDone> {
        calls += "fact:$id"
        factFail?.let { return answer("fact", MoiApi.Result.Failed(it)) }
        for ((cid, s) in sheets) {
            if (s.facts.any { it.note && it.id == id }) sheets[cid] = s.copy(facts = s.facts.filterNot { it.note && it.id == id })
        }
        return answer("fact", MoiApi.Result.Ok(ContactsDone(ok = true, message = "Oublié : elle ne le réapprendra pas.", id = id)))
    }
}
