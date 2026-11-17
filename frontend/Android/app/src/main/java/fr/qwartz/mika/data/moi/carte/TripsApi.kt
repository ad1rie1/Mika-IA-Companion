package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.decode
import fr.qwartz.mika.data.moi.map
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.HttpUrl

/**
 * Tes voyages par l'API par personne (`protocole-moi.md` § 10, « Tes voyages » ; ADR 0195), sous le jeton de ce
 * téléphone. Un voyage est à toi seule : celui d'une autre personne n'existe pas (404). Chaque écriture porte sa clé
 * d'envoi (`Idempotency-Key`) : redite, le serveur ne la refait pas (une création redite rend le même `id`) ; un voyage
 * changé entre la lecture et l'écriture répond 409 (« La situation a changé… ») : relire, puis recommencer. Le trajet,
 * l'ordre d'un jour, les lieux le long d'un trajet calculé et le GPX comptent dans la borne des itinéraires (20 par
 * minute et par compte, 429 au-delà). Un identifiant qui n'est pas du serveur ne part pas (404, [refOf]). Ouverte : un
 * voyage ouvert se teste contre une fausse (`TripModelTest`).
 */
open class TripsApi(private val api: MoiApi) {
    open suspend fun list(): MoiApi.Result<List<TripSummary>> = api.get(PATH, reader = TripList.serializer()).map { it.trips }

    /** Un voyage neuf : son titre (120 caractères), sa date `AAAA-MM-JJ`, son mode, ce qu'il évite ; 50 au plus (409). */
    open suspend fun create(values: TripValues, key: String): MoiApi.Result<WriteDone> =
        write(PATH, body(values), key)

    open suspend fun read(id: String): MoiApi.Result<Trip> {
        val ref = refOf(id) ?: return missing()
        return api.get("$PATH/$ref", reader = Trip.serializer())
    }

    /** Ce que [values] nomme, seulement (`start` vide : plus de date ; rien de nommé : 400). */
    open suspend fun change(id: String, values: TripValues, key: String): MoiApi.Result<WriteDone> {
        val ref = refOf(id) ?: return missing()
        return write("$PATH/$ref", body(values), key)
    }

    /** Le supprimer, ses arrêts avec. */
    open suspend fun remove(id: String, key: String): MoiApi.Result<WriteDone> {
        val ref = refOf(id) ?: return missing()
        return write("$PATH/$ref/supprimer", JsonObject(emptyMap()), key)
    }

    /** Un arrêt au jour `day`, à la place `index` de ce jour ; 60 arrêts au plus (409) ; sa note : 500 caractères. */
    open suspend fun addStop(id: String, stop: NewStop, key: String): MoiApi.Result<WriteDone> {
        val ref = refOf(id) ?: return missing()
        val fields = linkedMapOf(
            "name" to JsonPrimitive(stop.name),
            "lat" to JsonPrimitive(stop.lat),
            "lon" to JsonPrimitive(stop.lon),
            "kind" to JsonPrimitive(stop.kind),
            "day" to JsonPrimitive(stop.day),
            "index" to JsonPrimitive(stop.index),
        )
        if (stop.note.isNotEmpty()) fields["note"] = JsonPrimitive(stop.note)
        return write("$PATH/$ref/arrets", JsonObject(fields), key)
    }

    /** Déplacer un arrêt au jour [day], à la place [index] parmi les **autres** arrêts de ce jour (−1 : à la fin). */
    open suspend fun moveStop(id: String, stop: String, day: Int, index: Int, key: String): MoiApi.Result<WriteDone> {
        val path = stopPath(id, stop) ?: return missing()
        return write(path, JsonObject(mapOf("day" to JsonPrimitive(day), "index" to JsonPrimitive(index))), key)
    }

    /** Sa note (vide : plus de note). */
    open suspend fun noteStop(id: String, stop: String, note: String, key: String): MoiApi.Result<WriteDone> {
        val path = stopPath(id, stop) ?: return missing()
        return write(path, JsonObject(mapOf("note" to JsonPrimitive(note))), key)
    }

    open suspend fun removeStop(id: String, stop: String, key: String): MoiApi.Result<WriteDone> {
        val path = stopPath(id, stop) ?: return missing()
        return write("$path/retirer", JsonObject(emptyMap()), key)
    }

    /** Les tronçons d'un arrêt au suivant, rangés au jour de leur arrivée (503 sans itinéraires). */
    open suspend fun route(id: String): MoiApi.Result<TripRoute> {
        val ref = refOf(id) ?: return missing()
        return api.get("$PATH/$ref/trajet", reader = TripRoute.serializer())
    }

    /** Le meilleur ordre de ce jour, appliqué (son premier et son dernier arrêt restent) ; plus de 20 arrêts : 400. */
    open suspend fun optimize(id: String, day: Int, key: String): MoiApi.Result<WriteDone> {
        val ref = refOf(id) ?: return missing()
        return write("$PATH/$ref/ordre", JsonObject(mapOf("day" to JsonPrimitive(day))), key)
    }

    /**
     * Les lieux à moins de [corridor] mètres (200 à 50 000) du trajet de tout le voyage ([day] 0) ou d'un jour, dans
     * l'ordre où on les croise, d'une catégorie ([cat]) ; [limit] : 1 à 50.
     */
    open suspend fun along(id: String, cat: String = "", day: Int = 0, corridor: Int = CORRIDOR_M, limit: Int = ALONG_LIMIT): MoiApi.Result<Along> {
        val ref = refOf(id) ?: return missing()
        return api.get(
            "$PATH/$ref/sur-la-route",
            linkedMapOf(
                "cat" to cat,
                "day" to day.toString(),
                "corridor" to corridor.coerceIn(200, 50_000).toString(),
                "limit" to limit.coerceIn(1, CarteApi.LIMIT_MAX).toString(),
            ),
            Along.serializer(),
        )
    }

    /** L'adresse du GPX du voyage (sur le serveur de la session : ses arrêts, et le tracé quand il se calcule). */
    open fun gpxUrl(id: String): HttpUrl? = refOf(id)?.let { api.url("$PATH/$it/gpx") }

    private fun stopPath(id: String, stop: String): String? {
        val trip = refOf(id) ?: return null
        val s = refOf(stop) ?: return null
        return "$PATH/$trip/arrets/$s"
    }

    private suspend fun write(path: String, body: JsonObject, key: String): MoiApi.Result<WriteDone> =
        api.post(path, body, key).decode(WriteDone.serializer())

    private fun <T> missing(): MoiApi.Result<T> = MoiApi.Result.Failed(MoiError(404, NOT_HERE))

    companion object {
        const val PATH = "/voyages"

        /** Le corps d'un voyage réglé : ce qui n'est pas `null`, seulement ; ce qu'il évite en liste. */
        internal fun body(values: TripValues): JsonObject {
            val fields = linkedMapOf<String, kotlinx.serialization.json.JsonElement>()
            values.title?.let { fields["title"] = JsonPrimitive(it) }
            values.start?.let { fields["start"] = JsonPrimitive(it) }
            values.mode?.let { fields["mode"] = JsonPrimitive(it) }
            values.avoid?.let { list -> fields["avoid"] = JsonArray(list.map { JsonPrimitive(it) }) }
            return JsonObject(fields)
        }
    }
}

/** La largeur du couloir de « Sur la route », en mètres (les mots de la maquette : « à moins de 10 km »). */
const val CORRIDOR_M = 10_000

/** Combien de lieux « Sur la route » demande. */
const val ALONG_LIMIT = 12
