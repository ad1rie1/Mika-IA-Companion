package fr.qwartz.mika.data.moi

import kotlinx.serialization.Serializable
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/*
 * « Corriger » (ADR 0307), dans le champ de Mail et de Teams : les fautes de ce que tu écris (orthographe, accents,
 * accords, conjugaison, homophones, ponctuation et ses espaces), sans changer tes mots. `POST /api/moi/correct`
 * (`backendv2/docs/protocole-moi.md` § 2) ; il marche quand un modèle est donné au rôle `correct` (`GET /api/moi` →
 * `correct`, [Me.correct]). Le texte corrigé remplace le tien aussitôt, et « Annuler » te le rend. Porté de
 * `frontend/Web/src/screens/mail/compose.ts` (`correctField`), pur et testé sur la JVM ; les mots sont dans
 * `strings.xml` ([CorrectWords]).
 */

/**
 * Ce que rend `POST /api/moi/correct` : le texte, ses fautes corrigées ; [changes] : combien de corrections (0 : le
 * texte revient tel quel) ; [refused] : combien de changements du modèle ont été écartés parce qu'ils touchaient aux
 * mots (un mot ajouté, retiré ou remplacé, un chiffre changé). Un serveur d'avant ne dit pas [refused] : 0.
 */
@Serializable
data class Corrected(val text: String = "", val changes: Int = 0, val refused: Int = 0)

/** Ce qu'attend la réponse de « Corriger » : le serveur se donne 50 s au plus (`DEADLINE_S`, `app/me/writing.py`) et ne
 *  répond qu'à la fin — plus que les 30 s de lecture d'un appel court. */
const val CORRECT_READ_S = 75L

/** …et l'appel entier (la connexion, l'envoi, la réponse), plus que les 60 s d'un appel court. */
const val CORRECT_CALL_S = 90L

/** Le client de « Corriger » : celui des appels courts ([base]), qui attend la fin d'une correction. Dérivé
 *  (`newBuilder`), il partage ses connexions ; les délais des autres appels ne changent pas. */
fun correctClient(base: OkHttpClient): OkHttpClient = base.newBuilder()
    .readTimeout(CORRECT_READ_S, TimeUnit.SECONDS)
    .callTimeout(CORRECT_CALL_S, TimeUnit.SECONDS)
    .build()

/**
 * « Corriger » : les fautes de [text] (20 000 caractères au plus — un mail, une réponse Teams n'en ont jamais plus),
 * sans changer ses mots. Un appel au modèle, au premier plan (tu attends), une correction à la fois par compte ; rien
 * n'est gardé, donc pas de clé d'envoi. À faire sur un client qui attend assez ([correctClient]). Les refus se disent
 * tels que le serveur les donne : vide (400), aucun modèle (409), trop long pour être corrigé d'un coup (413), une
 * réponse incomplète du modèle (422 : rien n'est posé), une correction déjà en cours ou trop d'appels (429), le modèle
 * n'a pas répondu (502).
 */
suspend fun MoiApi.correct(text: String): MoiApi.Result<Corrected> =
    post("/correct", jsonOf(listOf("text" to text)), key = null).decode(Corrected.serializer())

/** Ce que fait la réponse de « Corriger ». */
enum class CorrectTurn {
    /** Le champ a changé pendant l'appel (tu as continué d'écrire) : rien n'est posé. */
    MOVED,

    /** Rien à corriger, ou rien qui ne touchait pas aux mots : ton texte reste tel quel. */
    NONE,

    /** Le texte corrigé remplace le tien. */
    PUT,
}

/** La réponse [got] à « Corriger » pour [asked] (le texte envoyé), le champ contenant maintenant [now]. */
fun correctTurn(asked: String, now: String, got: Corrected): CorrectTurn = when {
    now != asked -> CorrectTurn.MOVED
    got.changes <= 0 -> CorrectTurn.NONE
    else -> CorrectTurn.PUT
}

/** « Annuler » : ton texte d'avant ([before]) revient, seulement si le champ ([now]) contient encore le texte corrigé
 *  ([corrected]) ; sinon `null` — ce que tu as écrit depuis reste. */
fun undoCorrection(now: String, corrected: String, before: String): String? = if (now == corrected) before else null

/**
 * Ce que dit « Corriger », tiré de `strings.xml` par l'écran : le champ vide, aucune faute, tout ce qu'il proposait
 * touchait aux mots ([untouched]), tu as continué d'écrire, aucun modèle ; [fixed] : combien de fautes ont été
 * corrigées (le pluriel `correct_done`) ; [fixedDropped] : combien de fautes, et combien de changements écartés
 * (`correct_dropped`).
 */
class CorrectWords(
    val empty: String,
    val none: String,
    val untouched: String,
    val moved: String,
    val off: String,
    val fixed: (changes: Int) -> String,
    val fixedDropped: (changes: Int, refused: Int) -> String,
)

/** Ce que dit « Corriger » une fois fait (la règle du web, `correctedText`) : combien de fautes, ou aucune ; et combien
 *  de changements ont été écartés parce qu'ils touchaient aux mots. */
fun correctedText(changes: Int, refused: Int, words: CorrectWords): String = when {
    changes <= 0 -> if (refused > 0) words.untouched else words.none
    refused <= 0 -> words.fixed(changes)
    else -> words.fixedDropped(changes, refused)
}
