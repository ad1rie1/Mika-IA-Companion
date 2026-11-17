package fr.qwartz.mika.ui.carte

import fr.qwartz.mika.data.moi.carte.AlongState
import fr.qwartz.mika.data.moi.carte.Trip
import fr.qwartz.mika.data.moi.carte.TripDay
import fr.qwartz.mika.data.moi.carte.TripLeg
import fr.qwartz.mika.data.moi.carte.TripRoute
import fr.qwartz.mika.data.moi.carte.TripStop
import fr.qwartz.mika.data.moi.carte.alongPinId
import fr.qwartz.mika.data.moi.carte.legsByStop
import fr.qwartz.mika.data.moi.carte.stopCount

/*
 * Les lignes de l'éditeur d'un voyage, et où tomberait un arrêt qu'on glisse — sans Compose (`TripEditorRowsTest`).
 * L'écran ([TripScreen]) les pose dans sa liste, une clé par ligne, et lit sa mise en page pendant le glisser.
 */

/** Une ligne de l'éditeur : sa clé dans la liste, et ce qu'elle montre. */
internal sealed interface EditorRow {
    val key: String

    data object AlongHead : EditorRow { override val key = "along-head" }
    data class AlongPlace(val i: Int) : EditorRow { override val key = alongPinId(i) }
    data object AlongEnd : EditorRow { override val key = "along-end" }
    data class DayHead(val day: TripDay) : EditorRow { override val key = "day:${day.n}" }
    data class Leg(val day: Int, val to: String, val leg: TripLeg) : EditorRow { override val key = "leg:$to" }
    data class Stop(val day: Int, val stop: TripStop, val n: Int) : EditorRow { override val key = stopKey(stop.id) }
    data class Empty(val day: Int) : EditorRow { override val key = "empty:$day" }
    data class AddStop(val day: Int) : EditorRow { override val key = "add:$day" }
    data class AddDay(val day: Int) : EditorRow { override val key = "add-day" }
}

/** La clé de la ligne d'un arrêt. */
internal fun stopKey(id: String): String = "stop:$id"

/** Où tomberait l'arrêt glissé : ce jour, avant cet arrêt (`null` : à la fin du jour). */
internal data class DropTarget(val day: Int, val before: String?)

/** Une ligne telle que la liste l'a posée à l'écran : sa clé, son haut et sa hauteur (en pixels). */
internal data class RowBox(val key: Any, val offset: Int, val size: Int)

/** Les lignes de l'éditeur : « Sur la route » en tête quand il est ouvert, puis chaque jour, ses tronçons et ses arrêts. */
internal fun editorRows(trip: Trip, route: TripRoute?, along: AlongState, alongOpen: Boolean): List<EditorRow> = buildList {
    if (alongOpen && stopCount(trip) >= 2) {
        add(EditorRow.AlongHead)
        along.places.indices.forEach { add(EditorRow.AlongPlace(it)) }
        add(EditorRow.AlongEnd)
    }
    val legs = legsByStop(route)
    var n = 0
    for (d in trip.days) {
        add(EditorRow.DayHead(d))
        for (s in d.stops) {
            n += 1
            legs[s.id]?.let { add(EditorRow.Leg(d.n, s.id, it)) }
            add(EditorRow.Stop(d.n, s, n))
        }
        if (d.stops.isEmpty()) add(EditorRow.Empty(d.n))
        add(EditorRow.AddStop(d.n))
    }
    add(EditorRow.AddDay(trip.days.size + 1))
}

/**
 * Le jour et l'arrêt avant lequel tomberait l'arrêt [stop] glissé de [dy] pixels : le milieu de sa ligne, déplacé, et
 * la ligne posée dessous ([visible] : la mise en page du moment). Cette ligne se retrouve dans [rows] — la liste du
 * moment — **par sa clé**, jamais par sa place : des tronçons arrivés après l'ouverture, « Sur la route » ouvert, un
 * geste qui a changé l'ordre décalent les places, pas les clés.
 */
internal fun dropTarget(visible: List<RowBox>, rows: List<EditorRow>, stop: String, dy: Float): DropTarget? {
    val item = visible.firstOrNull { it.key == stopKey(stop) } ?: return null
    val y = item.offset + item.size / 2f + dy
    val under = visible.firstOrNull { y >= it.offset && y < it.offset + it.size } ?: return null
    val at = rows.indexOfFirst { it.key == under.key }
    if (at < 0) return null
    return when (val row = rows[at]) {
        is EditorRow.Stop -> if (y < under.offset + under.size / 2f) {
            DropTarget(row.day, row.stop.id)
        } else {
            // après lui : avant l'arrêt suivant du même jour, sinon à la fin du jour
            val next = rows.drop(at + 1).takeWhile { it !is EditorRow.AddStop }.firstOrNull { it is EditorRow.Stop } as? EditorRow.Stop
            DropTarget(row.day, next?.stop?.id)
        }
        is EditorRow.Leg -> DropTarget(row.day, row.to)
        is EditorRow.DayHead -> DropTarget(row.day.n, row.day.stops.firstOrNull()?.id)
        is EditorRow.Empty -> DropTarget(row.day, null)
        is EditorRow.AddStop -> DropTarget(row.day, null)
        else -> null
    }
}
