package fr.qwartz.mika.avatar3d

import fr.qwartz.mika.avatar3d.FrenchVisemes.Frame
import fr.qwartz.mika.avatar3d.FrenchVisemes.Viseme
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min

/**
 * La bouche articule le français qu'elle dit — port du cœur de `frontend/Web/src/audio/LipSyncController.ts` (et de
 * `cadence.ts`, du découpage des jetons de prosodie de `TTSService.lipSyncPlan`, de `affect.articulationFor`).
 *
 * Le texte devient des trames de visèmes ([FrenchVisemes]) ; ce fichier fait le rendu : coarticulation, poursuite
 * asymétrique, plafond d'ouverture face à la bouche des autres expressions, sortie vers les morphoses.
 *
 * Ce qui change par rapport au web, c'est la source de vérité du temps. Le web suit une VOIX : la synthèse annonce de
 * loin en loin le mot qu'elle prononce et `seekToChar` y saute. L'app n'a pas de voix : sa réponse s'affiche dans la
 * bulle, et un curseur exact (le caractère qui apparaît) arrive à CHAQUE image. Y sauter à chaque fois remettrait
 * sans cesse la trame à zéro — plus d'anticipation, une bouche qui hoquette sur chaque lettre. D'où
 * [trackChar] : le plan joue à son rythme tant qu'il reste près du texte (une marge morte de quelques caractères,
 * celle de l'écart naturel entre un affichage régulier et des phonèmes qui n'ont pas tous la même durée), accélère ou
 * ralentit en douceur quand il s'en écarte, et ne saute que sur un vrai saut du curseur.
 *
 * Pur : ni Android ni Filament, testé sur la JVM.
 */
class LipSync(rawMorphs: Set<String>? = null) {

    /** Un morceau de la réponse : du texte prononcé (à sa position dans la réponse), ou un temps sans parole. */
    sealed interface PlanSegment {
        data class Speech(val text: String, val start: Int = -1) : PlanSegment
        data class Silence(val ms: Double) : PlanSegment
    }

    private class Route(val viseme: Int, val out: Int, val factor: Float)

    // --- Sortie ---

    private val routes: Array<Route>
    /** Ce que la bouche écrit : les morphoses `vrc.v_*` du modèle, ou les noms des préréglages de repli (`aa`…). */
    val outputNames: List<String>
    private val outputValues: FloatArray
    private val rawVisemes: Int
    private val presetRoutes: Int

    init {
        val names = ArrayList<String>()
        fun indexOf(name: String): Int {
            val i = names.indexOf(name)
            if (i >= 0) return i
            names.add(name)
            return names.size - 1
        }
        val list = ArrayList<Route>()
        var raw = 0
        var presets = 0
        for (viseme in DRIVEN_VISEMES) {
            val v = viseme.ordinal
            if (rawMorphs == null || viseme.morph in rawMorphs) {
                list += Route(v, indexOf(viseme.morph), 1f)
                raw++
                continue
            }
            for ((preset, factor) in PRESET_FALLBACK.getValue(viseme)) {
                list += Route(v, indexOf(preset), factor)
                presets++
            }
        }
        routes = list.toTypedArray()
        outputNames = names
        outputValues = FloatArray(names.size)
        rawVisemes = raw
        presetRoutes = presets
    }

    /**
     * « visemes » : la bouche n'écrit que les morphoses VRChat ; « presets » : seulement les cinq voyelles VRM ;
     * « mixed » : un jeu VRChat incomplet, complété par les préréglages. Un `vrc.v_pp` absent ne fait pas un jeu
     * incomplet : la fermeture n'a pas de préréglage (voir [PRESET_FALLBACK]), rien n'est écrit à sa place.
     */
    val outputMode: String
        get() = when {
            rawVisemes == 0 -> "presets"
            presetRoutes == 0 -> "visemes"
            else -> "mixed"
        }

    // --- Plan ---

    private var frames: List<Frame> = emptyList()
    /** Instant de début de chaque trame dans le plan (ms). */
    private var starts = DoubleArray(0)
    private var total = 0.0
    /** Les trames qui portent un caractère (offset ≥ 0), et leurs offsets — croissants, pour la recherche. */
    private var voiced = IntArray(0)
    private var voicedOffsets = IntArray(0)
    /** Le caractère qui suit le dernier texte prononcé : un curseur au-delà a tout affiché. */
    private var spokenEnd = 0
    /** Fin de la dernière trame portant un caractère (ce qui suit n'est que silence de prosodie). */
    private var speechEnd = 0.0
    private var msPerChar = DEFAULT_MS_PER_CHAR

    /** Où en est le plan (ms) ; avance en temps réel, multiplié par [warp]. */
    private var playhead = 0.0
    private var index = 0
    private var speaking = false
    /** Cadence de la prochaine avance, posée par [trackChar] et consommée par [update]. */
    private var warp = 1.0
    /** La bouche attend un texte qui cale : le plan ne bouge plus, la bouche se détend. */
    private var held = false
    /** Le dernier curseur suivi : un curseur qui recule n'est pas un texte qui cale. */
    private var lastTracked = Int.MIN_VALUE
    /** Ruptures imposées par [trackChar] — sauts, attentes, silences de fin (diagnostic et tests : une lecture suivie
     * n'en fait aucune). */
    internal var resyncs = 0
        private set

    // --- Rendu ---

    /** Niveau lissé de chaque visème (ce que la bouche montre). */
    private val level = FloatArray(VISEME_COUNT)
    private val target = FloatArray(VISEME_COUNT)
    private val shapeA = FloatArray(VISEME_COUNT)
    private val shapeB = FloatArray(VISEME_COUNT)
    private var articulation = 1f

    /**
     * Amplitude des mouvements de bouche (0,4–1,2 ; 1 = normal). Une voix lasse ou triste articule moins : ~0,6–0,8.
     * Les fermetures n'en subissent qu'une part, pour que les « p » restent des « p ».
     */
    fun setArticulation(scale: Float) {
        articulation = if (scale.isFinite()) scale.coerceIn(ARTICULATION_MIN, ARTICULATION_MAX) else 1f
    }

    /** Ancien chemin, sans position : un texte et une durée totale ; les trames portent −1 et refusent un recalage. */
    fun startTextDriven(text: String, durationMs: Double) {
        val ms = durationMs / max(1, FrenchVisemes.spokenLength(text))
        begin(FrenchVisemes.frames(text, ms, -1), ms, 0)
    }

    /**
     * Joue un plan : chaque silence réservé par un jeton de prosodie devient une trame bouche fermée de sa durée
     * exacte, et seuls les caractères prononcés reçoivent du temps de parole.
     */
    fun startFromPlan(plan: List<PlanSegment>, msPerChar: Double = DEFAULT_MS_PER_CHAR) {
        val ms = if (msPerChar.isFinite() && msPerChar > 0) msPerChar else DEFAULT_MS_PER_CHAR
        val out = ArrayList<Frame>()
        var end = 0
        for (segment in plan) {
            when (segment) {
                is PlanSegment.Silence -> out += Frame(Viseme.SIL, 0.0, segment.ms, -1)
                is PlanSegment.Speech -> {
                    out += FrenchVisemes.frames(segment.text, ms, segment.start)
                    if (segment.start >= 0) end = max(end, segment.start + segment.text.length)
                }
            }
        }
        begin(out, ms, end)
    }

    private fun begin(plan: List<Frame>, ms: Double, end: Int) {
        frames = plan
        msPerChar = ms
        starts = DoubleArray(plan.size)
        var t = 0.0
        for (k in plan.indices) {
            starts[k] = t
            t += plan[k].duration
        }
        total = t
        voiced = plan.indices.filter { plan[it].charOffset >= 0 }.toIntArray()
        voicedOffsets = IntArray(voiced.size) { plan[voiced[it]].charOffset }
        spokenEnd = end
        speechEnd = voiced.lastOrNull()?.let { starts[it] + plan[it].duration } ?: 0.0
        playhead = 0.0
        index = 0
        warp = 1.0
        held = false
        lastTracked = Int.MIN_VALUE
        // Un plan vide n'a rien à dire : il ne « parle » pas (le web restait en parole pour toujours).
        speaking = plan.isNotEmpty()
    }

    /**
     * Recalage franc, celui du web (`seekToChar`) : sur la première trame qui porte ce caractère ou un suivant ;
     * au-delà du dernier caractère voisé, sur la dernière trame voisée. Avant ou arrière, et ranime un plan fini.
     * Rend false si le plan n'a aucune trame positionnée.
     */
    fun seekToChar(charIndex: Int): Boolean {
        if (frames.isEmpty() || voiced.isEmpty()) return false
        val p = upperBound(charIndex - 1) // première trame voisée d'offset ≥ charIndex
        moveTo(voiced[if (p < voiced.size) p else voiced.size - 1])
        return true
    }

    /**
     * Suivi image par image d'un curseur exact : `charIndex` est le caractère du texte d'origine en train d'apparaître
     * (le nombre de caractères déjà affichés). Le plan n'est touché que s'il s'éloigne du texte :
     *  - dans la marge ([SYNC_SLACK_CHARS] caractères autour du caractère courant), rien — la lecture reste exactement
     *    celle du plan, coarticulation comprise ;
     *  - un peu au-delà, le plan accélère (jusqu'à ×[WARP_MAX]) ou ralentit (jusqu'à ×[WARP_MIN]) : la bouche
     *    rattrape le texte sans saut ;
     *  - un curseur qui saute en avant de plus de [SNAP_CHARS] : saut franc au début du caractère ;
     *  - un curseur qui revient en arrière au-delà de [SNAP_CHARS] : saut arrière, et un plan fini se ranime ;
     *  - un texte qui cale (le plan le devance de plus de [HOLD_CHARS]) : la bouche l'attend, fermée, et reprend où
     *    elle en était quand il la rejoint — sauter en arrière la ferait bégayer la même syllabe en boucle ;
     *  - le texte entier affiché d'un coup alors que la bouche en est loin ([END_SNAP_CHARS]) : elle se tait et se
     *    referme en douceur plutôt que de sauter sur la dernière syllabe.
     * Rend false si le plan n'a aucune trame positionnée (rien à suivre).
     */
    fun trackChar(charIndex: Int): Boolean {
        if (frames.isEmpty() || voiced.isEmpty()) return false
        val backward = charIndex < lastTracked
        lastTracked = charIndex
        val atEnd = charIndex >= spokenEnd
        var first = 0
        val lo: Double
        val hi: Double
        if (atEnd) {
            lo = speechEnd
            hi = total
        } else {
            // Le caractère est « dit » par la dernière trame ancrée sur lui ou avant lui (une lettre muette, le « a »
            // de « eau », un jeton de prosodie appartiennent à ce qui les précède) ; son domaine court jusqu'à la
            // première trame ancrée après lui.
            val next = upperBound(charIndex)
            val anchor = next - 1
            first = if (anchor < 0) 0 else voiced[lowerBound(voicedOffsets[anchor])]
            lo = starts[first]
            hi = if (next < voiced.size) starts[voiced[next]] else total
        }
        val slack = SYNC_SLACK_CHARS * msPerChar
        val at = min(playhead, total)
        val drift = when {
            at < lo - slack -> lo - slack - at // le plan est en retard sur le texte
            at > hi + slack -> hi + slack - at // il est en avance
            else -> 0.0
        }
        // Le texte a rejoint une bouche qui l'attendait : elle reprend là où elle s'était arrêtée.
        if (drift >= 0.0) held = false
        if (drift == 0.0) return true
        if (atEnd && drift > END_SNAP_CHARS * msPerChar) {
            speaking = false
            held = false
            playhead = total
            index = frames.size
            resyncs++
            return true
        }
        if (drift > SNAP_CHARS * msPerChar || (backward && -drift > SNAP_CHARS * msPerChar)) {
            moveTo(first)
            resyncs++
            return true
        }
        if (speaking && !held && -drift > HOLD_CHARS * msPerChar) {
            held = true
            resyncs++
            return true
        }
        // Un plan fini un peu tôt n'a plus rien à ralentir : la dernière syllabe est dite.
        if (speaking && !held) warp = (1.0 + drift / (WARP_CHARS * msPerChar)).coerceIn(WARP_MIN, WARP_MAX)
        return true
    }

    /** Caractère de la trame courante (−1 hors plan ou dans un silence) — tests et diagnostic. */
    val currentCharOffset: Int get() = frames.getOrNull(index)?.charOffset ?: -1

    /** Visème de la trame courante (`SIL` hors plan) — tests et diagnostic. */
    val currentViseme: Viseme get() = frames.getOrNull(index)?.viseme ?: Viseme.SIL

    /** La bouche se tait : le plan est oublié, et elle revient au repos à la vitesse du relâchement. */
    fun stop() {
        speaking = false
        frames = emptyList()
        starts = DoubleArray(0)
        voiced = IntArray(0)
        voicedOffsets = IntArray(0)
        total = 0.0
        playhead = 0.0
        index = 0
        warp = 1.0
        held = false
    }

    val isSpeaking: Boolean get() = speaking

    /** Niveau lissé d'un visème, même sans morphose pour l'écrire (la fermeture `PP` de Mika) — tests et diagnostic. */
    internal fun levelOf(viseme: Viseme): Float = level[viseme.ordinal]

    /** Avance de `dt` secondes : le plan, puis la bouche vers sa forme. */
    fun update(dt: Float) {
        val step = if (dt.isFinite() && dt > 0f) dt.toDouble() else 0.0
        target.fill(0f)
        if (speaking && !held && frames.isNotEmpty()) {
            playhead += step * 1000.0 * warp
            while (index < frames.size && playhead >= starts[index] + frames[index].duration) index++
            if (index < frames.size) coarticulatedTarget(target) else speaking = false
        }
        warp = 1.0
        follow(target, step)
    }

    /**
     * Les poids à écrire, sous le plafond d'ouverture. `mouthLoad` (0…1) est ce que les autres expressions font déjà à
     * la bouche cette image ([mouthInvolvement], combinées en « ou » probabiliste) : un « a » plein sur une bouche déjà
     * ouverte par la surprise déforme le visage, la parole n'a alors droit qu'à ce qui reste — jamais moins que
     * [MIN_VISEME_ALLOWANCE] (on parle encore en riant).
     */
    inline fun forEachOutput(mouthLoad: Float, action: (name: String, weight: Float) -> Unit) {
        val values = render(mouthLoad)
        for (o in outputNames.indices) action(outputNames[o], values[o])
    }

    @PublishedApi
    internal fun render(mouthLoad: Float): FloatArray {
        val load = if (mouthLoad.isFinite()) mouthLoad.coerceIn(0f, 1f) else 0f
        var sum = 0f
        for (c in 0 until VISEME_COUNT) if (c != SIL) sum += level[c]
        val allowance = max(MIN_VISEME_ALLOWANCE, min(MAX_VISEME_SUM, MAX_MOUTH_TOTAL - load))
        val scale = if (sum > allowance) allowance / sum else 1f
        outputValues.fill(0f)
        for (route in routes) outputValues[route.out] += level[route.viseme] * route.factor * scale
        for (o in outputValues.indices) outputValues[o] = min(1f, outputValues[o])
        return outputValues
    }

    // --- Plan : positions ---

    /** Le plan repart du début de la trame `frame` (la trame est remise à zéro : c'est un saut, pas une lecture). */
    private fun moveTo(frame: Int) {
        index = frame
        playhead = starts[frame]
        speaking = true
        held = false
        warp = 1.0
    }

    /** Première position de [voicedOffsets] dont l'offset dépasse `offset`. */
    private fun upperBound(offset: Int): Int {
        var lo = 0
        var hi = voicedOffsets.size
        while (lo < hi) {
            val mid = (lo + hi) ushr 1
            if (voicedOffsets[mid] <= offset) lo = mid + 1 else hi = mid
        }
        return lo
    }

    /** Première position de [voicedOffsets] dont l'offset vaut au moins `offset`. */
    private fun lowerBound(offset: Int): Int {
        var lo = 0
        var hi = voicedOffsets.size
        while (lo < hi) {
            val mid = (lo + hi) ushr 1
            if (voicedOffsets[mid] < offset) lo = mid + 1 else hi = mid
        }
        return lo
    }

    // --- Rendu ---

    /**
     * Forme visée maintenant : celle de la trame courante, fondue dans la dernière part de la trame ([ANTICIPATION],
     * bornée en ms) vers celle de la suivante. Le fondu atteint la suivante pile à la frontière : la cible est
     * continue, et le lissage n'a plus qu'à suivre.
     */
    private fun coarticulatedTarget(out: FloatArray) {
        val frame = frames[index]
        val timer = playhead - starts[index]
        val progress = if (frame.duration > 0) min(1.0, timer / frame.duration) else 1.0

        shapeAt(index, progress, shapeA)
        var blend = 0.0
        if (index + 1 < frames.size) {
            val window = min(ANTICIPATION * frame.duration, ANTICIPATION_MAX_MS)
            val remaining = frame.duration - timer
            if (window > 0 && remaining < window) blend = smoothstep(1 - remaining / window)
        }
        if (blend > 0) {
            shapeAt(index + 1, 0.0, shapeB)
            for (c in 0 until VISEME_COUNT) out[c] = (shapeA[c] * (1 - blend) + shapeB[c] * blend).toFloat()
        } else {
            shapeA.copyInto(out)
        }
    }

    /** Forme d'une trame à un instant donné. Un blanc entre deux mots glisse de la forme précédente à la suivante sans
     * refermer la bouche ; une pause (`sil`) la referme. */
    private fun shapeAt(at: Int, progress: Double, out: FloatArray) {
        out.fill(0f)
        val frame = frames.getOrNull(at) ?: return
        if (!frame.gap) {
            frameShape(frame, out, 1.0)
            return
        }
        var before = at - 1
        while (before >= 0 && frames[before].gap) before--
        var after = at + 1
        while (after < frames.size && frames[after].gap) after++
        val t = smoothstep(progress)
        frameShape(frames.getOrNull(before), out, (1 - t) * GAP_OPENNESS)
        frameShape(frames.getOrNull(after), out, t * GAP_OPENNESS)
    }

    /**
     * Poursuite asymétrique : attaque rapide des fermetures, plus lente des voyelles ; une forme qui sort s'efface au
     * rythme de celle qui entre (vite si c'est une fermeture), et lentement seulement quand la bouche retourne au
     * repos.
     */
    private fun follow(target: FloatArray, dt: Double) {
        val art = articulation.toDouble()
        val closureArt = 1 - (1 - art) * CLOSURE_ARTICULATION_SHARE

        var dominant = SIL
        var wanted = 0.0
        for (c in 0 until VISEME_COUNT) {
            wanted += target[c]
            if (target[c] > target[dominant]) dominant = c
        }
        val closing = IS_CLOSURE[dominant] && target[dominant] > CLOSURE_DOMINANCE
        val handover = wanted > TRANSITION_MIN

        for (c in 0 until VISEME_COUNT) {
            if (c == SIL) continue
            val goal = target[c] * if (IS_CLOSURE[c]) closureArt else art
            val current = level[c].toDouble()
            val rate = when {
                goal > current -> ATTACK_RATES[c]
                closing && c != dominant -> YIELD
                handover -> CROSSFADE
                else -> RELEASE
            }
            val next = current + (goal - current) * (1 - exp(-rate * dt))
            // Une approche exponentielle n'atteint jamais zéro : une bouche revenue au repos garderait sinon treize
            // poids infimes pour toujours, que la sortie (qui omet les zéros) traînerait image après image.
            level[c] = if (goal == 0.0 && next < REST_EPSILON) 0f else next.toFloat()
        }
    }

    companion object {
        // --- Cadence (cadence.ts) ---

        /** Cadence par défaut, en ms par caractère prononcé. */
        const val DEFAULT_MS_PER_CHAR = 60.0

        /** La cadence suit le débit (multiplicateur d'émotion × persona sur le web), borné comme lui. */
        fun msPerCharForRate(rate: Double): Double {
            val r = if (rate.isFinite() && rate > 0) rate.coerceIn(0.5, 2.0) else 1.0
            return DEFAULT_MS_PER_CHAR / r
        }

        // --- Articulation (affect.ts) ---

        const val ARTICULATION_MIN = 0.4f
        const val ARTICULATION_MAX = 1.2f
        /** Part de la réduction d'articulation subie par les fermetures : une voix lasse ouvre moins la bouche, mais
         * ses « p » ferment toujours les lèvres. */
        private const val CLOSURE_ARTICULATION_SHARE = 0.3

        /**
         * Amplitude de la bouche selon ce qu'elle ressent (`affect.articulationFor`) : une voix excitée articule
         * grand, une voix triste, ennuyée ou fatiguée entrouvre à peine les lèvres. Arousal × intensité, moins la
         * fatigue.
         */
        fun articulationFor(emotion: String, intensity: Float, fatigue: Float = 0f): Float {
            val a = (Affect.AROUSAL[emotion] ?: 0f) * (if (intensity.isNaN()) 0f else intensity.coerceIn(0f, 1f))
            val f = if (fatigue.isNaN()) 0f else fatigue.coerceIn(0f, 1f)
            return (1f + 0.35f * a - 0.25f * f).coerceIn(0.6f, 1.15f)
        }

        // --- Prosodie (TTSService.lipSyncPlan) ---

        private val PROSODY_TOKEN = Regex("""\[(PAUSE(?::(\d+))?|SIGH|LAUGH|BREATH)]""", RegexOption.IGNORE_CASE)
        /** Durée des effets non verbaux, celle que le web leur réserve (`SFX_DURATION_MS`). */
        const val SIGH_MS = 600.0
        const val LAUGH_MS = 900.0
        const val BREATH_MS = 350.0
        const val DEFAULT_PAUSE_MS = 500.0

        /**
         * Le découpage d'une réponse : ce qui se prononce (à sa position dans la réponse, blancs de bord retirés), et
         * le temps réservé sans un mot. `[PAUSE:400]` est un silence de 400 ms (50…3000, 500 sans valeur), `[SIGH]`,
         * `[LAUGH]` et `[BREATH]` celui de leur effet. Sans lui, la bouche articulerait les caractères de
         * « [PAUSE:400] ».
         */
        fun speechPlan(text: String): List<PlanSegment> {
            val out = ArrayList<PlanSegment>()
            fun pushSpeech(from: Int, to: Int) {
                val raw = text.substring(from, to)
                val lead = raw.length - raw.trimStart().length
                val chunk = raw.trim()
                if (chunk.isNotEmpty()) out += PlanSegment.Speech(chunk, from + lead)
            }
            var cursor = 0
            for (match in PROSODY_TOKEN.findAll(text)) {
                if (match.range.first > cursor) pushSpeech(cursor, match.range.first)
                val kind = match.groupValues[1].uppercase()
                val ms = when {
                    kind.startsWith("PAUSE") -> {
                        val digits = match.groupValues[2]
                        if (digits.isEmpty()) DEFAULT_PAUSE_MS
                        else (digits.toLongOrNull() ?: Long.MAX_VALUE).coerceIn(50L, 3000L).toDouble()
                    }
                    kind == "SIGH" -> SIGH_MS
                    kind == "LAUGH" -> LAUGH_MS
                    else -> BREATH_MS
                }
                out += PlanSegment.Silence(ms)
                cursor = match.range.last + 1
            }
            if (cursor < text.length) pushSpeech(cursor, text.length)
            return out
        }

        // --- Visèmes et sortie ---

        private val VISEMES = Viseme.entries
        private val VISEME_COUNT = VISEMES.size
        private val SIL = Viseme.SIL.ordinal

        /** Visèmes effectivement pilotés : `sil` est l'absence de tous les autres. */
        val DRIVEN_VISEMES: List<Viseme> = VISEMES.filter { it != Viseme.SIL }
        val VRC_VISEME_MORPHS: List<String> = DRIVEN_VISEMES.map { it.morph }

        /** Les cinq préréglages de bouche VRM (noms VRM 1.0 / three-vrm ; un VRM 0.x les nomme a, i, u, e, o). */
        val MOUTH_PRESETS: List<String> = listOf("aa", "ih", "ou", "ee", "oh")

        /**
         * Repli sur les préréglages VRM. Une fermeture (`PP`) n'a pas de préréglage : c'est la bouche au repos, que
         * l'attaque rapide de la fermeture rend lisible entre deux voyelles. C'est aussi ce que fait le modèle de
         * Mika : son `vrc.v_pp` d'origine ne déplace aucun sommet (vrm_mobile.py l'a donc écarté), la fermeture y est
         * déjà « les autres visèmes qui s'effacent vite ». Les voyelles plafonnent sous 1 : un préréglage est une
         * forme pleine, et les modèles génériques l'ont souvent généreuse.
         */
        val PRESET_FALLBACK: Map<Viseme, Map<String, Float>> = mapOf(
            Viseme.SIL to emptyMap(),
            Viseme.PP to emptyMap(),
            Viseme.FF to mapOf("ih" to 0.25f),
            Viseme.TH to mapOf("ee" to 0.2f, "aa" to 0.1f),
            Viseme.DD to mapOf("ih" to 0.3f, "aa" to 0.12f),
            Viseme.KK to mapOf("aa" to 0.3f, "ih" to 0.15f),
            Viseme.CH to mapOf("ou" to 0.45f, "ih" to 0.15f),
            Viseme.SS to mapOf("ih" to 0.35f, "ee" to 0.25f),
            Viseme.NN to mapOf("ih" to 0.25f, "aa" to 0.1f),
            Viseme.RR to mapOf("ou" to 0.25f, "aa" to 0.15f),
            Viseme.AA to mapOf("aa" to 0.8f),
            Viseme.E to mapOf("ee" to 0.6f, "aa" to 0.15f),
            Viseme.IH to mapOf("ih" to 0.7f),
            Viseme.OH to mapOf("oh" to 0.75f),
            Viseme.OU to mapOf("ou" to 0.75f),
        )

        // --- Coarticulation ---
        // On ne passe pas d'une forme à l'autre au changement de trame : la bouche prépare la suivante avant de quitter
        // la courante, et les muscles ont des vitesses différentes selon le geste.

        /** Dernière fraction d'une trame qui glisse déjà vers la suivante… */
        private const val ANTICIPATION = 0.3
        /** …bornée en temps : une pause de 600 ms ne prépare pas le mot suivant pendant 180 ms. */
        private const val ANTICIPATION_MAX_MS = 70.0
        /** Ouverture conservée à travers un blanc entre deux mots. */
        private const val GAP_OPENNESS = 0.7
        /** Vitesses de poursuite (1/s, lissage exponentiel indépendant de la cadence d'image). Attaque : τ ≈ 21 ms
         * pour une fermeture, 33 ms pour une autre consonne, 42 ms pour une voyelle. */
        private const val ATTACK_CLOSURE = 48.0
        private const val ATTACK_CONSONANT = 30.0
        private const val ATTACK_VOWEL = 24.0
        /** Sous ce niveau, une forme qui s'éteint est éteinte. */
        private const val REST_EPSILON = 1e-4
        /** Retour au repos (fin de phrase, pause) : plus lent que toute attaque, τ ≈ 83 ms — la bouche se détend, elle
         * ne claque pas. */
        private const val RELEASE = 12.0
        /** Passage d'une forme à une autre : la sortante s'efface à peu près au rythme où l'entrante arrive
         * (τ ≈ 38 ms). Relâcher au rythme du repos ici laissait les lèvres à moitié closes pendant toute la voyelle
         * qui suit un « p ». */
        private const val CROSSFADE = 26.0
        /** …et plus vite encore quand c'est une fermeture qui arrive (τ ≈ 25 ms) : sans lui, le « a » qui s'éteint
         * garde la bouche ouverte sous le « p », et l'occlusive ne se lit pas. */
        private const val YIELD = 40.0
        /** Cible totale au-dessus de laquelle une forme sortante est un passage de relais et non un retour au repos. */
        private const val TRANSITION_MIN = 0.15
        /** Poids de forme au-dessus duquel une fermeture « tient » la cible. */
        private const val CLOSURE_DOMINANCE = 0.3f
        /** Les gestes qui doivent se voir nets : lèvres closes, lèvre sous les dents, dents serrées. */
        private val CLOSURES = setOf(Viseme.PP, Viseme.FF, Viseme.SS)
        private val VOWEL_VISEMES = setOf(Viseme.AA, Viseme.E, Viseme.IH, Viseme.OH, Viseme.OU)
        private val ATTACK_RATES = DoubleArray(VISEME_COUNT) {
            when (VISEMES[it]) {
                in CLOSURES -> ATTACK_CLOSURE
                in VOWEL_VISEMES -> ATTACK_VOWEL
                else -> ATTACK_CONSONANT
            }
        }
        private val IS_CLOSURE = BooleanArray(VISEME_COUNT) { VISEMES[it] in CLOSURES }

        // --- Suivi du texte (propre à l'app) ---

        /** Marge morte autour du caractère affiché, en caractères : l'écart naturel entre un affichage régulier et des
         * phonèmes de durées inégales (une voyelle tient, une lettre muette ne dure rien) reste de quelques
         * caractères, et la lecture ne doit pas en être touchée. */
        const val SYNC_SLACK_CHARS = 2.0
        /** Écart (au-delà de la marge) qui double ou divise par deux la cadence du plan. */
        const val WARP_CHARS = 4.0
        const val WARP_MIN = 0.5
        const val WARP_MAX = 2.0
        /** Au-delà, le curseur a vraiment sauté : la bouche aussi. */
        const val SNAP_CHARS = 16.0
        /** Une bouche qui devance le texte de plus que ceci l'attend (fermée) au lieu de continuer seule. */
        const val HOLD_CHARS = 8.0
        /** Le texte entier affiché d'un coup : au-delà de cet écart, la bouche se tait au lieu de rattraper. */
        const val END_SNAP_CHARS = 8.0

        // --- Plafond d'ouverture ---
        // D'autres couches écrivent sur la même bouche (sourire de l'émotion, micro-mouvements) et les morphoses
        // s'additionnent sur les sommets.

        /** Somme maximale des visèmes entre eux (deux formes en fondu = une bouche). */
        const val MAX_VISEME_SUM = 1.0f
        /** Somme maximale visèmes + charge buccale des autres expressions. */
        const val MAX_MOUTH_TOTAL = 1.3f
        /** Ce que la parole garde au minimum, même sur un visage hilare. */
        const val MIN_VISEME_ALLOWANCE = 0.45f
        /** Morphoses de bouche reconnues par leur nom (VRChat, ARKit, préréglages japonais). */
        private val MOUTH_MORPH =
            Regex("mouth|jaw|lip|tongue|teeth|tooth|^vrc\\.v_|^mth|^[あいうえおん]$", RegexOption.IGNORE_CASE)
        /** Celles qui ouvrent la bouche comptent plein ; un sourire, une moue, à 40 %. */
        private val OPENING_MORPH = Regex("open|jawopen|lowerdown|^あ$|^お$", RegexOption.IGNORE_CASE)
        private const val SHAPE_MORPH_FACTOR = 0.4f

        /** Ce qu'une expression fait à la bouche quand elle est pleine : le plus fort de ses liens de bouche, une
         * ouverture comptant plein, une forme (sourire, moue) à [SHAPE_MORPH_FACTOR]. 0 pour un groupe hors bouche. */
        fun mouthInvolvement(binds: List<VrmDocument.Bind>): Float {
            var involvement = 0f
            for (b in binds) {
                if (!MOUTH_MORPH.containsMatchIn(b.name)) continue
                val factor = if (OPENING_MORPH.containsMatchIn(b.name)) 1f else SHAPE_MORPH_FACTOR
                involvement = max(involvement, b.weight * factor)
            }
            return if (involvement > 0.01f) involvement else 0f
        }

        private fun smoothstep(x: Double): Double {
            val t = x.coerceIn(0.0, 1.0)
            return t * t * (3 - 2 * t)
        }

        private fun frameShape(frame: Frame?, out: FloatArray, scale: Double) {
            if (frame == null || frame.gap || frame.viseme == Viseme.SIL) return
            out[frame.viseme.ordinal] += (frame.weight * scale).toFloat()
        }
    }
}
