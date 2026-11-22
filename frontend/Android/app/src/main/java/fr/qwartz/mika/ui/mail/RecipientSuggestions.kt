package fr.qwartz.mika.ui.mail

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.contacts.RecipientProposal
import fr.qwartz.mika.data.moi.mail.parseAddresses
import fr.qwartz.mika.ui.contacts.ContactAvatar
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.Tag

/**
 * Les destinataires proposés sous un champ d'Écrire (la maquette validée, `ecrans/contacts.js` : `.cx-ac`) : tous tes
 * contacts, une ligne par adresse — son rond (un carré pour une organisation), son nom et son organisation, ou
 * « générique » pour une adresse sans personne derrière, l'adresse, et à droite d'où elle vient (une boîte et combien
 * de mails, son profil Teams). Rien trouvé : la ligne le dit ([noMatch] : le texte cherché), et ce qui est tapé sera
 * pris tel quel si c'est une adresse. Les règles sont dans `data/moi/contacts` (`proposals`, `RecipientSuggester`).
 */
@Composable
internal fun RecipientSuggestions(typed: String, proposals: List<RecipientProposal>, noMatch: String, onPick: (RecipientProposal) -> Unit) {
    val text = typed.trim()
    if (text.isEmpty() || (proposals.isEmpty() && noMatch != text)) return
    val scheme = MaterialTheme.colorScheme
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = scheme.surfaceContainerHigh,
        shadowElevation = 2.dp,
        modifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 8.dp),
    ) {
        Column {
            if (proposals.isEmpty()) {
                Text(
                    stringResource(if (parseAddresses(text).isNotEmpty()) R.string.mail_suggest_none_kept else R.string.mail_suggest_none, text),
                    style = MaterialTheme.typography.bodyMedium,
                    color = scheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                )
            }
            proposals.forEachIndexed { i, p ->
                if (i > 0) HorizontalDivider(color = scheme.outlineVariant)
                ProposalRow(p) { onPick(p) }
            }
        }
    }
}

/** Une proposition (`.cx-ac-row`). */
@Composable
private fun ProposalRow(p: RecipientProposal, onClick: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).heightIn(min = 58.dp).padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        ContactAvatar(p.shown, p.address, p.org, 32.dp)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    p.shown,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Medium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
                when {
                    p.generic -> {
                        Spacer(Modifier.width(6.dp))
                        Tag(stringResource(R.string.mail_suggest_generic), Tone.NEUTRAL)
                    }
                    p.about.isNotBlank() -> {
                        Spacer(Modifier.width(6.dp))
                        Text(p.about, fontSize = 12.5.sp, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                    }
                }
            }
            if (p.name.isNotBlank()) {
                Text(p.address, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        val hint = p.hint
        if (hint != null) {
            Spacer(Modifier.width(8.dp))
            Column(Modifier.widthIn(max = 92.dp), horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(1.dp)) {
                if (hint.top.isNotBlank() || hint.bottom.isNotBlank()) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        MIcon(if (hint.teams) R.drawable.ic_m_teams else R.drawable.ic_m_mail, null, size = 13.dp, tint = scheme.onSurfaceVariant)
                        if (hint.top.isNotBlank()) {
                            Spacer(Modifier.width(3.dp))
                            Text(hint.top, fontSize = 11.5.sp, lineHeight = 15.sp, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
                if (hint.bottom.isNotBlank()) {
                    Text(hint.bottom, fontSize = 11.5.sp, lineHeight = 15.sp, color = scheme.onSurfaceVariant, maxLines = 1, textAlign = TextAlign.End)
                }
            }
        }
    }
}
