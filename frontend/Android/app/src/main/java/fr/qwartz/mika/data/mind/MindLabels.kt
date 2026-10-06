package fr.qwartz.mika.data.mind

/**
 * Tous les libellés français de son état. Les noms restent anglais sur le fil (ceux de
 * `vocab/affect.py`) ; on ne les traduit qu'ici, à un seul endroit — repris de
 * `frontend/Web/src/types/emotions.ts` et `ui/InnerLifePanel.ts`.
 */
object MindLabels {

    data class EmotionMeta(val label: String, val category: Category)

    enum class Category { NEUTRAL, POSITIVE, NEGATIVE, COMPLEX }

    /** Les 29 émotions, dans l'ordre de `emotions.ts`. */
    val EMOTIONS: Map<String, EmotionMeta> = linkedMapOf(
        "neutral" to EmotionMeta("Neutre", Category.NEUTRAL),
        "happy" to EmotionMeta("Contente", Category.POSITIVE),
        "excited" to EmotionMeta("Excitée !", Category.POSITIVE),
        "love" to EmotionMeta("Amoureuse", Category.POSITIVE),
        "proud" to EmotionMeta("Fière", Category.POSITIVE),
        "grateful" to EmotionMeta("Reconnaissante", Category.POSITIVE),
        "playful" to EmotionMeta("Joueuse", Category.POSITIVE),
        "amused" to EmotionMeta("Amusée", Category.POSITIVE),
        "hopeful" to EmotionMeta("Pleine d'espoir", Category.POSITIVE),
        "relieved" to EmotionMeta("Soulagée", Category.POSITIVE),
        "sad" to EmotionMeta("Triste", Category.NEGATIVE),
        "angry" to EmotionMeta("En colère", Category.NEGATIVE),
        "scared" to EmotionMeta("Effrayée", Category.NEGATIVE),
        "disgusted" to EmotionMeta("Dégoûtée", Category.NEGATIVE),
        "frustrated" to EmotionMeta("Frustrée", Category.NEGATIVE),
        "lonely" to EmotionMeta("Seule", Category.NEGATIVE),
        "anxious" to EmotionMeta("Anxieuse", Category.NEGATIVE),
        "bored" to EmotionMeta("S'ennuie...", Category.NEGATIVE),
        "jealous" to EmotionMeta("Jalouse", Category.NEGATIVE),
        "surprised" to EmotionMeta("Surprise !", Category.COMPLEX),
        "thinking" to EmotionMeta("Réfléchit...", Category.COMPLEX),
        "confused" to EmotionMeta("Confuse", Category.COMPLEX),
        "embarrassed" to EmotionMeta("Gênée", Category.COMPLEX),
        "nostalgic" to EmotionMeta("Nostalgique", Category.COMPLEX),
        "dreamy" to EmotionMeta("Rêveuse", Category.COMPLEX),
        "determined" to EmotionMeta("Déterminée", Category.COMPLEX),
        "mischievous" to EmotionMeta("Malicieuse", Category.COMPLEX),
        "curious" to EmotionMeta("Curieuse", Category.COMPLEX),
        "melancholic" to EmotionMeta("Mélancolique", Category.COMPLEX),
    )

    fun isEmotionName(value: String?): Boolean = value != null && value in EMOTIONS

    private fun key(name: String?) = name.orEmpty().trim().lowercase()

    /**
     * `curious` → « Curieuse ». Un nom hors des 29 est rendu tel quel, jamais replié sur « Neutre » :
     * la valeur brute dit « cette émotion n'est pas dans la liste » au lieu de mentir.
     */
    fun emotion(name: String?): String = EMOTIONS[key(name)]?.label ?: name.orEmpty()

    /** La forme de la ligne d'état : « curieuse », « excitée », « s'ennuie », « pleine d'espoir ». */
    fun emotionLower(name: String?): String {
        val meta = EMOTIONS[key(name)] ?: return name.orEmpty()
        return meta.label.removeSuffix("...").removeSuffix(" !").trim().lowercase()
    }

    /** InnerLifePanel.ts:93-98. */
    fun sleepPhase(phase: String?): String = when (phase) {
        SleepPhases.LIGHT -> "endormie (journal)"
        SleepPhases.REM -> "endormie (rêve)"
        SleepPhases.DEEP -> "sommeil profond"
        else -> "éveillée"
    }

    /** Où elle est dans sa chambre (`contracts/place.py`). */
    val PLACES: Map<String, String> = linkedMapOf(
        "center" to "au milieu de sa chambre",
        "window" to "à la fenêtre",
        "desk" to "à son bureau",
        "bed" to "sur son lit",
        "bookshelf" to "près de sa bibliothèque",
        "door" to "près de la porte",
    )

    fun place(place: String?): String? = PLACES[place.orEmpty()]

    /** Ce qu'elle fait, conjugué pour la ligne d'état (les occupations de `faculties/world/chambre.json`). */
    val ACTIVITIES: Map<String, String> = linkedMapOf(
        "draw" to "dessine",
        "work" to "travaille",
        "browse_books" to "feuillette un livre",
        "water_plant" to "arrose sa plante",
        "look_outside" to "regarde dehors",
    )

    /**
     * « dessine » ; une occupation que l'app ne connaît pas (un objet ajouté à sa chambre) se dit avec le
     * libellé du serveur, « en train de jongler » ; sans libellé, rien.
     */
    fun activity(name: String?, label: String?): String? {
        ACTIVITIES[name.orEmpty()]?.let { return it }
        val raw = label.orEmpty().trim().takeIf { it.isNotEmpty() } ?: return null
        val of = if (raw.first().lowercaseChar() in "aeiouyàâéèêëîïôöùûü") "d'" else "de "
        return "en train $of$raw"
    }

    /** Le moment de la journée (InnerLifePanel.ts:30-38). */
    fun circadianPhase(phase: String?): String? = when (phase) {
        "morning" -> "Matin"
        "afternoon" -> "Aprem"
        "evening" -> "Soir"
        "night" -> "Nuit"
        else -> null
    }

    /** « Soir · 21 h ». */
    fun momentOfDay(phase: String?, hour: Double?): String? {
        val label = circadianPhase(phase) ?: return null
        return if (hour == null) label else "$label · ${hour.toInt()} h"
    }

    /** Les sortes de rêve (`contracts/self_.py::DREAM_KINDS`, InnerLifePanel.ts:102-108). */
    val DREAM_TYPES: Map<String, String> = linkedMapOf(
        "associative" to "rêve associatif",
        "nightmare" to "cauchemar léger",
        "pleasant" to "rêve doux",
        "mundane" to "rêve banal",
        "melancholic" to "rêve mélancolique",
    )

    fun dreamType(type: String?): String = DREAM_TYPES[type.orEmpty()] ?: type.orEmpty()

    /** Ses besoins, avec les mots de la console (InnerLifePanel.ts:46-50). */
    val DRIVES: Map<String, String> = linkedMapOf(
        "social" to "Compagnie",
        "expression" to "S'exprimer",
        "curiosity" to "Apprendre",
    )

    fun drive(kind: String): String = DRIVES[kind] ?: kind

    /** La confiance du transport, en mots (`vocab/privacy.py::ChannelTrust`). */
    fun trust(trust: String?): String = when (trust) {
        "authenticated" -> "connexion authentifiée"
        "account" -> "compte privé"
        "public" -> "salon public"
        "internal" -> "interne"
        else -> trust.orEmpty()
    }

    fun closeness(value: String?): String = when (value) {
        "stranger" -> "inconnu·e"
        "acquaintance" -> "connaissance"
        "friend" -> "ami·e"
        "close" -> "proche"
        else -> value.orEmpty()
    }

    fun tone(value: String?): String = when (value) {
        "direct" -> "direct"
        "gentle" -> "doux"
        "playful" -> "joueur"
        "formal" -> "formel"
        "unknown" -> "—"
        else -> value.orEmpty()
    }

    /** Le titre que le serveur donne au journal ; jamais « d'aujourd'hui », il s'écrit la nuit. */
    fun journalTitle(title: String?): String = title?.trim()?.takeIf { it.isNotEmpty() } ?: "Son dernier journal"
}
