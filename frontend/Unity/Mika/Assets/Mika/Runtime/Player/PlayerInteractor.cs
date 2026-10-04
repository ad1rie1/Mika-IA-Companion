using System;
using System.Collections.Generic;
using Mika.Net;
using Mika.World.Engine;
using Mika.World.Model;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.Player
{
    /// <summary>Ce que la joueuse regarde : un objet, un acteur, ou rien.</summary>
    public readonly struct Focus
    {
        public readonly string ObjectId;
        public readonly string ActorId;
        public readonly string Label;
        public readonly Vector3 Point;

        public Focus(string objectId, string actorId, string label, Vector3 point)
        {
            ObjectId = objectId;
            ActorId = actorId;
            Label = label;
            Point = point;
        }

        public bool IsEmpty => ObjectId == null && ActorId == null;
    }

    /// <summary>
    /// Viser et agir : ce que la joueuse regarde (un rayon depuis l'œil), ce qu'elle peut en faire
    /// (<see cref="ActionMenu"/>), et l'envoi de la commande au noyau. Le résultat arrive par le monde (on ne
    /// montre rien avant) ; un refus revient en phrase, affichée telle quelle.
    /// </summary>
    [AddComponentMenu("Mika/Joueuse/Interactions")]
    public sealed class PlayerInteractor : MonoBehaviour
    {
        public PlayerController controller;
        [Tooltip("Portée du bras (m) : au-delà, on s'approche d'abord.")]
        public float reach = 2.6f;

        WorldSession _session;
        WorldStage _stage;
        Focus _focus;
        List<ActionOption> _options = new List<ActionOption>();

        public Focus Current => _focus;
        public IReadOnlyList<ActionOption> Options => _options;

        /// <summary>La cible a changé (le HUD met à jour son invite).</summary>
        public event Action<Focus, IReadOnlyList<ActionOption>> FocusChanged;
        /// <summary>Le menu complet est demandé (clic droit / F).</summary>
        public event Action<Focus, IReadOnlyList<ActionOption>> MenuRequested;
        /// <summary>Une phrase à montrer (un refus du noyau, un rappel).</summary>
        public event Action<string> Notice;

        public void Bind(WorldSession session, WorldStage stage)
        {
            _session = session;
            _stage = stage;
        }

        void Update()
        {
            if (_session == null || _stage == null || controller == null || controller.view == null) return;
            if (!_session.Mirror.Ready || _session.Actor == null) return;
            UpdateFocus();
            var inputs = controller.Inputs;
            if (controller.CursorFree) return;
            if (inputs.Interact.WasPressedThisFrame())
            {
                var primary = _options.Find(o => o.Primary) ?? (_options.Count > 0 ? _options[0] : null);
                if (primary != null) Execute(primary);
            }
            if (inputs.Menu.WasPressedThisFrame())
            {
                var options = _options.Count > 0 ? _options : ActionMenu.ForSelf(_session.Mirror, _session.Actor);
                MenuRequested?.Invoke(_focus, options);
            }
            if (inputs.Drop.WasPressedThisFrame())
            {
                var self = ActionMenu.ForSelf(_session.Mirror, _session.Actor);
                var drop = self.Find(o => o.Command is Act a && a.Action == "drop") ?? self.Find(o => o.Primary);
                if (drop != null) Execute(drop);
            }
        }

        void UpdateFocus()
        {
            var cam = controller.view.transform;
            Focus next = default;
            if (Physics.Raycast(cam.position, cam.forward, out var hit, reach, ~0, QueryTriggerInteraction.Collide))
            {
                var body = hit.collider.GetComponentInParent<ActorBody>();
                var obj = hit.collider.GetComponentInParent<WorldObject>();
                if (body != null && body.actorId != _session.Actor)
                    next = new Focus(null, body.actorId, LabelOfActor(body.actorId), hit.point);
                else if (obj != null && _session.Mirror.World?.Object(obj.id) != null)
                    next = new Focus(obj.id, null, LabelOfObject(obj.id), hit.point);
            }
            if (next.ObjectId == _focus.ObjectId && next.ActorId == _focus.ActorId && _seq == _session.Mirror.Seq)
                return;
            _focus = next;
            _seq = _session.Mirror.Seq;
            _options = next.ObjectId != null ? ActionMenu.ForObject(_session.Mirror, _session.Actor, next.ObjectId)
                : next.ActorId != null ? ActionMenu.ForActor(_session.Mirror, _session.Actor, next.ActorId)
                : new List<ActionOption>();
            FocusChanged?.Invoke(_focus, _options);
        }

        long _seq = -2;

        string LabelOfObject(string id)
        {
            var world = _session.Mirror.World;
            var def = world.Object(id);
            return def?.Label ?? world.Archetype(def?.Archetype)?.Label ?? id;
        }

        string LabelOfActor(string id)
        {
            var def = _session.Mirror.World?.Actor(id);
            if (def != null) return def.Label;
            return _session.Mirror.Visitors.TryGetValue(id, out var v) && !string.IsNullOrEmpty(v.Label) ? v.Label : id;
        }

        /// <summary>Envoie la commande d'une option ; un refus du noyau revient en <see cref="Notice"/>.</summary>
        public async void Execute(ActionOption option)
        {
            if (option?.Command == null || _session == null) return;
            if (option.Command is Act act) act.Expect = _session.Mirror.Seq;
            var result = await _session.Command(option.Command);
            if (result.Status == Status.Refused)
                Notice?.Invoke(string.IsNullOrEmpty(result.Message) ? $"Refusé ({WireJson.Name(result.Code ?? Refusal.Unknown)})" : result.Message);
        }
    }
}
