package fr.qwartz.mika.data.moi.tools

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.settings.Services
import fr.qwartz.mika.data.moi.settings.SettingsApi

/**
 * Outils par l'API par personne, sous le jeton de ce téléphone : la matrice de tes droits (`protocole-moi.md` § 6) et
 * ses services (§ 8, la lecture même de Paramètres, [SettingsApi.services]). Rien ne s'y écrit : un service se règle
 * dans Paramètres, un accord se décide dans le chat.
 */
class ToolsApi(private val api: MoiApi) {
    private val settings = SettingsApi(api)

    /** Ce que Mika fait de chacun de ses outils pour toi, par chaque canal et à chaque moment. */
    suspend fun rights(): MoiApi.Result<Rights> = api.get("/rights", reader = Rights.serializer())

    /** Tes services, et ceux qu'on te partage (`received`). */
    suspend fun services(): MoiApi.Result<Services> = settings.services()
}
