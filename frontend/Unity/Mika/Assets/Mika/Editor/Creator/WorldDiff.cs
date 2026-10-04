using System.Collections.Generic;
using System.Linq;
using Mika.World.Protocol;
using Newtonsoft.Json.Linq;

namespace Mika.Editor.Creator
{
    /// <summary>
    /// Ce qui sépare deux définitions du monde, en éditions du protocole (<c>put</c> / <c>remove</c>) : ce que le
    /// créateur envoie au noyau pour passer de la révision qu'il a lue à la scène qu'il a écrite. Deux éléments
    /// sont égaux quand ils s'écrivent pareil sur le fil (les défauts compris) : pas de fausse différence.
    /// </summary>
    public static class WorldDiff
    {
        public static List<DefChange> Between(WorldDef from, WorldDef to)
        {
            var changes = new List<DefChange>();
            // L'ordre compte pour que le lot reste cohérent à chaque pas : on retire d'abord ce qui dépend
            // (objets, lieux), on ajoute d'abord ce dont on dépend (archétypes, pièces).
            Removals(changes, from.Objects, to.Objects, o => o.Id, DefKind.Object);
            Removals(changes, from.Actors, to.Actors, a => a.Id, DefKind.Actor);
            Removals(changes, from.Places, to.Places, p => p.Id, DefKind.Place);
            Removals(changes, from.Archetypes, to.Archetypes, a => a.Id, DefKind.Archetype);
            Removals(changes, from.Rooms, to.Rooms, r => r.Id, DefKind.Room);
            Puts(changes, from.Rooms, to.Rooms, r => r.Id);
            Puts(changes, from.Archetypes, to.Archetypes, a => a.Id);
            Puts(changes, from.Places, to.Places, p => p.Id);
            Puts(changes, from.Objects, to.Objects, o => o.Id);
            Puts(changes, from.Actors, to.Actors, a => a.Id);
            return changes;
        }

        static void Removals<T>(List<DefChange> changes, List<T> from, List<T> to, System.Func<T, string> id, DefKind kind)
        {
            var keep = new HashSet<string>(to.Select(id));
            foreach (var item in from.Where(i => !keep.Contains(id(i))))
                changes.Add(new DefRemove { Of = kind, Id = id(item) });
        }

        static void Puts<T>(List<DefChange> changes, List<T> from, List<T> to, System.Func<T, string> id) where T : DefItem
        {
            var before = from.ToDictionary(id, i => Canonical(i));
            foreach (var item in to)
                if (!before.TryGetValue(id(item), out var old) || !JToken.DeepEquals(old, Canonical(item)))
                    changes.Add(new DefPut { Item = item });
        }

        static JToken Canonical(object o) => JToken.Parse(WireJson.Write(o));

        public static string Describe(DefChange c) => c switch
        {
            DefPut p => $"+ {p.Item.Kind} {IdOf(p.Item)}",
            DefRemove r => $"− {WireJson.Name(r.Of)} {r.Id}",
            _ => "?",
        };

        static string IdOf(DefItem item) => item switch
        {
            RoomDef r => r.Id,
            PlaceDef p => p.Id,
            ArchetypeDef a => a.Id,
            ObjectDef o => o.Id,
            ActorDef a => a.Id,
            _ => "?",
        };
    }
}
