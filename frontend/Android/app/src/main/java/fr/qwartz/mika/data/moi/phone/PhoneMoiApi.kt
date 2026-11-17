package fr.qwartz.mika.data.moi.phone

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.decode
import fr.qwartz.mika.data.moi.jsonOf
import fr.qwartz.mika.data.moi.map

/**
 * Le Téléphone par l'API par personne (`backendv2/docs/protocole-moi.md` § 5), sous le jeton de ce téléphone : ses
 * conversations et leurs fils, ta dernière position, tes téléphones (et en révoquer un). Rien n'y envoie un message :
 * répondre d'ici passe par l'action « Répondre » de la notification de l'appli, sur ce téléphone même (ADR 0120), et
 * son sort par la porte du téléphone (`POST /api/phone/settled`, `data/phone/PhoneOutbox`). Ouverte : l'écran d'un fil
 * se teste sur une fausse API.
 */
open class PhoneMoiApi(private val api: MoiApi) {
    /** Ses conversations, la plus récente d'abord. */
    suspend fun conversations(size: Int = PhoneLimits.CONVERSATIONS): MoiApi.Result<List<PhoneConversation>> =
        api.get("/phone/conversations", mapOf("size" to size.toString()), PhoneConversations.serializer()).map { it.items }

    /** Le fil d'une conversation : ses [size] messages les plus récents (100 au plus), ses dix dernières propositions. */
    open suspend fun thread(conversation: String, size: Int = PhoneLimits.PAGE): MoiApi.Result<PhoneThread> =
        api.get("/phone/thread", linkedMapOf("conversation" to conversation, "size" to size.toString()), PhoneThread.serializer())

    suspend fun position(): MoiApi.Result<PhonePosition> = api.get("/phone/position", reader = PhonePosition.serializer())

    suspend fun phones(): MoiApi.Result<PhoneDevices> = api.get("/phone/phones", reader = PhoneDevices.serializer())

    /** Révoquer un de tes téléphones : son jeton ne vaut plus rien, ses messages restent. Déjà révoqué : 409. */
    suspend fun revoke(id: Long, key: String? = MoiApi.newKey()): MoiApi.Result<PhoneDone> =
        api.post("/phone/revoke", jsonOf(listOf("id" to id)), key).decode(PhoneDone.serializer())
}
