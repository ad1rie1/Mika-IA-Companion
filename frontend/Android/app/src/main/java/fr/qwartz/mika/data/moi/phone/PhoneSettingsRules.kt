package fr.qwartz.mika.data.moi.phone

/*
 * Paramètres › Téléphones, pur (porté de `frontendv2/src/screens/telephone/settings.ts`) : ce qu'un téléphone reçoit
 * application fermée, l'ordre de la liste et ce qui s'y révoque (R3-03). Tout se teste sur la JVM.
 */

// ── Tes téléphones ──────────────────────────────────────────────────────

/** Ce qu'un téléphone reçoit application fermée : ses notifications (Firebase, ADR 0077), ou rien. */
fun pushWords(push: Boolean): String = if (push) "même application fermée" else "sans notifications"

/**
 * Une ligne de la liste : le téléphone, si c'est celui-ci ([mine]), et s'il pourrait l'être sans qu'on le sache
 * ([unsure] : une session ouverte avant que l'app garde l'identifiant de son jeton, et un autre téléphone du même nom
 * que celui-ci). « Révoquer » ne s'offre que sur un autre téléphone sûr ([revocable]) : sur un « peut-être celui-ci »,
 * on se révoquerait soi-même pendant que l'autre continue.
 */
data class PhoneRow(val phone: PhoneDevice, val mine: Boolean, val unsure: Boolean = false) {
    val revocable: Boolean get() = !phone.revoked && !mine && !unsure
}

/** Tes téléphones dans l'ordre de la page : celui-ci d'abord, puis les autres du plus récemment servi, les révoqués à
 *  la fin. [tokenId] : l'identifiant du jeton de cette session (`null` : une session d'avant, reconnue par son nom). */
fun phoneRows(phones: List<PhoneDevice>, deviceLabel: String, tokenId: Long?): List<PhoneRow> {
    val mine = thisPhone(phones, deviceLabel, tokenId)
    fun unsure(p: PhoneDevice) = tokenId == null && p != mine && !p.revoked && p.label.trim() == deviceLabel.trim()
    return phones.sortedWith(compareBy<PhoneDevice>({ it != mine }, { it.revoked }, { -it.lastUsed }, { -it.id }))
        .map { PhoneRow(it, it == mine, unsure(it)) }
}
