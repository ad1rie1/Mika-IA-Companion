package fr.qwartz.mika.data.moi.agenda

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.decode
import fr.qwartz.mika.data.moi.settings.People
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * L'Agenda par l'API par personne (`backendv2/docs/protocole-moi.md` § 13, ADR 0309), sous le jeton du téléphone (sans
 * CSRF, ADR 0235) : ses agendas, une période, un événement, chercher, ses invitations et ce que Mika propose ; écrire,
 * répondre, décider ; ses comptes (Paramètres › Agendas) ; le tableau de droits d'un agenda (Outils › Droits) ; le
 * partager (`/shares/set`, § 9). Ouverte : un test JVM des écrans la remplace par une fausse, qui répond quand il veut.
 * Chaque écriture porte sa clé d'envoi (`Idempotency-Key`) : un double appui ne fait rien de plus.
 */
open class AgendaApi(private val api: MoiApi) {
    open suspend fun calendars(): MoiApi.Result<Calendars> = api.get("$A/calendars", reader = Calendars.serializer())

    /** Une période (`start`, `end` en `AAAA-MM-JJ`, le dernier jour compris) sur ces agendas (`mika` compris). */
    open suspend fun period(start: String, end: String, calendars: List<String>): MoiApi.Result<Period> =
        api.get("$A/period", mapOf("start" to start, "end" to end, "calendars" to calendars.joinToString(",")), Period.serializer())

    open suspend fun event(event: Int, occurrence: String = ""): MoiApi.Result<AgendaItem> =
        api.get("$A/event", mapOf("event" to event.toString(), "occurrence" to occurrence), AgendaItem.serializer())

    open suspend fun search(q: String, calendars: List<String>): MoiApi.Result<Found> =
        api.get("$A/search", mapOf("q" to q.trim(), "calendars" to calendars.joinToString(",")), Found.serializer())

    open suspend fun invitations(): MoiApi.Result<Invitations> = api.get("$A/invitations", reader = Invitations.serializer())

    open suspend fun proposals(): MoiApi.Result<Proposals> = api.get("$A/proposals", reader = Proposals.serializer())

    // ── écrire ──

    open suspend fun create(calendar: String, fields: EventFields, key: String? = MoiApi.newKey()): MoiApi.Result<AgendaDone> =
        write("/event/create", body("calendar" to JsonPrimitive(calendar)) + fields.json(), key)

    open suspend fun edit(event: Int, occurrence: String, scope: String, fields: EventFields, key: String? = MoiApi.newKey()): MoiApi.Result<AgendaDone> =
        write("/event/edit", body("event" to JsonPrimitive(event), "occurrence" to JsonPrimitive(occurrence), "scope" to JsonPrimitive(scope)) + fields.json(), key)

    open suspend fun delete(event: Int, occurrence: String, scope: String, key: String? = MoiApi.newKey()): MoiApi.Result<AgendaDone> =
        write("/event/delete", body("event" to JsonPrimitive(event), "occurrence" to JsonPrimitive(occurrence), "scope" to JsonPrimitive(scope)), key)

    /** Une copie de cette occurrence, dans [to] (un agenda où elle écrit ; vide : le même). */
    open suspend fun duplicate(event: Int, occurrence: String, to: String = "", key: String? = MoiApi.newKey()): MoiApi.Result<AgendaDone> =
        write("/event/duplicate", body("event" to JsonPrimitive(event), "occurrence" to JsonPrimitive(occurrence), "to" to JsonPrimitive(to)), key)

    /** Répondre à une invitation (`oui`, `peut`, `non`), avec un mot ; la série entière (`tous`) ou cette fois (`un`). */
    open suspend fun respond(event: Int, occurrence: String, answer: String, comment: String = "", scope: String = "tous", key: String? = MoiApi.newKey()): MoiApi.Result<AgendaDone> =
        write(
            "/event/respond",
            body(
                "event" to JsonPrimitive(event), "occurrence" to JsonPrimitive(occurrence), "answer" to JsonPrimitive(answer),
                "comment" to JsonPrimitive(comment), "scope" to JsonPrimitive(scope),
            ),
            key,
        )

    /** « Mika te le rappelle » pour cet événement (vide : le choix de l'agenda) — son propriétaire. */
    open suspend fun remind(event: Int, value: String): MoiApi.Result<AgendaDone> =
        write("/event/remind", body("event" to JsonPrimitive(event), "value" to JsonPrimitive(value)), MoiApi.newKey())

    /** Accepter ce que Mika propose tel qu'il a été lu ([seen] : l'empreinte de son aperçu). */
    open suspend fun accept(proposal: Int, seen: String, key: String? = MoiApi.newKey()): MoiApi.Result<AgendaDone> =
        write("/proposal/accept", body("proposal" to JsonPrimitive(proposal), "seen" to JsonPrimitive(seen)), key)

    open suspend fun refuse(proposal: Int, note: String = "", key: String? = MoiApi.newKey()): MoiApi.Result<AgendaDone> =
        write("/proposal/refuse", body("proposal" to JsonPrimitive(proposal), "note" to JsonPrimitive(note)), key)

    /** « Modifier » puis « Ajouter » un ajout qu'elle propose : ta version s'écrit, marquée « ajoutée par Mika ». */
    open suspend fun editProposal(proposal: Int, calendar: String, fields: EventFields, key: String? = MoiApi.newKey()): MoiApi.Result<AgendaDone> =
        write("/proposal/edit", body("proposal" to JsonPrimitive(proposal), "calendar" to JsonPrimitive(calendar)) + fields.json(), key)

    // ── ses comptes ──

    open suspend fun accounts(): MoiApi.Result<Accounts> = api.get("$A/accounts", reader = Accounts.serializer())

    /** Brancher un compte ([account] vide, [kind] : `google`, `microsoft`, `caldav`, `ical`) ou régler un des siens. */
    open suspend fun saveAccount(kind: String, account: String, values: Map<String, Any>, key: String? = MoiApi.newKey()): MoiApi.Result<AgendaDone> {
        val v = JsonObject(values.mapValues { (_, x) -> if (x is Boolean) JsonPrimitive(x) else JsonPrimitive(x.toString()) })
        val b = if (account.isEmpty()) body("kind" to JsonPrimitive(kind), "values" to v) else body("account" to JsonPrimitive(account), "values" to v)
        return write("/account/save", b, key)
    }

    /** Essayer un serveur CalDAV sans rien enregistrer ([account] : un compte à elle, son mot de passe gardé). */
    open suspend fun tryCaldav(url: String, username: String, password: String, account: String = ""): MoiApi.Result<TryResult> =
        api.post(
            "$A/account/try",
            body("url" to JsonPrimitive(url), "username" to JsonPrimitive(username), "password" to JsonPrimitive(password), "account" to JsonPrimitive(account)),
            null,
        ).decode(TryResult.serializer())

    open suspend fun googleStart(account: String): MoiApi.Result<AgendaDone> = write("/account/google/start", body("account" to JsonPrimitive(account)), null)

    /** Finir la connexion Google en collant l'adresse de la page qui n'a pas pu s'ouvrir (ou son code). */
    open suspend fun googleFinish(account: String, text: String): MoiApi.Result<AgendaDone> =
        write("/account/google/finish", body("account" to JsonPrimitive(account), "text" to JsonPrimitive(text)), null)

    open suspend fun microsoftStart(account: String): MoiApi.Result<AgendaDone> = write("/account/microsoft/start", body("account" to JsonPrimitive(account)), null)

    open suspend fun sync(account: String): MoiApi.Result<AgendaDone> = write("/account/sync", body("account" to JsonPrimitive(account)), null)

    open suspend fun disconnect(account: String): MoiApi.Result<AgendaDone> = write("/account/disconnect", body("account" to JsonPrimitive(account)), null)

    open suspend fun removeAccount(account: String): MoiApi.Result<AgendaDone> = write("/account/remove", body("account" to JsonPrimitive(account)), null)

    /** Un agenda de plus ([account] vide : son compte du système). */
    open suspend fun newCalendar(name: String, account: String = "", key: String? = MoiApi.newKey()): MoiApi.Result<AgendaDone> =
        write("/calendar/new", body("name" to JsonPrimitive(name), "account" to JsonPrimitive(account)), key)

    /** Régler un de ses agendas : seulement ce qui change ([changes] : `name`, `color`, `hidden`, `reminder`). */
    open suspend fun saveCalendar(calendar: String, changes: Map<String, Any>): MoiApi.Result<AgendaDone> =
        write(
            "/calendar/save",
            body("calendar" to JsonPrimitive(calendar)) + changes.mapValues { (_, x) -> if (x is Boolean) JsonPrimitive(x) else JsonPrimitive(x.toString()) },
            null,
        )

    // ── son tableau de droits ──

    open suspend fun rights(calendar: String): MoiApi.Result<AgendaRights> =
        api.get("$A/rights", mapOf("calendar" to calendar), AgendaRights.serializer())

    /** Le tableau entier (ses lignes, son défaut), sans leurs mots. */
    open suspend fun saveRights(calendar: String, lines: List<AgendaRule>, default: AgendaRule): MoiApi.Result<AgendaDone> {
        val rules = MikaJson.encodeToJsonElement(ListSerializer(AgendaRule.serializer()), lines.map { it.copy(words = null) })
        val def = MikaJson.encodeToJsonElement(AgendaRule.serializer(), default.copy(words = null))
        return write("/rights/save", body("calendar" to JsonPrimitive(calendar), "lines" to rules, "default" to def), null)
    }

    open suspend fun resetRights(calendar: String): MoiApi.Result<AgendaDone> =
        write("/rights/save", body("calendar" to JsonPrimitive(calendar), "reset" to JsonPrimitive(true)), null)

    // ── le partager (§ 9) ──

    /** Les personnes qui ont un compte, à qui partager. */
    open suspend fun people(): MoiApi.Result<People> = api.get("/people", reader = People.serializer())

    /** Partager un de ses agendas à [person], à [level] (vide : retirer le partage). */
    open suspend fun share(calendar: String, person: String, level: String): MoiApi.Result<AgendaDone> =
        api.post(
            "/shares/set",
            body("kind" to JsonPrimitive("agenda"), "key" to JsonPrimitive(calendar), "person" to JsonPrimitive(person), "level" to JsonPrimitive(level)),
            MoiApi.newKey(),
        ).decode(AgendaDone.serializer())

    private suspend fun write(path: String, body: JsonObject, key: String?): MoiApi.Result<AgendaDone> =
        api.post("$A$path", body, key).decode(AgendaDone.serializer())

    private companion object {
        const val A = "/agenda"

        fun body(vararg pairs: Pair<String, JsonElement>): JsonObject = JsonObject(linkedMapOf(*pairs))
    }
}

/** Deux corps réunis : les champs de [more] après ceux-ci. */
private operator fun JsonObject.plus(more: Map<String, JsonElement>): JsonObject = JsonObject(LinkedHashMap<String, JsonElement>(this).apply { putAll(more) })

/**
 * Ce qu'on écrit d'un événement (`create`, et ce qui change d'un `edit`) ; un champ `null` ne part pas. [reminders]
 * absent : ceux de l'agenda chez son fournisseur (une création), tels quels (une modification) ; une liste vide : aucun.
 */
data class EventFields(
    val title: String? = null,
    val start: String? = null,
    val end: String? = null,
    val allDay: Boolean? = null,
    val zone: String? = null,
    val location: String? = null,
    val description: String? = null,
    val conference: String? = null,
    val rule: String? = null,
    val invite: List<String>? = null,
    val free: Boolean? = null,
    val private: Boolean? = null,
    val remind: String? = null,
    val reminders: List<Alert>? = null,
) {
    val empty: Boolean get() = this == EventFields()

    fun json(): Map<String, JsonElement> = buildMap {
        title?.let { put("title", JsonPrimitive(it)) }
        start?.let { put("start", JsonPrimitive(it)) }
        end?.let { put("end", JsonPrimitive(it)) }
        allDay?.let { put("all_day", JsonPrimitive(it)) }
        zone?.let { put("zone", JsonPrimitive(it)) }
        location?.let { put("location", JsonPrimitive(it)) }
        description?.let { put("description", JsonPrimitive(it)) }
        conference?.let { put("conference", JsonPrimitive(it)) }
        rule?.let { put("rule", JsonPrimitive(it)) }
        invite?.let { put("invite", JsonArray(it.map(::JsonPrimitive))) }
        free?.let { put("free", JsonPrimitive(it)) }
        private?.let { put("private", JsonPrimitive(it)) }
        remind?.let { put("remind", JsonPrimitive(it)) }
        reminders?.let { list ->
            put("reminders", JsonArray(list.map { a -> JsonObject(mapOf("method" to JsonPrimitive(a.method), "minutes" to JsonPrimitive(a.minutes))) }))
        }
    }
}
