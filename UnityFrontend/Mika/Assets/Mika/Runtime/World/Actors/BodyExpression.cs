using System.Collections.Generic;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// Ce que l'humeur fait au corps entre deux actions : quelle attente elle prend (et combien de temps),
    /// quelle manière de parler, à quel tempo, quel geste une émotion déclenche, et la « vie » de fond (souffle,
    /// micro-mouvements) qui baisse quand elle dort. Portage du client web (manifeste d'animations, affect.ts,
    /// gestures.ts) : jamais deux fois la même boucle à l'identique, jamais une attente plaquée sur une humeur
    /// qui la contredit.
    /// </summary>
    /// <remarks>
    /// Le corps (<see cref="ActorBody"/>) fait les actions ; ce composant ne touche qu'aux paramètres d'humeur du
    /// contrôleur (<see cref="BodyAnim"/>). Il ne connaît pas les émotions par leur visage : la valence et
    /// l'activation lui sont données (le visage les tient), le nom sert aux gestes.
    /// </remarks>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Monde/Expression du corps")]
    public sealed class BodyExpression : MonoBehaviour
    {
        public BodyClipSet clips;

        ActorBody _body;
        Animator _animator;
        int _lifeLayer = -1;

        string _emotion = "neutral";
        float _intensity, _valence, _arousal;
        bool _asleep;
        string _posture;            // une attente que l'émotion impose (idle_sad…), tenue jusqu'à la réplique suivante
        int _idle = -1, _talk = -1;
        float _idleUntil, _talkUntil;
        float _tempo = 1f;
        double _lastOneShot = double.MinValue;

        public string Posture => _posture;

        static readonly int WalkBlend = Animator.StringToHash("WalkBlend");

        public void Bind(ActorBody body, BodyClipSet set)
        {
            _body = body;
            clips = set;
            _animator = body.animator;
            _lifeLayer = _animator != null && _animator.runtimeAnimatorController != null ? _animator.GetLayerIndex(BodyAnim.LifeLayer) : -1;
            _idle = -1;
            _talk = -1;
        }

        /// <summary>L'humeur du moment (émotion, intensité, et sa valence/activation).</summary>
        public void SetAffect(string emotion, float intensity, float valence, float arousal)
        {
            _emotion = string.IsNullOrEmpty(emotion) ? "neutral" : emotion;
            _intensity = Mathf.Clamp01(intensity);
            _valence = valence;
            _arousal = arousal;
        }

        public void SetAsleep(bool asleep) => _asleep = asleep;

        /// <summary>
        /// Une réplique (ou une dérive d'humeur, <paramref name="ambient"/>) : un geste, une posture d'attente, ou
        /// rien — selon <see cref="GestureRules"/>.
        /// </summary>
        public GestureDecision React(string emotion, float intensity, float firstWeight, float secondWeight, bool inner, bool ambient)
        {
            var d = GestureRules.Decide(emotion, intensity, firstWeight, secondWeight, inner, _asleep, ambient,
                Time.timeAsDouble, _lastOneShot, _posture);
            switch (d.Kind)
            {
                case GestureKind.OneShot when clips == null || clips.HasGesture(d.Target):
                    _lastOneShot = Time.timeAsDouble;
                    _body?.PlayGesture(d.Target);
                    break;
                case GestureKind.IdleVariant:
                    if (_posture != d.Target)
                    {
                        _posture = d.Target;
                        _idleUntil = 0; // changer tout de suite
                    }
                    break;
                case GestureKind.None when !ambient || d.Reason == "below_threshold":
                    // Une réplique qui n'appelle aucune posture relâche celle d'avant ; une dérive retombée aussi.
                    if (_posture != null && (d.Reason == "below_threshold" || d.Reason == "unmapped"))
                    {
                        _posture = null;
                        _idleUntil = 0;
                    }
                    break;
            }
            return d;
        }

        /// <summary>Un repère de la voix ([SIGH], [LAUGH]) : un geste au bon moment, même pendant le délai.</summary>
        public void Cue(string cue)
        {
            var g = GestureRules.CueGesture(cue);
            if (g == null || _asleep || (clips != null && !clips.HasGesture(g))) return;
            _body?.PlayGesture(g);
        }

        void Update()
        {
            if (_animator == null || _animator.runtimeAnimatorController == null || clips == null) return;
            var now = Time.time;
            var target = Mathf.Clamp(GestureRules.Tempo(_arousal, _intensity), GestureRules.TempoMin, GestureRules.TempoMax);
            // Le tempo glisse : un changement d'humeur ne fait pas sauter le pas.
            _tempo = Mathf.MoveTowards(_tempo, target, Time.deltaTime * 0.2f);
            _animator.SetFloat(BodyAnim.Tempo, _tempo);
            var walk = _body != null ? _body.StepSpeed : 0f;
            var scale = _animator.humanScale > 0f ? _animator.humanScale : 1f;
            if (clips.walkNorm > 0f && clips.walkSlowNorm > 0f)
            {
                // Marche capturée : lente et normale mélangées selon la vitesse, la cadence ajustée au reste (pieds collés).
                var v = walk / scale;
                var blend = WalkMix(clips, v, out var naturalNorm);
                var natural = naturalNorm * scale;
                _animator.SetFloat(WalkBlend, blend);
                _animator.SetFloat(BodyAnim.WalkPlayback, Mathf.Clamp(walk / Mathf.Max(0.2f, natural), 0.5f, 1.6f));
            }
            else
            {
                _animator.SetFloat(BodyAnim.WalkPlayback, Mathf.Clamp(walk / Mathf.Max(0.3f, clips.walkClipSpeed), 0.55f, 1.6f));
            }
            if (_lifeLayer >= 0) _animator.SetLayerWeight(_lifeLayer, _asleep ? 0.35f : 1f);

            if (_idle < 0 || now >= _idleUntil) PickIdle(now);
            var talking = _animator.GetBool(BodyAnim.Talking);
            if (talking && (_talk < 0 || now >= _talkUntil)) PickTalk(now);
        }

        /// <summary>
        /// Le mélange marche lente → normale pour une vitesse <paramref name="v"/> (tailles/s), et la vitesse que ce
        /// mélange donne à lecture normale. Le mélange synchronise les deux cycles sur une durée moyenne : sa vitesse
        /// est la foulée moyenne sur la durée moyenne, pas la moyenne des vitesses.
        /// </summary>
        public static float WalkMix(BodyClipSet clips, float v, out float natural)
        {
            float v0 = clips.walkSlowNorm, v1 = clips.walkNorm;
            float t0 = clips.walkSlowSeconds, t1 = clips.walkSeconds;
            if (t0 <= 0f || t1 <= 0f)
            {
                var linear = Mathf.InverseLerp(v0, v1, v);
                natural = Mathf.Lerp(v0, v1, linear);
                return linear;
            }
            float d0 = v0 * t0, d1 = v1 * t1;
            // v · lerp(t0, t1, b) = lerp(d0, d1, b)
            var den = (d1 - d0) - v * (t1 - t0);
            var blend = Mathf.Abs(den) > 1e-5f ? Mathf.Clamp01((v * t0 - d0) / den) : (v >= v1 ? 1f : 0f);
            natural = Mathf.Lerp(d0, d1, blend) / Mathf.Lerp(t0, t1, blend);
            return blend;
        }

        void PickIdle(float now)
        {
            BodyVariant chosen = null;
            if (_posture != null) chosen = clips.Idle(_posture);
            if (chosen == null) chosen = Draw(clips.idles, _idle);
            if (chosen == null) return;
            _idle = chosen.index;
            var hold = Random.Range(chosen.hold.x, chosen.hold.y) * GestureRules.HoldScale(_arousal, _intensity);
            _idleUntil = now + Mathf.Max(2f, hold);
            _animator.SetInteger(BodyAnim.IdleVariant, _idle);
        }

        void PickTalk(float now)
        {
            var chosen = Draw(clips.talks, _talk);
            if (chosen == null) return;
            _talk = chosen.index;
            _talkUntil = now + Random.Range(chosen.hold.x, chosen.hold.y) * GestureRules.HoldScale(_arousal, _intensity);
            _animator.SetInteger(BodyAnim.TalkVariant, _talk);
        }

        /// <summary>Un tirage pondéré par l'humeur, en évitant de reprendre la même (quand il y a le choix).</summary>
        BodyVariant Draw(List<BodyVariant> pool, int current)
        {
            var total = 0f;
            var weights = new float[pool.Count];
            for (var i = 0; i < pool.Count; i++)
            {
                var v = pool[i];
                if (v.weight <= 0 || (v.index == current && pool.Count > 1)) continue;
                weights[i] = v.weight * GestureRules.Affinity(v, _valence, _arousal, _intensity);
                total += weights[i];
            }
            if (total <= 0) return pool.Find(v => v.index == current) ?? (pool.Count > 0 ? pool[0] : null);
            var r = Random.value * total;
            for (var i = 0; i < pool.Count; i++)
            {
                r -= weights[i];
                if (weights[i] > 0 && r <= 0) return pool[i];
            }
            return pool[pool.Count - 1];
        }
    }
}
