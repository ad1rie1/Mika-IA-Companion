using System;
using System.Collections.Generic;
using System.Linq;
using UniVRM10;
using UnityEngine;

namespace Mika.Avatar
{
    /// <summary>
    /// Le visage de Mika : émotions, physiologie (rougeur, larmes, pupilles), clignements, micro-mouvements,
    /// synchronisation labiale, sommeil, énergie et regard des yeux. Se pose sur la racine de l'avatar, à côté
    /// du <see cref="Vrm10Instance"/>. Équivalent Unity de la couche visage du client web
    /// (<c>frontend/src/vtuber/</c>, <c>frontend/src/audio/</c>) ; voir le README du dossier.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Tout passe par l'API d'expressions d'UniVRM 1.0 : à chaque <c>LateUpdate</c>, les couches calculent un
    /// poids par expression, le composant les écrit (<c>Vrm10RuntimeExpression.SetWeight</c>), et
    /// <see cref="Vrm10Instance"/> — ordre d'exécution 11000, après celui-ci (10500) — les applique aux
    /// maillages dans son propre <c>LateUpdate</c>. Les yeux passent par son LookAt
    /// (<c>Vrm10RuntimeLookAt.SetYawPitchManually</c>) ; la tête, elle, appartient à l'IK de Mecanim.
    /// </para>
    /// <para>
    /// Le composant possède le visage : toute expression qu'il a écrite et qu'aucune couche ne demande plus est
    /// remise à zéro. Une autre source qui voudrait écrire une expression du visage doit passer par lui.
    /// </para>
    /// </remarks>
    [DisallowMultipleComponent]
    [DefaultExecutionOrder(10500)]
    [AddComponentMenu("Mika/Mika Face")]
    public sealed class MikaFace : MonoBehaviour
    {
        /// <summary>Soupape : une réplique dont la fin n'arrive jamais ne doit pas retenir la dérive d'humeur
        /// indéfiniment (<c>SpeechPresenter.ts::VOICED_HOLD_MAX_MS</c>).</summary>
        public const float VoicedHoldMaxSeconds = 60f;

        /// <summary>Après la dernière frappe de l'interlocuteur, elle « écoute » encore ce temps.</summary>
        public const float ListeningHoldSeconds = 2.5f;

        /// <summary>Au-delà de ces angles (rad), un tour de tête n'atteindrait pas l'interlocuteur : regard devant.</summary>
        public const float HeadReachYaw = 1.35f;
        public const float HeadReachPitch = 1f;

        [SerializeField, Tooltip("L'instance VRM 1.0 du modèle (cherchée sur cet objet ou ses enfants si vide).")]
        Vrm10Instance vrm;

        [SerializeField, Tooltip("Une vraie voix pilote la bouche : la fin de l'estimation ne termine pas la parole, " +
                                 "seuls StopSpeaking (ou une position de lecture) le font.")]
        bool externalVoice;

        [SerializeField, Tooltip("Tant qu'aucun LookAt n'a été donné, regarder la caméra principale (le spectateur).")]
        bool lookAtMainCameraByDefault = true;

        [SerializeField, Tooltip("Journaliser ce qui a été trouvé sur le modèle au démarrage.")]
        bool logSetup = true;

        /// <summary>La parole se termine : fin de l'estimation (ou de la voix), ou <see cref="StopSpeaking"/>. Une
        /// seule fois par <see cref="Speak"/> qui a rendu une durée &gt; 0 ; une parole qui en remplace une autre
        /// ne la termine pas.</summary>
        public event Action SpeechEnded;

        /// <summary>Un repère prosodique est atteint dans la réplique : <c>"sigh"</c>, <c>"laugh"</c> ou
        /// <c>"breath"</c> (au moment où le silence qu'il réserve commence). <c>[PAUSE]</c> n'en émet pas.</summary>
        public event Action<string> ProsodicCue;

        /// <summary>Un temps de la phrase est atteint (accent, insistance, question…) — pour que la couche du
        /// corps hoche la tête au bon mot. Les sourcils, eux, sont déjà gérés ici.</summary>
        public event Action<SpeechBeat> BeatReached;

        // ── État demandé ────────────────────────────────────────────────────
        string _emotion = Emotions.Neutral;
        float _intensity = 0.5f;
        readonly List<KeyValuePair<string, float>> _blend = new List<KeyValuePair<string, float>>();
        bool _emotionDirty = true;
        bool _driftHeld;
        string _heldEmotion;
        float _heldIntensity;
        readonly List<KeyValuePair<string, float>> _heldBlend = new List<KeyValuePair<string, float>>();
        float _speechStartedAt;

        SleepPhase _sleep = SleepPhase.Awake;
        float _energy = 1f;
        Transform _lookTarget;
        Vector3? _lookPoint;
        bool _lookSet;
        bool _replyPending;
        float _listeningUntil = float.NegativeInfinity;

        // ── Couches ────────────────────────────────────────────────────────
        readonly LipSyncModel _lip = new LipSyncModel();
        readonly SpeechBrows _brows = new SpeechBrows();
        readonly BlinkModel _blink = new BlinkModel();
        readonly FacePhysiology _physiology = new FacePhysiology();
        readonly AttentionDirector _attention = new AttentionDirector();
        readonly GazeModel _gaze = new GazeModel();
        FaceRig _rig;
        EmotionFace _emotionFace;
        FaceIdleModel _idle;
        VisemeRouting _routing;
        HashSet<string> _routingOutputs;
        GazeIntent _intent;
        bool _ready;
        bool _wasSpeaking;

        readonly Dictionary<string, float> _frame = new Dictionary<string, float>(StringComparer.Ordinal);
        HashSet<ExpressionKey> _written = new HashSet<ExpressionKey>();
        HashSet<ExpressionKey> _writtenNow = new HashSet<ExpressionKey>();
        readonly List<string> _cues = new List<string>();
        readonly List<SpeechBeat> _beats = new List<SpeechBeat>();
        readonly List<(float, float)> _loads = new List<(float, float)>();

        // ── API ─────────────────────────────────────────────────────────────

        /// <summary>
        /// Montre une émotion. <paramref name="blend"/> est le mélange du noyau (émotion → poids, trié par poids
        /// décroissant) : la secondaire transparaît à une part réduite. <paramref name="ambient"/> = dérive
        /// d'humeur entre deux répliques : pendant qu'elle parle, une dérive est retenue (la plus récente gagne)
        /// et appliquée quand la parole se termine — la balise [EMOTION:] est la vérité du tour, le visage ne
        /// glisse pas au milieu de la phrase. Une émotion inconnue vaut « neutral » pour une réplique et est
        /// ignorée pour une dérive.
        /// </summary>
        public void ShowEmotion(string emotion, float intensity, IReadOnlyList<KeyValuePair<string, float>> blend, bool ambient)
        {
            if (!Emotions.IsEmotion(emotion))
            {
                if (ambient)
                    return;
                emotion = Emotions.Neutral;
            }
            if (ambient && IsSpeaking && Time.time - _speechStartedAt < VoicedHoldMaxSeconds)
            {
                _driftHeld = true;
                _heldEmotion = emotion;
                _heldIntensity = intensity;
                Copy(blend, _heldBlend);
                return;
            }
            ApplyEmotion(emotion, intensity, blend);
        }

        /// <summary>
        /// Lance la synchronisation labiale sur <paramref name="text"/> (repères prosodiques compris, qui ne sont
        /// pas prononcés) au débit <paramref name="rate"/> (1 = normal, borné à [0,5 ; 2]). Rend la durée
        /// estimée en secondes (0 si rien n'est à dire). Remplace une parole en cours.
        /// </summary>
        public float Speak(string text, float rate = 1f)
        {
            var frames = SpeechPlan.Frames(text ?? "", SpeechCadence.MsPerCharForRate(rate));
            if (frames.Count == 0)
                return 0f;
            _lip.HoldAtEnd = externalVoice;
            _lip.SetArticulation(Emotions.ArticulationFor(_emotion, _intensity, Emotions.FatigueFromEnergy(_energy)));
            _lip.Begin(frames);
            _brows.Begin(SpeechBeats.Plan(text));
            _speechStartedAt = Time.time;
            _wasSpeaking = true;
            return SpeechPlan.DurationSeconds(frames);
        }

        /// <summary>
        /// Recale la bouche sur la position de lecture (index de caractère dans le texte passé à
        /// <see cref="Speak"/>) — pour une vraie voix qui rapporte où elle en est. En avant comme en arrière ; une
        /// estimation finie trop tôt repart. Sans effet après <see cref="StopSpeaking"/>.
        /// </summary>
        public void SeekSpeech(int charIndex)
        {
            if (_lip.Seek(charIndex) && !_wasSpeaking)
            {
                _wasSpeaking = true;
                _speechStartedAt = Time.time;
            }
        }

        /// <summary>Coupe la parole : la bouche se referme, <see cref="SpeechEnded"/> est émis si elle parlait.</summary>
        public void StopSpeaking()
        {
            bool was = _lip.IsSpeaking || _wasSpeaking;
            _lip.Stop();
            _brows.Begin(null);
            if (was)
                EndOfSpeech();
        }

        public bool IsSpeaking => _lip.IsSpeaking;

        /// <summary>Phase de sommeil du noyau : <c>awake</c>, <c>light_sleep</c>, <c>rem</c>, <c>deep_sleep</c>
        /// (une valeur inconnue vaut <c>awake</c>). Les yeux se ferment en douceur, frémissent en paradoxal.</summary>
        public void SetSleepPhase(string phase)
        {
            if (!SleepPhases.IsKnown(phase))
                Debug.LogWarning($"[Mika] phase de sommeil inconnue « {phase} » : traitée comme « awake ».");
            _sleep = SleepPhases.Parse(phase);
        }

        /// <summary>Énergie 0…1 (rythme circadien + fatigue) : paupières lourdes, clignements plus lents,
        /// articulation plus molle sous ~0,55.</summary>
        public void SetEnergy(float energy01)
        {
            _energy = Emotions.Clamp01(energy01);
            _emotionFace?.SetEnergy(_energy);
        }

        /// <summary>Les yeux suivent ce Transform (null : personne — regard devant elle).</summary>
        public void LookAt(Transform target)
        {
            _lookTarget = target;
            _lookPoint = null;
            _lookSet = true;
        }

        /// <summary>Les yeux vont vers ce point du monde (null : personne — regard devant elle).</summary>
        public void LookAt(Vector3? point)
        {
            _lookTarget = null;
            _lookPoint = point;
            _lookSet = true;
        }

        /// <summary>Un message de l'interlocuteur attend sa réponse (regard « je réfléchis », en haut et sur le
        /// côté, avec de brefs retours ; petit haussement de sourcils à la réception).</summary>
        public void SetReplyPending(bool pending)
        {
            if (pending && !_replyPending)
                _brows.Acknowledge();
            _replyPending = pending;
        }

        /// <summary>L'interlocuteur tape : elle le regarde, détourne moins les yeux, pendant ~2,5 s.</summary>
        public void NoteUserTyping() => _listeningUntil = Time.time + ListeningHoldSeconds;

        /// <summary>Elle murmure pour elle-même (persona « inner ») : elle ne regarde pas l'interlocuteur et ses
        /// sourcils ponctuent à peine.</summary>
        public bool InnerVoice { get; set; }

        /// <summary>Elle marche (fourni par la couche de locomotion) : les yeux regardent le chemin.</summary>
        public bool Walking { get; set; }

        /// <summary>Une vraie voix pilote la bouche (voir le champ de l'inspecteur).</summary>
        public bool ExternalVoice
        {
            get => externalVoice;
            set
            {
                externalVoice = value;
                _lip.HoldAtEnd = value;
            }
        }

        // ── Lecture ─────────────────────────────────────────────────────────

        /// <summary>Le modèle est prêt (expressions enregistrées, runtime UniVRM en place).</summary>
        public bool IsReady => _ready;
        public string CurrentEmotion => _emotion;
        public float CurrentIntensity => _intensity;
        public SleepPhase CurrentSleepPhase => _sleep;
        /// <summary>Où est son attention (contact, évitement, réflexion…) — la couche de la tête peut s'en servir.</summary>
        public AttentionState Attention => _intent.State;
        /// <summary>Angles appliqués aux yeux, en radians sémantiques (pitch &gt; 0 en bas, yaw &gt; 0 vers sa gauche).</summary>
        public GazeAngles EyeAngles => _gaze.Current;
        /// <summary>Caractère de la réplique que la bouche articule (−1 hors parole ou sur un silence).</summary>
        public int SpeechCursor => _lip.CurrentCharOffset;
        /// <summary>Insistance courante de la parole (0…1, décroissante) — sourcils, et la tête si elle le veut.</summary>
        public float SpeechEmphasis => _brows.Emphasis;
        /// <summary>« visemes » (morphs VRChat), « presets » (aa ih ou ee oh) ou « mixed ».</summary>
        public string LipSyncMode => _routing?.Mode ?? "none";
        /// <summary>Combien des 29 émotions passent par les groupes riches du modèle.</summary>
        public int RichEmotionCount => _emotionFace?.RichCount ?? 0;
        /// <summary>Les noms d'expression connus sur le modèle (presets, groupes, copies, morphs bruts).</summary>
        public IEnumerable<string> ExpressionNames => _rig?.Names ?? Enumerable.Empty<string>();

        /// <summary>
        /// Le corps vient d'être téléporté (un instantané du monde, une arrivée) : les ressorts des cheveux et des
        /// vêtements prendraient ce saut pour une vitesse énorme et s'envoleraient ; on les remet au repos.
        /// Reçu par message (<c>BroadcastMessage("OnTeleported")</c>) : le corps ne connaît pas l'avatar.
        /// </summary>
        public void OnTeleported()
        {
            if (vrm == null) return;
            try
            {
                vrm.Runtime?.SpringBone?.RestoreInitialTransform();
            }
            catch (System.Exception e)
            {
                // Avant la première image l'exécution VRM n'est pas encore prête : rien à remettre au repos.
                Debug.LogWarning($"[Mika] ressorts non réinitialisés : {e.Message}");
            }
        }

        // ── Cycle de vie ────────────────────────────────────────────────────

        void Awake()
        {
            // Pas de « ?? » sur un UnityEngine.Object : dans l'éditeur un composant absent est un faux null que
            // l'opérateur ne reconnaît pas.
            if (vrm == null)
                vrm = GetComponent<Vrm10Instance>();
            if (vrm == null)
                vrm = GetComponentInChildren<Vrm10Instance>(true);
            if (vrm == null || vrm.Vrm == null)
            {
                Debug.LogWarning($"[Mika] {name} : pas de Vrm10Instance avec un VRM10Object — le visage reste inerte.", this);
                return;
            }
            var groups = new HashSet<string>(EmotionFace.RichMap.Values.SelectMany(r => r.Keys)) { EmotionFace.TiredGroup };
            var raws = FacePhysiology.Morphs.Concat(VisemeRouting.VrcMorphs());
            try
            {
                _rig = new FaceRig(vrm, groups, raws);
            }
            catch (Exception e)
            {
                Debug.LogException(e, this);
                _rig = null;
                return;
            }
            _emotionFace = new EmotionFace(_rig.HasGroup, _rig.HasPreset);
            _emotionFace.SetEnergy(_energy);
            _idle = new FaceIdleModel(_rig.HasExpression);
            _routing = new VisemeRouting(_rig.HasRawMorph, _rig.HasPreset);
            _routingOutputs = new HashSet<string>(_routing.Outputs, StringComparer.Ordinal);
            _emotionDirty = true;
        }

        void Start()
        {
            if (_rig == null || vrm == null)
                return;
            try
            {
                _rig.Apply(vrm);
                // Le regard est piloté ici (lacet/tangage), jamais par un Transform suivi par UniVRM.
                vrm.LookAtTargetType = VRM10ObjectLookAt.LookAtTargetTypes.YawPitchValue;
                _ready = true;
            }
            catch (Exception e)
            {
                Debug.LogException(e, this);
                return;
            }
            if (logSetup)
                LogSetup();
        }

        void OnDestroy()
        {
            SpeechEnded = null;
            ProsodicCue = null;
            BeatReached = null;
            // Les expressions ajoutées vivent sur une copie du VRM10Object : on ne les détruit que si l'instance
            // VRM ne s'en sert plus (détruite avec nous). Sinon elles restent à elle, et Unity les ramassera avec
            // les assets inutilisés.
            if (_rig != null && vrm == null)
                _rig.DestroyCreated();
            _rig = null;
            _ready = false;
        }

        void LateUpdate() => Step(Time.deltaTime);

        /// <summary>Une image du visage. Séparée de <c>LateUpdate</c> pour qu'un outil d'éditeur puisse la piloter
        /// à pas fixe (vérification sur le vrai modèle sans passer en mode jeu).</summary>
        void Step(float dt)
        {
            if (!_ready || vrm == null || !vrm.isActiveAndEnabled)
                return;
            Vrm10Runtime runtime;
            try
            {
                runtime = vrm.Runtime;
            }
            catch (Exception)
            {
                return;
            }

            if (_driftHeld && (!_lip.IsSpeaking || Time.time - _speechStartedAt >= VoicedHoldMaxSeconds))
                ReleaseDrift();
            if (_emotionDirty)
            {
                _emotionFace.SetEmotion(_emotion, _intensity, _blend);
                _physiology.SetEmotion(_emotion, _intensity);
                _emotionDirty = false;
            }

            // Bouche d'abord : c'est elle qui dit si elle parle encore à ce pas.
            _lip.Update(dt);
            _lip.DrainCues(_cues);
            bool speaking = _lip.IsSpeaking;
            bool ended = _wasSpeaking && !speaking;
            if (ended)
                _wasSpeaking = false;

            float arousal = Emotions.ArousalOf(_emotion) * _intensity;
            float beatScale = (InnerVoice ? 0.35f : 1f) * Emotions.Clamp(1f + 0.45f * arousal, 0.55f, 1.4f);
            _brows.Step(dt, _lip.CurrentCharOffset, speaking, beatScale, _beats);

            bool asleep = _sleep != SleepPhase.Awake;
            float fatigue = Emotions.FatigueFromEnergy(_energy);

            // Regard : où est l'interlocuteur, mesuré dans le repère de la tête telle que l'animation et l'IK
            // l'ont posée à cette image — les yeux couvrent le reste (réflexe vestibulo-oculaire).
            GazeAngles? viewer = null;
            var point = LookPoint();
            if (point.HasValue)
            {
                var (yawDeg, pitchDeg) = runtime.LookAt.CalculateYawPitchFromLookAtPosition(point.Value);
                viewer = new GazeAngles(-pitchDeg * Mathf.Deg2Rad, -yawDeg * Mathf.Deg2Rad);
            }
            bool reachable = viewer.HasValue && Mathf.Abs(viewer.Value.Yaw) <= HeadReachYaw &&
                             Mathf.Abs(viewer.Value.Pitch) <= HeadReachPitch;
            _intent = _attention.Update(dt, new AttentionInput
            {
                Speaking = speaking,
                ReplyPending = _replyPending,
                Listening = Time.time < _listeningUntil,
                InnerVoice = InnerVoice,
                Emotion = _emotion,
                Intensity = _intensity,
                SleepPhase = _sleep,
                Reachable = reachable,
                ViewerAngle = viewer.HasValue ? Mathf.Sqrt(viewer.Value.Pitch * viewer.Value.Pitch + viewer.Value.Yaw * viewer.Value.Yaw) : 0f,
                Walking = Walking,
            });
            var eyes = _gaze.Step(dt, _intent, _emotion, _intensity, asleep, reachable ? viewer : null);
            ApplyEyes(runtime, eyes);

            // Visage : chaque couche AJOUTE ses poids ; les jeux de noms sont disjoints par construction.
            _frame.Clear();
            _frame["blink"] = _blink.Step(dt, _emotion, fatigue, speaking, _sleep, _intent.Shift);
            _physiology.Step(dt);
            _physiology.Write(_frame);
            _emotionFace.Step(dt, _frame);
            _idle.Step(dt, _emotion, _intensity, speaking, asleep, _brows.Emphasis, _brows.Question, _frame);

            // La bouche après les autres : elle lit ce qu'ils font déjà à la bouche pour ne pas la sur-ouvrir.
            _loads.Clear();
            foreach (var kv in _frame)
                if (!_routingOutputs.Contains(kv.Key))
                    _loads.Add((kv.Value, _rig.MouthInvolvement(kv.Key)));
            _routing.Write(_lip.Levels, MouthLoad.Combine(_loads), _frame);

            WriteExpressions(runtime);

            if (_cues.Count > 0)
            {
                foreach (var cue in _cues)
                    Raise(ProsodicCue, cue);
                _cues.Clear();
            }
            if (_beats.Count > 0)
            {
                foreach (var beat in _beats)
                    Raise(BeatReached, beat);
                _beats.Clear();
            }
            if (ended)
                EndOfSpeech();
        }

        // ── Interne ─────────────────────────────────────────────────────────

        void ApplyEmotion(string emotion, float intensity, IReadOnlyList<KeyValuePair<string, float>> blend)
        {
            _emotion = emotion;
            _intensity = Emotions.Clamp01(intensity);
            Copy(blend, _blend);
            _emotionDirty = true;
        }

        void ReleaseDrift()
        {
            _driftHeld = false;
            ApplyEmotion(_heldEmotion, _heldIntensity, _heldBlend);
        }

        void EndOfSpeech()
        {
            _wasSpeaking = false;
            if (_driftHeld)
                ReleaseDrift();
            Raise(SpeechEnded);
        }

        Vector3? LookPoint()
        {
            if (_lookTarget != null)
                return _lookTarget.position;
            if (_lookPoint.HasValue)
                return _lookPoint;
            if (!_lookSet && lookAtMainCameraByDefault)
            {
                var cam = Camera.main;
                if (cam != null)
                    return cam.transform.position;
            }
            return null;
        }

        /// <summary>
        /// Angles sémantiques → entrée du LookAt d'UniVRM (degrés, lacet + vers SA droite, tangage + vers le
        /// haut). Le LookAt applique la courbe de l'auteur (entrée 0…X° → œil 0…Y°) ; on l'inverse pour que l'œil
        /// tourne vraiment de l'angle voulu, la courbe restant la borne physique du modèle.
        /// </summary>
        void ApplyEyes(Vrm10Runtime runtime, GazeAngles eyes)
        {
            var la = vrm.Vrm.LookAt;
            float yawDeg = -eyes.Yaw * Mathf.Rad2Deg;
            float pitchDeg = -eyes.Pitch * Mathf.Rad2Deg;
            float yawIn, pitchIn;
            if (la.LookAtType == UniGLTF.Extensions.VRMC_vrm.LookAtType.bone)
            {
                yawIn = GazeModel.InverseCurve(yawDeg, la.HorizontalOuter.CurveXRangeDegree, la.HorizontalOuter.CurveYRangeDegree);
                var vertical = pitchDeg >= 0f ? la.VerticalUp : la.VerticalDown;
                pitchIn = GazeModel.InverseCurve(pitchDeg, vertical.CurveXRangeDegree, vertical.CurveYRangeDegree);
            }
            else
            {
                // LookAt par expressions : la courbe rend un poids, pas un angle. La portée du web (17° / 12,6°)
                // devient la pleine échelle.
                yawIn = Mathf.Clamp(yawDeg / (GazeModel.EyeMaxYaw * Mathf.Rad2Deg), -1f, 1f) * la.HorizontalOuter.CurveXRangeDegree;
                var vertical = pitchDeg >= 0f ? la.VerticalUp : la.VerticalDown;
                pitchIn = Mathf.Clamp(pitchDeg / (GazeModel.EyeMaxPitch * Mathf.Rad2Deg), -1f, 1f) * vertical.CurveXRangeDegree;
            }
            runtime.LookAt.SetYawPitchManually(yawIn, pitchIn);
        }

        void WriteExpressions(Vrm10Runtime runtime)
        {
            var expression = runtime.Expression;
            _writtenNow.Clear();
            foreach (var kv in _frame)
            {
                if (!_rig.TryResolve(kv.Key, out var key))
                    continue;
                float w = Mathf.Clamp01(kv.Value);
                expression.SetWeight(key, w);
                _writtenNow.Add(key);
            }
            // Une forme qui ne contribue plus est relâchée, sinon elle resterait figée à son dernier poids.
            foreach (var key in _written)
                if (!_writtenNow.Contains(key))
                    expression.SetWeight(key, 0f);
            (_written, _writtenNow) = (_writtenNow, _written);
        }

        void LogSetup()
        {
            var missing = EmotionFace.RichMap.Values.SelectMany(r => r.Keys).Distinct().Where(g => !_rig.HasGroup(g)).ToList();
            Debug.Log($"[Mika] visage prêt : {_emotionFace.RichCount}/{Emotions.All.Count} émotions sur les groupes du modèle" +
                      (missing.Count > 0 ? $" (absents : {string.Join(", ", missing)})" : "") +
                      $", bouche « {_routing.Mode} » ({_routing.RawVisemes}/14 visèmes VRChat)" +
                      $", physiologie {FacePhysiology.Morphs.Count(_rig.HasRawMorph)}/{FacePhysiology.Morphs.Count} morphs" +
                      $", micro-expressions {FaceIdleModel.CandidateShapes().Count(_rig.HasExpression)}/{FaceIdleModel.CandidateShapes().Count()}" +
                      $", clignement {(_rig.HasPreset("blink") ? "oui" : "NON")}, regard « {vrm.Vrm.LookAt.LookAtType} ».", this);
            if (_rig.StrippedReport.Count > 0)
                Debug.Log("[Mika] symboles retirés des groupes : " + string.Join(" ; ", _rig.StrippedReport), this);
        }

        static void Copy(IReadOnlyList<KeyValuePair<string, float>> from, List<KeyValuePair<string, float>> into)
        {
            into.Clear();
            if (from == null)
                return;
            for (int i = 0; i < from.Count; i++)
                into.Add(from[i]);
        }

        void Raise(Action handler)
        {
            if (handler == null)
                return;
            try { handler(); }
            catch (Exception e) { Debug.LogException(e, this); }
        }

        void Raise<T>(Action<T> handler, T arg)
        {
            if (handler == null)
                return;
            try { handler(arg); }
            catch (Exception e) { Debug.LogException(e, this); }
        }
    }
}
