using System;
using System.Collections.Generic;
using System.Linq;
using Mika.World.Protocol;

namespace Mika.World.Model
{
    /// <summary>
    /// La définition du monde (ce que le créateur a écrit), indexée par identifiant. Immuable : une édition
    /// (<see cref="With"/>) en donne une nouvelle, si bien qu'un lecteur qui tient l'ancienne ne la voit jamais
    /// changer sous lui.
    /// </summary>
    /// <remarks>
    /// Le moteur ne valide pas la définition : le noyau l'a fait avant de la diffuser (« cohérent ou rien »).
    /// Ce qui manque ici (un lieu inconnu, un archétype absent) est un cas de version — on l'ignore sans planter.
    /// </remarks>
    public sealed class WorldIndex
    {
        public WorldDef Def { get; }
        public long Rev => Def.Rev;
        public string Id => Def.Id;

        public IReadOnlyDictionary<string, RoomDef> Rooms { get; }
        public IReadOnlyDictionary<string, PlaceDef> Places { get; }
        public IReadOnlyDictionary<string, ArchetypeDef> Archetypes { get; }
        public IReadOnlyDictionary<string, ObjectDef> Objects { get; }
        public IReadOnlyDictionary<string, ActorDef> Actors { get; }

        WorldIndex(WorldDef def)
        {
            Def = def;
            Rooms = ById(def.Rooms, r => r.Id);
            Places = ById(def.Places, p => p.Id);
            Archetypes = ById(def.Archetypes, a => a.Id);
            Objects = ById(def.Objects, o => o.Id);
            Actors = ById(def.Actors, a => a.Id);
        }

        public static WorldIndex Of(WorldDef def) => new WorldIndex(def ?? throw new ArgumentNullException(nameof(def)));

        static IReadOnlyDictionary<string, T> ById<T>(IEnumerable<T> items, Func<T, string> id)
        {
            var map = new Dictionary<string, T>(StringComparer.Ordinal);
            if (items != null)
                foreach (var item in items)
                    map[id(item)] = item;
            return map;
        }

        public RoomDef Room(string id) => id != null && Rooms.TryGetValue(id, out var r) ? r : null;
        public PlaceDef Place(string id) => id != null && Places.TryGetValue(id, out var p) ? p : null;
        public ObjectDef Object(string id) => id != null && Objects.TryGetValue(id, out var o) ? o : null;
        public ActorDef Actor(string id) => id != null && Actors.TryGetValue(id, out var a) ? a : null;

        public ArchetypeDef Archetype(string id) => id != null && Archetypes.TryGetValue(id, out var a) ? a : null;

        public ArchetypeDef ArchetypeOf(string objectId) => Archetype(Object(objectId)?.Archetype);

        public IEnumerable<PlaceDef> PlacesIn(string room) => Def.Places.Where(p => p.Room == room);

        public IEnumerable<ObjectDef> ObjectsIn(string room) =>
            Def.Objects.Where(o => RoomOf(o.Home) == room);

        /// <summary>Le lieu où entre une personne : le lieu <c>spawn</c> de la pièce, sinon le premier lieu <c>spawn</c>.</summary>
        public PlaceDef SpawnPlace(string room = null)
        {
            var spawns = Def.Places.Where(p => p.Tags != null && p.Tags.Contains("spawn")).ToList();
            return spawns.FirstOrDefault(p => p.Room == room) ?? spawns.FirstOrDefault() ?? Def.Places.FirstOrDefault();
        }

        /// <summary>La pièce d'un emplacement (en remontant les contenants et les surfaces, jamais en boucle).</summary>
        public string RoomOf(Location location, Func<string, Location> locationOfObject = null)
        {
            var seen = new HashSet<string>();
            var loc = location;
            while (loc != null)
            {
                switch (loc)
                {
                    case InRoom r:
                        return r.Room;
                    case On on:
                        if (!seen.Add(on.Object)) return null;
                        loc = (locationOfObject ?? HomeOf)(on.Object);
                        break;
                    case In inside:
                        if (!seen.Add(inside.Object)) return null;
                        loc = (locationOfObject ?? HomeOf)(inside.Object);
                        break;
                    default:
                        return null; // tenu : la pièce est celle de l'acteur, que la définition ne connaît pas
                }
            }
            return null;
        }

        Location HomeOf(string objectId) => Object(objectId)?.Home;

        /// <summary>
        /// La définition après un lot d'éditions (<c>definition_delta</c>). Le lot vient du noyau, qui l'a déjà
        /// validé en entier : on l'applique tel quel.
        /// </summary>
        public WorldIndex With(IEnumerable<DefChange> changes, long rev)
        {
            var def = Clone(Def);
            def.Rev = rev;
            foreach (var change in changes)
            {
                switch (change)
                {
                    case DefPut put:
                        Put(def, put.Item);
                        break;
                    case DefRemove remove:
                        Remove(def, remove.Of, remove.Id);
                        break;
                }
            }
            return new WorldIndex(def);
        }

        static void Put(WorldDef def, DefItem item)
        {
            switch (item)
            {
                case RoomDef r: Replace(def.Rooms, r, x => x.Id == r.Id); break;
                case PlaceDef p: Replace(def.Places, p, x => x.Id == p.Id); break;
                case ArchetypeDef a: Replace(def.Archetypes, a, x => x.Id == a.Id); break;
                case ObjectDef o: Replace(def.Objects, o, x => x.Id == o.Id); break;
                case ActorDef a: Replace(def.Actors, a, x => x.Id == a.Id); break;
            }
        }

        static void Replace<T>(List<T> list, T item, Predicate<T> same)
        {
            var i = list.FindIndex(same);
            if (i >= 0) list[i] = item;
            else list.Add(item);
        }

        static void Remove(WorldDef def, DefKind kind, string id)
        {
            switch (kind)
            {
                case DefKind.Room: def.Rooms.RemoveAll(x => x.Id == id); break;
                case DefKind.Place: def.Places.RemoveAll(x => x.Id == id); break;
                case DefKind.Archetype: def.Archetypes.RemoveAll(x => x.Id == id); break;
                case DefKind.Object: def.Objects.RemoveAll(x => x.Id == id); break;
                case DefKind.Actor: def.Actors.RemoveAll(x => x.Id == id); break;
            }
        }

        /// <summary>Une copie profonde (par le fil : c'est la seule forme dont on soit sûr qu'elle est complète).</summary>
        public static WorldDef Clone(WorldDef def) => WireJson.ReadWorld(WireJson.Write(def));
    }
}
