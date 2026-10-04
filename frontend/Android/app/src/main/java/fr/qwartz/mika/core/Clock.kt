package fr.qwartz.mika.core

/**
 * Deux horloges, injectables. `wallMs` date ce qu'on montre (l'heure d'une bulle, le `t` d'un ping) ;
 * `elapsedMs` mesure des durées (silence de la socket, délais) et continue de compter quand le
 * téléphone dort — l'heure murale, elle, peut sauter.
 */
interface Clock {
    fun wallMs(): Long
    fun elapsedMs(): Long
}
