package fr.qwartz.mika.data.moi.carte

/*
 * La carte miniature d'un voyage ou d'un regard de Mika (ADR 0196), sans Compose, portée de `frontendv2/src/map/cards.ts`
 * et `minis.ts` : ce qu'elle montre (un voyage — ses arrêts reliés —, ses lieux, le trajet qu'elle a gardé), son titre,
 * ce qu'elle est, ce qu'elle ouvre dans l'écran Carte, et les places des cartes vivantes (quatre à la fois). Rien n'y
 * demande d'itinéraire : un voyage s'y dessine en reliant ses arrêts, un regard avec le tracé résumé qu'elle a gardé.
 * La liste des voyages s'en sert ; le chat (ses notes de carte sous ses bulles, lot 7) s'en servira.
 */

/** Une note de carte d'un de ses messages : un voyage (`trip`), ce qu'elle a cherché (`look`) ou montré (`map`). */
object MapNoteKind {
    const val TRIP = "trip"
    const val LOOK = "look"
    const val MAP = "map"

    val ALL = setOf(TRIP, LOOK, MAP)
}

/** Ce qu'une miniature montre : sa sorte et ce qu'elle désigne ([ref] : l'identifiant d'un voyage, le `seq` d'un regard). */
data class MiniRef(val kind: String, val ref: String) {
    /** Ce que la miniature garde d'une lecture à l'autre : `trip:640`, `look:812`. */
    val id: String get() = "$kind:$ref"

    companion object {
        fun trip(id: String) = MiniRef(MapNoteKind.TRIP, id)
    }
}

/**
 * Ce qu'une miniature ouvre dans l'écran Carte : un voyage ([trip]), sinon l'onglet [tab] sur un regard ([look]).
 * L'interface le traduit en route (`ui/carte/CarteMinis.kt`).
 */
data class MiniOpen(val trip: String = "", val tab: String = "explorer", val look: String = "")

/** Ce qu'une note ouvre : le voyage, ou le regard (ses lieux dans Explorer). */
fun noteOpen(ref: MiniRef): MiniOpen =
    if (ref.kind == MapNoteKind.TRIP) MiniOpen(trip = ref.ref) else MiniOpen(tab = "explorer", look = ref.ref)

/** Ce qu'une miniature montre, une fois lu. */
data class MiniData(
    val title: String,
    val sub: String,
    val opens: MiniOpen,
    val scene: Scene = Scene.EMPTY,
    /** Plus là (un voyage supprimé, un regard oublié depuis). */
    val gone: Boolean = false,
    /** Le dernier changement de ce qu'elle montre (un voyage : son `updated`, en ms) ; un regard ne change pas. */
    val version: Long? = null,
)

/** Un voyage, en miniature : ses arrêts numérotés (roses : les siens), reliés à vol d'oiseau. */
fun tripMini(trip: Trip): MiniData {
    val pins = tripPins(trip)
    val hers = hersCount(trip)
    val line = straightLine(pins.map { LatLon(it.lat, it.lon) })
    val sub = listOfNotNull(
        plural(trip.days.size.toLong(), "jour"),
        plural(stopCount(trip).toLong(), "arrêt"),
        if (hers > 0) "$hers de Mika" else null,
    ).joinToString(" · ")
    return MiniData(
        title = "Voyage · ${trip.title.ifBlank { "sans titre" }}",
        sub = sub,
        opens = MiniOpen(trip = trip.id),
        scene = Scene(pins = pins, lines = listOfNotNull(line)),
        version = trip.updated,
    )
}

/** Les lieux d'un regard (ou d'une carte), tels qu'elle les a gardés : ses épingles, roses ; [numbered] : A, 1, 2…, B. */
fun regardPins(regard: Regard, numbered: Boolean = false): List<ScenePin> = regard.places.mapIndexedNotNull { i, p ->
    val at = p.at ?: return@mapIndexedNotNull null
    val label = if (!numbered) "" else pointLetter(i, regard.places.size)
    ScenePin(placeId(p, i), at.lat, at.lon, label = label, mika = true, title = p.name)
}

/** Le tracé d'un regard : celui qu'elle a gardé, sinon ses lieux reliés (une carte qui relie sans tracé calculé). */
fun regardLine(regard: Regard): List<SceneLine> {
    val route = regard.route ?: return emptyList()
    val shape = safeDecode(route.shape)
    if (shape.size >= 2) return listOf(SceneLine(shape, mika = true))
    val line = straightLine(regard.places.mapNotNull { it.at }) ?: return emptyList()
    return listOf(line.copy(mika = true))
}

/** Un regard en miniature : ses lieux en rose, son trajet ; ce qu'il ouvre (son voyage, Itinéraire pour un trajet, sinon Explorer). */
fun regardMini(seq: String, regard: Regard): MiniData {
    val route = regard.isRoute
    val pins = regardPins(regard, numbered = route)
    val lines = regardLine(regard)
    val r = regard.route
    val trip = if (r != null) listOf(km(r.distanceM), duration(r.durationS)).filter { it.isNotBlank() }.joinToString(" · ") else ""
    val how = r?.mode?.let { modeWords(it) }.orEmpty()
    val places = plural(pins.size.toLong(), "lieu", "lieux")
    val sub = when {
        route -> listOf("Mika a calculé le trajet", listOf(trip, how).filter { it.isNotBlank() }.joinToString(" "))
            .filter { it.isNotBlank() }.joinToString(" · ")
        regard.kind == Regard.KIND_LOOK -> "Mika a cherché · $places"
        else -> listOf("Une carte de Mika", places, trip).filter { it.isNotBlank() }.joinToString(" · ")
    }
    val opens = when {
        regard.trip.isNotBlank() -> MiniOpen(trip = regard.trip)
        route -> MiniOpen(tab = "itineraire", look = seq)
        else -> MiniOpen(tab = "explorer", look = seq)
    }
    return MiniData(regard.title.ifBlank { "Sa carte" }, sub, opens, Scene(pins = pins, lines = lines))
}

/** Avant d'être lue : le texte de la note ([text]), et ce qu'elle est. */
fun pendingMini(ref: MiniRef, text: String): MiniData {
    val sub = when (ref.kind) {
        MapNoteKind.TRIP -> "Un voyage préparé avec Mika"
        MapNoteKind.MAP -> "Une carte de Mika"
        else -> "Ce que Mika a cherché"
    }
    return MiniData(if (ref.kind == MapNoteKind.TRIP) "Voyage · $text" else text, sub, noteOpen(ref))
}

/** Plus là : le voyage supprimé, le regard oublié. */
fun goneMini(ref: MiniRef, text: String = ""): MiniData = pendingMini(ref, text).copy(
    sub = if (ref.kind == MapNoteKind.TRIP) "Ce voyage n'existe plus." else "Ce qu'elle avait vu n'est plus là.",
    gone = true,
)

/** Combien de miniatures vivantes à la fois (chacune tient une carte MapLibre ; au-delà, le plan reste). */
const val MAX_LIVE_MINIS = 4

/** Une lecture de miniature qui a échoué ne se refait pas avant. */
const val MINI_RETRY_MS = 30_000L

/** Les places des cartes vivantes : au plus [max] ; une miniature qui sort de la vue rend la sienne. */
class MiniPool(val max: Int = MAX_LIVE_MINIS) {
    private val live = LinkedHashSet<String>()

    val size: Int get() = live.size

    fun has(key: String): Boolean = key in live

    /** Une place pour cette miniature (elle l'a déjà, ou il en reste une). */
    fun take(key: String): Boolean {
        if (key in live) return true
        if (live.size >= max) return false
        live.add(key)
        return true
    }

    fun give(key: String) {
        live.remove(key)
    }
}
