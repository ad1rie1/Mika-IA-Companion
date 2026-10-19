package fr.qwartz.mika.data.location

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf

/**
 * Ce que le téléphone dit à Mika de l'endroit où est la personne (« Lui dire où je suis », ADR 0119) : sa position
 * à elle, jamais celle d'un autre, et seulement application au premier plan — ni service, ni localisation en
 * arrière-plan (ADR 0077).
 */
sealed interface WhereShare {
    /**
     * Une mesure : les coordonnées exactes, la précision en mètres (0 : inconnue), le nom du lieu (vide : pas
     * trouvé) et l'instant de la mesure sur l'horloge qui compte quand le téléphone dort (`elapsedRealtime`, en
     * ms). Son âge se calcule au moment où elle part : elle est redite à chaque ouverture de la socket.
     */
    data class Fix(
        val lat: Double,
        val lon: Double,
        val accuracyM: Int,
        val label: String,
        val fixElapsedMs: Long,
    ) : WhereShare

    /** Elle ne la partage pas, ou plus : sa dernière position s'efface chez Mika (rien, s'il n'y en avait pas). */
    data object Off : WhereShare

    companion object {
        /**
         * Ce qui doit partir, d'après le réglage et le premier plan. Hors du premier plan : rien (`null`), même si la
         * socket reste ouverte 30 s ou s'ouvre pour une réponse depuis une notification — et la socket oublie la
         * dernière valeur, qu'elle ne redit plus. Réglage coupé : [Off]. Sinon les mesures de [fixes], abonnées à
         * chaque entrée au premier plan et à chaque réglage allumé (l'autorisation y est revue), lâchées dès qu'on
         * en sort.
         */
        @OptIn(ExperimentalCoroutinesApi::class)
        fun follow(sharing: Flow<Boolean>, visible: Flow<Boolean>, fixes: () -> Flow<WhereShare>): Flow<WhereShare?> =
            combine(sharing, visible) { on, shown -> on to shown }
                .distinctUntilChanged()
                .flatMapLatest { (on, shown) ->
                    when {
                        !shown -> flowOf(null)
                        !on -> flowOf(Off)
                        else -> fixes()
                    }
                }
    }
}
