package fr.qwartz.mika

import android.app.Application
import android.content.Context
import coil3.ImageLoader
import coil3.PlatformContext
import coil3.SingletonImageLoader
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.service.NotificationChannels

class MikaApp : Application(), SingletonImageLoader.Factory {
    lateinit var graph: AppGraph
        private set

    override fun onCreate() {
        super.onCreate()
        NotificationChannels.create(this)
        graph = AppGraph(this)
        graph.start()
    }

    /** Les images de Mika passent par le client authentifié de l'app (le jeton seulement vers son serveur). */
    override fun newImageLoader(context: PlatformContext): ImageLoader = graph.newImageLoader(context)
}

val Context.graph: AppGraph get() = (applicationContext as MikaApp).graph
