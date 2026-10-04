using System.Collections.Generic;
using System.Linq;
using Mika.World.Protocol;

namespace Mika.World.Model
{
    /// <summary>Une chose que la personne peut faire là, maintenant : ce qu'on lui affiche, et la commande qui part.</summary>
    public sealed class ActionOption
    {
        public string Label;
        /// <summary>La commande à envoyer (<c>act</c> ou <c>address</c>) ; son <c>cmd</c> est fixé à l'envoi.</summary>
        public ClientFrame Command;
        /// <summary>Le geste par défaut (touche d'action principale).</summary>
        public bool Primary;
    }

    /// <summary>
    /// Ce qu'une personne peut tenter sur ce qu'elle regarde, déduit de la définition et de l'état reçus. C'est
    /// un menu, pas une validation : le noyau reste seul juge (et dit pourquoi il refuse). On n'y propose que ce
    /// qui a une chance raisonnable de passer, pour ne pas faire choisir l'impossible.
    /// </summary>
    public static class ActionMenu
    {
        public static int HandsBusy(WorldMirror mirror, string actor)
        {
            var me = mirror.Actor(actor);
            if (me == null) return 0;
            var n = 0;
            foreach (var held in me.Holding)
                n += mirror.World?.ArchetypeOf(held)?.Size == Size.Arms ? 2 : 1;
            return n;
        }

        /// <summary>Les actions possibles sur un objet.</summary>
        public static List<ActionOption> ForObject(WorldMirror mirror, string actor, string objectId)
        {
            var options = new List<ActionOption>();
            var world = mirror.World;
            var def = world?.Object(objectId);
            var state = mirror.Object(objectId);
            if (def == null || state == null) return options;
            var archetype = world.Archetype(def.Archetype);
            var label = def.Label ?? archetype?.Label ?? objectId;
            var holder = mirror.HolderOf(objectId);
            var me = mirror.Actor(actor);
            var myHeld = me?.Holding?.FirstOrDefault();
            var busy = HandsBusy(mirror, actor);

            if (archetype != null && archetype.Size != Size.Fixed)
            {
                if (holder == null && busy + (archetype.Size == Size.Arms ? 2 : 1) <= 2)
                    options.Add(new ActionOption { Label = $"Prendre {label}", Command = new Act { Action = "take", Object = objectId }, Primary = true });
                else if (holder != null && holder != actor)
                    options.Add(new ActionOption { Label = $"Le demander ({label})", Command = new Address { To = holder, Request = RequestKind.Ask, Object = objectId } });
                else if (holder == actor)
                    options.Add(new ActionOption { Label = $"Lâcher {label}", Command = new Act { Action = "drop", Object = objectId } });
            }

            if (myHeld != null && myHeld != objectId && archetype != null)
            {
                var heldLabel = world.Object(myHeld)?.Label ?? world.ArchetypeOf(myHeld)?.Label ?? myHeld;
                var slot = FreeSlot(mirror, objectId, archetype.SurfaceSlots);
                if (slot >= 0)
                    options.Add(new ActionOption { Label = $"Poser {heldLabel} ici", Command = new Act { Action = "put", Object = myHeld, Target = new On { Object = objectId, Slot = slot } }, Primary = options.Count == 0 });
                else if (archetype.ContainerSlots > 0 && Contained(mirror, objectId) < archetype.ContainerSlots)
                    options.Add(new ActionOption { Label = $"Ranger {heldLabel} dedans", Command = new Act { Action = "put", Object = myHeld, Target = new In { Object = objectId } } });
            }

            if (archetype?.Affordances != null)
            {
                var current = state.State ?? archetype.InitialState;
                foreach (var a in archetype.Affordances)
                {
                    if (a.RequiresState != null && a.RequiresState.Count > 0 && !a.RequiresState.Contains(current)) continue;
                    if (a.Held && holder != actor) continue;
                    options.Add(new ActionOption { Label = Capitalize(a.Label), Command = new Act { Action = a.Id, Object = objectId }, Primary = options.Count == 0 });
                }
            }

            foreach (var place in world.Def.Places.Where(p => p.OfObject == objectId))
            {
                if (place.PlaceKind == PlaceKind.Seat || place.PlaceKind == PlaceKind.Bed)
                    options.Add(new ActionOption { Label = "S'asseoir", Command = new Act { Action = "sit", Place = place.Id }, Primary = options.Count == 0 });
                if (place.PlaceKind == PlaceKind.Bed)
                    options.Add(new ActionOption { Label = "S'allonger", Command = new Act { Action = "lie", Place = place.Id } });
            }
            return options;
        }

        /// <summary>Ce qu'on peut faire envers quelqu'un (Mika, une autre personne) : des gestes, des demandes.</summary>
        public static List<ActionOption> ForActor(WorldMirror mirror, string actor, string other)
        {
            var options = new List<ActionOption>();
            if (other == null || other == actor) return options;
            var me = mirror.Actor(actor);
            var them = mirror.Actor(other);
            var world = mirror.World;
            options.Add(new ActionOption { Label = "Faire coucou", Command = new Address { To = other, Gesture = Gesture.Wave }, Primary = true });
            var myHeld = me?.Holding?.FirstOrDefault();
            if (myHeld != null)
            {
                var label = world?.Object(myHeld)?.Label ?? world?.ArchetypeOf(myHeld)?.Label ?? myHeld;
                options.Add(new ActionOption { Label = $"Lui tendre {label}", Command = new Address { To = other, Request = RequestKind.Offer, Object = myHeld } });
            }
            var theirHeld = them?.Holding?.FirstOrDefault();
            if (theirHeld != null)
            {
                var label = world?.Object(theirHeld)?.Label ?? world?.ArchetypeOf(theirHeld)?.Label ?? theirHeld;
                options.Add(new ActionOption { Label = $"Lui demander {label}", Command = new Address { To = other, Request = RequestKind.Ask, Object = theirHeld } });
            }
            options.Add(new ActionOption { Label = "Lui faire un câlin", Command = new Address { To = other, Request = RequestKind.Hug } });
            options.Add(new ActionOption { Label = "Tope là", Command = new Address { To = other, Request = RequestKind.HighFive } });
            options.Add(new ActionOption { Label = "Lui prendre la main", Command = new Address { To = other, Request = RequestKind.HoldHand } });
            options.Add(new ActionOption { Label = "Lui caresser la tête", Command = new Address { To = other, Gesture = Gesture.PatHead } });
            options.Add(new ActionOption { Label = "Hocher la tête", Command = new Address { To = other, Gesture = Gesture.Nod } });
            options.Add(new ActionOption { Label = "Applaudir", Command = new Address { To = other, Gesture = Gesture.Clap } });
            options.Add(new ActionOption { Label = "La taquiner (pousser du doigt)", Command = new Address { To = other, Gesture = Gesture.Poke } });
            return options;
        }

        /// <summary>Ce que la personne peut faire d'elle-même (sans cible) : se lever, lâcher ce qu'elle tient.</summary>
        public static List<ActionOption> ForSelf(WorldMirror mirror, string actor)
        {
            var options = new List<ActionOption>();
            var me = mirror.Actor(actor);
            if (me == null) return options;
            if (me.Posture != Posture.Stand)
                options.Add(new ActionOption { Label = "Se lever", Command = new Act { Action = "stand" }, Primary = true });
            foreach (var held in me.Holding)
            {
                var label = mirror.World?.Object(held)?.Label ?? mirror.World?.ArchetypeOf(held)?.Label ?? held;
                options.Add(new ActionOption { Label = $"Lâcher {label}", Command = new Act { Action = "drop", Object = held } });
            }
            return options;
        }

        /// <summary>La première place libre d'une surface, -1 s'il n'y en a pas.</summary>
        public static int FreeSlot(WorldMirror mirror, string surfaceId, int slots)
        {
            if (slots <= 0) return -1;
            var taken = new HashSet<long>(mirror.Objects.Values
                .Select(o => o.Location as On)
                .Where(on => on != null && on.Object == surfaceId)
                .Select(on => (long)on.Slot));
            for (var i = 0; i < slots; i++)
                if (!taken.Contains(i)) return i;
            return -1;
        }

        static int Contained(WorldMirror mirror, string containerId) =>
            mirror.Objects.Values.Count(o => o.Location is In i && i.Object == containerId);

        static string Capitalize(string s) => string.IsNullOrEmpty(s) ? s : char.ToUpperInvariant(s[0]) + s.Substring(1);
    }
}
