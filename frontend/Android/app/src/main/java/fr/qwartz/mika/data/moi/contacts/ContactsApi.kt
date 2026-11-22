package fr.qwartz.mika.data.moi.contacts

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.decode
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Contacts par l'API par personne (`backendv2/docs/protocole-moi.md` § 12, ADR 0298), sous le jeton du téléphone : une
 * page de tes contacts (la recherche, la sorte), la fiche d'un contact, l'oublier, qu'elle oublie un fait. Ouverte : un
 * test JVM des écrans la remplace par une fausse, qui répond quand il veut.
 */
open class ContactsApi(private val api: MoiApi) {
    /** Tes contacts, le dernier vu d'abord ; [q] cherche dans leurs noms et leurs identifiants, [kind] : `person`,
     *  `org` ou tous (vide). */
    open suspend fun page(q: String = "", kind: String = "", page: Int = 1, size: Int = ContactsLimits.PAGE): MoiApi.Result<ContactsPage> =
        api.get(
            "/contacts",
            mapOf("q" to q.trim(), "kind" to kind, "page" to page.toString(), "size" to size.toString()),
            ContactsPage.serializer(),
        )

    open suspend fun sheet(id: Int): MoiApi.Result<ContactSheet> =
        api.get("/contacts/fiche", mapOf("id" to id.toString()), ContactSheet.serializer())

    /** L'oublier : seulement quand tout ce que tu en vois vient de tes comptes (sinon 403, avec les mots du serveur). */
    open suspend fun forget(id: Int, key: String? = MoiApi.newKey()): MoiApi.Result<ContactsDone> =
        api.post("/contacts/forget", JsonObject(mapOf("id" to JsonPrimitive(id))), key).decode(ContactsDone.serializer())

    /** Qu'elle oublie un fait tiré de ses messages (seulement d'un de tes comptes ; il ne se réapprend pas). */
    open suspend fun forgetFact(id: Int, key: String? = MoiApi.newKey()): MoiApi.Result<ContactsDone> =
        api.post("/contacts/fact/forget", JsonObject(mapOf("id" to JsonPrimitive(id))), key).decode(ContactsDone.serializer())
}
