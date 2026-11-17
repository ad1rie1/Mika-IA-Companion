package fr.qwartz.mika.data.moi.carte

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

/** Le tracé d'un itinéraire (polyline à six décimales) : les mêmes cas que `frontendv2/src/map/polyline.test.ts`. */
class PolylineTest {
    // Les mêmes points que `backendv2/tests/unit/test_maps_routing.py`, encodés par `mika.ports.maps.encode_polyline6`.
    private val shape = listOf(LatLon(45.899543, 6.128952), LatLon(45.8, 6.05), LatLon(45.564275, 5.91769))
    private val shape6 = "mpnpvAorauJllaEneyCxkkMjlaG"
    // Des longitudes et latitudes à leurs bornes : rien ne déborde.
    private val far = listOf(LatLon(-33.868, 151.21), LatLon(51.5074, -0.1278), LatLon(0.0, 0.0), LatLon(89.999999, -179.999999))
    private val far6 = "~lcr_A_`cl_Hoy{yaDns|s_HnkwfaBorxF}fdtjD|niivI"

    @Test fun `se lit comme le serveur l'écrit`() {
        assertEquals(shape, decodePolyline6(shape6))
        assertEquals(far, decodePolyline6(far6))
        // l'exemple de l'algorithme (cinq décimales), lu à six : les mêmes chiffres, une décimale plus loin
        assertEquals(
            listOf(LatLon(3.85, -12.02), LatLon(4.07, -12.095), LatLon(4.3252, -12.6453)),
            decodePolyline6("_p~iF~ps|U_ulLnnqC_mqNvxq`@"),
        )
        assertEquals(emptyList<LatLon>(), decodePolyline6(""))
    }

    @Test fun `s'écrit comme le serveur`() {
        assertEquals(shape6, encodePolyline6(shape))
        assertEquals(far6, encodePolyline6(far))
        assertEquals(shape, decodePolyline6(encodePolyline6(shape)))
    }

    @Test fun `refuse un tracé tronqué ou illisible, safeDecode rend alors rien`() {
        assertEquals("un tracé tronqué", assertThrows(PolylineException::class.java) { decodePolyline6("_p~iF~ps|U_") }.message)
        assertEquals("un tracé illisible", assertThrows(PolylineException::class.java) { decodePolyline6("_p~iF~ps|U\u007f") }.message)
        assertEquals(emptyList<LatLon>(), safeDecode("_p~iF~ps|U_"))
        assertEquals(emptyList<LatLon>(), safeDecode(null))
        assertEquals(shape, safeDecode(shape6))
    }
}
