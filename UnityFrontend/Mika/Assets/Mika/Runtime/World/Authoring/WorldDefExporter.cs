using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.World.Engine.Authoring
{
    /// <summary>
    /// Lit une scène écrite par le créateur et en tire la définition du monde que le noyau tient
    /// (<see cref="WorldDef"/>) : pièces, lieux (positions mesurées dans l'espace de leur pièce), archétypes,
    /// objets (leur emplacement de départ déduit de la scène), personnages. Ce qui ne peut pas passer — un
    /// identifiant invalide, un nom trop long, deux choses du même nom — est dit d'un coup, comme le noyau le
    /// fera ; le noyau reste juge de la cohérence complète.
    /// </summary>
    public static class WorldDefExporter
    {
        static readonly Regex Id = new Regex("^[a-z][a-z0-9_]{0,47}$");
        static readonly Regex Label = new Regex("^[^\\x00-\\x1f\\x7f]{1,60}$");

        public static WorldDef Export(WorldAuthoring root, List<string> problems)
        {
            var rooms = root.GetComponentsInChildren<RoomAuthoring>(true);
            var places = root.GetComponentsInChildren<PlaceAuthoring>(true);
            var objects = root.GetComponentsInChildren<ObjectAuthoring>(true);
            var actors = root.GetComponentsInChildren<ActorAuthoring>(true);

            var shared = new Dictionary<string, Object>();
            void Claim(string id, Object owner, string what)
            {
                if (string.IsNullOrEmpty(id) || !Id.IsMatch(id))
                    problems.Add($"{what} « {id} » ({owner.name}) : identifiant invalide ([a-z][a-z0-9_]*, 48 caractères au plus).");
                else if (shared.TryGetValue(id, out var other) && other != owner)
                    problems.Add($"« {id} » est pris deux fois ({other.name} et {owner.name}) : pièces, lieux et objets partagent un seul espace de noms.");
                else
                    shared[id] = owner;
            }
            void CheckLabel(string label, Object owner)
            {
                if (string.IsNullOrEmpty(label) || !Label.IsMatch(label))
                    problems.Add($"{owner.name} : nom absent, trop long (60 au plus) ou sur plusieurs lignes.");
            }

            var def = new WorldDef { Id = root.worldId, Label = root.label, Rev = root.baseRev };
            CheckLabel(root.label, root);

            foreach (var r in rooms)
            {
                Claim(r.id, r, "Pièce");
                CheckLabel(r.label, r);
                def.Rooms.Add(new RoomDef
                {
                    Id = r.id,
                    Label = r.label,
                    Tags = r.tags.ToList(),
                    Exits = r.exits.Where(e => e.via != null && e.to != null && e.arrives != null)
                        .Select(e => new Exit { Via = e.via.id, To = e.to.id, Arrives = e.arrives.id }).ToList(),
                });
            }

            foreach (var p in places)
            {
                Claim(p.id, p, "Lieu");
                CheckLabel(p.label, p);
                var room = RoomAuthoring.Of(p);
                if (room == null)
                {
                    problems.Add($"Lieu « {p.id} » : il n'est dans aucune pièce (placez-le sous une Pièce).");
                    continue;
                }
                var local = room.transform.InverseTransformPoint(p.transform.position);
                var rot = Quaternion.Inverse(room.transform.rotation) * p.transform.rotation;
                def.Places.Add(new PlaceDef
                {
                    Id = p.id,
                    Room = room.id,
                    Label = p.label,
                    PlaceKind = p.kind,
                    Capacity = Mathf.Max(1, p.capacity),
                    Pos = RoomSpace.ToPos(local),
                    Facing = RoomSpace.FacingOf(rot),
                    OfObject = p.ofObject != null ? p.ofObject.id : null,
                    Tags = p.tags.ToList(),
                });
            }

            var archetypes = new Dictionary<string, ArchetypeAsset>();
            var surfaceHomes = AssignSurfaces(objects, problems);
            foreach (var o in objects)
            {
                Claim(o.id, o, "Objet");
                if (o.archetype == null)
                {
                    problems.Add($"Objet « {o.id} » : pas d'archétype.");
                    continue;
                }
                if (!string.IsNullOrEmpty(o.label)) CheckLabel(o.label, o);
                archetypes[o.archetype.id] = o.archetype;
                def.Objects.Add(new ObjectDef
                {
                    Id = o.id,
                    Archetype = o.archetype.id,
                    Label = string.IsNullOrEmpty(o.label) ? null : o.label,
                    Home = surfaceHomes.TryGetValue(o, out var on) ? on : HomeOf(o, places, problems),
                    State = string.IsNullOrEmpty(o.state) ? null : o.state,
                    Owner = string.IsNullOrEmpty(o.owner) ? null : o.owner,
                    GivenBy = string.IsNullOrEmpty(o.givenBy) ? null : o.givenBy,
                    Access = o.access,
                    Salience = o.overrideSalience ? System.Math.Round((double)o.salience, 4) : (double?)null,
                    Tags = o.tags.ToList(),
                });
            }
            foreach (var a in archetypes.Values.OrderBy(a => a.id))
            {
                if (string.IsNullOrEmpty(a.id) || !Id.IsMatch(a.id))
                    problems.Add($"Archétype « {a.id} » ({a.name}) : identifiant invalide.");
                CheckLabel(a.label, a);
                def.Archetypes.Add(a.ToDef());
            }

            foreach (var a in actors)
            {
                CheckLabel(a.label, a);
                if (a.home == null) problems.Add($"Personnage « {a.id} » : pas de lieu de départ.");
                def.Actors.Add(new ActorDef
                {
                    Id = a.id,
                    Label = a.label,
                    Asset = a.assetKey,
                    Home = a.home != null ? a.home.id : null,
                    Controller = a.controller,
                    Tags = a.tags.ToList(),
                });
            }
            if (!def.Actors.Any(a => a.Id == "mika"))
                problems.Add("Le monde n'a pas de Mika (un Personnage d'identifiant « mika »).");
            return def;
        }

        /// <summary>
        /// L'emplacement de départ d'un objet : déclaré, ou déduit — posé sur la place de surface la plus proche
        /// sous lui (à 25 cm près), sinon dans sa pièce près du lieu le plus proche.
        /// </summary>
        public static Location HomeOf(ObjectAuthoring o, IReadOnlyList<PlaceAuthoring> places, List<string> problems)
        {
            switch (o.home)
            {
                case HomeKind.On when o.support != null:
                    return new On { Object = o.support.id, Slot = o.slot };
                case HomeKind.In when o.support != null:
                    return new In { Object = o.support.id };
                case HomeKind.Room:
                {
                    var room = RoomAuthoring.Of(o);
                    return new InRoom { Room = room != null ? room.id : null, Near = (o.near != null ? o.near : Nearest(o.transform.position, room, places))?.id };
                }
            }
            var r = RoomAuthoring.Of(o);
            if (r == null) problems?.Add($"Objet « {o.id} » : il n'est dans aucune pièce.");
            return new InRoom { Room = r != null ? r.id : null, Near = Nearest(o.transform.position, r, places)?.id };
        }

        /// <summary>
        /// Les objets posés sur une surface (emplacement « Auto ») : chacun reçoit la place libre la plus proche
        /// sous lui, une place n'en portant qu'un (règle du noyau). On attribue d'abord les paires les plus
        /// proches, de sorte qu'un objet bien centré sur sa place la garde. Un objet sans place libre est signalé.
        /// </summary>
        public static Dictionary<ObjectAuthoring, Location> AssignSurfaces(IReadOnlyList<ObjectAuthoring> objects, List<string> problems)
        {
            var result = new Dictionary<ObjectAuthoring, Location>();
            var slots = Object.FindObjectsByType<SurfaceSlot>(FindObjectsInactive.Exclude)
                .Select(s => (slot: s, owner: s.GetComponentInParent<ObjectAuthoring>()))
                .Where(s => s.owner != null)
                .ToList();
            var candidates = new List<(ObjectAuthoring obj, SurfaceSlot slot, ObjectAuthoring owner, float d)>();
            var onSurface = new HashSet<ObjectAuthoring>();
            foreach (var o in objects.Where(o => o.home == HomeKind.Auto))
            {
                var pos = o.transform.position;
                foreach (var (slot, owner) in slots)
                {
                    if (owner == o || slot.transform.IsChildOf(o.transform)) continue;
                    var d = slot.transform.position - pos;
                    // Sur (ou un peu au-dessus de) la surface : un objet empilé sur un autre reste sur le meuble.
                    if (d.y > 0.06f || d.y < -0.35f) continue;
                    if (!OverSupport(owner, pos)) continue;
                    onSurface.Add(o);
                    candidates.Add((o, slot, owner, new Vector2(d.x, d.z).magnitude));
                }
            }
            var taken = new HashSet<(ObjectAuthoring, int)>();
            foreach (var c in candidates.OrderBy(c => c.d))
            {
                if (result.ContainsKey(c.obj) || taken.Contains((c.owner, c.slot.index))) continue;
                result[c.obj] = new On { Object = c.owner.id, Slot = c.slot.index };
                taken.Add((c.owner, c.slot.index));
            }
            foreach (var o in onSurface.Where(o => !result.ContainsKey(o)))
                problems.Add($"« {o.id} » est posé sur un meuble qui n'a plus de place libre : ajoutez une place (SurfaceSlot) ou déplacez-le.");
            return result;
        }

        /// <summary>La position est-elle au-dessus de l'emprise du meuble (à 5 cm près) ?</summary>
        static bool OverSupport(ObjectAuthoring support, Vector3 position)
        {
            var renderers = support.GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0) return true;
            var b = renderers[0].bounds;
            foreach (var r in renderers.Skip(1)) b.Encapsulate(r.bounds);
            return position.x >= b.min.x - 0.05f && position.x <= b.max.x + 0.05f && position.z >= b.min.z - 0.05f && position.z <= b.max.z + 0.05f;
        }

        static PlaceAuthoring Nearest(Vector3 position, RoomAuthoring room, IReadOnlyList<PlaceAuthoring> places)
        {
            PlaceAuthoring best = null;
            var bestD = float.MaxValue;
            foreach (var p in places)
            {
                if (room != null && RoomAuthoring.Of(p) != room) continue;
                var d = (p.transform.position - position).sqrMagnitude;
                if (d < bestD)
                {
                    bestD = d;
                    best = p;
                }
            }
            return best;
        }
    }
}
