using System;
using System.Collections;
using System.Linq;
using Mika.World.Model;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// Ce qu'un hôte dit au noyau pendant qu'il joue une action. Un écran qui n'est pas l'hôte joue la même
    /// action sans rien dire (<see cref="Active"/> faux).
    /// </summary>
    public interface IIntentReporter
    {
        bool Active { get; }
        void Progress(string intent, int step);
        void Finished(string intent, Outcome outcome, Refusal? reason, ActorMoved at);
    }

    /// <summary>
    /// Joue une action décidée par le noyau sur le corps d'un acteur, pas à pas, au rythme de son calendrier
    /// nominal : se lever, marcher, s'asseoir, prendre, poser, donner, allumer… Un écran qui arrive en cours de
    /// route reprend l'action là où le calendrier dit qu'elle en est (les pas passés sont posés, pas rejoués).
    /// </summary>
    /// <remarks>
    /// Le résultat fait foi quand il arrive (<c>intent_end</c>) : ce que ce joueur a montré entre-temps n'est
    /// qu'un rendu, et la scène se recale sur l'état reçu même s'il contredit l'animation.
    /// </remarks>
    [DisallowMultipleComponent]
    public sealed class IntentPlayer : MonoBehaviour
    {
        ActorBody _body;
        WorldStage _stage;
        Coroutine _run;
        Intent _intent;
        string _place;
        string _room;

        public string Current => _intent?.Id;

        public void Init(ActorBody body, WorldStage stage)
        {
            _body = body;
            _stage = stage;
        }

        /// <summary>Lance (ou reprend en cours de route) une action ; une action en cours est abandonnée.</summary>
        public void Play(Intent intent, KernelClock clock, IIntentReporter reporter)
        {
            Stop();
            _intent = intent;
            var actor = _stage.Mirror.Actor(intent.Actor);
            _place = actor?.Place;
            _room = actor?.Room;
            _run = StartCoroutine(Run(intent, clock, reporter));
        }

        /// <summary>Arrête de jouer (fin reçue, ou une autre action prend la place).</summary>
        public void Stop()
        {
            if (_run != null) StopCoroutine(_run);
            _run = null;
            _intent = null;
        }

        IEnumerator Run(Intent intent, KernelClock clock, IIntentReporter reporter)
        {
            var at = clock.Synced ? IntentTimeline.At(intent, clock.NowUs) : new IntentPoint(0, 0, intent.Steps.FirstOrDefault()?.DurationUs / 1e6 ?? 0);
            // Les pas déjà passés : poser leur résultat sans les jouer.
            for (var i = 0; i < at.Step && i < intent.Steps.Count; i++)
                SkipStep(intent.Steps[i]);

            var failed = false;
            Refusal? reason = null;
            for (var i = at.Step; i < intent.Steps.Count && !failed; i++)
            {
                var step = intent.Steps[i];
                var duration = i == at.Step ? (float)at.RemainingS : step.DurationUs / 1e6f;
                if (reporter != null && reporter.Active && i > 0)
                    reporter.Progress(intent.Id, i);
                var ok = true;
                yield return PlayStep(intent, step, Mathf.Max(0.15f, duration), r => ok = r);
                if (!ok)
                {
                    failed = true;
                    reason = Refusal.Unreachable;
                }
            }

            if (reporter != null && reporter.Active && _intent == intent)
            {
                if (failed)
                    reporter.Finished(intent.Id, Outcome.Failed, reason, WhereAmI(intent.Actor));
                else
                    reporter.Finished(intent.Id, Outcome.Done, null, null);
            }
            _run = null;
        }

        IEnumerator PlayStep(Intent intent, Step step, float duration, Action<bool> result)
        {
            switch (step.Kind)
            {
                case StepKind.Posture:
                {
                    var place = _stage.Place(_place);
                    yield return _body.ChangePosture(step.Posture ?? Posture.Stand, place, duration);
                    result(true);
                    break;
                }
                case StepKind.Walk:
                {
                    var place = _stage.Place(step.ToPlace);
                    if (place == null)
                    {
                        Debug.LogWarning($"[Mika] {intent.Actor} : lieu inconnu de la scène « {step.ToPlace} » — saut direct");
                        result(true);
                        break;
                    }
                    var arrived = true;
                    yield return _body.WalkTo(place.Position, place.Rotation, duration, a => arrived = a);
                    if (arrived)
                    {
                        _place = step.ToPlace;
                        _room = step.ToRoom ?? place.Room?.Id;
                    }
                    result(arrived);
                    break;
                }
                case StepKind.Act:
                    yield return PlayAct(step, duration);
                    result(true);
                    break;
                default:
                    yield return new WaitForSeconds(duration);
                    result(true);
                    break;
            }
        }

        IEnumerator PlayAct(Step step, float duration)
        {
            var obj = _stage.Object(step.Object);
            switch (step.Action)
            {
                case "take":
                    if (obj == null) break;
                    yield return _body.Reach(obj.GripPoint, duration, () => _body.Hold(obj, Hand.Right));
                    break;
                case "put":
                {
                    if (obj == null) break;
                    var target = _stage.TargetPoint(step.Target);
                    yield return _body.Reach(target ?? obj.transform.position, duration, () =>
                    {
                        _body.Release(obj);
                        if (step.Target != null) _stage.PlaceObject(obj, step.Target, instant: false);
                    });
                    break;
                }
                case "drop":
                    if (obj == null) break;
                    _body.Release(obj);
                    obj.SetPhysics(ObjectPhysics.Free);
                    yield return new WaitForSeconds(duration);
                    break;
                case "give":
                {
                    if (obj == null) break;
                    var other = _stage.Actor(step.TargetActor);
                    var hand = other != null ? other.Head.position + Vector3.down * 0.45f + (transform.position - other.transform.position).normalized * 0.35f : transform.position + transform.forward * 0.5f + Vector3.up;
                    yield return _body.Reach(hand, duration, () =>
                    {
                        _body.Release(obj);
                        if (other != null) other.Hold(obj, Hand.Right);
                    });
                    break;
                }
                case "sit":
                case "lie":
                case "stand":
                    yield return _body.ChangePosture(step.Action == "sit" ? Posture.Sit : step.Action == "lie" ? Posture.Lie : Posture.Stand, _stage.Place(_place), duration);
                    break;
                default:
                {
                    // Une affordance (allumer, arroser, lire…) : la main vers l'objet s'il est à portée, l'animation déclarée.
                    var affordance = _stage.Affordance(step.Object, step.Action);
                    if (!string.IsNullOrEmpty(affordance?.Animation))
                        _body.PlayGesture(affordance.Animation);
                    if (obj != null && !_body.IsHolding(obj) && affordance?.Effect == Effect.State)
                        yield return _body.Reach(obj.GripPoint, Mathf.Min(duration, 1.2f), null);
                    var rest = duration - Mathf.Min(duration, 1.2f);
                    if (rest > 0) yield return new WaitForSeconds(rest);
                    break;
                }
            }
        }

        /// <summary>Le résultat d'un pas sans le jouer (un écran qui arrive en route).</summary>
        void SkipStep(Step step)
        {
            switch (step.Kind)
            {
                case StepKind.Walk:
                    _place = step.ToPlace;
                    _room = step.ToRoom;
                    var place = _stage.Place(_place);
                    if (place != null) _body.Snap(place.Position, place.Rotation, Posture.Stand);
                    break;
                case StepKind.Posture:
                    var p = _stage.Place(_place);
                    if (p != null) _body.Snap(p.Position, p.Rotation, step.Posture ?? Posture.Stand, p);
                    break;
                case StepKind.Act when step.Action == "take":
                    var o = _stage.Object(step.Object);
                    if (o != null) _body.Hold(o, Hand.Right);
                    break;
            }
        }

        /// <summary>Où est vraiment l'acteur (pour un échec) : sa pièce, le lieu le plus proche, sa posture.</summary>
        ActorMoved WhereAmI(string actor)
        {
            var nearest = _stage.NearestPlace(_body.transform.position, _room);
            return new ActorMoved
            {
                Actor = actor,
                Room = nearest?.Room?.Id ?? _room,
                Place = nearest?.Id,
                Posture = _body.Posture,
            };
        }
    }
}
