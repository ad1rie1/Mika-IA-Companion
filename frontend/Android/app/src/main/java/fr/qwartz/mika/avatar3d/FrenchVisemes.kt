package fr.qwartz.mika.avatar3d

import java.text.Normalizer
import kotlin.math.floor
import kotlin.math.min
import kotlin.math.sin

/**
 * Texte français → visèmes, pour une bouche qui articule — port de `frontend/Web/src/audio/frenchVisemes.ts`, règle
 * pour règle.
 *
 * Une lecture lettre à lettre fait trois bouches pour « eau », prononce le « s » muet de « les », en fait deux pour
 * « ch », « gn » et « qu », et ne ferme jamais les lèvres sur un « p ». Ici, un passage graphème → phonème
 * raisonnable (digrammes, nasales, lettres muettes, élisions, nombres en toutes lettres), puis chaque phonème est
 * projeté sur les 15 visèmes VRChat/Oculus que porte le modèle.
 *
 * Ce n'est pas un phonétiseur de linguiste : il doit avoir l'air juste sur un visage à vitesse de parole. Les erreurs
 * résiduelles (liaisons non modélisées, « -ent » ambigu, homographes) coûtent une voyelle de travers, jamais une
 * bouche qui part en vrille.
 *
 * Pur : ni Android ni Filament, testé sur la JVM. Les index sont des `Char` (unités UTF-16), comme ceux du web : le
 * curseur que l'app passe compte dans la même chaîne.
 *
 * Deux invariants que le lip-sync exige :
 *  - chaque trame garde l'index d'ORIGINE du caractère qu'elle articule (le recalage s'y fait, en index du texte
 *    complet) ;
 *  - la durée totale d'un segment vaut `msPerChar × spokenLength(texte)`, c'est-à-dire la longueur aux blancs
 *    repliés — à une exception près : un nombre compte pour la longueur de sa forme en toutes lettres, parce que
 *    c'est ce qui se dit (« 2026 » dure « deux mille vingt-six », pas quatre caractères).
 */
object FrenchVisemes {

    // --- Visèmes ---

    /** Les 15 visèmes VRChat/Oculus, dans l'ordre de leurs morphoses `vrc.v_*`. `id` est le nom du web. */
    enum class Viseme(val id: String) {
        SIL("sil"), PP("PP"), FF("FF"), TH("TH"), DD("DD"), KK("kk"), CH("CH"), SS("SS"), NN("nn"), RR("RR"),
        AA("aa"), E("E"), IH("ih"), OH("oh"), OU("ou");

        /** La morphose VRChat du visème : `vrc.v_aa`, `vrc.v_pp`… */
        val morph: String get() = "vrc.v_${id.lowercase()}"
    }

    /**
     * Une trame : un visème tenu `duration` ms à son poids crête. `charOffset` est l'index, dans le texte complet de
     * la réponse, du caractère qu'elle articule ; −1 pour un silence de prosodie ou un plan sans position. `gap` : un
     * blanc entre deux mots — pas de fermeture, la bouche glisse d'une forme à la suivante (on ne referme pas la
     * bouche entre chaque mot en parlant).
     */
    data class Frame(
        val viseme: Viseme,
        val weight: Double,
        val duration: Double,
        val charOffset: Int,
        val gap: Boolean = false,
    )

    // --- Phonèmes ---

    /**
     * Inventaire réduit, notation proche du X-SAMPA : `@` schwa, `2` « eu », `E` « è », `~` nasale, `J` « gn »,
     * `S`/`Z` « ch »/« j », `H` le « u » de « nuit », `R` le r français.
     */
    data class PhonemeToken(val ph: String, val at: Int)

    class PhonemeInfo(val viseme: Viseme, val weight: Double, val length: Double, val vowel: Boolean)

    private fun info(viseme: Viseme, weight: Double, length: Double, vowel: Boolean = false) =
        PhonemeInfo(viseme, weight, length, vowel)

    val PHONEMES: Map<String, PhonemeInfo> = mapOf(
        "a" to info(Viseme.AA, 1.0, 1.0, true),
        "a~" to info(Viseme.AA, 0.75, 1.15, true),
        "e" to info(Viseme.E, 0.8, 0.95, true),
        "E" to info(Viseme.E, 0.85, 1.0, true),
        "e~" to info(Viseme.E, 0.7, 1.15, true),
        // Le schwa français est arrondi et bref (« le » ≈ [lø]).
        "@" to info(Viseme.OH, 0.4, 0.6, true),
        "2" to info(Viseme.OH, 0.6, 1.0, true),
        "i" to info(Viseme.IH, 0.8, 0.9, true),
        "o" to info(Viseme.OH, 0.9, 1.0, true),
        "o~" to info(Viseme.OH, 0.8, 1.15, true),
        "u" to info(Viseme.OU, 0.9, 0.95, true),
        // [y] : lèvres arrondies et serrées, la même bouche que « ou » vue de face.
        "y" to info(Viseme.OU, 0.85, 0.9, true),
        "j" to info(Viseme.IH, 0.5, 0.4),
        "w" to info(Viseme.OU, 0.7, 0.45),
        "H" to info(Viseme.OU, 0.6, 0.4),
        // Bilabiales : les lèvres se ferment, poids plein.
        "p" to info(Viseme.PP, 1.0, 0.55),
        "b" to info(Viseme.PP, 1.0, 0.55),
        "m" to info(Viseme.PP, 1.0, 0.6),
        // Labiodentales : lèvre inférieure sous les incisives.
        "f" to info(Viseme.FF, 1.0, 0.65),
        "v" to info(Viseme.FF, 0.95, 0.6),
        "t" to info(Viseme.DD, 0.85, 0.5),
        "d" to info(Viseme.DD, 0.85, 0.5),
        "n" to info(Viseme.NN, 0.85, 0.55),
        "l" to info(Viseme.NN, 0.75, 0.5),
        "J" to info(Viseme.NN, 0.9, 0.6),
        "k" to info(Viseme.KK, 0.85, 0.55),
        "g" to info(Viseme.KK, 0.8, 0.55),
        "s" to info(Viseme.SS, 0.95, 0.65),
        "z" to info(Viseme.SS, 0.9, 0.6),
        "S" to info(Viseme.CH, 1.0, 0.65),
        "Z" to info(Viseme.CH, 0.95, 0.6),
        // Le r uvulaire ne se voit presque pas sur les lèvres.
        "R" to info(Viseme.RR, 0.7, 0.5),
    )

    private fun phoneme(ph: String): PhonemeInfo = PHONEMES.getValue(ph)

    // --- Timing ---

    /** Part d'un caractère qu'un blanc garde pour lui (le reste nourrit les phonèmes) : assez pour une détente, trop
     * peu pour une fermeture. */
    private const val SPACE_GAP_SHARE = 0.5
    /** Allongement de la dernière voyelle avant une pause : l'accent français tombe en fin de groupe. Redistribué, il
     * ne change pas la durée totale. */
    private const val FINAL_LENGTHENING = 1.35
    /** Variation d'amplitude déterministe d'une voyelle à l'autre (±4 %) : sans elle, deux « a » successifs sont deux
     * copies — c'est ce qui fait robot. */
    private const val WEIGHT_JITTER = 0.08

    // --- Classes de lettres ---

    /** Hors du mot : les règles lisent ce caractère comme « rien » (la chaîne vide du web). */
    private const val NONE = '\u0000'
    private const val VOWEL_LETTERS = "aàâäeéèêëiîïoôöuùûüyÿœæ"
    private const val FRONT_LETTERS = "eéèêëiîïyÿ" // c et g doux devant elles
    private const val SILENT_FINALS = "stdxzp"
    /** Apostrophes et traits d'union : ils lient un mot sans s'entendre (« qu'est-ce », « peut-être »). */
    private const val JOINERS = "'’ʼ-‐‑"
    private const val APOSTROPHES = "'’ʼ"
    /** Ponctuation qui pose une vraie pause (fermeture). Les guillemets, parenthèses, astérisques ou émojis ne se
     * disent pas : ils glissent, comme un blanc. */
    private const val PAUSE_PUNCT = ".,;:!?…—–"

    private fun inSet(c: Char, set: String): Boolean = c != NONE && set.indexOf(c) >= 0
    private fun isVowelLetter(c: Char): Boolean = inSet(c, VOWEL_LETTERS)
    private fun isLetter(c: Char): Boolean = Character.isLetter(c)
    private fun isMark(c: Char): Boolean = when (Character.getType(c).toByte()) {
        Character.NON_SPACING_MARK, Character.ENCLOSING_MARK, Character.COMBINING_SPACING_MARK -> true
        else -> false
    }
    /** Le `\s` du JavaScript : les blancs Unicode, espace insécable et BOM compris. */
    private fun isSpace(c: Char): Boolean = c.isWhitespace() || c == '﻿'
    private fun isDigit(c: Char): Boolean = c in '0'..'9'
    private fun isJoiner(c: Char): Boolean = JOINERS.indexOf(c) >= 0
    private fun isApostrophe(c: Char): Boolean = APOSTROPHES.indexOf(c) >= 0

    // --- Lexique : ce que les règles ne savent pas deviner ---

    /** Mots entiers irréguliers (phonèmes séparés par des espaces). */
    private val EXCEPTIONS: Map<String, String> = mapOf(
        "est" to "E", "et" to "e", "es" to "E", "ok" to "o k e",
        "vingt" to "v e~", "vingts" to "v e~", "sept" to "s E t", "huit" to "H i t", "six" to "s i s", "dix" to "d i s",
        "soixante" to "s w a s a~ t", "fils" to "f i s", "femme" to "f a m", "femmes" to "f a m",
        "monsieur" to "m @ s j 2", "messieurs" to "m e s j 2", "oignon" to "o J o~",
        "second" to "s @ g o~", "seconde" to "s @ g o~ d", "eu" to "y", "eus" to "y", "eut" to "y",
        "pays" to "p E i", "août" to "u t", "ouest" to "w E s t", "œil" to "2 j", "yeux" to "j 2",
        "gens" to "Z a~", "chez" to "S e", "clef" to "k l e", "doigt" to "d w a", "doigts" to "d w a",
        "corps" to "k o R", "blanc" to "b l a~", "franc" to "f R a~", "tabac" to "t a b a",
        "estomac" to "E s t o m a", "porc" to "p o R", "hier" to "j E R", "fier" to "f j E R", "cher" to "S E R",
        "hiver" to "i v E R", "super" to "s y p E R", "enfer" to "a~ f E R", "amer" to "a m E R",
    )

    /** Mots dont la consonne finale se prononce malgré la règle des muettes. */
    private val FINAL_KEPT: Set<String> = setOf(
        "bus", "os", "ours", "mars", "sens", "virus", "bonus", "tennis", "hélas", "maïs",
        "jadis", "oasis", "iris", "atlas", "cactus", "campus", "lys", "autobus",
        "net", "but", "test", "brut", "chut", "dot", "kit", "mat", "sud",
        "stop", "top", "cap", "slip", "clip", "hip",
        "gaz", "fax", "box", "max", "relax", "lynx", "index", "linux", "sphinx",
    )

    /** « -er » final prononcé [ɛʁ] (le cas général est l'infinitif muet). */
    private val ER_KEPT: Set<String> = setOf("laser", "cancer", "hamster", "poster", "master", "starter", "leader")

    /** « -ent » final qui n'est pas une terminaison verbale. */
    private val ENT_PRONOUNCED: Set<String> = setOf(
        "parent", "souvent", "absent", "présent", "argent", "agent", "urgent", "client",
        "patient", "impatient", "talent", "accent", "content", "serpent", "évident",
        "différent", "intelligent", "prudent", "récent", "fréquent", "excellent",
        "innocent", "adolescent", "accident", "incident", "président", "résident",
        "équivalent", "violent", "ardent", "torrent", "orient", "occident", "quotient",
        "permanent", "compétent", "décent", "indécent", "pertinent", "continent",
    )

    /** Sujets qui rendent un « -ent » final muet à coup sûr (« ils mangent »). */
    private val PLURAL_SUBJECTS: Set<String> = setOf("ils", "elles")

    /** Monosyllabes où le « e » final se dit (schwa). */
    private val SCHWA_WORDS: Set<String> = setOf("que")

    /** « ill » qui se dit [il] et non [ij]. */
    private val LL_PRONOUNCED = Regex("^(vill|mill|tranquill|lill|distill|oscill|pupill|bacill)")
    private val VERBAL_IENT = Regex("[tv]ient$")

    /** Consonne élidée devant une apostrophe (« l'ami », « c'est », « j'ai »). */
    private val ELIDED_LETTER: Map<String, String> = mapOf(
        "l" to "l", "d" to "d", "j" to "Z", "m" to "m", "n" to "n", "s" to "s", "t" to "t", "c" to "s", "ç" to "s",
    )

    /** Une lettre isolée se dit par son nom (« le point b ») ; « y » et « a » sont des mots. */
    private val LETTER_NAMES: Map<String, String> = mapOf(
        "a" to "a", "à" to "a", "â" to "a", "e" to "@", "é" to "e", "è" to "E", "ê" to "E", "i" to "i", "î" to "i",
        "o" to "o", "ô" to "o", "u" to "y", "y" to "i",
        "b" to "b e", "c" to "s e", "ç" to "s e", "d" to "d e", "f" to "E f", "g" to "Z e", "h" to "a S", "j" to "Z i",
        "k" to "k a", "l" to "E l", "m" to "E m", "n" to "E n", "p" to "p e", "q" to "k y", "r" to "E R", "s" to "E s",
        "t" to "t e", "v" to "v e", "w" to "d u b l @ v e", "x" to "i k s", "z" to "z E d",
    )

    // --- Mots ---

    /** Répartit une chaîne de phonèmes sur les lettres d'un mot, en ordre. */
    private fun spread(phonemes: String, pos: List<Int>, out: MutableList<PhonemeToken>) {
        val parts = phonemes.split(" ")
        val count = pos.size
        parts.forEachIndexed { k, ph ->
            out.add(PhonemeToken(ph, pos[min(count - 1, (k * count) / parts.size)]))
        }
    }

    /**
     * Longueur prononcée d'un mot : ce qui suit est muet (e muet, « -es », « -ent » verbal, consonnes finales, r de
     * l'infinitif). Les lettres muettes restent lisibles par les règles comme contexte (« mangent » : le « e » muet
     * adoucit quand même le « g »).
     */
    private fun pronouncedEnd(s: String, prev: String): Int {
        val len = s.length
        if (len <= 1) return len
        if (s.endsWith("aient")) return len - 3 // imparfait : « étaient »
        if (s.endsWith("ent") && len >= 4) {
            if (prev in PLURAL_SUBJECTS) return len - 3
            if (len >= 5 && !s.endsWith("ment") && s !in ENT_PRONOUNCED && !VERBAL_IENT.containsMatchIn(s)) {
                return len - 3
            }
        }
        var end = len
        if (s.endsWith("es") && len > 3 && s !in FINAL_KEPT) {
            end = len - 2 // pluriel ou 2e personne d'un mot en e muet
        } else if (s.endsWith("e")) {
            if (len > 2 && s !in SCHWA_WORDS) end = len - 1 // e muet
        } else if (s !in FINAL_KEPT && !s.endsWith("ss") && inSet(s[len - 1], SILENT_FINALS)) {
            val first = s[len - 1]
            end = len - 1
            // « grands », « temps », « petits » : le pluriel découvre une autre muette.
            if ((first == 's' || first == 'x') && end > 1 && inSet(s[end - 1], "tdp")) end -= 1
        }
        val base = s.substring(0, end)
        if (base.endsWith("er") && end >= 4 && base !in ER_KEPT) end -= 1 // infinitif, -ier
        else if (base.endsWith("ng")) end -= 1 // « long », « sang »
        return end
    }

    /**
     * Phonétise un mot sans apostrophe ni trait d'union. `s` est en minuscules composées, `pos[i]` l'index source de
     * la lettre `s[i]`.
     */
    private fun pronounceWord(
        s: String,
        orig: String,
        pos: List<Int>,
        prev: String,
        elided: Boolean,
        out: MutableList<PhonemeToken>,
    ) {
        val len = s.length
        if (len == 0) return

        if (elided && len == 1) {
            val ph = ELIDED_LETTER[s]
            if (ph != null) out.add(PhonemeToken(ph, pos[0])) else spread(LETTER_NAMES[s] ?: "@", pos, out)
            return
        }
        if (!elided) {
            val exception = EXCEPTIONS[s]
            if (exception != null) return spread(exception, pos, out)
            if (len == 1) return spread(LETTER_NAMES[s] ?: "@", pos, out)
            // Sigle sans voyelle (« SMS ») : la voix l'épelle.
            if (orig == orig.uppercase() && orig != orig.lowercase() && s.none { isVowelLetter(it) }) {
                for (k in 0 until len) spread(LETTER_NAMES[s[k].toString()] ?: "@", listOf(pos[k]), out)
                return
            }
        }

        val end = if (elided) len else pronouncedEnd(s, prev)
        val base = out.size
        fun ch(k: Int): Char = if (k in 0 until len) s[k] else NONE
        fun vowelAt(k: Int): Boolean = isVowelLetter(ch(k))
        fun consonantAt(k: Int): Boolean = ch(k) != NONE && !isVowelLetter(ch(k))
        fun emit(ph: String, k: Int) {
            out.add(PhonemeToken(ph, pos[min(k, len - 1)]))
        }
        // Un n/m nasalise la voyelle qui le précède s'il n'est suivi ni d'une voyelle — même muette : « une »,
        // « bonne » — ni d'un n/m/h.
        fun nasal(k: Int): Boolean = inSet(ch(k), "nm") && k < end && !vowelAt(k + 1) && !inSet(ch(k + 1), "nmh")

        /** Consonne simple ; une consonne doublée ne se dit qu'une fois. */
        fun doubled(k: Int, ph: String): Int {
            emit(ph, k)
            return if (ch(k + 1) == s[k]) 2 else 1
        }

        /** Le « e » sans accent ni digramme : [e], [ɛ], schwa, ou rien. */
        fun plainE(k: Int) {
            if (k == end - 1) {
                if (end < len) {
                    // Suivi de muettes : « manger », « chez », « pied », « les » / « poulet ».
                    emit(if (inSet(ch(k + 1), "rzds")) "e" else "E", k)
                } else {
                    emit("@", k) // « le », « que »
                }
                return
            }
            if (k == 0) {
                emit("E", k) // « elle », « Eric »
                return
            }
            if (!consonantAt(k + 1)) {
                emit("E", k)
                return
            }
            // Une consonne (un digramme compte pour une) puis une voyelle : syllabe ouverte, schwa ; deux consonnes ou
            // une finale : syllabe fermée, [ɛ].
            val pair = "${ch(k + 1)}${ch(k + 2)}"
            val after = k + if (pair == "ch" || pair == "ph" || pair == "th" || pair == "gn") 3 else 2
            val cluster = inSet(ch(k + 1), "bcdfgkptv") && inSet(ch(k + 2), "lr") && vowelAt(k + 3)
            val closed = !cluster && (consonantAt(after) || after >= end)
            if (closed) {
                emit("E", k)
                return
            }
            // Schwa entre une seule consonne et une consonne + voyelle : il tombe (« samedi » [samdi],
            // « maintenant » [mɛ̃tnɑ̃]).
            val n = out.size - base
            val elidable = n >= 2 &&
                !phoneme(out[out.size - 1].ph).vowel &&
                phoneme(out[out.size - 2].ph).vowel &&
                consonantAt(k + 1) &&
                vowelAt(k + 2)
            if (!elidable) emit("@", k)
        }

        var i = 0
        while (i < end) {
            val c = s[i]
            when (c) {
                'a', 'à', 'â', 'ä' -> {
                    if (c == 'a' && ch(i + 1) == 'i' && ch(i + 2) == 'l' && (i + 3 >= end || ch(i + 3) == 'l')) {
                        emit("a", i) // « travail », « paille »
                        emit("j", i + 1)
                        i += if (ch(i + 3) == 'l') 4 else 3
                    } else if (c == 'a' && inSet(ch(i + 1), "iî")) {
                        if (nasal(i + 2)) {
                            emit("e~", i) // « pain », « faim »
                            i += 3
                        } else {
                            emit("E", i)
                            i += 2
                        }
                    } else if (c == 'a' && inSet(ch(i + 1), "uû")) {
                        emit("o", i)
                        i += 2
                    } else if (c == 'a' && ch(i + 1) == 'y') {
                        emit("E", i) // « crayon » : le y suit en [j]
                        i += 1
                    } else if (nasal(i + 1)) {
                        emit("a~", i)
                        i += 2
                    } else {
                        emit("a", i)
                        i += 1
                    }
                }
                'e' -> {
                    if (ch(i + 1) == 'a' && ch(i + 2) == 'u') {
                        emit("o", i) // « eau », « oiseau »
                        i += 3
                    } else if (ch(i + 1) == 'u' && ch(i + 2) == 'i' && ch(i + 3) == 'l') {
                        emit("2", i) // « feuille », « fauteuil »
                        emit("j", i + 2)
                        i += if (ch(i + 4) == 'l') 5 else 4
                    } else if (inSet(ch(i + 1), "uû")) {
                        emit("2", i)
                        i += 2
                    } else if (ch(i + 1) == 'i' && ch(i + 2) == 'l' && (i + 3 >= end || ch(i + 3) == 'l')) {
                        emit("E", i) // « soleil », « abeille »
                        emit("j", i + 1)
                        i += if (ch(i + 3) == 'l') 4 else 3
                    } else if (inSet(ch(i + 1), "iî")) {
                        if (nasal(i + 2)) {
                            emit("e~", i) // « plein »
                            i += 3
                        } else {
                            emit("E", i)
                            i += 2
                        }
                    } else if (ch(i + 1) == 'y') {
                        emit("E", i)
                        i += 1
                    } else if (nasal(i + 1)) {
                        // « bien », « européen », « viendra » : [ɛ̃] après i/é/y en fin de mot ou devant d ;
                        // « science », « patience », et partout ailleurs : [ɑ̃].
                        val ien = inSet(ch(i - 1), "iéy") && (i + 2 >= end || ch(i + 2) == 'd')
                        emit(if (ien) "e~" else "a~", i)
                        i += 2
                    } else {
                        plainE(i)
                        i += 1
                    }
                }
                'é', 'æ' -> {
                    emit("e", i)
                    i += 1
                }
                'è', 'ê', 'ë' -> {
                    emit("E", i)
                    i += 1
                }
                'i', 'î', 'ï', 'y', 'ÿ' -> {
                    val isY = c == 'y' || c == 'ÿ'
                    if (isY && ((i == 0 && vowelAt(i + 1)) || (vowelAt(i - 1) && vowelAt(i + 1)))) {
                        emit("j", i) // « yaourt », « crayon », « voyage »
                        i += 1
                    } else if (c == 'i' && i > 0 && ch(i + 1) == 'l' && ch(i + 2) == 'l') {
                        if (LL_PRONOUNCED.containsMatchIn(s)) {
                            emit("i", i) // « ville », « million » : le « ll » suit en [l]
                            i += 1
                        } else {
                            emit("i", i) // « fille », « famille »
                            emit("j", i + 1)
                            i += 3
                        }
                    } else if ((c == 'i' || isY) && nasal(i + 1)) {
                        emit("e~", i)
                        i += 2
                    } else if (c == 'i' && i > 0 && consonantAt(i - 1) && vowelAt(i + 1) && i + 1 < end) {
                        emit("j", i) // « pied », « bien », « nation »
                        i += 1
                    } else {
                        emit("i", i)
                        i += 1
                    }
                }
                'o', 'ô', 'ö' -> {
                    if (c == 'o' && ch(i + 1) == 'i' && nasal(i + 2)) {
                        emit("w", i) // « loin », « point »
                        emit("e~", i + 1)
                        i += 3
                    } else if (c == 'o' && inSet(ch(i + 1), "iî")) {
                        emit("w", i) // « moi », « oiseau »
                        emit("a", i + 1)
                        i += 2
                    } else if (c == 'o' && ch(i + 1) == 'y') {
                        emit("w", i) // « voyage » : le y suit en [j]
                        emit("a", i)
                        i += 1
                    } else if (c == 'o' && inSet(ch(i + 1), "uùû")) {
                        if (ch(i + 2) == 'i' && ch(i + 3) == 'l' && ch(i + 4) == 'l') {
                            emit("u", i) // « grenouille »
                            emit("j", i + 2)
                            i += 5
                        } else if (vowelAt(i + 2) && i + 2 < end) {
                            emit("w", i) // « oui », « jouer »
                            i += 2
                        } else {
                            emit("u", i)
                            i += 2
                        }
                    } else if (nasal(i + 1)) {
                        emit("o~", i)
                        i += 2
                    } else {
                        emit("o", i)
                        i += 1
                    }
                }
                'œ' -> {
                    emit("2", i) // « cœur », « œuvre »
                    i += if (ch(i + 1) == 'u') 2 else 1
                }
                'u', 'ù', 'û', 'ü' -> {
                    if (c == 'u' && ch(i + 1) == 'e' && ch(i + 2) == 'i' && ch(i + 3) == 'l') {
                        emit("2", i) // « accueil », « cueillir »
                        emit("j", i + 2)
                        i += if (ch(i + 4) == 'l') 5 else 4
                    } else if (c == 'u' && ch(i + 1) == 'm' && i + 2 >= len) {
                        emit("o", i) // « album », « maximum »
                        emit("m", i + 1)
                        i += 2
                    } else if (c == 'u' && nasal(i + 1)) {
                        emit("e~", i) // « un », « lundi »
                        i += 2
                    } else if (i > 0 && vowelAt(i + 1) && i + 1 < end) {
                        emit("H", i) // « nuit », « lui »
                        i += 1
                    } else {
                        emit("y", i)
                        i += 1
                    }
                }
                'c' -> {
                    if (ch(i + 1) == 'h') {
                        emit(if (inSet(ch(i + 2), "rl")) "k" else "S", i) // « chat » / « chrome »
                        i += 2
                    } else if (ch(i + 1) == 'c') {
                        emit("k", i)
                        if (inSet(ch(i + 2), FRONT_LETTERS)) emit("s", i + 1) // « accent »
                        i += 2
                    } else if (ch(i + 1) == 'k') {
                        emit("k", i)
                        i += 2
                    } else {
                        emit(if (inSet(ch(i + 1), FRONT_LETTERS)) "s" else "k", i)
                        i += 1
                    }
                }
                'ç' -> {
                    emit("s", i)
                    i += 1
                }
                'g' -> {
                    if (ch(i + 1) == 'n') {
                        emit("J", i) // « champagne »
                        i += 2
                    } else if (ch(i + 1) == 'u' && inSet(ch(i + 2), FRONT_LETTERS)) {
                        emit("g", i) // « guitare »
                        i += 2
                    } else if (ch(i + 1) == 'e' && inSet(ch(i + 2), "aâoôu")) {
                        emit("Z", i) // « mangeons », « geai »
                        i += 2
                    } else if (ch(i + 1) == 'g') {
                        emit("g", i)
                        if (inSet(ch(i + 2), FRONT_LETTERS)) emit("Z", i + 1) // « suggérer »
                        i += 2
                    } else {
                        emit(if (inSet(ch(i + 1), FRONT_LETTERS)) "Z" else "g", i)
                        i += 1
                    }
                }
                'h' -> i += 1 // muet hors digrammes
                'j' -> {
                    emit("Z", i)
                    i += 1
                }
                'p' -> {
                    if (ch(i + 1) == 'h') {
                        emit("f", i) // « photo »
                        i += 2
                    } else {
                        i += doubled(i, "p")
                    }
                }
                'q' -> {
                    emit("k", i) // « qu » : le u ne se dit pas
                    i += if (ch(i + 1) == 'u') 2 else 1
                }
                's' -> {
                    if (ch(i + 1) == 'c' && ch(i + 2) == 'h') {
                        emit("S", i)
                        i += 3
                    } else if (ch(i + 1) == 'h') {
                        emit("S", i)
                        i += 2
                    } else if (ch(i + 1) == 's') {
                        emit("s", i)
                        i += 2
                    } else if (ch(i + 1) == 'c' && inSet(ch(i + 2), FRONT_LETTERS)) {
                        emit("s", i) // « science »
                        i += 2
                    } else {
                        emit(if (vowelAt(i - 1) && vowelAt(i + 1)) "z" else "s", i) // « oiseau », « chose »
                        i += 1
                    }
                }
                't' -> {
                    if (ch(i + 1) == 'h' || ch(i + 1) == 't') {
                        emit("t", i)
                        i += 2
                    } else if (
                        ch(i + 1) == 'i' && ch(i + 2) == 'o' && ch(i + 3) == 'n' && i > 0 && !inSet(ch(i - 1), "sx")
                    ) {
                        emit("s", i) // « nation », mais « question »
                        i += 1
                    } else {
                        emit("t", i)
                        i += 1
                    }
                }
                'x' -> {
                    if (i == 1 && ch(0) == 'e' && (vowelAt(2) || ch(2) == 'h')) {
                        emit("g", i) // « exemple »
                        emit("z", i)
                    } else if (s.contains("xième")) {
                        emit("z", i) // « deuxième »
                    } else {
                        emit("k", i) // « taxi »
                        emit("s", i)
                    }
                    i += 1
                }
                'w' -> {
                    emit("w", i)
                    i += 1
                }
                'ñ' -> {
                    emit("J", i)
                    i += 1
                }
                'ß' -> {
                    emit("s", i)
                    i += 1
                }
                'b', 'd', 'f', 'k', 'l', 'm', 'n', 'v', 'z' -> i += doubled(i, c.toString())
                'r' -> i += doubled(i, "R")
                // Lettre hors du français (autre écriture) : une ouverture neutre, pour que la bouche bouge quand le
                // texte parle.
                else -> {
                    emit("@", i)
                    i += 1
                }
            }
        }
    }

    // --- Nombres ---

    private val UNITS = listOf(
        "zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
        "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize",
    )
    private val TENS = mapOf(2 to "vingt", 3 to "trente", 4 to "quarante", 5 to "cinquante", 6 to "soixante")

    private fun below100(n: Int): String {
        if (n < 17) return UNITS[n]
        if (n < 20) return "dix-${UNITS[n - 10]}"
        val tens = n / 10
        val unit = n % 10
        if (tens == 7) return if (unit == 1) "soixante et onze" else "soixante-${below100(10 + unit)}"
        if (tens == 8) return if (unit == 0) "quatre-vingts" else "quatre-vingt-${UNITS[unit]}"
        if (tens == 9) return "quatre-vingt-${below100(10 + unit)}"
        val name = TENS.getValue(tens)
        if (unit == 0) return name
        return if (unit == 1) "$name et un" else "$name-${UNITS[unit]}"
    }

    private fun below1000(n: Int): String {
        val hundreds = n / 100
        val rest = n % 100
        val head = when (hundreds) {
            0 -> ""
            1 -> "cent"
            else -> "${UNITS[hundreds]} cent${if (rest == 0) "s" else ""}"
        }
        return listOf(head, if (rest != 0) below100(rest) else "").filter { it.isNotEmpty() }.joinToString(" ")
    }

    /** Écrit un entier en toutes lettres, comme une voix le lit. Au-delà de neuf chiffres, ou avec un zéro de tête
     * (« 06… »), chiffre par chiffre. */
    fun spellNumber(digits: String): String {
        if (digits.length > 9 || (digits.length > 1 && digits[0] == '0')) {
            return digits.map { UNITS[it - '0'] }.joinToString(" ")
        }
        val n = digits.toInt()
        if (n == 0) return UNITS[0]
        val millions = n / 1_000_000
        val thousands = (n / 1000) % 1000
        val rest = n % 1000
        val parts = ArrayList<String>()
        if (millions != 0) parts += if (millions == 1) "un million" else "${below1000(millions)} millions"
        if (thousands != 0) parts += if (thousands == 1) "mille" else "${below1000(thousands)} mille"
        if (rest != 0) parts += below1000(rest)
        return parts.joinToString(" ")
    }

    // --- Analyse ---

    private enum class UnitKind { WORD, NUMBER, SPACE, PAUSE, SYMBOL }

    /** Un morceau du texte. `chars` est son poids temporel en caractères (la longueur aux blancs repliés). */
    private class TextUnit(val kind: UnitKind, val from: Int, val chars: Int, val phonemes: List<PhonemeToken>)

    private class Letters(val orig: String, val lower: String, val pos: List<Int>)

    /** Minuscule composée d'un caractère, réduite à un caractère (« İ » minuscule en fait deux). */
    private fun lowerChar(c: String): Char = Normalizer.normalize(c.lowercase(), Normalizer.Form.NFC)[0]

    /** Lettres d'un fragment, diacritiques combinants recomposés sur leur base (un « é » décomposé reste une lettre,
     * à l'index de sa base). */
    private fun composeLetters(text: String, from: Int, to: Int): Letters {
        val orig = StringBuilder()
        val lower = StringBuilder()
        val pos = ArrayList<Int>()
        for (k in from until to) {
            val c = text[k]
            if (isMark(c)) {
                if (pos.isEmpty()) continue
                val composed = Normalizer.normalize("${orig[orig.length - 1]}$c", Normalizer.Form.NFC)
                if (composed.length == 1) {
                    orig.setCharAt(orig.length - 1, composed[0])
                    lower.setCharAt(lower.length - 1, lowerChar(composed))
                }
                continue
            }
            orig.append(c)
            lower.append(lowerChar(c.toString()))
            pos.add(k)
        }
        return Letters(orig.toString(), lower.toString(), pos)
    }

    /** Un mot, apostrophes et traits d'union compris : chaque fragment est phonétisé à part (« qu'est-ce »,
     * « peut-être »). Rend le dernier fragment, contexte du mot suivant. */
    private fun pronounceWordUnit(
        text: String,
        from: Int,
        to: Int,
        prevWord: String,
        out: MutableList<PhonemeToken>,
    ): String {
        var prev = prevWord
        var k = from
        while (k < to) {
            var e = k
            while (e < to && !isJoiner(text[e])) e++
            val letters = composeLetters(text, k, e)
            val elided = e < to && isApostrophe(text[e])
            pronounceWord(letters.lower, letters.orig, letters.pos, prev, elided, out)
            prev = letters.lower
            k = e + 1
        }
        return prev
    }

    private val NUMBER_WORD = Regex("[^\\s-]+")

    /** Phonèmes d'un nombre écrit en toutes lettres, ramenés sur ses chiffres : l'index est interpolé le long de
     * « 2026 » pour rester monotone. */
    private fun numberPhonemes(spelled: String, from: Int, to: Int): List<PhonemeToken> {
        val local = ArrayList<PhonemeToken>()
        var prev = ""
        for (match in NUMBER_WORD.findAll(spelled)) {
            val at = match.range.first
            val letters = composeLetters(spelled, at, at + match.value.length)
            pronounceWord(letters.lower, letters.orig, letters.pos, prev, false, local)
            prev = letters.lower
        }
        val width = to - from
        return local.map { PhonemeToken(it.ph, from + (it.at * width) / spelled.length) }
    }

    private fun analyze(text: String): List<TextUnit> {
        val units = ArrayList<TextUnit>()
        val n = text.length
        var prevWord = ""
        var i = 0
        while (i < n) {
            val c = text[i]
            var j = i + 1
            if (isSpace(c)) {
                while (j < n && isSpace(text[j])) j++
                units += TextUnit(UnitKind.SPACE, i, 1, emptyList())
            } else if (isDigit(c)) {
                while (j < n && isDigit(text[j])) j++
                val spelled = spellNumber(text.substring(i, j))
                units += TextUnit(UnitKind.NUMBER, i, spelled.length, numberPhonemes(spelled, i, j))
                prevWord = ""
            } else if (isLetter(c)) {
                while (j < n) {
                    if (isLetter(text[j]) || isMark(text[j])) j++
                    else if (isJoiner(text[j]) && j + 1 < n && isLetter(text[j + 1])) j++
                    else break
                }
                val phonemes = ArrayList<PhonemeToken>()
                prevWord = pronounceWordUnit(text, i, j, prevWord, phonemes)
                units += TextUnit(UnitKind.WORD, i, j - i, phonemes)
            } else {
                while (j < n && !isSpace(text[j]) && !isDigit(text[j]) && !isLetter(text[j])) j++
                val pause = (i until j).any { PAUSE_PUNCT.indexOf(text[it]) >= 0 }
                if (pause) prevWord = ""
                units += TextUnit(if (pause) UnitKind.PAUSE else UnitKind.SYMBOL, i, j - i, emptyList())
            }
            i = j
        }
        return units
    }

    /** Phonèmes du texte, dans l'ordre (tests et diagnostic). */
    fun phonemes(text: String): List<PhonemeToken> = analyze(text).flatMap { it.phonemes }

    /** Longueur temporelle d'un texte en caractères : blancs repliés, nombres comptés en toutes lettres.
     * `durée = msPerChar × spokenLength`. */
    fun spokenLength(text: String): Int = analyze(text).sumOf { it.chars }

    /** Variation déterministe dans [0, 1) — même texte, même bouche. */
    private fun hash01(x: Int): Double {
        val v = sin(x * 12.9898 + 78.233) * 43758.5453
        return v - floor(v)
    }

    private class Draft(
        val viseme: Viseme,
        val weight: Double,
        var length: Double,
        val at: Int,
        val fixed: Boolean,
        val gap: Boolean = false,
    )

    /**
     * Trames de visèmes d'un segment prononcé. `start` est l'index du segment dans la réponse complète (−1 : pas de
     * position, les trames portent −1).
     *
     * Les blancs et la ponctuation ont une durée fixe ; le reste du budget du segment se répartit sur les phonèmes au
     * prorata de leur durée relative — un mot dure donc ce qu'il se prononce (« eaux » est une voyelle, pas quatre
     * lettres), et le total reste `msPerChar × spokenLength(text)`.
     */
    fun frames(text: String, msPerChar: Double, start: Int = -1): List<Frame> {
        val ms = if (msPerChar.isFinite() && msPerChar > 0) msPerChar else 0.0
        val units = analyze(text)
        val total = ms * units.sumOf { it.chars }

        val drafts = ArrayList<Draft>()
        var lastVowel = -1
        fun lengthen() {
            if (lastVowel >= 0) drafts[lastVowel].length *= FINAL_LENGTHENING
            lastVowel = -1
        }

        for (unit in units) {
            when (unit.kind) {
                UnitKind.SPACE ->
                    drafts += Draft(Viseme.SIL, 0.0, ms * SPACE_GAP_SHARE, unit.from, fixed = true, gap = true)
                UnitKind.SYMBOL ->
                    drafts += Draft(Viseme.SIL, 0.0, ms * unit.chars, unit.from, fixed = true, gap = true)
                UnitKind.PAUSE -> {
                    lengthen()
                    drafts += Draft(Viseme.SIL, 0.0, ms * unit.chars, unit.from, fixed = true)
                }
                UnitKind.WORD, UnitKind.NUMBER -> for (token in unit.phonemes) {
                    val p = phoneme(token.ph)
                    if (p.vowel) lastVowel = drafts.size
                    val jitter = 1 - WEIGHT_JITTER / 2 + WEIGHT_JITTER * hash01(token.at + drafts.size)
                    drafts += Draft(
                        p.viseme,
                        min(1.0, p.weight * (if (p.vowel) jitter else 1.0)),
                        p.length,
                        token.at,
                        fixed = false,
                    )
                }
            }
        }
        lengthen()

        var fixed = 0.0
        var relative = 0.0
        for (d in drafts) if (d.fixed) fixed += d.length else relative += d.length
        val free = maxOf(0.0, total - fixed)

        val frames = drafts.mapTo(ArrayList()) { d ->
            Frame(
                viseme = d.viseme,
                weight = d.weight,
                duration = if (d.fixed) d.length else if (relative > 0) free * d.length / relative else 0.0,
                charOffset = if (start >= 0) start + d.at else -1,
                gap = d.gap,
            )
        }
        // Rien d'articulé (« … ») : le temps restant tient sur la dernière trame plutôt que de disparaître du budget.
        if (relative == 0.0 && free > 0 && frames.isNotEmpty()) {
            val last = frames.size - 1
            frames[last] = frames[last].copy(duration = frames[last].duration + free)
        }
        return frames
    }
}
