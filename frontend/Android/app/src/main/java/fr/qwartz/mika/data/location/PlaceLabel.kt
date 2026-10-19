package fr.qwartz.mika.data.location

import fr.qwartz.mika.data.net.MikaProtocol

/**
 * Le nom du lieu que le téléphone joint à sa position (ADR 0119), tiré d'une adresse du `Geocoder` : pur, pour
 * que les tests n'aient besoin ni d'Android ni de réseau.
 */
object PlaceLabel {
    private val BLANKS = Regex("[\\s\\p{Cc}]+")

    /**
     * « 12 Rue de la République, Lyon » : le numéro et la rue, puis la ville — à défaut le département, la région,
     * le pays. Sans rue, le nom du lieu ([feature] : un parc, une gare…) s'il n'est pas qu'un numéro ; sans rien de
     * tout ça, la ligne d'adresse ([line]). Ce qui manque est sauté, un doublon aussi ; rien de lisible : vide.
     * Sur une ligne, borné à [MikaProtocol.MAX_WHERE_LABEL_CHARS].
     */
    fun format(
        number: String?,
        street: String?,
        locality: String?,
        subAdminArea: String? = null,
        adminArea: String? = null,
        feature: String? = null,
        country: String? = null,
        line: String? = null,
    ): String {
        val road = clean(street)
        val num = clean(number)
        val first = when {
            road.isNotEmpty() -> if (num.isNotEmpty()) "$num $road" else road
            else -> clean(feature).takeIf { f -> f.isNotEmpty() && f != num && !f.all { it.isDigit() } }.orEmpty()
        }
        val place = listOf(locality, subAdminArea, adminArea, country).map(::clean).firstOrNull { it.isNotEmpty() }.orEmpty()
        val parts = listOf(first, place).filter { it.isNotEmpty() }.distinct()
        return bound(if (parts.isEmpty()) clean(line) else parts.joinToString(", "))
    }

    /** Coupé à [MikaProtocol.MAX_WHERE_LABEL_CHARS] sans casser un caractère en deux (une paire de substitution). */
    fun bound(text: String, max: Int = MikaProtocol.MAX_WHERE_LABEL_CHARS): String {
        if (text.length <= max) return text
        val end = if (Character.isHighSurrogate(text[max - 1])) max - 1 else max
        return text.substring(0, end).trimEnd()
    }

    private fun clean(text: String?): String = text?.replace(BLANKS, " ")?.trim().orEmpty()
}
