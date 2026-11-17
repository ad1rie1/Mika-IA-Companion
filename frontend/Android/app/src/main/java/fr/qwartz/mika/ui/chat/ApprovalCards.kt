package fr.qwartz.mika.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
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
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.approvals.ApprovalView
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.net.ApprovalDecision
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.theme.mika

/**
 * Ce qui attend ta décision, juste au-dessus de la barre de saisie (ADR 0235, point 4) : une seule ligne rose —
 * combien d'accords, combien de brouillons à relire, le compte à rebours de l'accord le plus proche — qui déplie les
 * cartes d'accord (exactement ce qui partira, inchangées : leurs boutons seuls décident) et les liens vers ses
 * brouillons, qui se décident dans Mail ou Teams (ADR 0191). En mode pro, pour une opératrice, « Tout accepter » au-dessus
 * de deux accords ou plus (ADR 0170). Bornée en hauteur par l'appelant ([modifier]) : dépliée, ce qui est sous la ligne
 * défile, et la conversation reste.
 */
@Composable
internal fun ChatTrayBand(
    tray: TrayView,
    open: Boolean,
    nowWallMs: Long,
    onToggle: () -> Unit,
    onDecide: (ApprovalView, ApprovalDecision) -> Unit,
    onOpen: (Route) -> Unit,
    modifier: Modifier = Modifier,
    acceptAll: Boolean = false,
    acceptingAll: Boolean = false,
    onAcceptAll: () -> Unit = {},
) {
    if (tray.isEmpty) return
    Column(
        modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        TrayLine(tray, open, nowWallMs, onToggle)
        if (open) {
            Column(
                Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (acceptAll) AcceptAllRow(tray, acceptingAll, onAcceptAll)
                for (card in tray.accords) {
                    key(card.id) { ApprovalCardView(card, onDecide) }
                }
                if (tray.drafts.isNotEmpty()) {
                    Surface(shape = RoundedCornerShape(14.dp), color = MaterialTheme.colorScheme.surfaceContainerLow) {
                        Column(Modifier.padding(vertical = 4.dp)) {
                            for (d in tray.drafts) DraftLinkRow(d, onOpen)
                        }
                    }
                }
            }
        }
    }
}

/** La ligne repliée : « 1 accord · 2 brouillons à relire », le compte à rebours, le chevron. */
@Composable
private fun TrayLine(tray: TrayView, open: Boolean, nowWallMs: Long, onToggle: () -> Unit) {
    val accords = tray.accords.size
    val accordsText = if (accords > 0) pluralStringResource(R.plurals.chat_tray_accords, accords, accords) else null
    val draftsText = if (tray.draftCount > 0) pluralStringResource(R.plurals.chat_tray_drafts, tray.draftCount, tray.draftCount) else null
    val left = ChatTray.countdown(tray.soonest, nowWallMs)
    val urgent = ChatTray.urgent(tray.soonest, nowWallMs)
    val shown = buildAnnotatedString {
        if (accordsText != null) withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append(accordsText) }
        if (accordsText != null && draftsText != null) append(" · ")
        if (draftsText != null) append(draftsText)
    }
    val said = listOfNotNull(accordsText, draftsText, left?.let { stringResource(R.string.chat_tray_expires, it) }).joinToString(", ")
    val state = stringResource(if (open) R.string.chat_tray_open else R.string.chat_tray_folded)
    val action = stringResource(if (open) R.string.chat_tray_fold else R.string.chat_tray_unfold)
    Surface(
        shape = RoundedCornerShape(14.dp),
        color = mika.soft,
        border = BorderStroke(1.dp, mika.line),
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClickLabel = action, role = Role.Button, onClick = onToggle)
            .clearAndSetSemantics {
                contentDescription = said
                stateDescription = state
                role = Role.Button
                onClick(label = action) { onToggle(); true }
                liveRegion = LiveRegionMode.Polite
            },
    ) {
        Row(Modifier.heightIn(min = 44.dp).padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            MIcon(R.drawable.ic_m_shield, null, size = 18.dp, tint = mika.accent)
            Spacer(Modifier.width(10.dp))
            Text(shown, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            if (left != null) {
                Spacer(Modifier.width(8.dp))
                Tag(left, if (urgent) Tone.WARN else Tone.NEUTRAL)
            }
            Spacer(Modifier.width(6.dp))
            MIcon(if (open) R.drawable.ic_m_chev_up else R.drawable.ic_m_chev_down, null, size = 18.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** En mode pro (ADR 0170) : « N accords attendent » et « Tout accepter », qui ne prend que ce que « Accepter » permettrait. */
@Composable
private fun AcceptAllRow(tray: TrayView, busy: Boolean, onAcceptAll: () -> Unit) {
    val n = tray.accords.size
    val possible = ChatTray.acceptAllTargets(tray.accords).isNotEmpty()
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(
            pluralStringResource(R.plurals.chat_tray_waiting, n, n),
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f),
        )
        TextButton(onClick = onAcceptAll, enabled = possible && !busy) {
            Text(stringResource(if (busy) R.string.chat_tray_accepting else R.string.chat_tray_accept_all))
        }
    }
}

/** Un brouillon à relire : où il se décide, ce qu'elle a préparé, et le chemin jusqu'à lui. */
@Composable
private fun DraftLinkRow(d: TrayDraft, onOpen: (Route) -> Unit) {
    val where = stringResource(if (d.place == DraftPlace.MAIL) R.string.nav_mail else R.string.nav_teams)
    val what = if (d.count > 0) {
        stringResource(if (d.place == DraftPlace.MAIL) R.string.chat_tray_mail_list else R.string.chat_tray_teams_list, d.count)
    } else {
        listOf(d.title, d.detail).filter { it.isNotBlank() }.joinToString(" ")
    }
    val open = stringResource(R.string.chat_tray_open_in, where)
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 48.dp)
            .clickable(onClickLabel = open, role = Role.Button) { onOpen(d.route) }
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MIcon(if (d.place == DraftPlace.MAIL) R.drawable.ic_m_mail else R.drawable.ic_m_teams, null, size = 18.dp, tint = mika.accent)
        Spacer(Modifier.width(10.dp))
        Text(
            buildAnnotatedString {
                withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append(where) }
                append(" · ")
                append(what)
            },
            style = MaterialTheme.typography.bodyMedium,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
        MIcon(R.drawable.ic_m_chev_right, null, size = 16.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
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
