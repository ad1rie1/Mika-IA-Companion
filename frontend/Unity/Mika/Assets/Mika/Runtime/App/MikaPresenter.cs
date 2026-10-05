using System.Collections.Generic;
using System.Linq;
using Mika.Avatar;
using Mika.Chat;
using Mika.Player;
using Mika.World.Engine;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.App
{
    /// <summary>
    /// Ce que la conversation fait au corps de Mika : sa parole anime ses lèvres et son visage, sa dérive d'humeur
    /// colore son visage entre deux répliques, son sommeil ferme ses yeux, et sa tête suit son attention (vers la
    /// personne qui lui parle, ailleurs quand elle réfléchit ou rêvasse). Équivalent du <c>SpeechPresenter</c> du
    /// client web, avec la même règle : la balise <c>[EMOTION:]</c> d'une réplique est la vérité du tour. Elle finit
    /// sa phrase : une réplique qui arrive pendant qu'elle parle attend la fin de la précédente, et son visage, ses
    /// lèvres et son sous-titre ne viennent qu'à son début réel.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Présentation de Mika")]
    public sealed class MikaPresenter : MonoBehaviour
    {
        /// <summary>Le temps qu'elle marque entre deux répliques de la file avant d'enchaîner (le battement du
        /// <c>SPEECH_SETTLE_S</c> web : elle reste dans sa posture de parole).</summary>
        public const float PauseBetweenRepliesSeconds = 0.4f;

        public MikaApp app;
        public WorldStage stage;
        public PlayerController player;
        public string mikaActor = "mika";

        /// <summary>Au-delà (m/s), la joueuse se déplace — elle marche à 1,6 m/s : un mouvement net, pas un
        /// tremblement du contrôleur.</summary>
        const float ViewerMovedSpeed = 0.5f;

        /// <summary>Une réplique commence pour de vrai — à sa réception, ou à la fin de celle qu'elle attendait :
        /// le sous-titre la suit.</summary>
        public event System.Action<SpeechFrame> UtteranceStarted;

        // Les répliques reçues pendant qu'elle parle, dans l'ordre : chacune attend la fin de la précédente.
        readonly Queue<SpeechFrame> _pending = new Queue<SpeechFrame>();
        // Quand la suivante peut commencer (la fin de la précédente plus le battement), et depuis quand elle parle.
        float _nextAt;
        float _speakingSince;
        // La dérive reçue pendant qu'une réplique attend son tour : confiée au visage au début de la dernière de la
        // file (il la retient jusqu'à sa fin) plutôt que montrée dans le battement puis écrasée par la suivante.
        EmotionUpdateFrame _driftAfterQueue;

        ActorBody _body;
        MikaFace _face;
        BodyExpression _expression;
        BodyActivity _activity;
        IntentPlayer _intents;
        // Le dernier état intérieur reçu : il peut arriver avant que la scène ait fait apparaître le corps.
        string _sleepPhase;
        float? _energy;
        // La phase que montrent son visage et ses gestes : « awake » tant qu'elle marche encore vers son lit.
        string _shownPhase;

        void OnEnable()
        {
            if (app == null) return;
            app.MikaSpoke += OnSpeech;
            app.MikaMoodDrifted += OnDrift;
            app.InnerStateChanged += OnInnerState;
            app.MessageAcknowledged += OnAck;
            if (app.hud != null) UtteranceStarted += app.hud.ShowSubtitle;
        }

        void OnDisable()
        {
            _pending.Clear();
            _driftAfterQueue = null;
            if (app == null) return;
            app.MikaSpoke -= OnSpeech;
            app.MikaMoodDrifted -= OnDrift;
            app.InnerStateChanged -= OnInnerState;
            app.MessageAcknowledged -= OnAck;
            if (app.hud != null) UtteranceStarted -= app.hud.ShowSubtitle;
        }

        /// <summary>Le corps de Mika peut être recréé (une nouvelle définition) : on se relie à celui qui est là.</summary>
        bool Bind()
        {
            var body = stage != null ? stage.Actor(mikaActor) : null;
            if (body == _body && (_body == null || _face != null || body.GetComponentInChildren<MikaFace>() == null))
                return _body != null;
            _body = body;
            _face = body != null ? body.GetComponentInChildren<MikaFace>() : null;
            _expression = body != null ? body.GetComponent<BodyExpression>() : null;
            _activity = body != null ? body.GetComponent<BodyActivity>() : null;
            _intents = body != null ? body.GetComponent<IntentPlayer>() : null;
            _shownPhase = null;
            if (_activity != null && player != null && player.view != null) _activity.companion = player.view.transform;
            if (_face != null)
            {
                _face.SpeechEnded += () =>
                {
                    // Une réplique adressée attend son tour : le corps garde sa posture de parole le temps du
                    // battement, sans repasser par l'attente.
                    _nextAt = Time.time + PauseBetweenRepliesSeconds;
                    if (_body != null && (_pending.Count == 0 || _pending.Peek().Inner)) _body.SetTalking(false);
                };
                // Un soupir, un rire dans la voix : le corps les joue au bon moment.
                _face.ProsodicCue += cue =>
                {
                    if (_expression != null) _expression.Cue(cue);
                };
                if (player != null && player.view != null) _face.LookAt(player.view.transform);
            }
            ApplyInnerState();
            return _body != null;
        }

        void Update()
        {
            if (!Bind()) return;
            ShowSleep();
            if (_face == null) return;
            NextUtterance();
            _face.Walking = _body.Speed > 0.15f;
            // Seule et occupée, elle s'absorbe dans ce qu'elle fait ; la joueuse qui se déplace lui fait lever les yeux.
            _face.Occupied = _activity != null && _activity.Activity != null;
            _face.ViewerMoved = player != null && HorizontalSpeed(player.Velocity) > ViewerMovedSpeed;
            // La tête suit l'attention : vers la personne quand elle la regarde, devant elle sinon (les yeux, eux,
            // vont où l'attention les mène — MikaFace s'en charge).
            var lookingAtYou = _face.Attention == AttentionState.Contact || _face.Attention == AttentionState.Avert;
            _body.LookAt(lookingAtYou && player != null && player.view != null ? player.view.transform.position : (Vector3?)null);
        }

        void OnSpeech(SpeechFrame s)
        {
            if (!Bind())
            {
                // Pas encore de corps : rien à attendre, le sous-titre se montre tout de suite.
                UtteranceStarted?.Invoke(s);
                return;
            }
            if (_face == null)
            {
                // Pas de visage (silhouette) : le corps parle quand même, le temps de la phrase.
                if (!string.IsNullOrEmpty(s.Text) && !s.Inner) _body.SetTalking(true);
                UtteranceStarted?.Invoke(s);
                return;
            }
            _face.SetReplyPending(false);
            // Elle finit sa phrase : une réplique qui arrive pendant qu'elle parle (ou dans le battement qui suit)
            // attend son tour. Une trame vide ou muette (« speak: false ») n'a rien à articuler : elle passe.
            var busy = _face.IsSpeaking || _pending.Count > 0 || Time.time < _nextAt;
            if (s.Speak && !string.IsNullOrEmpty(s.Text) && _face.IsReady && busy)
            {
                _pending.Enqueue(s);
                return;
            }
            Begin(s);
        }

        /// <summary>Le début réel d'une réplique : son émotion, son geste, sa voix intérieure, ses lèvres et son
        /// sous-titre.</summary>
        void Begin(SpeechFrame s)
        {
            // Elle répond à quelqu'un : elle se tourne vers lui (sa chaise pivote, son occupation attend).
            if (!s.Inner && _activity != null) _activity.Engage(14f);
            _face.ShowEmotion(s.Emotion, s.EmotionIntensity, Blend(s.EmotionBlend), ambient: false);
            Express(s.Emotion, s.EmotionIntensity, s.EmotionBlend, s.Inner, ambient: false);
            UtteranceStarted?.Invoke(s);
            if (string.IsNullOrEmpty(s.Text)) return;
            _face.InnerVoice = s.Inner;
            // « speak: false » : on montre le texte sans articuler (un autre écran parle, ou elle est muette ici).
            if (!s.Speak) return;
            var duration = _face.Speak(s.Text, s.VoiceProfile?.Rate ?? 1f);
            _speakingSince = Time.time;
            // Le corps a pu garder sa posture de parole depuis la réplique précédente : un murmure ou une réplique
            // sans rien à articuler la relâche.
            _body.SetTalking(duration > 0 && !s.Inner);
        }

        /// <summary>
        /// La réplique suivante de la file commence quand la précédente est finie et que le battement est passé —
        /// ou quand la précédente dépasse la soupape du visage : une parole dont la fin n'arrive jamais ne retient
        /// pas la file.
        /// </summary>
        void NextUtterance()
        {
            if (_pending.Count == 0) return;
            if (_face.IsSpeaking ? Time.time - _speakingSince < MikaFace.VoicedHoldMaxSeconds : Time.time < _nextAt)
                return;
            Begin(_pending.Dequeue());
            if (_pending.Count > 0 || _driftAfterQueue == null) return;
            // La dernière de la file a commencé : le visage retient la dérive jusqu'à sa fin.
            var drift = _driftAfterQueue;
            _driftAfterQueue = null;
            _face.ShowEmotion(drift.Emotion, drift.EmotionIntensity, Blend(drift.EmotionBlend), ambient: true);
        }

        void OnDrift(EmotionUpdateFrame u)
        {
            if (Bind() && _face != null)
            {
                // Une réplique attend son tour : la dérive ne s'intercale pas dans le battement entre deux.
                if (_pending.Count > 0) _driftAfterQueue = u;
                else _face.ShowEmotion(u.Emotion, u.EmotionIntensity, Blend(u.EmotionBlend), ambient: true);
            }
            if (_body != null) Express(u.Emotion, u.EmotionIntensity, u.EmotionBlend, inner: false, ambient: true);
        }

        void OnInnerState(InnerStateFrame s)
        {
            if (s.SleepPhase != null) _sleepPhase = s.SleepPhase;
            if (s.Energy.HasValue) _energy = s.Energy;
            if (Bind()) ApplyInnerState();
        }

        void ApplyInnerState()
        {
            if (_body == null) return;
            // Le corps reçoit le sommeil tout de suite : c'est lui qui ouvre la couette en s'allongeant.
            if (_sleepPhase != null) _body.SetAsleep(_sleepPhase != "awake");
            ShowSleep();
            if (_face == null) return;
            if (_energy.HasValue) _face.SetEnergy(_energy.Value);
        }

        /// <summary>
        /// Elle s'endort une fois couchée : tant que le réflexe du coucher la mène à son lit, ses yeux restent
        /// ouverts et ses gestes éveillés (ADR 0050) ; la phase reçue s'applique quand elle est allongée ou
        /// quand l'action s'achève.
        /// </summary>
        void ShowSleep()
        {
            if (_sleepPhase == null) return;
            var onHerWayToBed = _sleepPhase != "awake" && _intents != null && _intents.PlayingReflex
                                && _body.Posture != Posture.Lie;
            var phase = onHerWayToBed ? "awake" : _sleepPhase;
            if (phase == _shownPhase) return;
            _shownPhase = phase;
            if (_expression != null) _expression.SetAsleep(phase != "awake");
            if (_face != null) _face.SetSleepPhase(phase);
        }

        void OnAck(AckFrame a)
        {
            if (a.Status != "accepted" || !Bind()) return;
            if (_face != null) _face.SetReplyPending(true);
            if (_activity != null) _activity.Engage(16f);
        }

        /// <summary>Quand la joueuse écrit, Mika l'écoute (le regard se pose sur elle).</summary>
        public void NoteUserTyping()
        {
            if (!Bind()) return;
            if (_face != null) _face.NoteUserTyping();
            if (_activity != null) _activity.Engage(8f);
        }

        /// <summary>L'humeur du tour dans le corps : l'attente et le tempo qu'elle choisit, le geste qu'elle déclenche.</summary>
        void Express(string emotion, float intensity, List<BlendPart> blend, bool inner, bool ambient)
        {
            if (_expression == null) return;
            _expression.SetAffect(emotion, intensity, Emotions.ValenceOf(emotion), Emotions.ArousalOf(emotion));
            var parts = (blend ?? new List<BlendPart>()).OrderByDescending(p => p.Weight).ToList();
            var first = parts.Count > 0 ? parts[0].Weight : 0f;
            var second = parts.Count > 1 ? parts[1].Weight : 0f;
            _expression.React(emotion, intensity, first, second, inner, ambient);
        }

        static float HorizontalSpeed(Vector3 velocity) => new Vector2(velocity.x, velocity.z).magnitude;

        static IReadOnlyList<KeyValuePair<string, float>> Blend(List<BlendPart> parts) =>
            (parts ?? new List<BlendPart>())
                .OrderByDescending(p => p.Weight)
                .Select(p => new KeyValuePair<string, float>(p.Emotion, p.Weight))
                .ToList();
    }
}
