package fr.qwartz.mika.ui.contacts

import androidx.annotation.DrawableRes
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.contacts.ContactsApi
import fr.qwartz.mika.data.moi.contacts.IdentKinds
import fr.qwartz.mika.data.moi.contacts.PlaceIcon
import fr.qwartz.mika.data.moi.hue
import fr.qwartz.mika.data.moi.initials
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/*
 * Ce que les écrans de Contacts partagent (ADR 0298, la maquette validée `ecrans/contacts.js`) : l'API, le rond d'un
 * contact (un carré pour une organisation, ses initiales — l'ADR 0300 ne pose pas les photos sur Android), les icônes
 * d'une source, d'un identifiant et d'un lieu, et ce qu'une fiche dit à la liste.
 */

/** Contacts sur l'API du téléphone. */
internal fun AppGraph.contactsApi(): ContactsApi = ContactsApi(moi)

/** Ce que les écrans de Contacts prennent de la session : l'API. Un test JVM la donne sans le graphe de l'app. */
class ContactsDeps(val api: ContactsApi) {
    constructor(graph: AppGraph) : this(graph.contactsApi())
}

/** Ce qu'une fiche dit à la liste : ce contact est oublié (il la quitte sans attendre sa relecture). */
internal object ContactsChanges {
    private val forgotten = MutableSharedFlow<Int>(extraBufferCapacity = 8)
    val flow: SharedFlow<Int> = forgotten.asSharedFlow()

    fun forgot(id: Int) {
        forgotten.tryEmit(id)
    }
}

/** Les teintes des ronds d'initiales (`.av.c0`…`.av.c7` de la maquette, celles de `PersonAvatar`). */
private val AVATAR_COLORS = listOf(
    Color(0xFF4F46E5), Color(0xFFC2410C), Color(0xFF0F766E), Color(0xFF7C3AED),
    Color(0xFF475569), Color(0xFFB45309), Color(0xFF0369A1), Color(0xFFBE185D),
)

/** Le rond d'un contact, d'une teinte stable pour [key] ; une organisation ([org]), son carré (`.av.sq`). */
@Composable
internal fun ContactAvatar(name: String, key: String, org: Boolean, size: Dp = 40.dp) {
    val shape = if (org) RoundedCornerShape(size * 0.3f) else CircleShape
    Box(
        Modifier.size(size).clip(shape).background(AVATAR_COLORS[hue(key.ifBlank { name })]),
        contentAlignment = Alignment.Center,
    ) {
        Text(initials(name.ifBlank { key }), color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = (size.value * 0.36f).sp, maxLines = 1)
    }
}

/** La clé de la teinte d'un contact (la même que le web : `contact:<n°>`). */
internal fun contactKey(id: Int): String = "contact:$id"

/** L'icône d'une source (une étiquette de la liste, un fait de la fiche). */
@DrawableRes
internal fun sourceIcon(source: String): Int = when (source) {
    "teams" -> R.drawable.ic_m_teams
    "mail" -> R.drawable.ic_m_mail
    "whatsapp" -> R.drawable.ic_m_chat
    "sms", "phone" -> R.drawable.ic_m_phone
    "told" -> R.drawable.ic_m_sparkle
    else -> R.drawable.ic_m_user
}

/** L'icône d'une sorte d'identifiant. */
@DrawableRes
internal fun identIcon(kind: String): Int = when (kind) {
    IdentKinds.EMAIL -> R.drawable.ic_m_mail
    IdentKinds.TEAMS, IdentKinds.TENANT -> R.drawable.ic_m_teams
    IdentKinds.PHONE -> R.drawable.ic_m_phone
    IdentKinds.PHONE_APP -> R.drawable.ic_m_chat
    IdentKinds.DOMAIN -> R.drawable.ic_m_globe
    IdentKinds.COMPANY -> R.drawable.ic_m_users
    else -> R.drawable.ic_m_user
}

/** L'icône d'une ligne de « Où vous vous croisez ». */
@DrawableRes
internal fun placeIcon(icon: PlaceIcon): Int = when (icon) {
    PlaceIcon.TEAMS -> R.drawable.ic_m_teams
    PlaceIcon.MAIL -> R.drawable.ic_m_mail
    PlaceIcon.CHAT -> R.drawable.ic_m_chat
    PlaceIcon.PHONE -> R.drawable.ic_m_phone
}
