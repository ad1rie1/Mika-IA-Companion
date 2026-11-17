package fr.qwartz.mika.ui.shell

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError

/** Ce qu'un écran a lu du serveur : en cours, prêt, ou refusé (en mots). Une relecture garde ce qui était montré. */
sealed interface Load<out T> {
    data object Loading : Load<Nothing>
    data class Ready<T>(val value: T, val refreshing: Boolean = false) : Load<T>
    data class Failed(val error: MoiError) : Load<Nothing>

    val valueOrNull: T? get() = (this as? Ready<T>)?.value

    companion object {
        fun <T> of(result: MoiApi.Result<T>): Load<T> = when (result) {
            is MoiApi.Result.Ok -> Ready(result.value)
            is MoiApi.Result.Failed -> Failed(result.error)
        }
    }
}

/**
 * Ce qu'un écran montre selon sa lecture : un rond qui tourne, le contenu, ou le refus et « Réessayer ». Une page vide
 * n'est jamais muette ([empty] dit pourquoi elle l'est).
 */
@Composable
fun <T> LoadBox(load: Load<T>, onRetry: () -> Unit, modifier: Modifier = Modifier, content: @Composable (T) -> Unit) {
    when (load) {
        Load.Loading -> Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        is Load.Failed -> Notice(load.error.message, modifier, action = stringResource(R.string.retry), onAction = onRetry)
        is Load.Ready -> content(load.value)
    }
}

/** Un mot au milieu d'un écran (rien à montrer, un refus), avec un geste s'il y en a un. */
@Composable
fun Notice(text: String, modifier: Modifier = Modifier, action: String? = null, onAction: () -> Unit = {}) {
    Column(
        modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(text, style = MaterialTheme.typography.bodyLarge, textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (action != null) {
            Spacer(Modifier.height(16.dp))
            FilledTonalButton(onClick = onAction) { Text(action) }
        }
    }
}
