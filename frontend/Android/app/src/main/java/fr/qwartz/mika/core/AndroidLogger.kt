package fr.qwartz.mika.core

import android.util.Log

/** Le journal Android ; [Logger] a déjà retiré tout jeton du message. */
object AndroidLogger : Logger {
    override fun log(level: Logger.Level, tag: String, message: String, error: Throwable?) {
        val t = "Mika.$tag"
        when (level) {
            Logger.Level.DEBUG -> Log.d(t, message, error)
            Logger.Level.INFO -> Log.i(t, message, error)
            Logger.Level.WARN -> Log.w(t, message, error)
            Logger.Level.ERROR -> Log.e(t, message, error)
        }
    }
}
