using System.Collections.Generic;
using Mika.Net;
using Mika.World.Engine;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.Player
{
    /// <summary>
    /// La joueuse dans le monde vu du noyau : elle y entre quand le noyau l'annonce (<c>presence</c>, au lieu
    /// <c>spawn</c>), sa pose continue est relayée aux autres écrans (jamais au journal), et ses arrivées — quand
    /// elle s'arrête près d'un lieu — sont dites au noyau (<c>moved</c>), qui seul les retient. Les poses des
    /// autres personnes arrivent ici et font marcher leur corps.
    /// </summary>
    [AddComponentMenu("Mika/Joueuse/Présence")]
    public sealed class PlayerPresence : MonoBehaviour
    {
        public PlayerController controller;
        [Tooltip("Poses par seconde (le protocole en accepte 20).")]
        public float poseRate = 15f;
        [Tooltip("Immobile depuis ce temps (s) : elle est arrivée quelque part.")]
        public float settleTime = 0.6f;

        WorldSession _session;
        WorldStage _stage;
        float _lastPose;
        Vector3 _lastSentPos;
        float _lastSentYaw;
        float _stillSince = -1;
        string _reportedPlace;
        bool _spawned;
        // Le noyau a annoncé son entrée depuis l'accueil : une annonce suivante est un retour après un silence.
        bool _entered;
        readonly Dictionary<string, RemoteBody> _remote = new Dictionary<string, RemoteBody>();

        sealed class RemoteBody
        {
            public Vector3 Target;
            public Quaternion Rotation;
            public float Received;
        }

        public void Bind(WorldSession session, WorldStage stage)
        {
            Unbind();
            _session = session;
            _stage = stage;
            session.Welcomed += _ =>
            {
                _spawned = false;
                _entered = false;
            };
            session.PoseReceived += OnPose;
            session.Mirror.PresenceChanged += OnPresence;
        }

        void OnDestroy() => Unbind();

        void Unbind()
        {
            if (_session == null) return;
            _session.PoseReceived -= OnPose;
            _session.Mirror.PresenceChanged -= OnPresence;
        }

        /// <summary>
        /// Le noyau la fait entrer : son corps va au lieu qu'il lui a donné (celui de la pièce où est Mika). Revenue
        /// après un silence, elle n'a pas bougé pour autant : elle redit seulement où elle est.
        /// </summary>
        void OnPresence(Presence p)
        {
            if (!p.Joined || _session == null || p.Actor != _session.Actor) return;
            if (_entered)
                _reportedPlace = null;
            else
                _spawned = false;
            _entered = true;
        }

        void Update()
        {
            if (_session == null || _stage == null || _session.State != LinkState.Online) return;
            var me = _session.Actor;
            if (me == null) return;
            _stage.localActor = me;
            SpawnOnce(me);
            SendPose();
            DetectArrival(me);
            FollowRemotes();
        }

        /// <summary>À l'entrée : le corps apparaît là où le noyau l'a fait entrer (lieu <c>spawn</c>).</summary>
        void SpawnOnce(string me)
        {
            if (_spawned) return;
            var state = _session.Mirror.Actor(me);
            var place = _stage.Place(state?.Place) ?? _stage.Place(_session.Mirror.World?.SpawnPlace()?.Id);
            if (place == null) return;
            controller.Teleport(place.Position, place.Rotation);
            _reportedPlace = place.Id;
            _spawned = true;
        }

        void SendPose()
        {
            var t = Time.unscaledTime;
            if (t - _lastPose < 1f / Mathf.Max(1f, poseRate)) return;
            var pos = controller.transform.position;
            var yaw = controller.transform.eulerAngles.y;
            if ((pos - _lastSentPos).sqrMagnitude < 0.0004f && Mathf.Abs(Mathf.DeltaAngle(yaw, _lastSentYaw)) < 2f && t - _lastPose < 1f)
                return;
            _lastPose = t;
            _lastSentPos = pos;
            _lastSentYaw = yaw;
            var room = _stage.RoomAt(pos);
            var local = room != null ? room.ToLocal(pos) : pos;
            var v = RoomSpace.ToVec3(local);
            var phi = RoomSpace.FacingOf(room != null ? Quaternion.Inverse(room.Root.rotation) * controller.transform.rotation : controller.transform.rotation);
            var anim = controller.Velocity.sqrMagnitude > 0.04f ? "walk" : "idle";
            _session.SendPose(v.X, v.Y, v.Z, phi, anim);
        }

        void DetectArrival(string me)
        {
            if (controller.Velocity.sqrMagnitude > 0.01f)
            {
                _stillSince = -1;
                return;
            }
            if (_stillSince < 0) _stillSince = Time.unscaledTime;
            if (Time.unscaledTime - _stillSince < settleTime) return;
            var place = _stage.NearestPlace(controller.transform.position);
            if (place == null || place.Id == _reportedPlace) return;
            _reportedPlace = place.Id;
            _ = _session.Command(new Moved { Room = place.Room.Id, Near = place.Id });
        }

        void OnPose(PoseOut pose)
        {
            if (pose.Actor == _session.Actor) return;
            var body = _stage.Actor(pose.Actor);
            if (body == null) return;
            var room = _stage.RoomAt(body.transform.position);
            var local = RoomSpace.ToUnity(pose.Pos);
            var world = room != null ? room.ToWorld(local) : local;
            var rot = (room != null ? room.Root.rotation : Quaternion.identity) * RoomSpace.Facing(pose.Yaw);
            if (!_remote.TryGetValue(pose.Actor, out var r))
                _remote[pose.Actor] = r = new RemoteBody();
            r.Target = world;
            r.Rotation = rot;
            r.Received = Time.unscaledTime;
        }

        void FollowRemotes()
        {
            foreach (var kv in _remote)
            {
                var body = _stage.Actor(kv.Key);
                if (body == null) continue;
                var k = 1f - Mathf.Exp(-Time.deltaTime * 10f);
                body.transform.position = Vector3.Lerp(body.transform.position, kv.Value.Target, k);
                body.transform.rotation = Quaternion.Slerp(body.transform.rotation, kv.Value.Rotation, k);
            }
        }
    }
}
