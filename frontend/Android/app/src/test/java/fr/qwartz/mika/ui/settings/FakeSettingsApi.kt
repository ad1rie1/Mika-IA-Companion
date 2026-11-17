package fr.qwartz.mika.ui.settings

import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.mail.MailBoxes
import fr.qwartz.mika.data.moi.settings.BoxSettings
import fr.qwartz.mika.data.moi.settings.People
import fr.qwartz.mika.data.moi.settings.Services
import fr.qwartz.mika.data.moi.settings.SettingsApi
import fr.qwartz.mika.data.moi.settings.SettingsDone
import fr.qwartz.mika.data.moi.settings.Shares
import fr.qwartz.mika.data.moi.settings.TeamsSettings
import fr.qwartz.mika.data.moi.teams.TeamsAccount
import fr.qwartz.mika.data.moi.teams.TeamsAccounts
import kotlinx.coroutines.CompletableDeferred
import kotlinx.serialization.json.JsonObject
import okhttp3.OkHttpClient

/**
 * Une fausse API de Paramètres pour les modèles des pages : un petit serveur en mémoire (ses boîtes, ses comptes Teams,
 * ses services, ses partages) et des barrières — un appel retenu ne répond que quand le test le lâche, avec ce qu'il
 * avait lu en arrivant. Chaque écriture se note ([calls], [sent]) : ce qui est parti, et pour qui.
 */
class FakeSettingsApi : SettingsApi(MoiApi(OkHttpClient(), { null }, {})) {
    var boxes = MailBoxes(
        boxes = listOf(
            MailBox(key = "pro", name = "Pro", address = "moi@atelier.fr", level = Levels.OWNER, ready = true),
            MailBox(key = "perso", name = "Perso", address = "moi@perso.fr", level = Levels.OWNER, ready = true),
        ),
    )
    val box = HashMap<String, BoxSettings>()
    var accounts = TeamsAccounts(
        accounts = listOf(
            TeamsAccount(key = "pro", name = "Pro", level = Levels.OWNER),
            TeamsAccount(key = "perso", name = "Perso", level = Levels.OWNER),
        ),
    )
    val account = HashMap<String, TeamsSettings>()
    var services = Services()
    var shares = Shares()
    var people = People()

    /** Ce qu'une écriture rend, si le test l'impose (sinon : `ok`). */
    var saveBoxResult: MoiApi.Result<SettingsDone>? = null
    var rulesResult: MoiApi.Result<SettingsDone>? = null
    var newKeyResult: MoiApi.Result<SettingsDone> = MoiApi.Result.Ok(SettingsDone(ok = true, key = "mtk_neuve"))

    /** Les appels, dans l'ordre (« box:pro », « saveBox:pro », « rules:courrier:pro »…). */
    val calls = mutableListOf<String>()
    /** Les corps envoyés, par appel (« saveBox:pro » → ses valeurs ; « rules » → la règle entière). */
    val sent = mutableListOf<Pair<String, JsonObject>>()

    private val gates = HashMap<String, CompletableDeferred<Unit>>()

    /** Retenir le prochain appel de ce nom (`box:<clé>`, `saveBox`, `rules`, `newKey`, `saveService`, `services`…). */
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

    private fun done(message: String) = MoiApi.Result.Ok(SettingsDone(ok = true, message = message))

    override suspend fun boxes(): MoiApi.Result<MailBoxes> = answer("boxes", MoiApi.Result.Ok(boxes))

    override suspend fun box(key: String): MoiApi.Result<BoxSettings> {
        calls += "box:$key"
        val got = box[key]?.let { MoiApi.Result.Ok(it) } ?: MoiApi.Result.Failed(MoiError(404, "Introuvable : ce n'est plus là."))
        return answer("box:$key", got)
    }

    override suspend fun saveBox(values: JsonObject, box: String, key: String?): MoiApi.Result<SettingsDone> {
        calls += "saveBox:$box"
        sent += "saveBox:$box" to values
        return answer("saveBox", saveBoxResult ?: done("Boîte enregistrée."))
    }

    override suspend fun saveRules(body: JsonObject): MoiApi.Result<SettingsDone> {
        val canal = (body["canal"] as? kotlinx.serialization.json.JsonPrimitive)?.content.orEmpty()
        calls += "rules:$canal"
        sent += "rules" to body
        return answer("rules", rulesResult ?: done("Règle d'envoi enregistrée."))
    }

    override suspend fun testBox(box: String): MoiApi.Result<SettingsDone> {
        calls += "testBox:$box"
        return answer("testBox", done("Elle répond."))
    }

    override suspend fun shares(): MoiApi.Result<Shares> = answer("shares", MoiApi.Result.Ok(shares))

    override suspend fun people(): MoiApi.Result<People> = answer("people", MoiApi.Result.Ok(people))

    override suspend fun teamsAccounts(): MoiApi.Result<TeamsAccounts> = answer("accounts", MoiApi.Result.Ok(accounts))

    override suspend fun teamsAccount(key: String): MoiApi.Result<TeamsSettings> {
        calls += "account:$key"
        val got = account[key]?.let { MoiApi.Result.Ok(it) } ?: MoiApi.Result.Failed(MoiError(404, "Introuvable : ce n'est plus là."))
        return answer("account:$key", got)
    }

    override suspend fun saveTeamsAccount(values: JsonObject, account: String, key: String?): MoiApi.Result<SettingsDone> {
        calls += "saveTeams:$account"
        sent += "saveTeams:$account" to values
        return answer("saveTeams", done("Compte enregistré."))
    }

    override suspend fun newExtensionKey(account: String): MoiApi.Result<SettingsDone> {
        calls += "newKey:$account"
        return answer("newKey", newKeyResult)
    }

    override suspend fun services(): MoiApi.Result<Services> = answer("services", MoiApi.Result.Ok(services))

    override suspend fun saveService(name: String, values: JsonObject): MoiApi.Result<SettingsDone> {
        calls += "saveService:$name"
        sent += "saveService:$name" to values
        return answer("saveService", done("Service réglé."))
    }

    override suspend fun chooseTools(name: String, choices: Map<String, String>): MoiApi.Result<SettingsDone> {
        calls += "tools:$name:" + choices.entries.joinToString(",") { "${it.key}=${it.value}" }
        return answer("tools", done("Ses outils sont choisis."))
    }

    override suspend fun setShare(kind: String, key: String, person: String, level: String): MoiApi.Result<SettingsDone> {
        calls += "share:$kind:$key:$person:$level"
        return answer("share", done("Partage retiré."))
    }
}

/** Les textes de l'app, nommés pour les tests : « « Pro » : … » pour le sort d'un geste dont la page est quittée. */
fun testDeps(api: SettingsApi, badges: () -> Unit = {}): SettingsDeps = SettingsDeps(
    api,
    { id, args -> if (id == R.string.settings_elsewhere) "« ${args[0]} » : ${args[1]}" else "texte:$id" },
    badges,
)
