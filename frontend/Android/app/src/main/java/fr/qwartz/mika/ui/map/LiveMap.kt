package fr.qwartz.mika.ui.map

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.PointF
import android.graphics.RectF
import android.view.MotionEvent
import androidx.core.view.doOnNextLayout
import fr.qwartz.mika.data.moi.carte.Bounds
import fr.qwartz.mika.data.moi.carte.CarteStyle
import fr.qwartz.mika.data.moi.carte.LatLon
import fr.qwartz.mika.data.moi.carte.LiveFailure
import fr.qwartz.mika.data.moi.carte.MapFond
import fr.qwartz.mika.data.moi.carte.Scene
import fr.qwartz.mika.data.moi.carte.TileWatch
import fr.qwartz.mika.data.moi.carte.circle
import fr.qwartz.mika.data.moi.carte.cleanScene
import fr.qwartz.mika.data.moi.carte.framingFor
import fr.qwartz.mika.data.moi.carte.hereFocus
import fr.qwartz.mika.data.moi.carte.hereRadius
import fr.qwartz.mika.data.moi.carte.pinRank
import fr.qwartz.mika.data.moi.carte.sceneBounds
import fr.qwartz.mika.data.moi.carte.sceneFraming
import fr.qwartz.mika.data.moi.carte.sceneKey
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import org.maplibre.android.camera.CameraPosition
import org.maplibre.android.camera.CameraUpdate
import org.maplibre.android.camera.CameraUpdateFactory
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.geometry.LatLngBounds
import org.maplibre.android.maps.MapLibreMap
import org.maplibre.android.maps.MapLibreMapOptions
import org.maplibre.android.maps.MapView
import org.maplibre.android.maps.Style
import org.maplibre.android.style.expressions.Expression
import org.maplibre.android.style.layers.CircleLayer
import org.maplibre.android.style.layers.FillLayer
import org.maplibre.android.style.layers.LineLayer
import org.maplibre.android.style.layers.Property
import org.maplibre.android.style.layers.PropertyFactory
import org.maplibre.android.style.layers.SymbolLayer
import org.maplibre.android.style.sources.GeoJsonSource
import org.maplibre.android.tile.TileOperation
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** Sans rien à montrer ni zone servie : la France. */
private val FRANCE = LatLon(46.6, 2.35)
private const val FRANCE_ZOOM = 5.0
/** Le zoom le plus fin qu'on laisse atteindre (au-delà, le fond n'a plus rien à dire). */
private const val MAX_ZOOM = 19.0
/** La durée d'un cadrage animé, comme le web. */
private const val EASE_MS = 600
/** On touche une épingle d'un peu plus loin que son dessin. */
private const val TOUCH_DP = 14f

// les sources et les calques que l'app pose par-dessus le fond, dans cet ordre (le cercle sous les tracés, la position
// sous les épingles)
private const val SRC_ZONE = "mika-ici-zone"
private const val SRC_LINES = "mika-lignes"
private const val SRC_HERE = "mika-ici"
private const val SRC_PINS = "mika-epingles"
private const val L_ZONE = "mika-ici-zone"
private const val L_ZONE_EDGE = "mika-ici-bord"
private const val L_LINE_EDGE = "mika-lignes-bord"
private const val L_LINE = "mika-lignes-trait"
private const val L_LINE_STRAIGHT = "mika-lignes-droites"
private const val L_HERE_HALO = "mika-ici-halo"
private const val L_HERE = "mika-ici-point"
private const val L_PINS = "mika-epingles"

/** Les marges que l'écran pose sur sa carte (la recherche en haut, la feuille en bas), en pixels. */
internal data class MapInsets(val left: Int = 0, val top: Int = 0, val right: Int = 0, val bottom: Int = 0)

/**
 * Une carte MapLibre et ce que l'app pose dessus (ADR 0193, 0194), tenue hors de Compose : le style du fond (un autre
 * thème, un autre fond servi : reposé, et la scène avec), la scène — épingles en images, tracés, la position et le
 * cercle de sa précision —, ses cadrages, les touchers, et ses échecs (des tuiles en échec de suite, un style qui ne se
 * lit pas) qui rendent la main au plan. Porté de `frontend/Web/src/map/view.ts` et `base.ts`. Le nord reste en haut : ni
 * rotation ni inclinaison, aucune boussole pour y revenir.
 */
internal class LiveMapHolder(val view: MapView, private val interactive: Boolean, private val density: Float) {
    var map: MapLibreMap? = null
        private set
    private var style: Style? = null
    private var styleJson: String? = null
    private var scene: Scene = Scene.EMPTY
    private var key = ""
    private var colors: MapColors? = null
    private var fond: MapFond? = null
    private val images = HashSet<String>()
    private val watch = TileWatch()
    private var failed = false
    private var framed = false
    private var gestured = false
    private var pendingFit: Boolean? = null
    var insets = MapInsets()

    var onPin: ((String) -> Unit)? = null
    var onMove: (() -> Unit)? = null
    var onFail: ((LiveFailure) -> Unit)? = null

    init {
        // les tuiles du fond : une lue remet le compte à zéro, une série en échec rend la main au plan
        view.addOnTileActionListener { op, _, _, _, _, _, source ->
            if (source != CarteStyle.SOURCE) return@addOnTileActionListener
            when (op) {
                TileOperation.Error -> view.post { if (watch.error()) fail(LiveFailure.TILES) }
                TileOperation.LoadFromNetwork, TileOperation.LoadFromCache -> view.post { watch.ok() }
                else -> Unit
            }
        }
        view.addOnDidFailLoadingMapListener { view.post { fail(LiveFailure.STYLE) } }
        // une icône que la planche n'a pas (le style la demande pour une sorte de lieu) : une image vide, sans bruit
        view.addOnStyleImageMissingListener { id ->
            val s = style ?: return@addOnStyleImageMissingListener
            if (id.isNotEmpty() && s.getImage(id) == null) s.addImage(id, PinImages.blank())
        }
        view.getMapAsync { m -> ready(m) }
    }

    private fun ready(m: MapLibreMap) {
        map = m
        m.uiSettings.apply {
            isCompassEnabled = false
            isLogoEnabled = false
            isAttributionEnabled = false
            isRotateGesturesEnabled = false
            isTiltGesturesEnabled = false
            if (!interactive) setAllGesturesEnabled(false)
        }
        m.setMaxZoomPreference(MAX_ZOOM)
        m.addOnCameraMoveStartedListener { reason ->
            if (reason == MapLibreMap.OnCameraMoveStartedListener.REASON_API_GESTURE) gestured = true
        }
        m.addOnCameraIdleListener {
            if (gestured) {
                gestured = false
                onMove?.invoke() // la personne l'a bougée, pas un cadrage de l'écran
            }
        }
        if (interactive) m.addOnMapClickListener { at -> pinAt(at)?.let { onPin?.invoke(it); true } ?: false }
        styleJson?.let { json ->
            styleJson = null
            setStyle(json)
        }
    }

    /** Le style du fond (un autre thème, un autre fond servi) : reposé, la scène et ses cadrages avec. */
    fun setStyle(json: String, fond: MapFond? = this.fond) {
        if (fond != this.fond) {
            this.fond = fond
            watch.reset()
        }
        if (json == styleJson) return
        styleJson = json
        val m = map ?: return
        style = null
        images.clear()
        m.setStyle(Style.Builder().fromJson(json)) { s ->
            if (styleJson != json) return@setStyle // un autre style est parti depuis
            style = s
            addOverlay(s)
            applyScene(s)
            val fit = pendingFit
            if (!framed || fit != null) {
                val first = !framed
                framed = true
                pendingFit = null
                fit(animate = false, orBase = fit ?: scene.isEmpty, first = first)
            }
        }
    }

    /** Les couleurs du thème : la scène se repose avec elles (le style, lui, suit le même thème). */
    fun setColors(next: MapColors) {
        if (next == colors) return
        colors = next
        style?.let { s ->
            removeOverlay(s)
            images.clear()
            addOverlay(s)
            applyScene(s)
        }
    }

    /** Une autre scène : ses épingles et ses tracés, reposés (rien de changé : rien à reposer). */
    fun show(next: Scene) {
        val clean = cleanScene(next)
        val k = sceneKey(clean)
        if (k == key) return
        key = k
        scene = clean
        style?.let { applyScene(it) }
    }

    /**
     * Cadrer la scène. Une position seule et sa précision : centrée — au zoom qui montre son cercle la première fois
     * ([first]), ensuite au zoom où on l'a laissée. Rien à montrer : la vue reste, sauf [orBase] : la zone du fond servi,
     * sinon la France.
     */
    fun fit(animate: Boolean, orBase: Boolean = false, first: Boolean = false) {
        val m = map
        if (m == null || style == null) {
            pendingFit = orBase
            return
        }
        if (view.width <= 0 || view.height <= 0) {
            // pas encore mesurée : le cadrage attend sa taille
            view.doOnNextLayout { fit(animate = false, orBase = orBase, first = first) }
            return
        }
        val ms = if (animate && interactive) EASE_MS else 0
        hereFocus(scene)?.let { f ->
            val at = LatLng(f.center.lat, f.center.lon)
            move(m, if (first) CameraUpdateFactory.newLatLngZoom(at, f.zoom) else CameraUpdateFactory.newLatLng(at), ms)
            return
        }
        val framing = sceneFraming(scene, interactive)
        val bounds = framing?.bounds ?: (if (orBase) fond?.zone else null)
        if (bounds == null) {
            if (orBase) move(m, CameraUpdateFactory.newLatLngZoom(LatLng(FRANCE.lat, FRANCE.lon), FRANCE_ZOOM), ms)
            return
        }
        val f = framing?.framing ?: framingFor(interactive)
        val pad = (f.paddingDp * density).roundToInt()
        val camera = cameraFor(m, bounds, pad) ?: return
        val maxZoom = if (framing != null) f.maxZoom else (fond?.maxzoom?.toDouble() ?: f.maxZoom)
        val target = if (camera.zoom > maxZoom) CameraPosition.Builder(camera).zoom(maxZoom).build() else camera
        move(m, CameraUpdateFactory.newCameraPosition(target), ms)
    }

    /** Amener ce point à l'écran, au même zoom, s'il est hors de ce que la carte montre. */
    fun reveal(point: LatLon) {
        val m = map ?: return
        val b = frame() ?: return
        if (point.lat in b.south..b.north && point.lon in b.west..b.east) return
        move(m, CameraUpdateFactory.newLatLng(LatLng(point.lat, point.lon)), if (interactive) EASE_MS else 0)
    }

    /** Ce que la carte montre en ce moment, sans ce que la recherche et la feuille couvrent (ouest, sud, est, nord). */
    fun frame(): Bounds? {
        val m = map ?: return null
        val w = view.width
        val h = view.height
        if (w <= 0 || h <= 0) return null
        var top = insets.top.toFloat()
        var bottom = (h - insets.bottom).toFloat()
        if (bottom - top < 48 * density) {
            top = 0f
            bottom = h.toFloat()
        }
        val a = m.projection.fromScreenLocation(PointF(insets.left.toFloat(), top))
        val b = m.projection.fromScreenLocation(PointF((w - insets.right).toFloat(), bottom))
        return Bounds(
            max(-180.0, min(a.longitude, b.longitude)),
            max(-90.0, min(a.latitude, b.latitude)),
            min(180.0, max(a.longitude, b.longitude)),
            min(90.0, max(a.latitude, b.latitude)),
        )
    }

    /** La carte ne se dessine pas ici : dit une fois, l'écran reprend son plan. */
    private fun fail(why: LiveFailure) {
        if (failed) return
        failed = true
        onFail?.invoke(why)
    }

    /** La caméra qui tient cette zone dans ce que rien ne couvre, avec sa marge ; une vue pas encore mesurée : rien. */
    private fun cameraFor(m: MapLibreMap, b: Bounds, pad: Int): CameraPosition? {
        val w = view.width
        val h = view.height
        if (w <= 0 || h <= 0) return null
        var left = insets.left + pad
        var top = insets.top + pad
        var right = insets.right + pad
        var bottom = insets.bottom + pad
        // une feuille haute et une recherche : il reste au moins un quart de la carte, sinon les marges cèdent
        val minSide = (64 * density).roundToInt()
        if (w - left - right < minSide) {
            left = pad
            right = pad
        }
        if (h - top - bottom < minSide) {
            top = min(top, h / 4)
            bottom = min(bottom, h / 4)
        }
        val bounds = LatLngBounds.from(b.north, b.east, b.south, b.west)
        return m.getCameraForLatLngBounds(bounds, intArrayOf(left, top, right, bottom))
    }

    private fun move(m: MapLibreMap, update: CameraUpdate, ms: Int) {
        if (ms > 0) m.easeCamera(update, ms) else m.moveCamera(update)
    }

    /** L'épingle sous le doigt (la plus haute, s'il y en a plusieurs), sinon `null`. */
    private fun pinAt(at: LatLng): String? {
        val m = map ?: return null
        if (style == null) return null
        val p = m.projection.toScreenLocation(at)
        val r = TOUCH_DP * density
        val hits = m.queryRenderedFeatures(RectF(p.x - r, p.y - r, p.x + r, p.y + r), L_PINS)
        return hits.maxByOrNull { it.getNumberProperty("rank")?.toDouble() ?: 0.0 }?.getStringProperty("id")
    }

    // ── Ce qui se pose par-dessus le fond ────────────────────────────────

    private fun addOverlay(s: Style) {
        val c = colors ?: return
        s.addSource(GeoJsonSource(SRC_ZONE, empty()))
        s.addLayer(FillLayer(L_ZONE, SRC_ZONE).withProperties(PropertyFactory.fillColor(c.accent), PropertyFactory.fillOpacity(0.14f)))
        s.addLayer(
            LineLayer(L_ZONE_EDGE, SRC_ZONE).withProperties(
                PropertyFactory.lineColor(c.accent),
                PropertyFactory.lineOpacity(0.5f),
                PropertyFactory.lineWidth(1.5f),
            ),
        )
        s.addSource(GeoJsonSource(SRC_LINES, empty()))
        val routed = Expression.not(Expression.toBool(Expression.get("straight")))
        val color = Expression.switchCase(Expression.toBool(Expression.get("mika")), Expression.color(c.mika), Expression.color(c.accent))
        s.addLayer(
            LineLayer(L_LINE_EDGE, SRC_LINES).withFilter(routed).withProperties(
                PropertyFactory.lineCap(Property.LINE_CAP_ROUND),
                PropertyFactory.lineJoin(Property.LINE_JOIN_ROUND),
                PropertyFactory.lineColor(c.raised),
                PropertyFactory.lineWidth(7f),
                PropertyFactory.lineOpacity(0.9f),
            ),
        )
        s.addLayer(
            LineLayer(L_LINE, SRC_LINES).withFilter(routed).withProperties(
                PropertyFactory.lineCap(Property.LINE_CAP_ROUND),
                PropertyFactory.lineJoin(Property.LINE_JOIN_ROUND),
                PropertyFactory.lineColor(color),
                PropertyFactory.lineWidth(4f),
            ),
        )
        s.addLayer(
            LineLayer(L_LINE_STRAIGHT, SRC_LINES).withFilter(Expression.toBool(Expression.get("straight"))).withProperties(
                PropertyFactory.lineCap(Property.LINE_CAP_ROUND),
                PropertyFactory.lineColor(color),
                PropertyFactory.lineWidth(2.5f),
                PropertyFactory.lineOpacity(0.75f),
                PropertyFactory.lineDasharray(arrayOf(1.4f, 2f)),
            ),
        )
        s.addSource(GeoJsonSource(SRC_HERE, empty()))
        s.addLayer(
            CircleLayer(L_HERE_HALO, SRC_HERE).withProperties(
                PropertyFactory.circleRadius(16f),
                PropertyFactory.circleColor(c.accent),
                PropertyFactory.circleOpacity(0.18f),
            ),
        )
        s.addLayer(
            CircleLayer(L_HERE, SRC_HERE).withProperties(
                PropertyFactory.circleRadius(7f),
                PropertyFactory.circleColor(c.accent),
                PropertyFactory.circleStrokeColor(c.raised),
                PropertyFactory.circleStrokeWidth(3f),
            ),
        )
        s.addSource(GeoJsonSource(SRC_PINS, empty()))
        s.addLayer(
            SymbolLayer(L_PINS, SRC_PINS).withProperties(
                PropertyFactory.iconImage(Expression.get("icon")),
                PropertyFactory.iconAllowOverlap(true),
                PropertyFactory.iconIgnorePlacement(true),
                PropertyFactory.symbolSortKey(Expression.get("rank")),
            ),
        )
    }

    private fun removeOverlay(s: Style) {
        for (id in listOf(L_PINS, L_HERE, L_HERE_HALO, L_LINE_STRAIGHT, L_LINE, L_LINE_EDGE, L_ZONE_EDGE, L_ZONE)) s.removeLayer(id)
        for (id in listOf(SRC_PINS, SRC_HERE, SRC_LINES, SRC_ZONE)) s.removeSource(id)
    }

    private fun applyScene(s: Style) {
        val c = colors ?: return
        // les images d'abord : un symbole posé sans la sienne serait comblé d'une image vide
        for (p in scene.pins) {
            val name = PinImages.name(p, c)
            if (images.add(name)) s.addImage(name, PinImages.bitmap(p, c, density))
        }
        s.getSourceAs<GeoJsonSource>(SRC_ZONE)?.setGeoJson(zoneJson(scene))
        s.getSourceAs<GeoJsonSource>(SRC_LINES)?.setGeoJson(linesJson(scene))
        s.getSourceAs<GeoJsonSource>(SRC_HERE)?.setGeoJson(hereJson(scene))
        s.getSourceAs<GeoJsonSource>(SRC_PINS)?.setGeoJson(pinsJson(scene, c))
    }

    companion object {
        /**
         * Une carte MapLibre pour cet écran ; MapLibre qui ne se charge pas sur ce téléphone : `null`, le plan. [texture] :
         * dans une page qui défile (la Position du Téléphone), une vue de texture plutôt qu'une surface, qui défile avec
         * elle.
         */
        fun create(context: Context, scene: Scene, fond: MapFond, interactive: Boolean, texture: Boolean): MapView? {
            val options = MapLibreMapOptions.createFromAttributes(context)
                .textureMode(texture)
                .compassEnabled(false)
                .logoEnabled(false)
                .attributionEnabled(false)
                .rotateGesturesEnabled(false)
                .tiltGesturesEnabled(false)
                .maxZoomPreference(MAX_ZOOM)
                .camera(initialCamera(scene, fond))
            return try {
                MapView(context, options).also { it.onCreate(null) }
            } catch (_: LinkageError) {
                null
            } catch (_: RuntimeException) {
                null
            }
        }

        /** Où regarder avant le premier cadrage : la scène, sinon la zone du fond, sinon la France. */
        private fun initialCamera(scene: Scene, fond: MapFond): CameraPosition {
            val clean = cleanScene(scene)
            hereFocus(clean)?.let { return CameraPosition.Builder().target(LatLng(it.center.lat, it.center.lon)).zoom(it.zoom).build() }
            val b = sceneBounds(clean) ?: fond.zone
            if (b == null) return CameraPosition.Builder().target(LatLng(FRANCE.lat, FRANCE.lon)).zoom(FRANCE_ZOOM).build()
            val zoom = if (sceneBounds(clean) != null) 12.0 else 6.0
            return CameraPosition.Builder().target(LatLng((b.south + b.north) / 2, (b.west + b.east) / 2)).zoom(zoom).build()
        }

        /** Rendre le doigt à la carte dans une page qui défile : ses glissés la déplacent, sans faire défiler la page. */
        @SuppressLint("ClickableViewAccessibility") // aucun clic ici : le toucher continue vers la carte (false)
        fun holdTouches(view: MapView) {
            view.setOnTouchListener { v, e ->
                if (e.actionMasked == MotionEvent.ACTION_DOWN) v.parent?.requestDisallowInterceptTouchEvent(true)
                false
            }
        }
    }
}

// ── La scène en GeoJSON (lon, lat) ──────────────────────────────────────

private fun empty(): String = collection(JsonArray(emptyList()))

private fun collection(features: JsonArray): String =
    buildJsonObject { put("type", "FeatureCollection"); put("features", features) }.toString()

private fun feature(geometry: JsonObject, properties: JsonObject = JsonObject(emptyMap())): JsonObject = buildJsonObject {
    put("type", "Feature")
    put("properties", properties)
    put("geometry", geometry)
}

private fun position(lat: Double, lon: Double) = buildJsonArray { add(JsonPrimitive(lon)); add(JsonPrimitive(lat)) }

/** Les épingles : leur image, leur rang (la choisie au-dessus), ce qu'un toucher vise. */
internal fun pinsJson(scene: Scene, colors: MapColors): String = collection(
    buildJsonArray {
        for (p in scene.pins) {
            add(
                feature(
                    buildJsonObject { put("type", "Point"); put("coordinates", position(p.lat, p.lon)) },
                    buildJsonObject {
                        put("id", p.id)
                        put("icon", PinImages.name(p, colors))
                        put("rank", pinRank(p))
                    },
                ),
            )
        }
    },
)

/** Les tracés : roses pour ce qu'elle a montré, en pointillés à vol d'oiseau. */
internal fun linesJson(scene: Scene): String = collection(
    buildJsonArray {
        for (l in scene.lines) {
            add(
                feature(
                    buildJsonObject {
                        put("type", "LineString")
                        putJsonArray("coordinates") { for (p in l.points) add(position(p.lat, p.lon)) }
                    },
                    buildJsonObject { put("mika", l.mika); put("straight", l.straight) },
                ),
            )
        }
    },
)

/** La position, un point ; sans elle, rien. */
internal fun hereJson(scene: Scene): String {
    val here = scene.here ?: return empty()
    return collection(buildJsonArray { add(feature(buildJsonObject { put("type", "Point"); put("coordinates", position(here.lat, here.lon)) })) })
}

/** Le cercle de sa précision, en polygone ; sans position ou sans rayon, rien. */
internal fun zoneJson(scene: Scene): String {
    val here = scene.here ?: return empty()
    val r = hereRadius(here)
    if (r <= 0) return empty()
    val ring = circle(here.lat, here.lon, r)
    return collection(
        buildJsonArray {
            add(
                feature(
                    buildJsonObject {
                        put("type", "Polygon")
                        putJsonArray("coordinates") { add(buildJsonArray { for (p in ring) add(position(p.lat, p.lon)) }) }
                    },
                ),
            )
        },
    )
}
