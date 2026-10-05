using System;
using System.Collections.Generic;
using System.Linq;
using Mika.World.Protocol;

namespace Mika.World.Model
{
    /// <summary>Ce qu'une trame a fait au miroir.</summary>
    public enum FrameEffect
    {
        /// <summary>Appliquée.</summary>
        Applied,
        /// <summary>Déjà vue (seq inférieur ou égal au dernier appliqué) : ignorée.</summary>
        Duplicate,
        /// <summary>Pas une trame d'état (accusé, bail, pong, erreur) : rien à appliquer.</summary>
        NotState,
        /// <summary>Reçue avant la définition ou l'instantané : ignorée, l'état complet suivra.</summary>
        NotReady,
    }

    /// <summary>Une personne présente dans le monde, telle que <c>presence</c> l'a annoncée.</summary>
    public sealed class Visitor
    {
        public string Actor { get; set; }
        public string Label { get; set; }
        public string Asset { get; set; }
    }

    /// <summary>
    /// La copie locale du monde : la définition et l'état vécu, tenus à jour par les trames du noyau, dans
    /// l'ordre du journal. C'est la seule chose que les vues lisent : un écran ne montre jamais un état qu'il
    /// n'a pas reçu (règle 1 du protocole), même le sien.
    /// </summary>
    /// <remarks>
    /// Le <c>seq</c> est celui du journal du noyau : il croît, mais n'est pas contigu (le journal porte aussi le
    /// reste de sa vie). Une trame dont le <c>seq</c> n'avance pas est un doublon (un rattrapage qui chevauche).
    /// Pur C#, sans Unity : testable en mode édition, réutilisable par un outil.
    /// </remarks>
    public sealed class WorldMirror
    {
        readonly Dictionary<string, ActorState> _actors = new Dictionary<string, ActorState>(StringComparer.Ordinal);
        readonly Dictionary<string, ObjectState> _objects = new Dictionary<string, ObjectState>(StringComparer.Ordinal);
        readonly Dictionary<string, Intent> _intents = new Dictionary<string, Intent>(StringComparer.Ordinal);
        readonly Dictionary<string, Request> _requests = new Dictionary<string, Request>(StringComparer.Ordinal);
        readonly Dictionary<string, Visitor> _visitors = new Dictionary<string, Visitor>(StringComparer.Ordinal);

        public WorldIndex World { get; private set; }

        /// <summary>Le dernier <c>seq</c> appliqué ; -1 tant qu'aucun état n'a été posé.</summary>
        public long Seq { get; private set; } = -1;

        /// <summary>Vrai dès qu'une définition et un état complet ont été reçus.</summary>
        public bool Ready => World != null && Seq >= 0;

        /// <summary>
        /// Vrai quand ce qui est montré ne vient pas du noyau (aperçu hors ligne d'un monde lu sur disque) : à la
        /// connexion, on redemande tout plutôt que de se croire à jour.
        /// </summary>
        public bool Provisional { get; set; }

        public IReadOnlyDictionary<string, ActorState> Actors => _actors;
        public IReadOnlyDictionary<string, ObjectState> Objects => _objects;
        public IReadOnlyDictionary<string, Intent> Intents => _intents;
        public IReadOnlyDictionary<string, Request> Requests => _requests;
        public IReadOnlyDictionary<string, Visitor> Visitors => _visitors;

        // --- ce que les vues écoutent ------------------------------------------------------------------------
        /// <summary>Nouvelle définition (entière ou éditée) : reconstruire ce qui en dépend.</summary>
        public event Action<WorldIndex> DefinitionChanged;
        /// <summary>Un instantané a remplacé tout l'état : poser chaque chose sans rien jouer.</summary>
        public event Action StateReset;
        public event Action<string> ActorChanged;
        public event Action<string> ObjectChanged;
        public event Action<string> ObjectRemoved;
        public event Action<Intent> IntentStarted;
        public event Action<IntentEnd> IntentEnded;
        public event Action<Request> RequestOpened;
        public event Action<RequestClose> RequestClosed;
        public event Action<GestureOut> Gestured;
        public event Action<Presence> PresenceChanged;

        public ActorState Actor(string id) => id != null && _actors.TryGetValue(id, out var a) ? a : null;
        public ObjectState Object(string id) => id != null && _objects.TryGetValue(id, out var o) ? o : null;

        /// <summary>L'action en cours d'un acteur (au plus une : une nouvelle interrompt la précédente).</summary>
        public Intent IntentOf(string actor) => _intents.Values.FirstOrDefault(i => i.Actor == actor);

        /// <summary>Qui tient un objet, ou <c>null</c>.</summary>
        public string HolderOf(string objectId) => (Object(objectId)?.Location as Held)?.Actor;

        /// <summary>La pièce où se trouve un objet (en remontant surfaces et contenants, ou par la main qui le tient).</summary>
        public string RoomOfObject(string objectId)
        {
            var o = Object(objectId);
            if (o == null) return null;
            if (o.Location is Held held) return Actor(held.Actor)?.Room;
            return World?.RoomOf(o.Location, id => Object(id)?.Location ?? World.Object(id)?.Home);
        }

        public FrameEffect Apply(ServerFrame frame)
        {
            switch (frame)
            {
                case Definition d:
                    World = WorldIndex.Of(d.World);
                    DefinitionChanged?.Invoke(World);
                    return FrameEffect.Applied;
                case Snapshot s:
                    ResetTo(s.State);
                    return FrameEffect.Applied;
            }

            var seq = SeqOf(frame);
            if (seq == null)
                return FrameEffect.NotState;
            if (!Ready)
                return FrameEffect.NotReady;
            if (seq.Value <= Seq)
                return FrameEffect.Duplicate;

            switch (frame)
            {
                case DefinitionDelta dd:
                    World = World.With(dd.Changes, dd.Rev);
                    Seq = dd.Seq;
                    DefinitionChanged?.Invoke(World);
                    break;
                case Delta delta:
                    Seq = delta.Seq;
                    ApplyChanges(delta.Changes);
                    break;
                case IntentStart start:
                    Seq = start.Seq;
                    _intents[start.Intent.Id] = start.Intent;
                    // Comme le noyau : une action qui commence arrache l'acteur à ce qu'il faisait, sans changement
                    // dans la trame (ni l'intent ni sa fin ne portent d'occupation remise à rien).
                    var interrupted = _actors.TryGetValue(start.Intent.Actor, out var starter) && starter.Activity != null;
                    if (interrupted) starter.Activity = null;
                    IntentStarted?.Invoke(start.Intent);
                    if (interrupted) ActorChanged?.Invoke(start.Intent.Actor);
                    break;
                case IntentEnd end:
                    Seq = end.Seq;
                    _intents.Remove(end.Intent);
                    ApplyChanges(end.Changes);
                    if (_actors.TryGetValue(end.Actor, out var actor) && actor.Moving?.Intent == end.Intent)
                    {
                        actor.Moving = null;
                        ActorChanged?.Invoke(end.Actor);
                    }
                    IntentEnded?.Invoke(end);
                    break;
                case RequestOpen open:
                    Seq = open.Seq;
                    _requests[open.Request.Id] = open.Request;
                    RequestOpened?.Invoke(open.Request);
                    break;
                case RequestClose close:
                    Seq = close.Seq;
                    _requests.Remove(close.Request);
                    ApplyChanges(close.Changes);
                    RequestClosed?.Invoke(close);
                    break;
                case GestureOut gesture:
                    Seq = gesture.Seq;
                    Gestured?.Invoke(gesture);
                    break;
                case Presence presence:
                    Seq = presence.Seq;
                    ApplyPresence(presence);
                    break;
                default:
                    return FrameEffect.NotState;
            }
            return FrameEffect.Applied;
        }

        /// <summary>Le <c>seq</c> d'une trame d'état, <c>null</c> pour les autres.</summary>
        public static long? SeqOf(ServerFrame frame) => frame switch
        {
            DefinitionDelta f => f.Seq,
            Delta f => f.Seq,
            IntentStart f => f.Seq,
            IntentEnd f => f.Seq,
            RequestOpen f => f.Seq,
            RequestClose f => f.Seq,
            GestureOut f => f.Seq,
            Presence f => f.Seq,
            _ => (long?)null,
        };

        void ResetTo(WorldState state)
        {
            _actors.Clear();
            _objects.Clear();
            _intents.Clear();
            _requests.Clear();
            foreach (var a in state.Actors) _actors[a.Id] = a;
            foreach (var o in state.Objects) _objects[o.Id] = o;
            foreach (var i in state.Intents ?? new List<Intent>()) _intents[i.Id] = i;
            foreach (var r in state.Requests ?? new List<Request>()) _requests[r.Id] = r;
            // Les visiteurs connus restent (le snapshot ne porte pas leur nom) ; on oublie ceux qui n'y sont plus.
            foreach (var gone in _visitors.Keys.Where(k => !_actors.ContainsKey(k)).ToList())
                _visitors.Remove(gone);
            Seq = state.Seq;
            Provisional = false;
            StateReset?.Invoke();
        }

        void ApplyPresence(Presence p)
        {
            if (p.Joined)
            {
                _visitors[p.Actor] = new Visitor { Actor = p.Actor, Label = p.Label, Asset = p.Asset };
                if (!_actors.TryGetValue(p.Actor, out var state))
                {
                    state = new ActorState { Id = p.Actor };
                    _actors[p.Actor] = state;
                }
                if (p.Room != null) state.Room = p.Room;
                state.Place = p.Place;
            }
            else
            {
                _visitors.Remove(p.Actor);
                _actors.Remove(p.Actor);
            }
            PresenceChanged?.Invoke(p);
            ActorChanged?.Invoke(p.Actor);
        }

        void ApplyChanges(IEnumerable<Change> changes)
        {
            if (changes == null) return;
            foreach (var change in changes)
            {
                switch (change)
                {
                    case ActorMoved moved:
                    {
                        var a = ActorOrNew(moved.Actor);
                        a.Room = moved.Room;
                        a.Place = moved.Place;
                        a.Posture = moved.Posture;
                        a.Moving = null;
                        ActorChanged?.Invoke(moved.Actor);
                        break;
                    }
                    case ActorBusy busy:
                    {
                        var a = ActorOrNew(busy.Actor);
                        a.Activity = busy.Activity;
                        ActorChanged?.Invoke(busy.Actor);
                        break;
                    }
                    case ObjectMoved om:
                    {
                        var o = ObjectOrNew(om.Object);
                        var before = (o.Location as Held)?.Actor;
                        o.Location = om.To;
                        var after = (om.To as Held)?.Actor;
                        if (before != null && before != after && _actors.TryGetValue(before, out var b))
                        {
                            b.Holding.Remove(om.Object);
                            ActorChanged?.Invoke(before);
                        }
                        if (after != null)
                        {
                            var a = ActorOrNew(after);
                            if (!a.Holding.Contains(om.Object)) a.Holding.Add(om.Object);
                            ActorChanged?.Invoke(after);
                        }
                        ObjectChanged?.Invoke(om.Object);
                        break;
                    }
                    case ObjectSet set:
                    {
                        var o = ObjectOrNew(set.Object);
                        o.State = set.State;
                        ObjectChanged?.Invoke(set.Object);
                        break;
                    }
                    case ObjectGone gone:
                    {
                        var holder = HolderOf(gone.Object);
                        _objects.Remove(gone.Object);
                        if (holder != null && _actors.TryGetValue(holder, out var h))
                        {
                            h.Holding.Remove(gone.Object);
                            ActorChanged?.Invoke(holder);
                        }
                        ObjectRemoved?.Invoke(gone.Object);
                        break;
                    }
                }
            }
        }

        ActorState ActorOrNew(string id)
        {
            if (!_actors.TryGetValue(id, out var a))
            {
                a = new ActorState { Id = id };
                _actors[id] = a;
            }
            return a;
        }

        ObjectState ObjectOrNew(string id)
        {
            if (!_objects.TryGetValue(id, out var o))
            {
                o = new ObjectState { Id = id };
                _objects[id] = o;
            }
            return o;
        }
    }
}
