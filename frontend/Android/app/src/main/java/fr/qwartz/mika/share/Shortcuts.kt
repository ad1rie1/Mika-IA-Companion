package fr.qwartz.mika.share

import android.content.Context
import android.content.Intent
import androidx.core.app.Person
import androidx.core.content.LocusIdCompat
import androidx.core.content.pm.ShortcutInfoCompat
import androidx.core.content.pm.ShortcutManagerCompat
import androidx.core.graphics.drawable.IconCompat
import fr.qwartz.mika.MainActivity
import fr.qwartz.mika.R
import fr.qwartz.mika.ui.DeepLinks

/**
 * Mika comme conversation pour Android : une personne (« Mika », clé `mika`) et un raccourci durable
 * du même nom. C'est ce qui range ses notifications dans la section « Conversations » et la propose
 * en tête de la feuille de partage.
 */
object Shortcuts {
    const val ID = "mika"
    const val SHARE_CATEGORY = "fr.qwartz.mika.category.SHARE_TARGET"

    fun mika(context: Context): Person = Person.Builder()
        .setName(context.getString(R.string.mika))
        .setKey(ID)
        .setIcon(IconCompat.createWithResource(context, R.mipmap.ic_launcher))
        .setImportant(true)
        .build()

    fun me(context: Context): Person = Person.Builder().setName(context.getString(R.string.me)).build()

    /** Publier (ou rafraîchir) le raccourci ; un refus du lanceur (quota) n'empêche rien d'autre. */
    fun publish(context: Context) {
        val intent = Intent(context, MainActivity::class.java)
            .setAction(Intent.ACTION_VIEW)
            .putExtra(DeepLinks.EXTRA_OPEN, DeepLinks.CHAT)
        val shortcut = ShortcutInfoCompat.Builder(context, ID)
            .setShortLabel(context.getString(R.string.shortcut_short))
            .setLongLabel(context.getString(R.string.shortcut_long))
            .setIcon(IconCompat.createWithResource(context, R.mipmap.ic_launcher))
            .setIntent(intent)
            .setLongLived(true)
            .setPerson(mika(context))
            .setLocusId(LocusIdCompat(ID))
            .setCategories(setOf(SHARE_CATEGORY))
            .build()
        try {
            ShortcutManagerCompat.pushDynamicShortcut(context, shortcut)
        } catch (_: IllegalStateException) {
            // Limite de fréquence du lanceur : le raccourci de la fois précédente reste.
        } catch (_: IllegalArgumentException) {
        }
    }
}
