package fr.qwartz.mika

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.mutableStateOf
import fr.qwartz.mika.ui.DeepLinks
import fr.qwartz.mika.ui.MikaRoot

class MainActivity : ComponentActivity() {
    /** Ce qu'une notification ou un raccourci demande d'ouvrir ; consommé une fois par l'écran. */
    private val deepLink = mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        // Une recréation (rotation) ne rejoue pas le lien qui a ouvert l'activité.
        if (savedInstanceState == null) deepLink.value = targetOf(intent)
        setContent { MikaRoot(graph, deepLink.value) { deepLink.value = null } }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        targetOf(intent)?.let { deepLink.value = it }
    }

    private fun targetOf(intent: Intent?): String? = intent?.getStringExtra(DeepLinks.EXTRA_OPEN)
}
