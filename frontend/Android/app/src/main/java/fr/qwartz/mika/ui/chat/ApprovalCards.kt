package fr.qwartz.mika.ui.chat

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.approvals.ApprovalView
import fr.qwartz.mika.data.net.ApprovalDecision

/**
 * Les cartes d'accord, juste au-dessus de la barre de saisie : ce que Mika veut envoyer à un service
 * extérieur et qui attend l'accord de la personne. Bornées en hauteur par l'appelant ([modifier]) et
 * défilables : plusieurs cartes ne mangent pas la conversation.
 */
@Composable
internal fun ApprovalTray(
    cards: List<ApprovalView>,
    onDecide: (ApprovalView, ApprovalDecision) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (cards.isEmpty()) return
    Column(
        modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        for (card in cards) {
            key(card.id) { ApprovalCardView(card, onDecide) }
        }
    }
}

@Composable
private fun ApprovalCardView(card: ApprovalView, onDecide: (ApprovalView, ApprovalDecision) -> Unit) {
    val scheme = MaterialTheme.colorScheme
    Card(
        colors = CardDefaults.cardColors(containerColor = scheme.tertiaryContainer),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(stringResource(R.string.approval_heading), style = MaterialTheme.typography.labelMedium)
            Text(card.title, style = MaterialTheme.typography.titleSmall, modifier = Modifier.semantics { heading() })
            if (card.text.isNotEmpty()) {
                // Exactement ce qui partira : du texte brut, à chasse fixe, jamais interprété (ni gras, ni liens).
                Surface(shape = RoundedCornerShape(8.dp), color = scheme.surface, modifier = Modifier.fillMaxWidth()) {
                    Text(
                        card.text,
                        fontFamily = FontFamily.Monospace,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier
                            .heightIn(max = 160.dp)
                            .verticalScroll(rememberScrollState())
                            .padding(8.dp),
                    )
                }
            }
            card.blocked?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = scheme.error)
            }
            card.hint?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    card.expiry.orEmpty(),
                    style = MaterialTheme.typography.labelSmall,
                    color = if (card.expired) scheme.error else scheme.onTertiaryContainer.copy(alpha = 0.8f),
                    modifier = Modifier.weight(1f),
                )
                OutlinedButton(onClick = { onDecide(card, ApprovalDecision.REFUSE) }, enabled = card.canRefuse) {
                    Text(stringResource(R.string.approval_refuse))
                }
                Button(onClick = { onDecide(card, ApprovalDecision.ACCEPT) }, enabled = card.canAccept) {
                    Text(stringResource(R.string.approval_accept))
                }
            }
        }
    }
}
