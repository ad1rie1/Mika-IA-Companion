package fr.qwartz.mika.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.Saver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.auth.Session
import fr.qwartz.mika.data.files.MikaFileRefs
import fr.qwartz.mika.data.settings.Settings
import fr.qwartz.mika.ui.chat.ChatScreen
import fr.qwartz.mika.ui.login.LoginScreen
import fr.qwartz.mika.ui.mind.MindScreen
import fr.qwartz.mika.ui.settings.SettingsScreen
import fr.qwartz.mika.ui.theme.MikaTheme
import fr.qwartz.mika.ui.viewer.ImageViewerScreen

/** La porte de l'app : la session décide de l'écran ; une fois connectée, une petite pile d'écrans. */
@Composable
fun MikaRoot(graph: AppGraph, deepLink: String?, onDeepLinkHandled: () -> Unit) {
    val settings by graph.settings.settings.collectAsStateWithLifecycle(Settings())
    MikaTheme(settings.theme, settings.dynamicColor) {
        Surface(Modifier.fillMaxSize()) {
            val session by graph.auth.session.collectAsStateWithLifecycle()
            when (val s = session) {
                Session.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
                is Session.LoggedOut -> LoginScreen(graph, s.reason)
                is Session.LoggedIn -> SignedIn(graph, deepLink, onDeepLinkHandled)
            }
        }
    }
}

private val StackSaver = Saver<BackStack, String>(save = { it.encode() }, restore = { BackStack.decode(it) })

@Composable
private fun SignedIn(graph: AppGraph, deepLink: String?, onDeepLinkHandled: () -> Unit) {
    var stack by rememberSaveable(stateSaver = StackSaver) { mutableStateOf(BackStack()) }
    LaunchedEffect(deepLink) {
        if (deepLink != null) {
            stack = BackStack.forDeepLink(deepLink)
            onDeepLinkHandled()
        }
    }
    // Le geste « retour » (prédictif depuis Android 14) dépile ; à la racine, il sort de l'app.
    BackHandler(enabled = stack.canPop) { stack.pop()?.let { stack = it } }
    val back = { stack.pop()?.let { stack = it } }
    when (val top = stack.top) {
        Route.Chat -> ChatScreen(
            graph,
            onOpenMind = { stack = stack.push(Route.Mind) },
            onOpenSettings = { stack = stack.push(Route.Settings) },
            onOpenImage = { att ->
                val path = MikaFileRefs.path(att)
                if (path != null && att.id != null) {
                    stack = stack.push(Route.Viewer(att.id, att.name, path, att.mime, att.size))
                }
            },
        )
        Route.Mind -> MindScreen(graph, onBack = { back() })
        Route.Settings -> SettingsScreen(graph, onBack = { back() })
        is Route.Viewer -> ImageViewerScreen(graph, top, onBack = { back() })
    }
}
