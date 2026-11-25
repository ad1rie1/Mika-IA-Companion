package fr.qwartz.mika.data.moi.teams

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.ago
import fr.qwartz.mika.data.moi.settings.changes
import fr.qwartz.mika.data.moi.settings.shareWords
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject

/*
 * Les règles pures de Paramètres › Comptes Teams, portées du client web (`frontendv2/src/screens/teams/settings.ts`) :
 * ce qu'un formulaire en envoie et les noms de ses champs, ce que l'on sait de son extension, un compte qu'on te
 * partage. Tout se teste sur la JVM.
 */

// ── Ses formulaires ─────────────────────────────────────────────────────

/** Ce qui part d'un compte Teams réglé : ce qui a changé. */
fun teamsChanges(before: TeamsValues, after: TeamsValues): JsonObject = changes(
    MikaJson.encodeToJsonElement(TeamsValues.serializer(), before).jsonObject,
    MikaJson.encodeToJsonElement(TeamsValues.serializer(), after).jsonObject,
)

val TEAMS_LABELS: Map<String, String> = mapOf(
    "label" to "Nom affiché", "enabled" to "Actif", "display_name" to "Ton nom", "tone" to "Ton",
    "instructions" to "Consignes", "sign" to "Signer ses réponses", "signature" to "Signature",
)

// ── Les comptes Teams ───────────────────────────────────────────────────

/** Ce que l'on sait de son extension : inactif, rien reçu, ou son dernier envoi. */
fun batchWords(a: TeamsAccount, now: Long): Pair<Tone, String> = when {
    !a.enabled -> Tone.NEUTRAL to "inactif"
    a.lastBatch <= 0 -> Tone.WARN to "rien reçu de son extension"
    else -> Tone.OK to "dernier envoi ${ago(a.lastBatch, now)}"
}

/** Un compte qu'on te partage, en une phrase. */
fun sharedAccountSentence(a: TeamsAccount): String {
    val owner = a.ownerName.ifBlank { "Son propriétaire" }
    return "$owner te l'a ouvert : ${shareWords(a.level).lowercase()}. Tu le lis dans Teams ; seul son propriétaire le règle."
}
