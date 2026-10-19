package fr.qwartz.mika.core

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Address
import android.location.Geocoder
import android.location.Location
import android.location.LocationManager
import android.os.Build
import androidx.core.content.ContextCompat
import androidx.core.location.LocationListenerCompat
import androidx.core.location.LocationManagerCompat
import androidx.core.location.LocationRequestCompat
import fr.qwartz.mika.data.location.PlaceLabel
import fr.qwartz.mika.data.location.WhereShare
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.mapLatest
import kotlinx.coroutines.runInterruptible
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import java.io.IOException
import java.util.Locale
import kotlin.coroutines.resume

/**
 * La position du téléphone pour « Lui dire où je suis » (ADR 0119) : des mesures tant qu'on les écoute — l'app au
 * premier plan seulement (`WhereShare.follow`), jamais en arrière-plan, sans service ni notification (ADR 0077).
 * Chaque mesure porte le nom du lieu trouvé par le `Geocoder` du téléphone (vide s'il n'en trouve pas).
 */
class LocationMonitor(context: Context, private val clock: Clock, private val logger: Logger = Logger.NONE) {
    private val context = context.applicationContext
    private val manager: LocationManager? = this.context.getSystemService(LocationManager::class.java)

    /**
     * Les mesures, nommées. L'autorisation est revue à chaque abonnement : sans elle, [WhereShare.Off] (la
     * position d'avant s'efface chez Mika). La localisation coupée : rien, jusqu'à ce qu'elle revienne.
     */
    @OptIn(ExperimentalCoroutinesApi::class)
    fun fixes(): Flow<WhereShare> = flow {
        if (!permitted(context)) {
            emit(WhereShare.Off)
            return@flow
        }
        // une nouvelle mesure abandonne le nom de la précédente, encore en route
        emitAll(locations().mapLatest { fix(it) })
    }.flowOn(Dispatchers.IO)

    /**
     * Les mesures du fournisseur choisi, en commençant par la dernière connue si elle est récente. Un fournisseur
     * éteint (la localisation coupée) reste écouté : ses mesures viennent quand on la rallume.
     */
    private fun locations(): Flow<Location> = callbackFlow {
        val lm = manager
        val fine = granted(context, Manifest.permission.ACCESS_FINE_LOCATION)
        val coarse = granted(context, Manifest.permission.ACCESS_COARSE_LOCATION)
        val provider = lm?.let { provider(it, fine) }
        if (lm == null || provider == null || !(fine || coarse)) {
            close()
            return@callbackFlow
        }
        val listener = LocationListenerCompat { trySend(it) }
        try {
            lastKnown(lm, provider, fine)?.let { trySend(it) }
            LocationManagerCompat.requestLocationUpdates(lm, provider, REQUEST, ContextCompat.getMainExecutor(context), listener)
        } catch (e: SecurityException) {
            // Autorisation retirée entre la vérification et la demande : rien ne part, la prochaine entrée la revoit.
            logger.w(TAG, "localisation refusée", e)
            close()
        } catch (e: IllegalArgumentException) {
            logger.w(TAG, "fournisseur $provider indisponible", e)
            close()
        }
        awaitClose {
            try {
                LocationManagerCompat.removeUpdates(lm, listener)
            } catch (_: SecurityException) {
                // autorisation retirée entre-temps : plus rien n'arrive de toute façon
            }
        }
    }

    /**
     * Le fournisseur fusionné (Android 12 et plus) ; sinon le GPS s'il est permis et allumé, le réseau sinon — et,
     * tout éteint, celui qui reviendra le premier. Une autorisation approximative seule n'ouvre jamais le GPS.
     */
    private fun provider(lm: LocationManager, fine: Boolean): String? {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && lm.hasProvider(LocationManager.FUSED_PROVIDER)) {
            return LocationManager.FUSED_PROVIDER
        }
        val providers = lm.allProviders
        val gps = fine && LocationManager.GPS_PROVIDER in providers
        val network = LocationManager.NETWORK_PROVIDER in providers
        return when {
            gps && lm.isProviderEnabled(LocationManager.GPS_PROVIDER) -> LocationManager.GPS_PROVIDER
            network -> LocationManager.NETWORK_PROVIDER
            gps -> LocationManager.GPS_PROVIDER
            else -> null
        }
    }

    /** La plus récente des dernières mesures connues des fournisseurs permis, si elle a moins de [LAST_KNOWN_MAX_AGE_MS]. */
    private fun lastKnown(lm: LocationManager, provider: String, fine: Boolean): Location? {
        val now = clock.elapsedMs()
        val known = lm.allProviders
        return listOfNotNull(provider, LocationManager.NETWORK_PROVIDER, LocationManager.GPS_PROVIDER.takeIf { fine })
            .distinct()
            .filter { it in known }
            .mapNotNull { p ->
                try {
                    lm.getLastKnownLocation(p)
                } catch (_: SecurityException) {
                    null // autorisation retirée entre-temps
                }
            }
            .filter { now - elapsedMs(it) in 0..LAST_KNOWN_MAX_AGE_MS }
            .maxByOrNull { elapsedMs(it) }
    }

    private suspend fun fix(location: Location): WhereShare.Fix = WhereShare.Fix(
        lat = location.latitude,
        lon = location.longitude,
        accuracyM = if (location.hasAccuracy()) location.accuracy.toInt().coerceAtLeast(0) else 0,
        label = label(location),
        fixElapsedMs = elapsedMs(location),
    )

    /** Le nom du lieu (« 12 Rue de la République, Lyon ») ; sans `Geocoder`, sans réseau, ou trop lent : vide. */
    private suspend fun label(location: Location): String {
        if (!Geocoder.isPresent()) return ""
        val address = try {
            withTimeoutOrNull(GEOCODE_TIMEOUT_MS) { address(Geocoder(context, Locale.getDefault()), location) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: IOException) {
            logger.w(TAG, "lieu introuvable : ${e.javaClass.simpleName}")
            null
        } catch (e: IllegalArgumentException) {
            null
        } ?: return ""
        return PlaceLabel.format(
            number = address.subThoroughfare,
            street = address.thoroughfare,
            locality = address.locality,
            subAdminArea = address.subAdminArea,
            adminArea = address.adminArea,
            feature = address.featureName,
            country = address.countryName,
            line = if (address.maxAddressLineIndex >= 0) address.getAddressLine(0) else null,
        )
    }

    private suspend fun address(geocoder: Geocoder, location: Location): Address? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            suspendCancellableCoroutine { cont ->
                geocoder.getFromLocation(location.latitude, location.longitude, 1, object : Geocoder.GeocodeListener {
                    override fun onGeocode(addresses: MutableList<Address>) {
                        if (cont.isActive) cont.resume(addresses.firstOrNull())
                    }

                    override fun onError(errorMessage: String?) {
                        if (cont.isActive) cont.resume(null)
                    }
                })
            }
        } else {
            runInterruptible {
                @Suppress("DEPRECATION")
                geocoder.getFromLocation(location.latitude, location.longitude, 1)?.firstOrNull()
            }
        }

    /** L'instant d'une mesure sur l'horloge qui compte quand le téléphone dort (celle de `Clock.elapsedMs`). */
    private fun elapsedMs(location: Location): Long = location.elapsedRealtimeNanos / 1_000_000

    companion object {
        private const val TAG = "Location"
        /** Une mesure par minute au plus souvent voulu, jamais moins de 30 s entre deux, ni pour moins de 50 m. */
        private const val INTERVAL_MS = 60_000L
        private const val MIN_INTERVAL_MS = 30_000L
        private const val MIN_DISTANCE_M = 50f
        /** La dernière mesure connue ne sert de départ que si elle a moins de 10 min. */
        private const val LAST_KNOWN_MAX_AGE_MS = 10 * 60_000L
        private const val GEOCODE_TIMEOUT_MS = 10_000L

        private val REQUEST = LocationRequestCompat.Builder(INTERVAL_MS)
            .setQuality(LocationRequestCompat.QUALITY_HIGH_ACCURACY)
            .setMinUpdateIntervalMillis(MIN_INTERVAL_MS)
            .setMinUpdateDistanceMeters(MIN_DISTANCE_M)
            .build()

        /** La localisation est-elle permise, précise ou approximative (Android 12 et plus peut ne donner que celle-ci) ? */
        fun permitted(context: Context): Boolean =
            granted(context, Manifest.permission.ACCESS_FINE_LOCATION) ||
                granted(context, Manifest.permission.ACCESS_COARSE_LOCATION)

        private fun granted(context: Context, permission: String): Boolean =
            ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED
    }
}
