using System.Collections.Generic;
using System.Linq;
using Mika.World.Model;
using Mika.World.Protocol;

namespace Mika.App
{
    /// <summary>
    /// Montrer le monde quand le noyau ne répond pas : la définition lue sur disque, chaque chose à son
    /// emplacement de départ, rien ne bouge. Ce n'est pas un second noyau — aucune action n'est jouée ni
    /// validée — seulement une vitrine, marquée <see cref="WorldMirror.Provisional"/> pour qu'à la connexion on
    /// redemande tout au vrai noyau.
    /// </summary>
    public static class OfflinePreview
    {
        public static void Apply(WorldMirror mirror, WorldDef def)
        {
            var index = WorldIndex.Of(def);
            var actors = def.Actors.Select(a =>
            {
                var place = index.Place(a.Home);
                return new ActorState
                {
                    Id = a.Id,
                    Room = place?.Room ?? def.Rooms.FirstOrDefault()?.Id,
                    Place = a.Home,
                    Posture = place?.PlaceKind == PlaceKind.Seat ? Posture.Sit : Posture.Stand,
                };
            }).ToList();
            var objects = def.Objects.Select(o => new ObjectState
            {
                Id = o.Id,
                Location = o.Home,
                State = o.State ?? index.Archetype(o.Archetype)?.InitialState,
            }).ToList();
            mirror.Apply(new Definition { World = def });
            mirror.Apply(new Snapshot
            {
                State = new WorldState
                {
                    Rev = def.Rev, Seq = 0, Actors = actors, Objects = objects,
                    Intents = new List<Intent>(), Requests = new List<Request>(),
                },
            });
            mirror.Provisional = true;
        }
    }
}
