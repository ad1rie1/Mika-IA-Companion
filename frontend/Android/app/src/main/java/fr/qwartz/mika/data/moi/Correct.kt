package fr.qwartz.mika.data.moi

import kotlinx.serialization.Serializable

/*
 * « Corriger » (ADR 0307), dans le champ de Mail et de Teams : les fautes de ce que tu écris (orthographe, accents,
 * accords, conjugaison, homophones, ponctuation et ses espaces), sans changer tes mots. `POST /api/moi/correct`
 * (`backendv2/docs/protocole-moi.md` § 2) ; il marche quand un modèle est donné au rôle `correct` (`GET /api/moi` →
 * `correct`, [Me.correct]). Le texte corrigé remplace le tien aussitôt, et « Annuler » te le rend. Porté de
 * `frontendv2/src/screens/mail/compose.ts` (`correctField`), pur et testé sur la JVM ; les mots sont dans
 * `strings.xml` ([CorrectWords]).
 */

/** Ce que rend `POST /api/moi/correct` : le texte, ses fautes corrigées, et combien d'endroits ont changé (0 : rien à
 *  corriger, le texte revient tel quel). */
@Serializable
data class Corrected(val text: String = "", val changes: Int = 0)

/**
 * « Corriger » : les fautes de [text] (20 000 caractères au plus — un mail, une réponse Teams n'en ont jamais plus),
 * sans changer ses mots. Un appel au modèle, au premier plan (tu attends) ; rien
 * n'est gardé, donc pas de clé d'envoi. Les refus se disent tels que le serveur les donne : vide (400), aucun modèle
 * (409), le modèle a trop réécrit (422 : rien n'est remplacé), trop d'appels (429), le modèle n'a pas répondu (502).
 */
suspend fun MoiApi.correct(text: String): MoiApi.Result<Corrected> =
    post("/correct", jsonOf(listOf("text" to text)), key = null).decode(Corrected.serializer())

/** Ce que fait la réponse de « Corriger ». */
enum class CorrectTurn {
    /** Le champ a changé pendant l'appel (tu as continué d'écrire) : rien n'est posé. */
    MOVED,

    /** Rien à corriger : ton texte reste tel quel. */
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
 * Ce que dit « Corriger », tiré de `strings.xml` par l'écran : le champ vide, aucune faute, tu as continué d'écrire,
 * aucun modèle ; [fixed] : combien de fautes ont été corrigées (le pluriel `correct_done`).
 */
class CorrectWords(
    val empty: String,
    val none: String,
    val moved: String,
    val off: String,
    val fixed: (Int) -> String,
)

/** Ce que dit « Corriger » une fois fait : combien de fautes, ou aucune. */
fun correctedText(changes: Int, words: CorrectWords): String = if (changes <= 0) words.none else words.fixed(changes)
