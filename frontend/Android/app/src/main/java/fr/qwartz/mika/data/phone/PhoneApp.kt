package fr.qwartz.mika.data.phone

/** Les cases des réglages : une par famille d'applis (ADR 0120). */
enum class PhoneFamily { WHATSAPP, MESSAGES }

/**
 * Les applis dont le téléphone lit les messages (« Lui montrer mes messages », ADR 0120) : une liste d'inclusion, jamais
 * une liste d'exclusions — la banque et les codes à usage unique n'en font jamais partie. Chacune a son code sur le fil
 * (`app`, ce que le serveur range) et la case des réglages qui l'ouvre.
 */
enum class PhoneApp(val packageName: String, val code: String, val family: PhoneFamily) {
    WHATSAPP("com.whatsapp", "whatsapp", PhoneFamily.WHATSAPP),
    WHATSAPP_BUSINESS("com.whatsapp.w4b", "whatsapp_business", PhoneFamily.WHATSAPP),
    MESSAGES("com.google.android.apps.messaging", "messages", PhoneFamily.MESSAGES),
    SAMSUNG_MESSAGES("com.samsung.android.messaging", "samsung_messages", PhoneFamily.MESSAGES),
    ;

    companion object {
        private val byPackage = entries.associateBy { it.packageName }
        private val byCode = entries.associateBy { it.code }

        /** Les paquets lus : tout autre notification est écartée avant le moindre travail. */
        val PACKAGES: Set<String> = byPackage.keys

        fun ofPackage(packageName: String?): PhoneApp? = packageName?.let(byPackage::get)
        fun ofCode(code: String?): PhoneApp? = code?.let(byCode::get)
    }
}

/**
 * Ce que la personne permet de lire (Paramètres › Ses messages, ADR 0120) : l'interrupteur, coupé par défaut ; une case
 * par appli, cochées par défaut une fois l'interrupteur allumé ; les groupes, coupés par défaut (bavards).
 */
data class PhoneGate(
    val enabled: Boolean = false,
    val whatsapp: Boolean = true,
    val messages: Boolean = true,
    val groups: Boolean = false,
) {
    fun reads(app: PhoneApp): Boolean = enabled && when (app.family) {
        PhoneFamily.WHATSAPP -> whatsapp
        PhoneFamily.MESSAGES -> messages
    }
}
