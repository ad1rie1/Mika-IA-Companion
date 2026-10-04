package fr.qwartz.mika.core

import android.os.SystemClock

/** `elapsedRealtime` continue de compter quand le téléphone dort, contrairement à `uptimeMillis`. */
object AndroidClock : Clock {
    override fun wallMs(): Long = System.currentTimeMillis()
    override fun elapsedMs(): Long = SystemClock.elapsedRealtime()
}
