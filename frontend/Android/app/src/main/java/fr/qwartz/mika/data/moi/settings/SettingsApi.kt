package fr.qwartz.mika.data.moi.settings

import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.decode
import fr.qwartz.mika.data.moi.jsonOf
import fr.qwartz.mika.data.moi.mail.BoxSettings
import fr.qwartz.mika.data.moi.mail.MailApi
import fr.qwartz.mika.data.moi.mail.MailBoxes
import fr.qwartz.mika.data.moi.phone.PhoneDevices
import fr.qwartz.mika.data.moi.phone.PhoneDone
import fr.qwartz.mika.data.moi.phone.PhoneMoiApi
import fr.qwartz.mika.data.moi.teams.TeamsAccounts
import fr.qwartz.mika.data.moi.teams.TeamsApi
import fr.qwartz.mika.data.moi.teams.TeamsSettings
import fr.qwartz.mika.data.moi.tools.ServiceTest
import fr.qwartz.mika.data.moi.tools.Services
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Paramètres par l'API par personne, sous le jeton de ce téléphone (qui écrit sans CSRF, ADR 0235) : son compte, ses
 * boîtes et ses comptes Teams, comment part ce que Mika y prépare (ADR 0207), ses services MCP, ses partages
 * (`protocole-moi.md` § 7, 8, 9), et ses téléphones (§ 5, par [PhoneMoiApi]). Les listes des boîtes et des comptes sont
 * celles de Mail et de Teams ([MailApi], [TeamsApi]) : une seule lecture de chaque, ici comme là.
 *
 * Une création (une boîte, un compte Teams, un service) porte sa clé d'envoi ([key]) : redite, elle ne refait rien.
 * Les autres réglages s'écrivent tels quels. Ouverte : les modèles des pages se testent sur une fausse API.
 */
open class SettingsApi(private val api: MoiApi) {
    private val mail = MailApi(api)
    private val teams = TeamsApi(api)
    private val phone = PhoneMoiApi(api)

    // ── son compte ──

    /** Son nom, celui sous lequel elle la connaît (120 caractères au plus). */
    open suspend fun saveName(name: String) = write("/account/name", jsonOf(listOf("name" to name)))

    /** Son mot de passe : l'actuel d'abord ; réussi, toutes ses sessions se ferment ([SettingsDone.relogin]). */
    open suspend fun savePassword(current: String, password: String) =
        write("/account/password", jsonOf(listOf("current" to current, "password" to password)))

    // ── ses boîtes ──

    open suspend fun boxes(): MoiApi.Result<MailBoxes> = mail.boxes()

    open suspend fun box(key: String): MoiApi.Result<BoxSettings> =
        api.get("/mail/box", mapOf("box" to key), BoxSettings.serializer())

    /** Une boîte nouvelle ([box] vide, avec sa clé d'envoi [key]) → `box`, sa clé ; sinon, la régler : seulement ce qui
     *  a changé ([values]), un secret vide jamais. */
    open suspend fun saveBox(values: JsonObject, box: String = "", key: String? = MoiApi.newKey()): MoiApi.Result<SettingsDone> {
        val body = if (box.isEmpty()) mapOf("values" to values) else mapOf("box" to JsonPrimitive(box), "values" to values)
        return write("/mail/box/save", JsonObject(body), key)
    }

    open suspend fun removeBox(box: String) = write("/mail/box/remove", jsonOf(listOf("box" to box)))

    /** Essayer sa connexion (trente fois par minute au plus : 429). */
    open suspend fun testBox(box: String) = write("/mail/box/test", jsonOf(listOf("box" to box)))

    /** La relever sans attendre (§ 3). */
    open suspend fun pollBox(box: String) = mail.poll(box)

    /** Connecter une boîte Microsoft : un code à entrer chez Microsoft, que [box] dit ensuite (`signin`). */
    open suspend fun connectMicrosoft(box: String) = write("/mail/box/microsoft", jsonOf(listOf("box" to box)))

    // ── ses comptes Teams ──

    open suspend fun teamsAccounts(): MoiApi.Result<TeamsAccounts> = teams.accounts()

    open suspend fun teamsAccount(key: String): MoiApi.Result<TeamsSettings> =
        api.get("/teams/account", mapOf("account" to key), TeamsSettings.serializer())

    /** Un compte nouveau ([account] vide, avec sa clé d'envoi) → `account` ; sinon, le régler. */
    open suspend fun saveTeamsAccount(values: JsonObject, account: String = "", key: String? = MoiApi.newKey()): MoiApi.Result<SettingsDone> {
        val body = if (account.isEmpty()) mapOf("values" to values) else mapOf("account" to JsonPrimitive(account), "values" to values)
        return write("/teams/account/save", JsonObject(body), key)
    }

    /** Une clé neuve pour son extension, rendue cette fois seulement ([SettingsDone.key]) ; l'ancienne ne vaut plus. */
    open suspend fun newExtensionKey(account: String) = write("/teams/account/key", jsonOf(listOf("account" to account)))

    open suspend fun revokeExtensionKey(account: String) = write("/teams/account/revoke", jsonOf(listOf("account" to account)))

    open suspend fun removeTeamsAccount(account: String) = write("/teams/account/remove", jsonOf(listOf("account" to account)))

    // ── comment part ce qu'elle prépare (ADR 0207) ──

    /** La règle d'un de ses comptes ([SettingsRules.ruleBody]) ; changée ailleurs entre-temps : 409. */
    open suspend fun saveRules(body: JsonObject) = write("/rules", body)

    // ── ses services MCP ──

    open suspend fun services(): MoiApi.Result<Services> = api.get("/mcp/services", reader = Services.serializer())

    /** Brancher un service distant (avec sa clé d'envoi) → `name`. */
    open suspend fun plugService(name: String, purpose: String, url: String, headers: String, whenToUse: String, key: String? = MoiApi.newKey()) =
        write(
            "/mcp/plug",
            jsonOf(listOf("name" to name, "purpose" to purpose, "url" to url, "headers" to headers, "when_to_use" to whenToUse)),
            key,
        )

    /** Rouvrir une session et relire ses outils : `ok` faux quand il ne répond pas. */
    open suspend fun testService(name: String): MoiApi.Result<ServiceTest> =
        api.post("/mcp/test", jsonOf(listOf("name" to name))).decode(ServiceTest.serializer())

    /** Choisir ses outils : `{"<outil>": "non" | "lecture" | "action"}`. */
    open suspend fun chooseTools(name: String, choices: Map<String, String>) = write(
        "/mcp/tools",
        JsonObject(mapOf("name" to JsonPrimitive(name), "choices" to JsonObject(choices.mapValues { JsonPrimitive(it.value) }))),
    )

    /** Le régler : `purpose`, `when_to_use`, `enabled`, `url`, `secret_headers` (vides, ils restent). */
    open suspend fun saveService(name: String, values: JsonObject) =
        write("/mcp/save", JsonObject(mapOf("name" to JsonPrimitive(name), "values" to values)))

    open suspend fun removeService(name: String) = write("/mcp/remove", jsonOf(listOf("name" to name)))

    // ── ses partages ──

    open suspend fun people(): MoiApi.Result<People> = api.get("/people", reader = People.serializer())

    open suspend fun shares(): MoiApi.Result<Shares> = api.get("/shares", reader = Shares.serializer())

    /** Partager une de ses ressources avec une personne, à un niveau ; un niveau vide retire le partage. */
    open suspend fun setShare(kind: String, key: String, person: String, level: String) =
        write("/shares/set", jsonOf(listOf("kind" to kind, "key" to key, "person" to person, "level" to level)))

    // ── ses téléphones (§ 5) ──

    open suspend fun phones(): MoiApi.Result<PhoneDevices> = phone.phones()

    /** Révoquer un de tes téléphones ; déjà révoqué : 409. */
    open suspend fun revokePhone(id: Long): MoiApi.Result<PhoneDone> = phone.revoke(id)

    private suspend fun write(path: String, body: JsonObject, key: String? = MoiApi.newKey()): MoiApi.Result<SettingsDone> =
        api.post(path, body, key).decode(SettingsDone.serializer())
}

internal fun AppGraph.settingsApi(): SettingsApi = SettingsApi(moi)
