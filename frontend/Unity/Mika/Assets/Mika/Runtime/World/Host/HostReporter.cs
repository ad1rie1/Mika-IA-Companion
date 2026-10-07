using System.Collections.Generic;
using System.Linq;
using Mika.Net;
using Mika.World.Model;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// Ce que l'hôte dit au noyau : où en est une action, qu'elle est finie ou qu'elle a échoué (et où est
    /// vraiment l'acteur), ce qui manque pour montrer le monde, et ce que la physique a fait d'un objet laissé
    /// libre. Il ne constate que ce qui change l'état discret (un objet qui s'arrête près d'un autre lieu),
    /// jamais une trajectoire.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Monde/Hôte (constats)")]
    public sealed class HostReporter : MonoBehaviour, IIntentReporter
    {
        public WorldStage stage;
        [Tooltip("Un objet libre est tenu pour posé après ce temps immobile (s).")]
        public float settleAfter = 0.8f;

        WorldSession _session;
        readonly Dictionary<WorldObject, float> _restingSince = new Dictionary<WorldObject, float>();
        long _loadedRev = -1;
        bool _builtHooked;
        bool _settledUnsupported;

        public bool Active => _session != null && _session.IsHost;

        public void Bind(WorldSession session, WorldStage worldStage)
        {
            _session = session;
            if (stage != worldStage || !_builtHooked)
            {
                stage = worldStage;
                stage.Built += _ => _loadedRev = -1;
                _builtHooked = true;
            }
            session.HostChanged += host =>
            {
                if (!host) return;
                _loadedRev = -1;
                _settledUnsupported = false; // un nouveau bail, peut-être un autre noyau : il peut le servir
            };
        }

        public void Progress(string intent, int step)
        {
            if (!Active) return;
            _ = _session.Command(new Report { ReportValue = new Progress { Intent = intent, Step = step } });
        }

        public async void Finished(string intent, Outcome outcome, Refusal? reason, ActorMoved at)
        {
            if (!Active) return;
            var result = await _session.Command(new Report
            {
                ReportValue = new Finished { Intent = intent, Outcome = outcome, Reason = reason, At = at },
            });
            if (result.Status == Status.Refused && result.Code != Refusal.Unknown)
                Debug.LogWarning($"[Mika] le noyau refuse la fin de {intent} : {result.Code} — {result.Message}");
        }

        void Update()
        {
            if (!Active || stage == null || stage.Mirror?.World == null) return;
            ReportLoaded();
            WatchFreeObjects();
        }

        void ReportLoaded()
        {
            var rev = stage.Mirror.World.Rev;
            if (_loadedRev == rev) return;
            _loadedRev = rev;
            _ = _session.Command(new Report
            {
                ReportValue = new Loaded
                {
                    Rev = rev,
                    MissingAssets = stage.MissingAssets.OrderBy(x => x).ToList(),
                    MissingAnchors = stage.MissingAnchors.OrderBy(x => x).ToList(),
                },
            });
        }

        /// <summary>Un objet libre (tombé, poussé) qui s'arrête près d'un autre lieu : le constater.</summary>
        void WatchFreeObjects()
        {
            if (_settledUnsupported) return;
            foreach (var kv in stage.Objects)
            {
                var view = kv.Value;
                if (view == null || view.Physics != ObjectPhysics.Free || view.Body == null) continue;
                if (!view.Body.IsSleeping() && view.Body.linearVelocity.sqrMagnitude > 0.0004f)
                {
                    _restingSince.Remove(view);
                    continue;
                }
                if (!_restingSince.TryGetValue(view, out var since))
                {
                    _restingSince[view] = Time.time;
                    continue;
                }
                if (Time.time - since < settleAfter) continue;
                _restingSince[view] = float.MaxValue; // une seule fois par repos
                var state = stage.Mirror.Object(kv.Key);
                var known = state?.Location as InRoom;
                var place = stage.NearestPlace(view.transform.position, known?.Room);
                if (place == null || (known != null && known.Near == place.Id)) continue;
                ReportSettled(kv.Key, new InRoom { Room = place.Room.Id, Near = place.Id });
            }
        }

        /// <summary>
        /// Le constat d'un objet posé, et ce qu'en dit le noyau. Tant qu'il ne sert pas <c>settled</c>
        /// (<c>unsupported</c>, protocole-monde.md), l'objet reste pour lui où il était : le dire une fois, et ne
        /// plus constater jusqu'au prochain bail.
        /// </summary>
        async void ReportSettled(string objectId, InRoom to)
        {
            var result = await _session.Command(new Report { ReportValue = new Settled { Object = objectId, To = to } });
            if (result.Status != Status.Refused) return;
            if (result.Code == Refusal.Unsupported)
            {
                if (_settledUnsupported) return;
                _settledUnsupported = true;
                Debug.LogWarning($"[Mika] ce noyau ne sert pas encore « settled » : {objectId} reste pour lui où il était — {result.Message}");
                return;
            }
            Debug.LogWarning($"[Mika] le noyau refuse le constat de {objectId} : {result.Code} — {result.Message}");
        }
    }
}
