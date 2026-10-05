using System;
using System.Collections.Generic;

namespace Mika.Avatar
{
    /// <summary>
    /// Angles de regard sémantiques, en radians, indépendants des conventions du rig : <c>Pitch &gt; 0</c> = vers
    /// le BAS, <c>Yaw &gt; 0</c> = vers SA gauche (la droite de qui la regarde de face). Même convention que le
    /// client web (<c>gazeMath.ts</c>), pour que les tables se recopient telles quelles.
    /// </summary>
    public struct GazeAngles
    {
        public float Pitch;
        public float Yaw;
        public GazeAngles(float pitch, float yaw) { Pitch = pitch; Yaw = yaw; }
        public static readonly GazeAngles Zero = default;
        public override string ToString() => $"(pitch {Pitch:0.000}, yaw {Yaw:0.000})";
    }

    public enum AttentionState
    {
        /// <summary>Les yeux sur l'interlocuteur.</summary>
        Contact,
        /// <summary>Un bref regard ailleurs, puis retour.</summary>
        Avert,
        /// <summary>Seule avec ses pensées : elle regarde la pièce.</summary>
        Wander,
        /// <summary>Elle traverse la pièce : les yeux sur le chemin.</summary>
        Walking,
        /// <summary>Une réponse se compose : absorbée, en haut et sur le côté.</summary>
        Thinking,
        /// <summary>Elle murmure pour elle-même : pas pour vous.</summary>
        Inner,
        /// <summary>L'interlocuteur est hors d'atteinte (derrière elle, ou personne) : regard devant elle.</summary>
        Away,
        Asleep,
    }

    public struct AttentionInput
    {
        public bool Speaking;
        /// <summary>Un message a été accepté et rien n'y a encore répondu.</summary>
        public bool ReplyPending;
        /// <summary>La personne en face est en train d'écrire.</summary>
        public bool Listening;
        /// <summary>La voix intérieure (murmure à elle-même), pas une parole adressée.</summary>
        public bool InnerVoice;
        public string Emotion;
        public float Intensity;
        public SleepPhase SleepPhase;
        /// <summary>L'interlocuteur est à portée d'un tour de tête (false = derrière elle, ou pas de cible).</summary>
        public bool Reachable;
        /// <summary>Distance angulaire à l'interlocuteur (rad) : dimensionne le saut quand le contact bascule.</summary>
        public float ViewerAngle;
        public bool Walking;
        /// <summary>Elle est à une occupation (lire, taper, regarder dehors…) : seule, ses yeux y retournent entre
        /// deux coups d'œil vers l'interlocuteur, et y restent de plus en plus longtemps.</summary>
        public bool Occupied;
        /// <summary>L'interlocuteur bouge nettement à cette image (il se déplace) : on lève les yeux vers qui bouge
        /// près de soi.</summary>
        public bool ViewerMoved;
    }

    public struct GazeIntent
    {
        public AttentionState State;
        /// <summary>Part de la direction de l'interlocuteur dans la cible des yeux, 0…1.</summary>
        public float Contact;
        /// <summary>Ajouté au regard — un évitement, la pose de réflexion, le murmure intérieur.</summary>
        public GazeAngles Offset;
        /// <summary>Petit saut de fixation courant, changé à la cadence des saccades.</summary>
        public GazeAngles Saccade;
        /// <summary>Saut saccadique décidé À CE PAS (rad) ; 0 quand les yeux sont restés fixes.</summary>
        public float Shift;
    }

    /// <summary>
    /// Où est l'attention de Mika — la couche de décision derrière les yeux. Portage de
    /// <c>frontend/Web/src/vtuber/animation/attention.ts</c>. Pur : aléa injectable, le temps n'entre que par
    /// <c>dt</c>.
    /// </summary>
    /// <remarks>
    /// Le regard conversationnel tel que la littérature le décrit (Kendon 1967, Argyle &amp; Cook 1976) : qui
    /// écoute garde les yeux sur qui parle ; qui parle détourne le regard au DÉBUT d'un énoncé (il planifie) et
    /// revient ; qui cherche une pensée regarde en haut et sur le côté, avec de brefs retours ; la honte, la
    /// tristesse et l'anxiété font baisser les yeux, l'amour et la gratitude les détournent à peine. Et qui
    /// murmure pour elle-même ne vous regarde pas. Tout CHANGEMENT de regard ici est un saut, jamais un
    /// glissement : un œil qui glisse vers sa cible a l'air ivre.
    /// </remarks>
    public sealed class AttentionDirector
    {
        public readonly struct AversionProfile
        {
            public readonly float P;
            public readonly GazeAngles? Dir;
            public AversionProfile(float p, GazeAngles? dir = null) { P = p; Dir = dir; }
        }

        static GazeAngles G(float pitch, float yaw) => new GazeAngles(pitch, yaw);

        public static readonly IReadOnlyDictionary<string, AversionProfile> Aversion = new Dictionary<string, AversionProfile>
        {
            // La honte et l'humeur basse détournent vers le BAS — l'indice le plus fort, le plus lisible.
            ["embarrassed"] = new AversionProfile(2.2f, G(0.18f, -0.16f)),
            ["anxious"] = new AversionProfile(1.8f, G(0.12f, 0.14f)),
            ["scared"] = new AversionProfile(1.4f, G(0.1f, 0.18f)),
            ["sad"] = new AversionProfile(1.6f, G(0.2f, 0f)),
            ["lonely"] = new AversionProfile(1.6f, G(0.18f, -0.05f)),
            ["melancholic"] = new AversionProfile(1.5f, G(0.16f, -0.1f)),
            ["jealous"] = new AversionProfile(1.4f, G(0.06f, -0.2f)),
            ["disgusted"] = new AversionProfile(1.2f, G(0.04f, -0.18f)),
            // La remémoration et la rêverie vont vers le HAUT et sur le côté.
            ["thinking"] = new AversionProfile(1.8f, G(-0.16f, 0.18f)),
            ["confused"] = new AversionProfile(1.5f, G(-0.1f, -0.14f)),
            ["dreamy"] = new AversionProfile(1.5f, G(-0.18f, 0.04f)),
            ["nostalgic"] = new AversionProfile(1.4f, G(-0.12f, 0.12f)),
            ["hopeful"] = new AversionProfile(0.9f, G(-0.12f, 0.06f)),
            ["frustrated"] = new AversionProfile(1.1f, G(-0.08f, 0.16f)),
            ["bored"] = new AversionProfile(1.7f, G(-0.04f, 0.22f)),
            ["proud"] = new AversionProfile(0.7f, G(-0.1f, 0.1f)),
            // Regard tenu : les émotions d'attachement, et celles qui fixent.
            ["love"] = new AversionProfile(0.35f),
            ["grateful"] = new AversionProfile(0.5f),
            ["determined"] = new AversionProfile(0.4f),
            ["angry"] = new AversionProfile(0.6f),
            ["curious"] = new AversionProfile(0.8f),
            ["surprised"] = new AversionProfile(0.3f),
        };

        static readonly HashSet<string> Focused = new HashSet<string> { "love", "grateful", "proud", "determined" };
        static readonly HashSet<string> RestlessSet = new HashSet<string> { "scared", "anxious", "surprised", "excited" };

        // Durées (s) et amplitudes (rad).
        public static readonly (float lo, float hi) AversionInterval = (3.5f, 8f);
        public static readonly (float lo, float hi) AversionDuration = (0.7f, 2f);
        public const float AversionPIdle = 0.4f;
        public const float AversionPSpeaking = 0.55f;
        public const float AversionPListening = 0.18f;
        /// <summary>Regard de planification au début d'un énoncé.</summary>
        public const float OnsetAversionP = 0.45f;
        public static readonly (float lo, float hi) OnsetAversionDuration = (0.9f, 1.6f);
        public static readonly GazeAngles PlanningOffset = G(-0.12f, 0.16f);
        public const float ThinkingContact = 0.15f;
        public static readonly GazeAngles ThinkingOffset = G(-0.14f, 0.2f);
        public static readonly (float lo, float hi) ThinkingCheckinInterval = (2.5f, 5f);
        public static readonly (float lo, float hi) ThinkingCheckinDuration = (0.5f, 0.9f);
        /// <summary>Une réponse qui ne vient jamais cesse d'être « réfléchie » au bout de ça.</summary>
        public const float ThinkingMaxS = 90f;
        public const float InnerContact = 0.1f;
        public static readonly GazeAngles InnerOffset = G(0.14f, 0.12f);
        public static readonly (float lo, float hi) SaccadeInterval = (1.8f, 4.5f);
        /// <summary>En contact les yeux balaient le visage (yeux ↔ bouche, 1–4°) ; hors contact, plus large.</summary>
        public static readonly (float lo, float hi) SaccadeAmplitudeContact = (0.02f, 0.07f);
        public static readonly (float lo, float hi) SaccadeAmplitudeFree = (0.04f, 0.1f);
        public static readonly GazeAngles WalkingOffset = G(0.16f, 0f);
        /// <summary>Laissée seule, on ne fixe pas l'endroit où quelqu'un était : après ce temps sans personne
        /// (ni parole, ni frappe, ni réponse attendue), l'attention dérive vers la pièce.</summary>
        public const float WanderAfterS = 25f;
        public const float WanderP = 0.75f;
        public static readonly (float lo, float hi) WanderDuration = (2.5f, 7f);
        public static readonly (float lo, float hi) WanderInterval = (2f, 6f);
        /// <summary>
        /// Seule, elle revient vers l'interlocuteur de moins en moins souvent : une pente, pas un seuil. La rêverie
        /// (le temps passé ailleurs entre deux coups d'œil) est multipliée par une échelle qui monte de 1 à son
        /// plafond en <see cref="AbsorptionRampS"/> de solitude tranquille. Occupée (un livre, l'écran), elle
        /// s'absorbe nettement : 2,5–7 s au début, 20–56 s après dix minutes. Sans rien à faire, la seule personne
        /// présente reste ce qu'il y a de plus intéressant à regarder : la pente est plus douce. Une parole, une
        /// frappe, ou l'interlocuteur qui bouge la remettent à zéro.
        /// </summary>
        public const float AbsorptionRampS = 600f;
        public const float AbsorbedMaxScale = 8f;
        public const float IdleAbsorbedMaxScale = 3f;

        /// <summary>
        /// Points d'intérêt dans son repère sémantique, relatifs à SON devant (la porte, le lit, le sol, ses
        /// mains, la lumière de la fenêtre, le lointain). Sans tête à tourner, les yeux s'arrêtent au coin de
        /// l'œil : c'est la couche d'IK du corps qui porte le reste si elle suit <see cref="MikaFace.Attention"/>.
        /// </summary>
        public static readonly GazeAngles[] WanderPoints =
        {
            G(0.04f, 0.55f), G(0.24f, -0.5f), G(0.34f, 0.08f), G(0.3f, -0.14f),
            G(-0.12f, -0.72f), G(-0.2f, 0.32f), G(0.02f, -0.38f),
        };

        static readonly GazeAngles[] AversionDirs =
        {
            G(0.14f, 0.16f), G(0.14f, -0.16f), G(-0.12f, 0.18f), G(-0.12f, -0.18f), G(0.02f, 0.22f), G(0.02f, -0.22f),
        };

        readonly Func<float> _random;
        AttentionState _state = AttentionState.Contact;
        float _contact = 1f;
        GazeAngles _offset;
        GazeAngles _saccade;
        float _aversionTimer;
        float _nextAversionAt;
        float _aversionRemaining;
        float _saccadeTimer;
        float _nextSaccadeAt;
        float _thinkingElapsed;
        float _thinkingSide = 1f;
        float _checkinTimer;
        float _nextCheckinAt;
        float _checkinRemaining;
        float _innerSide = 1f;
        bool _wasSpeaking;
        bool _wasPending;
        float _idleFor;
        bool _wandering;
        bool _wasViewerMoving;
        float _absorbedFor;

        public AttentionDirector(Func<float> random = null)
        {
            _random = random ?? BlinkModel.DefaultRandom();
            _nextAversionAt = Sample(AversionInterval);
            _nextSaccadeAt = Sample(SaccadeInterval);
            _nextCheckinAt = Sample(ThinkingCheckinInterval);
        }

        public AttentionState State => _state;

        public GazeIntent Update(float dt, AttentionInput input)
        {
            if (!(dt > 0f))
                dt = 0f;
            float prevContact = _contact;
            float prevPitch = _offset.Pitch;
            float prevYaw = _offset.Yaw;

            bool speakingStarted = input.Speaking && !_wasSpeaking;
            bool pendingStarted = input.ReplyPending && !_wasPending;
            bool viewerStirred = input.ViewerMoved && !_wasViewerMoving;
            _wasSpeaking = input.Speaking;
            _wasPending = input.ReplyPending;
            _wasViewerMoving = input.ViewerMoved;

            if (input.SleepPhase != SleepPhase.Awake)
            {
                _state = AttentionState.Asleep;
                _contact = 0f;
                _offset = default;
                _saccade = default;
                _aversionRemaining = 0f;
                _checkinRemaining = 0f;
                _thinkingElapsed = 0f;
                return Emit(0f);
            }

            if (pendingStarted)
            {
                _thinkingElapsed = 0f;
                _thinkingSide = _random() < 0.5f ? -1f : 1f;
                _checkinTimer = 0f;
                _nextCheckinAt = Sample(ThinkingCheckinInterval);
                _checkinRemaining = 0f;
            }
            _thinkingElapsed = input.ReplyPending ? _thinkingElapsed + dt : 0f;
            bool engaged = input.Speaking || input.ReplyPending || input.Listening;
            _idleFor = engaged ? 0f : _idleFor + dt;
            _absorbedFor = engaged || input.ViewerMoved || _idleFor < WanderAfterS ? 0f : _absorbedFor + dt;
            if (engaged && _wandering)
            {
                // Quelqu'un est là de nouveau : le regard ailleurs finit maintenant, pas quand il devait finir.
                _wandering = false;
                _aversionRemaining = 0f;
                _offset = default;
                _aversionTimer = 0f;
                _nextAversionAt = Sample(AversionInterval);
            }

            AttentionState mode;
            if (input.Walking)
                mode = AttentionState.Walking;
            else if (input.InnerVoice && input.Speaking)
                mode = AttentionState.Inner;
            else if (input.ReplyPending && !input.Speaking && _thinkingElapsed <= ThinkingMaxS)
                // Un message en attente pendant qu'elle dit encore la réplique précédente ne détourne pas son
                // regard : on finit sa phrase d'abord.
                mode = AttentionState.Thinking;
            else
                mode = AttentionState.Contact;

            if (mode == AttentionState.Walking)
            {
                _aversionRemaining = 0f;
                _wandering = false;
                _contact = input.Speaking ? 0.35f : 0f;
                _offset = WalkingOffset;
            }
            else if (mode == AttentionState.Inner)
            {
                if (_state != AttentionState.Inner)
                    _innerSide = _random() < 0.5f ? -1f : 1f;
                _aversionRemaining = 0f;
                _contact = InnerContact;
                _offset = G(InnerOffset.Pitch, InnerOffset.Yaw * _innerSide);
            }
            else if (mode == AttentionState.Thinking)
            {
                _aversionRemaining = 0f;
                if (_checkinRemaining > 0f)
                {
                    // Un regard vers vous entre deux moments d'absorption.
                    _checkinRemaining -= dt;
                    _contact = 1f;
                    _offset = default;
                }
                else
                {
                    _checkinTimer += dt;
                    if (_checkinTimer >= _nextCheckinAt)
                    {
                        _checkinTimer = 0f;
                        _nextCheckinAt = Sample(ThinkingCheckinInterval);
                        _checkinRemaining = Sample(ThinkingCheckinDuration);
                        _contact = 1f;
                        _offset = default;
                    }
                    else
                    {
                        _contact = ThinkingContact;
                        _offset = G(ThinkingOffset.Pitch, ThinkingOffset.Yaw * _thinkingSide);
                    }
                }
            }
            else
            {
                if (_state == AttentionState.Thinking || _state == AttentionState.Inner)
                {
                    // Retour vers vous : l'horloge des évitements repart, pour que le retour ne soit pas aussitôt
                    // suivi d'un regard ailleurs.
                    _aversionTimer = 0f;
                    _nextAversionAt = Sample(AversionInterval);
                }
                if (speakingStarted && _aversionRemaining <= 0f && _random() < OnsetAversionP)
                {
                    // Regard de planification : le regard ailleurs qui ouvre un énoncé.
                    _aversionRemaining = Sample(OnsetAversionDuration);
                    float side = _random() < 0.5f ? -1f : 1f;
                    _offset = G(PlanningOffset.Pitch, PlanningOffset.Yaw * side);
                }
                bool alone = _idleFor >= WanderAfterS;
                if (alone && viewerStirred && _aversionRemaining > 0f)
                {
                    // Il se lève, traverse la pièce, s'approche : on lève les yeux vers qui bouge près de soi —
                    // maintenant, pas à la fin de la rêverie.
                    _aversionRemaining = 0f;
                    _wandering = false;
                    _offset = default;
                    _aversionTimer = 0f;
                    _nextAversionAt = Sample(WanderInterval);
                }
                if (_aversionRemaining > 0f)
                {
                    _aversionRemaining -= dt;
                    if (_aversionRemaining <= 0f)
                    {
                        _aversionRemaining = 0f;
                        _wandering = false;
                        _offset = default;
                        _aversionTimer = 0f;
                        _nextAversionAt = alone ? Sample(WanderInterval) : Sample(AversionInterval) * IntervalScale(input);
                    }
                }
                else if (alone)
                {
                    _offset = default;
                    _aversionTimer += dt;
                    if (_aversionTimer >= _nextAversionAt)
                    {
                        _aversionTimer = 0f;
                        _nextAversionAt = Sample(WanderInterval);
                        if (_random() < WanderP)
                        {
                            _wandering = true;
                            _aversionRemaining = Sample(WanderDuration) * AbsorptionScale(input.Occupied);
                            // Occupée, ses yeux retournent à ce qu'elle fait (la tête y est déjà, portée par son
                            // occupation) : une longue rêverie n'est pas un regard fixé sur la porte. Sans rien à
                            // faire, ils parcourent la pièce.
                            _offset = input.Occupied
                                ? GazeAngles.Zero
                                : WanderPoints[Math.Min(WanderPoints.Length - 1, (int)(_random() * WanderPoints.Length))];
                        }
                    }
                }
                else
                {
                    _offset = default;
                    _aversionTimer += dt;
                    if (_aversionTimer >= _nextAversionAt)
                    {
                        _aversionTimer = 0f;
                        _nextAversionAt = Sample(AversionInterval) * IntervalScale(input);
                        AversionProfile profile = default;
                        bool hasProfile = input.Emotion != null && Aversion.TryGetValue(input.Emotion, out profile);
                        float p = BaseAversionP(input) * (hasProfile ? profile.P : 1f);
                        if (_random() < p)
                        {
                            _aversionRemaining = Sample(AversionDuration);
                            _offset = hasProfile && profile.Dir.HasValue
                                ? profile.Dir.Value
                                : AversionDirs[Math.Min(AversionDirs.Length - 1, (int)(_random() * AversionDirs.Length))];
                        }
                    }
                }
                // Le regard qui erre regarde la pièce elle-même (relativement à son devant), pas un point à côté
                // de l'interlocuteur.
                _contact = _wandering ? 0f : 1f;
                mode = _wandering ? AttentionState.Wander : _aversionRemaining > 0f ? AttentionState.Avert : AttentionState.Contact;
            }

            if (!input.Reachable)
            {
                // Personne en face qu'un tour de tête atteindrait : le terme de contact n'a pas de sens. Une pensée
                // ou un murmure gardent leur décalage — relatif à son devant, pas à un interlocuteur.
                _contact = 0f;
                if (mode == AttentionState.Contact || mode == AttentionState.Avert)
                    mode = AttentionState.Away;
            }

            float saccadeJump = UpdateSaccade(dt, input, mode);
            _state = mode;

            float offsetJump = Hypot(_offset.Pitch - prevPitch, _offset.Yaw - prevYaw);
            float contactJump = Math.Abs(_contact - prevContact) * Math.Min(Math.Abs(input.ViewerAngle), 0.5f);
            return Emit(offsetJump + contactJump + saccadeJump);
        }

        GazeIntent Emit(float shift) => new GazeIntent
        {
            State = _state,
            Contact = _contact,
            Offset = _offset,
            Saccade = _saccade,
            Shift = shift,
        };

        static float BaseAversionP(AttentionInput input) =>
            input.Listening ? AversionPListening : input.Speaking ? AversionPSpeaking : AversionPIdle;

        static float IntervalScale(AttentionInput input) => input.Listening ? 1.8f : input.Speaking ? 0.8f : 1f;

        float AbsorptionScale(bool occupied)
        {
            float max = occupied ? AbsorbedMaxScale : IdleAbsorbedMaxScale;
            return 1f + (max - 1f) * Math.Min(1f, _absorbedFor / AbsorptionRampS);
        }

        float UpdateSaccade(float dt, AttentionInput input, AttentionState mode)
        {
            _saccadeTimer += dt;
            if (_saccadeTimer < _nextSaccadeAt)
                return 0f;
            _saccadeTimer = 0f;
            bool focused = input.Emotion != null && Focused.Contains(input.Emotion);
            bool restless = input.Emotion != null && RestlessSet.Contains(input.Emotion);
            float amp = Sample(mode == AttentionState.Contact ? SaccadeAmplitudeContact : SaccadeAmplitudeFree);
            if (focused)
                amp *= 0.5f;
            if (restless)
                amp *= 1.4f;
            if (input.Listening)
                amp *= 0.6f;
            float angle = _random() * MathF.PI * 2f;
            float pitch = MathF.Sin(angle) * amp;
            float yaw = MathF.Cos(angle) * amp;
            float jump = Hypot(pitch - _saccade.Pitch, yaw - _saccade.Yaw);
            _saccade = G(pitch, yaw);
            float interval = Sample(SaccadeInterval);
            if (focused)
                interval *= 1.4f;
            if (restless)
                interval *= 0.55f;
            if (input.Listening)
                interval *= 1.5f;
            _nextSaccadeAt = interval;
            return jump;
        }

        float Sample((float lo, float hi) range) => range.lo + _random() * Math.Max(0f, range.hi - range.lo);

        static float Hypot(float a, float b) => MathF.Sqrt(a * a + b * b);
    }

    /// <summary>
    /// Ce que les yeux font de l'intention d'attention : contact × direction de l'interlocuteur (bornée à ce que
    /// l'œil atteint) + biais d'émotion + décalage d'attention + saccade, bornés, puis suivis en ~30 ms — un
    /// saut, pas un glissement. Portage de <c>GazeController.ts</c>, sans les os : la sortie est un couple
    /// d'angles sémantiques que <see cref="MikaFace"/> confie au LookAt d'UniVRM.
    /// </summary>
    public sealed class GazeModel
    {
        /// <summary>Portée prudente : un œil VRM tourné au-delà de ~17° montre du blanc sur la plupart des modèles.</summary>
        public const float EyeMaxYaw = 0.3f;
        public const float EyeMaxPitch = 0.22f;
        /// <summary>~2 images : l'œil atterrit, il ne glisse pas.</summary>
        public const float EyeTau = 0.03f;
        /// <summary>Endormie : paupières closes, les yeux reposent un peu vers le bas, comme chez qui dort.</summary>
        public const float EyeSleepPitch = 0.06f;

        public static readonly IReadOnlyDictionary<string, GazeAngles> EmotionBias = new Dictionary<string, GazeAngles>
        {
            ["embarrassed"] = new GazeAngles(0.08f, -0.08f), // en bas, ailleurs : elle détourne
            ["scared"] = new GazeAngles(0.1f, 0.06f),
            ["jealous"] = new GazeAngles(0.05f, -0.1f), // regard en coin
            ["anxious"] = new GazeAngles(0.06f, 0.04f),
            ["lonely"] = new GazeAngles(0.06f, 0f),
            ["sad"] = new GazeAngles(0.08f, 0f),
            ["melancholic"] = new GazeAngles(0.07f, -0.02f),
            ["bored"] = new GazeAngles(0f, 0.1f), // regarde ailleurs
            ["thinking"] = new GazeAngles(-0.06f, 0.08f), // en haut et sur le côté
            ["curious"] = new GazeAngles(-0.04f, 0.06f),
            ["confused"] = new GazeAngles(-0.02f, -0.05f),
            ["dreamy"] = new GazeAngles(-0.05f, 0f), // en haut, vague
            ["proud"] = new GazeAngles(-0.02f, 0f),
        };

        GazeAngles _current;

        /// <summary>Les angles appliqués (lissés), en radians sémantiques.</summary>
        public GazeAngles Current => _current;

        /// <param name="viewer">Direction de l'interlocuteur dans le repère des yeux (null : personne).</param>
        public GazeAngles Step(float dt, GazeIntent intent, string emotion, float intensity, bool asleep, GazeAngles? viewer)
        {
            GazeAngles t;
            if (asleep)
                t = new GazeAngles(EyeSleepPitch, 0f);
            else
            {
                var bias = emotion != null && EmotionBias.TryGetValue(emotion, out var b) ? b : GazeAngles.Zero;
                // Un « thinking » léger bouge à peine le regard, un fort détourne nettement.
                float biasScale = 0.3f + Emotions.Clamp01(intensity) * 0.7f;
                t = new GazeAngles(bias.Pitch * biasScale, bias.Yaw * biasScale);
                if (intent.Contact > 0f && viewer.HasValue)
                {
                    // Seulement ce que l'œil atteint : un interlocuteur au-delà du coin de l'œil est regardé aussi
                    // loin que l'œil va. Le reste est le travail de la tête (IK du corps).
                    t.Pitch += intent.Contact * Emotions.Clamp(viewer.Value.Pitch, -EyeMaxPitch, EyeMaxPitch);
                    t.Yaw += intent.Contact * Emotions.Clamp(viewer.Value.Yaw, -EyeMaxYaw, EyeMaxYaw);
                }
                t.Pitch += intent.Offset.Pitch + intent.Saccade.Pitch;
                t.Yaw += intent.Offset.Yaw + intent.Saccade.Yaw;
                t.Pitch = Emotions.Clamp(t.Pitch, -EyeMaxPitch, EyeMaxPitch);
                t.Yaw = Emotions.Clamp(t.Yaw, -EyeMaxYaw, EyeMaxYaw);
            }
            float k = 1f - MathF.Exp(-Math.Max(0f, dt) / EyeTau);
            _current.Pitch += (t.Pitch - _current.Pitch) * k;
            _current.Yaw += (t.Yaw - _current.Yaw) * k;
            return _current;
        }

        /// <summary>
        /// Entrée à donner à une courbe VRM linéaire (<c>CurveMapper</c> : <c>sortie = clamp01(entrée / X) · Y</c>)
        /// pour que l'œil tourne réellement de <paramref name="desiredDegrees"/>. La courbe de l'auteur reste la
        /// borne : au-delà de <c>Y</c> degrés, l'œil s'arrête à <c>Y</c>.
        /// </summary>
        public static float InverseCurve(float desiredDegrees, float xRange, float yRange)
        {
            if (!(yRange > 0f) || !(xRange > 0f))
                return 0f;
            return Emotions.Clamp01(Math.Abs(desiredDegrees) / yRange) * xRange * Math.Sign(desiredDegrees);
        }
    }
}
