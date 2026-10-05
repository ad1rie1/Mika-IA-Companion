using System;
using System.Collections.Generic;
using System.Linq;
using Mika.World.Engine.Authoring;
using Mika.World.Model;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// La scène qui montre le monde : elle lit le miroir (la définition et l'état reçus du noyau) et met chaque
    /// chose à sa place — pièces, lieux, objets, acteurs —, fait jouer les actions annoncées, et se recale sur
    /// chaque fin d'action. Elle ne décide rien et n'écrit rien dans le monde : ce qui doit changer l'état passe
    /// par le noyau (constats de l'hôte, actes de la joueuse).
    /// </summary>
    /// <remarks>
    /// La géométrie vient de la scène quand elle existe (pièces, lieux et meubles posés par le créateur, voir
    /// <see cref="WorldAuthoring"/>) ; ce que la scène n'a pas est créé d'après la définition — un objet depuis
    /// son prefab (catalogue), un lieu à sa position grossière — et noté comme manquant (<see cref="Missing"/>).
    /// </remarks>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Monde/Scène du monde")]
    public sealed class WorldStage : MonoBehaviour
    {
        [Tooltip("Ce que le moteur sait montrer (archétypes, avatars).")]
        public AssetCatalog catalog;
        [Tooltip("La racine du monde dans la scène (vide : cherchée automatiquement).")]
        public WorldAuthoring authoring;
        [Tooltip("Où créer ce qui n'est pas dans la scène (objets apparus, acteurs).")]
        public Transform dynamicRoot;
        [Tooltip("L'acteur piloté localement (la joueuse de ce poste) : la scène ne le replace pas.")]
        public string localActor;
        [Tooltip("Où la joueuse de ce poste tient ce qu'elle a pris (devant la caméra).")]
        public Transform localHand;

        readonly Dictionary<string, RoomView> _rooms = new Dictionary<string, RoomView>();
        readonly Dictionary<string, PlaceView> _places = new Dictionary<string, PlaceView>();
        readonly Dictionary<string, WorldObject> _objects = new Dictionary<string, WorldObject>();
        readonly Dictionary<string, ActorBody> _actors = new Dictionary<string, ActorBody>();
        readonly HashSet<string> _missingAssets = new HashSet<string>();
        readonly HashSet<string> _missingAnchors = new HashSet<string>();
        readonly HashSet<WorldObject> _spawned = new HashSet<WorldObject>();
        // Les occupations montrées qui ont une échéance : à quitter quand elle passe (aucune trame ne le dira).
        readonly Dictionary<string, Activity> _bounded = new Dictionary<string, Activity>();

        WorldMirror _mirror;
        KernelClock _clock;
        IIntentReporter _reporter;

        public WorldMirror Mirror => _mirror;
        public KernelClock Clock => _clock;
        public IReadOnlyCollection<string> MissingAssets => _missingAssets;
        public IReadOnlyCollection<string> MissingAnchors => _missingAnchors;
        public IReadOnlyDictionary<string, ActorBody> Actors => _actors;
        public IReadOnlyDictionary<string, WorldObject> Objects => _objects;
        public IReadOnlyDictionary<string, PlaceView> Places => _places;

        /// <summary>Une nouvelle définition vient d'être montée : ce qui manque est à jour (pour <c>loaded</c>).</summary>
        public event Action<WorldIndex> Built;
        /// <summary>Un acteur vient d'apparaître (pour que l'avatar s'y greffe : visage, voix).</summary>
        public event Action<string, ActorBody> ActorSpawned;
        /// <summary>Un geste vient d'être montré (pour que l'avatar de celle qui le reçoit s'y tourne).</summary>
        public event Action<GestureOut> GestureShown;

        public RoomView Room(string id) => id != null && _rooms.TryGetValue(id, out var r) ? r : null;
        public PlaceView Place(string id) => id != null && _places.TryGetValue(id, out var p) ? p : null;
        public WorldObject Object(string id) => id != null && _objects.TryGetValue(id, out var o) ? o : null;
        public ActorBody Actor(string id) => id != null && _actors.TryGetValue(id, out var a) ? a : null;

        public void Bind(WorldMirror mirror, KernelClock clock, IIntentReporter reporter)
        {
            Unbind();
            _mirror = mirror;
            _clock = clock;
            _reporter = reporter;
            if (authoring == null) authoring = FindAnyObjectByType<WorldAuthoring>();
            if (catalog == null && authoring != null) catalog = authoring.catalog;
            if (dynamicRoot == null)
            {
                var root = new GameObject("Monde (dynamique)");
                root.transform.SetParent(transform, false);
                dynamicRoot = root.transform;
            }
            mirror.DefinitionChanged += OnDefinition;
            mirror.StateReset += OnReset;
            mirror.ActorChanged += OnActorChanged;
            mirror.ObjectChanged += OnObjectChanged;
            mirror.ObjectRemoved += OnObjectRemoved;
            mirror.IntentStarted += OnIntentStarted;
            mirror.IntentEnded += OnIntentEnded;
            mirror.Gestured += OnGesture;
            if (mirror.World != null) OnDefinition(mirror.World);
            if (mirror.Ready) OnReset();
        }

        public void Unbind()
        {
            if (_mirror == null) return;
            _mirror.DefinitionChanged -= OnDefinition;
            _mirror.StateReset -= OnReset;
            _mirror.ActorChanged -= OnActorChanged;
            _mirror.ObjectChanged -= OnObjectChanged;
            _mirror.ObjectRemoved -= OnObjectRemoved;
            _mirror.IntentStarted -= OnIntentStarted;
            _mirror.IntentEnded -= OnIntentEnded;
            _mirror.Gestured -= OnGesture;
            _mirror = null;
        }

        void OnDestroy() => Unbind();

        // --- monter la définition ------------------------------------------------------------------------------
        void OnDefinition(WorldIndex world)
        {
            _missingAssets.Clear();
            _missingAnchors.Clear();
            var sceneRooms = FindObjectsByType<RoomAuthoring>(FindObjectsInactive.Include).ToDictionary(r => r.id, r => r);
            var scenePlaces = FindObjectsByType<PlaceAuthoring>(FindObjectsInactive.Include).GroupBy(p => p.id).ToDictionary(g => g.Key, g => g.First());
            var sceneObjects = FindObjectsByType<ObjectAuthoring>(FindObjectsInactive.Include).GroupBy(o => o.id).ToDictionary(g => g.Key, g => g.First());

            // Pièces
            foreach (var stale in _rooms.Keys.Where(k => world.Room(k) == null).ToList())
            {
                if (_rooms[stale].Placeholder) Destroy(_rooms[stale].Root.gameObject);
                _rooms.Remove(stale);
            }
            foreach (var room in world.Def.Rooms)
            {
                if (_rooms.TryGetValue(room.Id, out var view))
                {
                    view.Def = room;
                    continue;
                }
                if (sceneRooms.TryGetValue(room.Id, out var ra))
                {
                    _rooms[room.Id] = new RoomView { Id = room.Id, Def = room, Root = ra.transform, Authoring = ra };
                }
                else
                {
                    var go = new GameObject($"Pièce {room.Id} (sans géométrie)");
                    go.transform.SetParent(dynamicRoot, false);
                    // Les pièces sans géométrie s'alignent à côté : on les voit, elles ne se chevauchent pas.
                    go.transform.position = new Vector3(12f * _rooms.Count, 0, 0);
                    _rooms[room.Id] = new RoomView { Id = room.Id, Def = room, Root = go.transform, Placeholder = true };
                    _missingAnchors.Add(room.Id);
                }
            }

            // Lieux
            foreach (var stale in _places.Keys.Where(k => world.Place(k) == null).ToList())
            {
                if (_places[stale].Authoring == null) Destroy(_places[stale].Approach.gameObject);
                _places.Remove(stale);
            }
            foreach (var place in world.Def.Places)
            {
                var room = Room(place.Room);
                if (room == null) continue;
                var anchorId = place.Anchor ?? place.Id;
                if (scenePlaces.TryGetValue(anchorId, out var pa))
                {
                    _places[place.Id] = new PlaceView { Id = place.Id, Def = place, Room = room, Approach = pa.transform, Authoring = pa, Stage = this };
                    continue;
                }
                if (!_places.TryGetValue(place.Id, out var view) || view.Authoring != null)
                {
                    var go = new GameObject($"Lieu {place.Id}");
                    view = new PlaceView { Id = place.Id, Approach = go.transform, Stage = this };
                    _places[place.Id] = view;
                    _missingAnchors.Add(place.Id);
                }
                view.Def = place;
                view.Room = room;
                view.Approach.SetParent(room.Root, false);
                view.Approach.localPosition = RoomSpace.ToUnity(place.Pos);
                view.Approach.localRotation = RoomSpace.Facing(place.Facing ?? 0);
            }

            // Objets
            foreach (var stale in _objects.Keys.Where(k => world.Object(k) == null).ToList())
                RemoveObject(stale);
            foreach (var obj in world.Def.Objects)
            {
                if (_objects.ContainsKey(obj.Id)) continue;
                var archetype = world.Archetype(obj.Archetype);
                WorldObject view;
                if (sceneObjects.TryGetValue(obj.Id, out var oa))
                {
                    view = oa.gameObject.GetOrAdd<WorldObject>();
                }
                else
                {
                    view = Spawn(archetype?.Asset, $"{obj.Id}");
                    _spawned.Add(view);
                }
                view.id = obj.Id;
                view.SetPhysics(archetype == null || archetype.Size == Size.Fixed ? ObjectPhysics.Fixed : ObjectPhysics.Placed);
                _objects[obj.Id] = view;
            }

            // Acteurs déclarés (Mika, personnages)
            foreach (var actor in world.Def.Actors)
                EnsureActor(actor.Id, actor.Asset, actor.Label);

            Built?.Invoke(world);
        }

        WorldObject Spawn(string assetKey, string name)
        {
            var prefab = catalog != null ? catalog.Prefab(assetKey) : null;
            GameObject go;
            if (prefab != null)
            {
                go = Instantiate(prefab, dynamicRoot);
            }
            else
            {
                if (!string.IsNullOrEmpty(assetKey)) _missingAssets.Add(assetKey);
                go = GameObject.CreatePrimitive(PrimitiveType.Cube);
                go.transform.SetParent(dynamicRoot, false);
                go.transform.localScale = Vector3.one * 0.12f;
            }
            go.name = name;
            return go.GetOrAdd<WorldObject>();
        }

        ActorBody EnsureActor(string id, string assetKey, string label)
        {
            if (_actors.TryGetValue(id, out var existing) && existing != null) return existing;
            var body = Spawn(id, assetKey, label);
            _actors[id] = body;
            ActorSpawned?.Invoke(id, body);
            return body;
        }

        /// <summary>
        /// Un corps monté exactement comme ceux du monde, mais que le noyau ne connaît pas et ne pilote pas : un
        /// banc d'essai d'animations, un aperçu du créateur. À détruire par qui l'a demandé.
        /// </summary>
        public ActorBody SpawnUnlisted(string id, string assetKey, string label) => Spawn(id, assetKey, label);

        ActorBody Spawn(string id, string assetKey, string label)
        {
            var prefab = catalog != null ? catalog.Prefab(assetKey) : null;
            GameObject go;
            if (prefab != null)
            {
                go = Instantiate(prefab, dynamicRoot);
            }
            else
            {
                if (!string.IsNullOrEmpty(assetKey)) _missingAssets.Add(assetKey);
                go = GameObject.CreatePrimitive(PrimitiveType.Capsule);
                go.transform.SetParent(dynamicRoot, false);
                Destroy(go.GetComponent<Collider>());
                go.transform.localScale = new Vector3(0.4f, 0.8f, 0.4f);
            }
            go.name = string.IsNullOrEmpty(label) ? id : $"{label} ({id})";
            // Un avatar humanoïde reçoit le contrôleur du corps commun avant que le corps ne s'y relie.
            var animator = go.GetComponentInChildren<Animator>();
            if (animator != null && animator.isHuman && catalog != null && catalog.humanoidController != null)
            {
                animator.runtimeAnimatorController = catalog.humanoidController;
                // Le mouvement de racine est calculé (s'asseoir capturé recule) mais jamais appliqué d'office :
                // le relais IK le reçoit (OnAnimatorMove) et le corps décide.
                animator.applyRootMotion = true;
            }
            var body = go.GetOrAdd<ActorBody>();
            if (catalog != null) body.clips = catalog.bodyClips;
            if (animator != null) body.Bind(animator);
            if (animator != null && animator.runtimeAnimatorController != null && catalog != null && catalog.bodyClips != null)
                go.GetOrAdd<BodyExpression>().Bind(body, catalog.bodyClips);
            body.actorId = id;
            if (animator != null && animator.runtimeAnimatorController != null)
                go.GetOrAdd<BodyActivity>().Bind(body, this);
            var player = go.GetOrAdd<IntentPlayer>();
            player.Init(body, this);
            return body;
        }

        // --- poser l'état --------------------------------------------------------------------------------------
        void OnReset()
        {
            if (_mirror?.World == null) return;
            foreach (var p in _actors.Values)
                if (p != null && p.TryGetComponent<IntentPlayer>(out var ip)) ip.Stop();
            // D'abord les objets qui ne sont pas tenus (une main a besoin de son corps posé).
            foreach (var o in _mirror.Objects.Values.Where(o => !(o.Location is Held)))
                ApplyObject(o, instant: true);
            foreach (var a in _mirror.Actors.Values)
                ApplyActor(a, instant: true);
            foreach (var o in _mirror.Objects.Values.Where(o => o.Location is Held))
                ApplyObject(o, instant: true);
            foreach (var intent in _mirror.Intents.Values)
                OnIntentStarted(intent);
        }

        void OnActorChanged(string id)
        {
            var state = _mirror.Actor(id);
            if (state == null)
            {
                if (_actors.TryGetValue(id, out var gone) && gone != null) Destroy(gone.gameObject);
                _actors.Remove(id);
                return;
            }
            ApplyActor(state, instant: false);
        }

        void ApplyActor(ActorState state, bool instant)
        {
            if (state.Id == localActor)
            {
                // La joueuse de ce poste a son propre corps (son contrôleur) : pas de double.
                if (_actors.TryGetValue(state.Id, out var twin) && twin != null) Destroy(twin.gameObject);
                _actors.Remove(state.Id);
                return;
            }
            ActorBody body;
            if (_mirror.World.Actor(state.Id) is { } def)
                body = EnsureActor(state.Id, def.Asset, def.Label);
            else
            {
                var visitor = _mirror.Visitors.TryGetValue(state.Id, out var v) ? v : null;
                body = EnsureActor(state.Id, visitor?.Asset ?? "avatars/default", visitor?.Label);
            }
            var live = Expired(state.Activity) ? null : state.Activity;
            if (live?.Until != null) _bounded[state.Id] = live;
            else _bounded.Remove(state.Id);
            ShowActivity(body, live);
            var player = body.GetComponent<IntentPlayer>();
            if (player != null && player.Current != null && !instant) return; // l'action en cours amène le corps
            var place = Place(state.Place);
            if (place == null)
            {
                var room = Room(state.Room);
                if (room != null && instant) body.Snap(room.Root.position, room.Root.rotation, state.Posture);
                return;
            }
            if (instant || Vector3.Distance(body.transform.position, place.Position) > 2.5f || body.Posture != state.Posture)
                body.Snap(place.Position, place.Rotation, state.Posture, place);
        }

        static void ShowActivity(ActorBody body, Activity activity)
        {
            body.SetActivity(activity?.Name);
            if (body.TryGetComponent<BodyActivity>(out var shown))
                shown.Set(activity?.Name, activity?.Object);
        }

        /// <summary>
        /// Une occupation bornée a passé son échéance : le noyau ne la prête plus (il compare <c>until</c> à
        /// maintenant, sans événement), le corps la quitte. Sans horloge recalée, on ne sait pas : elle reste.
        /// </summary>
        bool Expired(Activity activity) =>
            activity?.Until is long until && _clock != null && _clock.Synced && until <= _clock.NowUs;

        void Update()
        {
            if (_bounded.Count == 0 || _clock == null || !_clock.Synced) return;
            List<string> due = null;
            foreach (var kv in _bounded)
                if (Expired(kv.Value)) (due ??= new List<string>()).Add(kv.Key);
            if (due == null) return;
            foreach (var id in due)
            {
                _bounded.Remove(id);
                if (_actors.TryGetValue(id, out var body) && body != null) ShowActivity(body, null);
            }
        }

        void OnObjectChanged(string id)
        {
            var state = _mirror.Object(id);
            if (state != null) ApplyObject(state, instant: false);
        }

        void OnObjectRemoved(string id) => RemoveObject(id);

        void RemoveObject(string id)
        {
            if (!_objects.TryGetValue(id, out var view)) return;
            _objects.Remove(id);
            foreach (var body in _actors.Values) body.Release(view);
            if (view != null && _spawned.Remove(view)) Destroy(view.gameObject);
            else if (view != null) view.gameObject.SetActive(false);
        }

        void ApplyObject(ObjectState state, bool instant)
        {
            var view = Object(state.Id);
            if (view == null) return;
            var archetype = _mirror.World.ArchetypeOf(state.Id);
            view.ApplyState(state.State ?? archetype?.InitialState, instant);
            PlaceObject(view, state.Location, instant);
        }

        /// <summary>Met un objet là où le monde dit qu'il est.</summary>
        public void PlaceObject(WorldObject view, Location location, bool instant)
        {
            var archetype = _mirror?.World?.ArchetypeOf(view.id);
            var fixedObject = archetype == null || archetype.Size == Size.Fixed;
            foreach (var body in _actors.Values)
                if (!(location is Held h && body.actorId == h.Actor) && body.IsHolding(view))
                    body.Release(view);
            if (localHand != null && view.transform.parent == localHand && !(location is Held lh && lh.Actor == localActor))
                view.transform.SetParent(dynamicRoot, true);
            switch (location)
            {
                case Held held when held.Actor == localActor && localHand != null:
                {
                    view.SetPhysics(ObjectPhysics.Held);
                    view.SetVisible(true);
                    view.transform.SetParent(localHand, false);
                    view.transform.localRotation = Quaternion.identity;
                    view.transform.position += localHand.position - view.GripPoint;
                    break;
                }
                case Held held:
                {
                    var body = Actor(held.Actor);
                    // Déjà tenu mais dans l'autre main (l'animation a deviné) : la main du monde fait foi.
                    if (body != null && (!body.Held.TryGetValue(view, out var hand) || hand != held.Hand)) body.Hold(view, held.Hand);
                    break;
                }
                case On on when instant && IsAuthoredHome(view, location):
                    // À sa place d'origine : tel que la scène le pose (une pile de livres reste une pile).
                    view.SetVisible(true);
                    view.SetPhysics(fixedObject ? ObjectPhysics.Fixed : ObjectPhysics.Placed);
                    break;
                case On on:
                {
                    view.SetVisible(true);
                    var support = Object(on.Object);
                    var slot = support != null ? support.Slot(on.Slot) : null;
                    view.transform.SetParent(dynamicRoot, true);
                    if (slot != null) view.RestOn(slot);
                    else if (support != null)
                    {
                        var b = support.Bounds();
                        view.transform.position = new Vector3(b.center.x, b.max.y + 0.01f, b.center.z);
                        _missingAnchors.Add($"{on.Object}#{on.Slot}");
                    }
                    view.SetPhysics(fixedObject ? ObjectPhysics.Fixed : ObjectPhysics.Placed);
                    break;
                }
                case In inside:
                {
                    var container = Object(inside.Object);
                    view.transform.SetParent(dynamicRoot, true);
                    if (container != null)
                    {
                        view.transform.position = container.Container.position;
                        view.SetVisible(!container.hideContents);
                    }
                    view.SetPhysics(fixedObject ? ObjectPhysics.Fixed : ObjectPhysics.Placed);
                    break;
                }
                case InRoom inRoom:
                {
                    view.SetVisible(true);
                    if (fixedObject)
                    {
                        // Un meuble garde la place que la scène lui donne ; sans scène, il va au lieu nommé.
                        if (_spawned.Contains(view)) DropNear(view, inRoom, settle: false);
                        view.SetPhysics(ObjectPhysics.Fixed);
                        break;
                    }
                    var authored = view.GetComponent<ObjectAuthoring>();
                    var home = _mirror.World.Object(view.id)?.Home as InRoom;
                    if (authored != null && home != null && home.Room == inRoom.Room && home.Near == inRoom.Near && instant)
                    {
                        view.SetPhysics(ObjectPhysics.Placed); // à sa place d'origine, tel que la scène le pose
                        break;
                    }
                    view.transform.SetParent(dynamicRoot, true);
                    // Déjà au sol, près du bon lieu (il vient de tomber là) : on le laisse où la physique l'a mis.
                    if (!instant && view.Physics == ObjectPhysics.Free && NearestPlace(view.transform.position, inRoom.Room)?.Id == inRoom.Near)
                        break;
                    DropNear(view, inRoom, settle: true);
                    break;
                }
            }
        }

        /// <summary>L'objet vient de la scène et le monde le dit à son emplacement de départ.</summary>
        bool IsAuthoredHome(WorldObject view, Location location)
        {
            if (view.GetComponent<ObjectAuthoring>() == null) return false;
            var home = _mirror?.World?.Object(view.id)?.Home;
            return home != null && WireJson.Write(home) == WireJson.Write(location);
        }

        void DropNear(WorldObject view, InRoom where, bool settle)
        {
            var place = Place(where.Near);
            var room = Room(where.Room);
            Vector3 p;
            if (place != null)
                p = place.Position + place.Rotation * new Vector3(0.25f, 0f, 0.45f);
            else if (room != null)
                p = room.Root.position;
            else
                return;
            var b = view.Bounds();
            view.transform.position = p + Vector3.up * (view.transform.position.y - b.min.y + (settle ? 0.05f : 0f));
            view.SetPhysics(settle ? ObjectPhysics.Free : ObjectPhysics.Fixed);
        }

        // --- actions --------------------------------------------------------------------------------------------
        void OnIntentStarted(Intent intent)
        {
            if (intent.Actor == localActor) return;
            var body = Actor(intent.Actor);
            if (body == null) return;
            if (body.TryGetComponent<IntentPlayer>(out var player)) player.Play(intent, _clock, _reporter);
        }

        void OnIntentEnded(IntentEnd end)
        {
            var body = Actor(end.Actor);
            var player = body != null ? body.GetComponent<IntentPlayer>() : null;
            if (player != null && player.Current == end.Intent) player.Stop();
            // Recaler sur ce qui est vrai : les changements de la fin sont déjà dans le miroir.
            var state = _mirror.Actor(end.Actor);
            if (state != null && body != null && end.Actor != localActor)
            {
                var place = Place(state.Place);
                if (place != null && (Vector3.Distance(body.transform.position, place.Position) > 0.6f || body.Posture != state.Posture))
                    body.Snap(place.Position, place.Rotation, state.Posture, place);
            }
        }

        void OnGesture(GestureOut g)
        {
            var gesture = WireJson.Name(g.Gesture);
            var body = Actor(g.Actor);
            var target = Actor(g.ToActor);
            // La joueuse de ce poste n'a pas de corps ici : son geste ne se joue pas, mais il est fait.
            if (body != null)
            {
                if (target != null) body.LookAt(target.Head.position);
                body.PlayGesture(gesture);
            }
            // Celle qui le reçoit réagit tout de suite dans son corps (une caresse, une pichenette) ; ce qu'elle en
            // ressent revient ensuite par la dérive de son humeur.
            if (target != null && target.TryGetComponent<BodyExpression>(out var expression)) expression.Touched(gesture);
            GestureShown?.Invoke(g);
        }

        // --- lectures pour les joueurs d'actions ------------------------------------------------------------------
        public Affordance Affordance(string objectId, string action) =>
            _mirror?.World?.ArchetypeOf(objectId)?.Affordances?.FirstOrDefault(a => a.Id == action);

        /// <summary>Le point visé par une destination d'objet (une place de surface, un contenant, une main).</summary>
        public Vector3? TargetPoint(Location location)
        {
            switch (location)
            {
                case On on:
                    var support = Object(on.Object);
                    var slot = support != null ? support.Slot(on.Slot) : null;
                    return slot != null ? slot.position : support != null ? support.Bounds().center + Vector3.up * support.Bounds().extents.y : (Vector3?)null;
                case In inside:
                    return Object(inside.Object)?.Container.position;
                case Held held:
                    return Actor(held.Actor)?.Head.position + Vector3.down * 0.45f;
                case InRoom r:
                    var place = Place(r.Near);
                    return place != null ? place.Position + place.Rotation * new Vector3(0.25f, 0.05f, 0.45f) : (Vector3?)null;
            }
            return null;
        }

        /// <summary>Le lieu le plus proche d'une position (dans une pièce donnée si on la connaît).</summary>
        public PlaceView NearestPlace(Vector3 position, string room = null)
        {
            PlaceView best = null;
            var bestD = float.MaxValue;
            foreach (var p in _places.Values)
            {
                if (room != null && p.Room?.Id != room) continue;
                var d = (p.Position - position).sqrMagnitude;
                if (d < bestD)
                {
                    best = p;
                    bestD = d;
                }
            }
            return best;
        }

        /// <summary>La pièce qui contient une position (la plus proche de ses lieux).</summary>
        public RoomView RoomAt(Vector3 position) => NearestPlace(position)?.Room;
    }
}
