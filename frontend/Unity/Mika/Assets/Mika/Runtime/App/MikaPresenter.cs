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
    /// client web, avec la même règle : la balise <c>[EMOTION:]</c> d'une réplique est la vérité du tour.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Présentation de Mika")]
    public sealed class MikaPresenter : MonoBehaviour
    {
        public MikaApp app;
        public WorldStage stage;
        public PlayerController player;
        public string mikaActor = "mika";

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
        }

        void OnDisable()
        {
            if (app == null) return;
            app.MikaSpoke -= OnSpeech;
            app.MikaMoodDrifted -= OnDrift;
            app.InnerStateChanged -= OnInnerState;
            app.MessageAcknowledged -= OnAck;
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
                    if (_body != null) _body.SetTalking(false);
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
            _face.Walking = _body.Speed > 0.15f;
            // La tête suit l'attention : vers la personne quand elle la regarde, devant elle sinon (les yeux, eux,
            // vont où l'attention les mène — MikaFace s'en charge).
            var lookingAtYou = _face.Attention == AttentionState.Contact || _face.Attention == AttentionState.Avert;
            _body.LookAt(lookingAtYou && player != null && player.view != null ? player.view.transform.position : (Vector3?)null);
        }

        void OnSpeech(SpeechFrame s)
        {
            if (!Bind()) return;
            if (_face == null)
            {
                // Pas de visage (silhouette) : le corps parle quand même, le temps de la phrase.
                if (!string.IsNullOrEmpty(s.Text) && !s.Inner) _body.SetTalking(true);
                return;
            }
            _face.SetReplyPending(false);
            // Elle répond à quelqu'un : elle se tourne vers lui (sa chaise pivote, son occupation attend).
            if (!s.Inner && _activity != null) _activity.Engage(14f);
            _face.ShowEmotion(s.Emotion, s.EmotionIntensity, Blend(s.EmotionBlend), ambient: false);
            Express(s.Emotion, s.EmotionIntensity, s.EmotionBlend, s.Inner, ambient: false);
            if (string.IsNullOrEmpty(s.Text)) return;
            _face.InnerVoice = s.Inner;
            // « speak: false » : on montre le texte sans articuler (un autre écran parle, ou elle est muette ici).
            if (!s.Speak) return;
            var duration = _face.Speak(s.Text, s.VoiceProfile?.Rate ?? 1f);
            if (duration > 0 && !s.Inner) _body.SetTalking(true);
        }

        void OnDrift(EmotionUpdateFrame u)
        {
            if (Bind() && _face != null)
                _face.ShowEmotion(u.Emotion, u.EmotionIntensity, Blend(u.EmotionBlend), ambient: true);
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

        static IReadOnlyList<KeyValuePair<string, float>> Blend(List<BlendPart> parts) =>
            (parts ?? new List<BlendPart>())
                .OrderByDescending(p => p.Weight)
                .Select(p => new KeyValuePair<string, float>(p.Emotion, p.Weight))
                .ToList();
    }
}
