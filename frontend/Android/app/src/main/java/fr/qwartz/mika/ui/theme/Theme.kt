package fr.qwartz.mika.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import fr.qwartz.mika.data.settings.ThemeMode

/** Repli sans couleurs dynamiques : l'indigo du client web (#6366F1). */
private val LightFallback = lightColorScheme(
    primary = Color(0xFF4F46E5),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFE1E0FF),
    onPrimaryContainer = Color(0xFF14135E),
    secondaryContainer = Color(0xFFE3E1F9),
    onSecondaryContainer = Color(0xFF1B1A2C),
)

private val DarkFallback = darkColorScheme(
    primary = Color(0xFFC1C1FF),
    onPrimary = Color(0xFF22217A),
    primaryContainer = Color(0xFF3B3BA6),
    onPrimaryContainer = Color(0xFFE1E0FF),
    secondaryContainer = Color(0xFF46455B),
    onSecondaryContainer = Color(0xFFE3E1F9),
)

@Composable
fun MikaTheme(mode: ThemeMode = ThemeMode.SYSTEM, dynamicColor: Boolean = true, content: @Composable () -> Unit) {
    val dark = when (mode) {
        ThemeMode.SYSTEM -> isSystemInDarkTheme()
        ThemeMode.LIGHT -> false
        ThemeMode.DARK -> true
    }
    val context = LocalContext.current
    val scheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
            if (dark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        dark -> DarkFallback
        else -> LightFallback
    }
    MaterialTheme(colorScheme = scheme, content = content)
}
