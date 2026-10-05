package fr.qwartz.mika.avatar3d

import kotlin.math.asin
import kotlin.math.atan2
import kotlin.math.hypot
import kotlin.random.Random

/** Une demande ponctuelle à la respiration, consommée par elle : une inspiration rapide avant une proposition, ou un soupir. */
enum class BreathRequest { CATCH, SIGH }

/**
 * Ce que les couches du corps lisent et publient à chaque image — l'`OverlayContext` du web, sans le VRM : l'humeur,
 * le sommeil, la parole, la conversation, la lecture, la fatigue, où est le spectateur ; puis ce que les couches
 * laissent pour les suivantes ou pour le visage (le souffle, l'intention de regard, le spectateur mesuré dans la tête,
 * le saut de regard, les sourcils des temps forts de la parole).
 *
 * Les phases de sommeil et les émotions sont les chaînes du serveur (`"awake"`, `"rem"`, `"sad"`…) : le reste de
 * l'app les porte ainsi, et une table indexée par chaîne reste une copie lisible de celle du web.
 */
class BodyContext(
    emotion: String = "neutral",
    intensity: Float = 0.5f,
    sleepPhase: String = AWAKE,
    var speaking: Boolean = false,
    /** Un message a été accepté et rien n'y a encore répondu : elle compose, le regard part en haut et de côté. */
    var replyPending: Boolean = false,
    /**
     * La personne en face écrit en ce moment — à tenir vrai [LISTENING_HOLD_S] après la dernière frappe, comme le web :
     * le regard se pose sur elle et se détourne moins.
     */
    var listening: Boolean = false,
    /**
     * Elle lit le message qu'on vient de lui envoyer — la bulle, sous son visage, entre elle et la personne : le
     * regard s'abaisse et balaie les lignes ([AttentionState.READING]). À tenir vrai le temps de la lecture.
     */
    var reading: Boolean = false,
    /** La voix de la réponse en cours : `"speaking"`, `"inner"` (elle se murmure à elle-même), ou rien. */
    var persona: String? = null,
    /** La fatigue, 0 (fraîche) … 1 (épuisée) : un souffle plus lent, un corps plus immobile. */
    fatigue: Float = 0f,
    /** Elle traverse la pièce : le corps de la marche porte son propre mouvement. */
    var walking: Boolean = false,
    /** Où est le spectateur (la caméra), en repère monde du VRM ; `null` : personne, regard droit devant. */
    var viewer: Vec3? = null,
    /** Une demande ponctuelle à la respiration ; la couche la consomme (la remet à `null`). */
    var breathRequest: BreathRequest? = null,
) {
    var emotion: String = emotion

    var intensity: Float = intensity.coerceIn(0f, 1f)
        set(value) {
            field = value.coerceIn(0f, 1f)
        }

    /** La phase telle que le serveur l'envoie. Une valeur inconnue se lit « éveillée » ([phase]), comme le réducteur d'état. */
    var sleepPhase: String = sleepPhase

    var fatigue: Float = fatigue.coerceIn(0f, 1f)
        set(value) {
            field = value.coerceIn(0f, 1f)
        }

    /** La phase de sommeil, ramenée aux quatre connues. */
    val phase: String get() = if (sleepPhase in SLEEP_PHASES) sleepPhase else AWAKE
    val awake: Boolean get() = phase == AWAKE

    /** L'arousal signé de l'émotion à son intensité, −1 (vidée) … 1 (survoltée) : combien le corps bouge. */
    val arousal: Float get() = (Affect.AROUSAL[emotion] ?: 0f) * intensity

    // ── Publié par les couches, lu par les suivantes (ou par le visage) ─────────

    /** Le remplissage des poumons, 0 (vides) … 1 (pleins) ; un soupir passe au-delà. */
    var breath: Float = 0f
        internal set

    /** L'intention de regard de l'image (null avant la première). */
    var attention: GazeIntent? = null
        internal set

    /**
     * La direction du spectateur dans la tête telle que les couches précédentes l'ont posée (angles sémantiques),
     * mesurée par [HeadAttentionOverlay] : le directeur de l'image suivante y lit s'il est à portée.
     */
    var viewerYaw: Float = 0f
        internal set
    var viewerPitch: Float = 0f
        internal set
    var viewerMeasured: Boolean = false
        internal set

    /** Le saut de regard de l'image (rad), pour les clignements qu'il entraîne. */
    var gazeShift: Float = 0f
        internal set

    /**
     * L'éclair de sourcils du temps fort qui vient de partir, 0…1, décroissant — publié par [SpeechBodyOverlay],
     * pour le visage (`FaceDriver.setSpeechBeat`). Le « j'ai lu » le lève aussi.
     */
    var speechEmphasis: Float = 0f
        internal set

    /** Une question est posée : les sourcils tenus levés, 0…1, qui retombent une fois la tenue passée. */
    var speechQuestion: Float = 0f
        internal set

    companion object {
        const val AWAKE = "awake"
        const val LIGHT_SLEEP = "light_sleep"
        const val REM = "rem"
        const val DEEP_SLEEP = "deep_sleep"
        val SLEEP_PHASES = setOf(AWAKE, LIGHT_SLEEP, REM, DEEP_SLEEP)

        /** Combien de temps après la dernière frappe elle se sait encore écoutée (`AnimationSystem.LISTENING_HOLD_S`). */
        const val LISTENING_HOLD_S = 2.5f
    }
}

/**
 * La géométrie partagée des couches. C'est ici, et seulement ici, que les angles du web deviennent des rotations du
 * [CharacterFrame] — le seul endroit où un signe peut se tromper, donc le seul à vérifier.
 */
object BodyMath {
    /**
     * L'équivalent de `OverlayContext.addRotation(bone, x, y, z)` : un petit delta d'Euler composé SUR l'orientation
     * actuelle de l'os (celle du clip et des couches précédentes), jamais une valeur absolue — un absolu ne peut pas
     * cohabiter avec un clip, c'est ce qui avait tué l'ancienne architecture du web.
     *
     * Sur le web, le delta multiplie à droite la rotation locale d'un os normalisé (repos = identité, axes alignés sur
     * le monde) : son orientation monde devient `actuelle · delta`. Sur une [Pose] en orientations monde, c'est la
     * rotation monde `actuelle · delta · actuelle⁻¹`, appliquée à l'os ET à ce qu'il porte ([AvatarRig.rotate]) : une
     * poitrine qui respire soulève les bras, une tête qui penche emporte les yeux. Composé ainsi, l'ordre dans lequel
     * on touche un parent et son enfant n'importe pas, comme sur le web.
     *
     * Angles du web : `pitch` > 0 baisse le menton, `yaw` > 0 tourne vers SA GAUCHE (l'inverse de
     * [CharacterFrame.yaw] — d'où le signe ci-dessous), `roll` > 0 penche le haut vers sa droite. Composés dans
     * l'ordre XYZ de three.js (tangage · lacet · roulis), comme le web, plutôt que l'ordre YXZ de
     * [CharacterFrame.euler] : l'écart est du second ordre, mais un port exact n'a pas à le justifier.
     */
    fun addRotation(rig: AvatarRig, pose: Pose, bone: String, pitch: Float, yaw: Float, roll: Float) {
        if (pitch == 0f && yaw == 0f && roll == 0f) return
        val current = pose[bone] ?: return
        val delta = CharacterFrame.pitch(pitch) * CharacterFrame.yaw(-yaw) * CharacterFrame.roll(roll)
        rig.rotate(pose, bone, (current * delta * current.inverse()).normalized())
    }

    /**
     * Les angles sémantiques d'une direction exprimée dans le repère d'un os (`directionToGaze` du web, ici pour le
     * seul VRM 0.x qui regarde −Z). Exacts, pas aux petits angles : l'inverse exact de [gazeToQuaternion]. Une
     * direction nulle se lit droit devant plutôt que NaN.
     */
    fun directionToGaze(d: Vec3): GazeAngles {
        val len = d.length()
        if (len < 1e-9f) return GazeAngles.ZERO
        val up = (d.dot(CharacterFrame.UP) / len).coerceIn(-1f, 1f)
        return GazeAngles(
            pitch = -asin(up),
            yaw = atan2(-d.dot(CharacterFrame.RIGHT), d.dot(CharacterFrame.FORWARD)),
        )
    }

    /**
     * La rotation locale qui amène l'avant d'un os vers des angles sémantiques : le lacet d'abord, puis le tangage
     * autour de l'axe latéral déjà tourné (l'Euler YXZ du web).
     */
    fun gazeToQuaternion(g: GazeAngles): Quat = (CharacterFrame.yaw(-g.yaw) * CharacterFrame.pitch(g.pitch)).normalized()

    /**
     * La direction du spectateur dans le repère de la tête telle que [pose] la pose, depuis le milieu des yeux (ou la
     * tête sans yeux) : 7 cm entre l'œil et l'origine de la tête, c'est 4° d'erreur à bout de bras — assez pour que le
     * « contact » tombe sur le front. Résout le squelette pour mesurer (ce n'est pas cher).
     */
    fun viewerInHead(rig: AvatarRig, pose: Pose, viewer: Vec3): Vec3? {
        if (pose["head"] == null) return null
        rig.solve(pose)
        val (headRot, headPos) = rig.world("head") ?: return null
        val left = rig.world("leftEye")?.second
        val right = rig.world("rightEye")?.second
        val origin = when {
            left != null && right != null -> (left + right) * 0.5f
            left != null -> left
            right != null -> right
            else -> headPos
        }
        return headRot.inverse().rotate(viewer - origin)
    }

    internal fun smooth(t: Float): Float {
        val x = t.coerceIn(0f, 1f)
        return x * x * (3 - 2 * x)
    }
}

/**
 * Les couches procédurales du corps, dans l'ordre de l'`AnimationSystem` du web, posées SUR la pose du clip :
 *
 *   1. [AttentionDirector]     où est son attention (pur), décidé avant qu'aucune couche ne touche la tête ;
 *   2. [BreathingOverlay]      le souffle — poitrine, colonne, épaules, la nuque qui compense ;
 *   3. [LifeOverlay]           la vie entre les images enregistrées : micro-mouvements, transferts de poids ;
 *   4. [SleepOverlay]          la tête qui tombe en dormant ;
 *   5. [HeadEmotionOverlay]    le port de tête de l'émotion ;
 *   6. [HeadAttentionOverlay]  la part de la tête dans un regard, mesurée dans la tête telle que 2–5 l'ont posée ;
 *   7. [SpeechBodyOverlay]     les temps forts de la parole — hochements sur les mots appuyés, menton levé sur une
 *                              question, sourcils publiés pour le visage. APRÈS le tour de tête de l'attention : un
 *                              hochement est un geste, pas un changement de ce qu'elle regarde ;
 *   8. [GazeController]        les yeux, absolus, APRÈS toutes les têtes : ils visent le reste (le réflexe
 *                              vestibulo-oculaire — le clip tourne la tête, les yeux contre-tournent, le contact tient
 *                              à travers les hochements).
 *
 * L'app n'a pas de voix : sa réponse s'affiche progressivement dans la bulle, et le curseur des temps forts suit cet
 * affichage ([beginUtterance], [setSpeechCursor] à chaque image, [endUtterance]) — là où le web suit le curseur du
 * lip-sync de sa synthèse vocale.
 *
 * Contrat : [update] AJOUTE à la pose — elle doit être réécrite à chaque image (le clip échantillonné, chaque os
 * écrit), sinon les couches s'accumulent d'une image à l'autre. Les mesures résolvent le squelette ([AvatarRig.solve]) ;
 * la pose finale est à résoudre après [update] pour la poser sur le moteur.
 */
class BodyLayers(
    private val rig: AvatarRig,
    random: () -> Float = { Random.nextFloat() },
    /** Jusqu'où l'os de l'œil peut tourner sur ce modèle (rad) ; voir [GazeController.MIKA_EYE_RANGE]. */
    eyeRange: Float = GazeController.MIKA_EYE_RANGE,
) {
    val director = AttentionDirector(random)
    val breathing = BreathingOverlay(random)
    val life = LifeOverlay(random)
    val sleep = SleepOverlay()
    val headEmotion = HeadEmotionOverlay()
    val headAttention = HeadAttentionOverlay()
    val speechBody = SpeechBodyOverlay(random)
    val gaze = GazeController(eyeRange)

    val attentionState: AttentionState get() = director.currentState

    /**
     * Elle commence une réplique : `text` est le texte de la bulle, tel quel (`*mots*` et jetons `[SIGH]`,
     * `[PAUSE:ms]`… compris — ils sont lus comme le web les lit). Ses temps forts remplacent ceux de la précédente.
     */
    fun beginUtterance(text: String) = speechBody.begin(text)

    /**
     * Où en est l'affichage, à chaque image : l'indice du caractère atteint dans le texte de [beginUtterance]. Un
     * temps fort part quand le curseur l'atteint ; un bond (tout affiché d'un coup) ne fait partir aucun de ceux qu'il
     * franchit ; un retour en arrière les réarme.
     */
    fun setSpeechCursor(charIndex: Int) {
        speechBody.cursor = charIndex
    }

    /** La réplique est entièrement dite (ou abandonnée) : plus aucun temps fort ne part, la tête se pose. */
    fun endUtterance() = speechBody.end()

    /** Le petit hochement « j'ai lu » — après la lecture d'un message, avant d'y répondre. Rien en dormant. */
    fun acknowledge() = speechBody.acknowledge()

    /**
     * Une image : pose les couches sur `pose` (déjà écrite par le clip) et rend le saut de regard de l'image (rad),
     * pour les clignements qu'un grand changement de regard entraîne.
     */
    fun update(dt: Float, pose: Pose, ctx: BodyContext): Float {
        // Comme le web : un retour d'onglet ne fait pas exploser les ressorts.
        val step = dt.coerceIn(0f, MAX_DT)
        // La portée lue ici a été mesurée à l'image précédente : une image de retard sur « le spectateur est-il
        // derrière moi », ce n'est rien.
        val input = AttentionInput(
            speaking = ctx.speaking,
            replyPending = ctx.replyPending,
            listening = ctx.listening,
            reading = ctx.reading,
            persona = ctx.persona,
            emotion = ctx.emotion,
            intensity = ctx.intensity,
            sleepPhase = ctx.phase,
            reachable = ctx.viewer != null && ctx.viewerMeasured &&
                HeadAttentionOverlay.viewerReachable(ctx.viewerYaw, ctx.viewerPitch),
            viewerAngle = if (ctx.viewerMeasured) hypot(ctx.viewerYaw, ctx.viewerPitch) else 0f,
            walking = ctx.walking,
        )
        val intent = director.update(step, input)
        ctx.attention = intent

        breathing.update(step, ctx, rig, pose)
        life.update(step, ctx, rig, pose)
        sleep.update(step, ctx, rig, pose)
        headEmotion.update(step, ctx, rig, pose)
        headAttention.update(step, ctx, rig, pose)
        // Les temps forts après le tour de tête : les yeux, qui passent ensuite, tiennent le contact à travers eux.
        speechBody.update(step, ctx, rig, pose)
        gaze.update(step, ctx, rig, pose, intent)
        ctx.gazeShift = intent.shift
        return intent.shift
    }

    companion object {
        const val MAX_DT = 0.1f
    }
}
