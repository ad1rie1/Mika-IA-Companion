using System.Collections.Generic;
using Mika.World.Engine;
using Mika.World.Protocol;

namespace Mika.Editor.Import
{
    /// <summary>
    /// Les sortes d'objets de la chambre, telles qu'un créateur les décrirait : ce qu'elles sont, leurs états,
    /// ce qu'on peut en faire. Les neuf archétypes du monde par défaut du noyau sont relus depuis son fichier
    /// (ils font foi) ; ceux-ci complètent la bibliothèque pour les objets que le créateur fera entrer dans le
    /// monde (une tasse qu'on boit, un livre qu'on lit, une lampe qu'on allume).
    /// </summary>
    public static class ArchetypeLibrary
    {
        public sealed class Kind
        {
            public string Id;
            public string Label;
            public Size Size;
            public string[] States = new string[0];
            public string Initial;
            public (string state, string label)[] StateLabels = new (string, string)[0];
            public AffordanceSpec[] Affordances = new AffordanceSpec[0];
            public int SurfaceSlots;
            public int ContainerSlots;
            public float Salience = 0.3f;
        }

        static AffordanceSpec Toggle(string id, string label, string from, string to, float duration = 1.2f) =>
            new AffordanceSpec { id = id, label = label, effect = Effect.State, requiresState = new List<string> { from }, toState = to, durationS = duration };

        static AffordanceSpec Activity(string id, string label, string activity, float? duration, bool held = false) =>
            new AffordanceSpec { id = id, label = label, effect = Effect.Activity, activity = activity, held = held, durationS = duration ?? 0, untilInterrupted = duration == null };

        public static readonly Dictionary<string, Kind> Kinds = new Dictionary<string, Kind>
        {
            ["mug"] = new Kind
            {
                Id = "mug", Label = "tasse", Size = Size.Hand, States = new[] { "full", "empty" }, Initial = "full",
                StateLabels = new[] { ("full", "pleine"), ("empty", "vide") },
                Affordances = new[] { new AffordanceSpec { id = "boire", label = "boire", effect = Effect.State, requiresState = new List<string> { "full" }, toState = "empty", held = true, durationS = 4f } },
                Salience = 0.5f,
            },
            ["book"] = new Kind { Id = "book", Label = "livre", Size = Size.Hand, Affordances = new[] { Activity("lire", "lire", "read", null, held: true) }, Salience = 0.45f },
            ["sketchbook"] = new Kind { Id = "sketchbook", Label = "carnet", Size = Size.Hand, Affordances = new[] { Activity("dessiner", "dessiner", "draw", null, held: true) }, Salience = 0.5f },
            ["pen"] = new Kind { Id = "pen", Label = "stylo", Size = Size.Hand, Salience = 0.1f },
            ["lamp"] = new Kind
            {
                Id = "lamp", Label = "lampe", Size = Size.Hand, States = new[] { "on", "off" }, Initial = "on",
                StateLabels = new[] { ("on", "allumée"), ("off", "éteinte") },
                Affordances = new[] { Toggle("allumer", "allumer", "off", "on", 0.8f), Toggle("eteindre", "éteindre", "on", "off", 0.8f) },
                Salience = 0.4f,
            },
            ["ceiling_light"] = new Kind
            {
                Id = "ceiling_light", Label = "plafonnier", Size = Size.Fixed, States = new[] { "on", "off" }, Initial = "on",
                StateLabels = new[] { ("on", "allumé"), ("off", "éteint") },
                Affordances = new[] { Toggle("allumer", "allumer la lumière", "off", "on", 0.8f), Toggle("eteindre", "éteindre la lumière", "on", "off", 0.8f) },
                Salience = 0.3f,
            },
            ["monitor"] = new Kind
            {
                Id = "monitor", Label = "écran", Size = Size.Fixed, States = new[] { "off", "on" }, Initial = "on",
                StateLabels = new[] { ("on", "allumé"), ("off", "éteint") },
                Affordances = new[] { Toggle("allumer", "allumer", "off", "on"), Toggle("eteindre", "éteindre", "on", "off") },
                Salience = 0.4f,
            },
            ["candle"] = new Kind
            {
                Id = "candle", Label = "bougie", Size = Size.Hand, States = new[] { "lit", "out" }, Initial = "lit",
                StateLabels = new[] { ("lit", "allumée"), ("out", "éteinte") },
                Affordances = new[] { Toggle("allumer", "allumer", "out", "lit", 1.5f), Toggle("souffler", "souffler", "lit", "out", 1f) },
                Salience = 0.35f,
            },
            ["night_light"] = new Kind
            {
                Id = "night_light", Label = "veilleuse", Size = Size.Hand, States = new[] { "on", "off" }, Initial = "on",
                StateLabels = new[] { ("on", "allumée"), ("off", "éteinte") },
                Affordances = new[] { Toggle("allumer", "allumer", "off", "on", 0.6f), Toggle("eteindre", "éteindre", "on", "off", 0.6f) },
                Salience = 0.3f,
            },
            ["plushie"] = new Kind { Id = "plushie", Label = "peluche", Size = Size.Hand, Affordances = new[] { Activity("calin", "câliner", "hug_plush", 6f, held: true) }, Salience = 0.55f },
            ["small_plant"] = new Kind { Id = "small_plant", Label = "petite plante", Size = Size.Hand, Affordances = new[] { Activity("arroser", "arroser", "water_plant", 6f) }, Salience = 0.35f },
            ["alarm_clock"] = new Kind { Id = "alarm_clock", Label = "réveil", Size = Size.Hand, Salience = 0.2f },
            ["slippers"] = new Kind { Id = "slippers", Label = "chaussons", Size = Size.Hand, Salience = 0.15f },
            ["basket"] = new Kind { Id = "basket", Label = "panier", Size = Size.Arms, ContainerSlots = 6, Salience = 0.2f },
            ["storage_box"] = new Kind { Id = "storage_box", Label = "boîte de rangement", Size = Size.Arms, ContainerSlots = 6, Salience = 0.15f },
            ["bag"] = new Kind { Id = "bag", Label = "sac", Size = Size.Hand, ContainerSlots = 4, Salience = 0.2f },
            ["bin"] = new Kind { Id = "bin", Label = "poubelle", Size = Size.Hand, ContainerSlots = 10, Salience = 0.1f },
            ["paper_ball"] = new Kind { Id = "paper_ball", Label = "boule de papier", Size = Size.Hand, Salience = 0.15f },
            ["speaker"] = new Kind
            {
                Id = "speaker", Label = "enceinte", Size = Size.Hand, States = new[] { "off", "on" }, Initial = "off",
                StateLabels = new[] { ("on", "qui joue de la musique"), ("off", "éteinte") },
                Affordances = new[] { Toggle("musique", "mettre de la musique", "off", "on", 1f), Toggle("couper", "couper la musique", "on", "off", 1f) },
                Salience = 0.35f,
            },
            ["jewelry_box"] = new Kind
            {
                Id = "jewelry_box", Label = "boîte à bijoux", Size = Size.Hand, States = new[] { "closed", "open" }, Initial = "closed",
                StateLabels = new[] { ("closed", "fermée"), ("open", "ouverte") },
                Affordances = new[] { Toggle("ouvrir", "ouvrir", "closed", "open"), Toggle("fermer", "fermer", "open", "closed") },
                ContainerSlots = 4, Salience = 0.3f,
            },
            ["trinket"] = new Kind { Id = "trinket", Label = "bibelot", Size = Size.Hand, Salience = 0.2f },
            ["cushion"] = new Kind { Id = "cushion", Label = "coussin de sol", Size = Size.Arms, Salience = 0.25f },
            ["scarf"] = new Kind { Id = "scarf", Label = "écharpe", Size = Size.Hand, Salience = 0.15f },
            ["curtains"] = new Kind
            {
                Id = "curtains", Label = "rideaux", Size = Size.Fixed, States = new[] { "open", "closed" }, Initial = "open",
                StateLabels = new[] { ("open", "ouverts"), ("closed", "tirés") },
                Affordances = new[] { Toggle("tirer", "tirer les rideaux", "open", "closed", 2f), Toggle("ouvrir", "ouvrir les rideaux", "closed", "open", 2f) },
                Salience = 0.3f,
            },
            ["dresser"] = new Kind { Id = "dresser", Label = "commode", Size = Size.Fixed, SurfaceSlots = 3, ContainerSlots = 8, Salience = 0.3f },
            ["wall_shelf"] = new Kind { Id = "wall_shelf", Label = "étagère murale", Size = Size.Fixed, SurfaceSlots = 3, Salience = 0.2f },
        };

        /// <summary>Quel archétype et quel nom pour chaque objet de la chambre (hors monde par défaut du noyau).</summary>
        public static readonly Dictionary<string, (string kind, string label)> Objects = new Dictionary<string, (string, string)>
        {
            ["mug"] = ("mug", "ta tasse rose"),
            ["notebook"] = ("sketchbook", "ton carnet de croquis"),
            ["pen"] = ("pen", "ton stylo"),
            ["book_desk_1"] = ("book", "un livre sur ton bureau"),
            ["book_desk_2"] = ("book", "un autre livre sur ton bureau"),
            ["book_nightstand_1"] = ("book", "le livre de ta table de chevet"),
            ["book_nightstand_2"] = ("book", "un second livre de chevet"),
            ["open_book"] = ("book", "le livre ouvert sur le coussin"),
            ["desk_lamp"] = ("lamp", "ta lampe de bureau"),
            ["bedside_lamp"] = ("lamp", "ta lampe de chevet"),
            ["ceiling_lamp"] = ("ceiling_light", "le plafonnier"),
            ["monitor"] = ("monitor", "ton écran"),
            ["candle"] = ("candle", "ta bougie"),
            ["moon_lamp"] = ("night_light", "ta lampe lune"),
            ["star_lamp"] = ("night_light", "ta lampe étoile"),
            ["plushie"] = ("plushie", "ta peluche"),
            ["pothos"] = ("small_plant", "ton pothos"),
            ["cactus_windowsill"] = ("small_plant", "le cactus de la fenêtre"),
            ["succulent_windowsill"] = ("small_plant", "la plante grasse de la fenêtre"),
            ["succulent_desk"] = ("small_plant", "la plante grasse du bureau"),
            ["cactus_bookshelf"] = ("small_plant", "le cactus de la bibliothèque"),
            ["cactus_trinket_shelf"] = ("small_plant", "le cactus de l'étagère"),
            ["alarm_clock"] = ("alarm_clock", "ton réveil"),
            ["slippers"] = ("slippers", "tes chaussons"),
            ["laundry_basket"] = ("basket", "ton panier à linge"),
            ["shelf_basket_1"] = ("storage_box", "un panier de la bibliothèque"),
            ["shelf_basket_2"] = ("storage_box", "un autre panier de la bibliothèque"),
            ["storage_box_bookshelf"] = ("storage_box", "la boîte en haut de la bibliothèque"),
            ["wardrobe_box_a"] = ("storage_box", "une boîte sur l'armoire"),
            ["wardrobe_box_b"] = ("storage_box", "une autre boîte sur l'armoire"),
            ["tote_bag"] = ("bag", "ton tote bag"),
            ["waste_bin"] = ("bin", "ta corbeille"),
            ["paper_ball"] = ("paper_ball", "une boule de papier"),
            ["speaker"] = ("speaker", "ton enceinte"),
            ["jewelry_box"] = ("jewelry_box", "ta boîte à bijoux"),
            ["perfume_bottle"] = ("trinket", "ton flacon de parfum"),
            ["dried_flowers"] = ("trinket", "tes fleurs séchées"),
            ["vase_bookshelf"] = ("trinket", "le vase de la bibliothèque"),
            ["bunny_figurine"] = ("trinket", "la figurine lapin"),
            ["cat_figurine"] = ("trinket", "la figurine chat"),
            ["photo_frame_bookshelf"] = ("trinket", "le cadre photo de la bibliothèque"),
            ["photo_frame_trinket_shelf"] = ("trinket", "le cadre photo de l'étagère"),
            ["floor_cushion"] = ("cushion", "ton coussin de sol"),
            ["book_stack_floor"] = ("book", "la pile de livres par terre"),
            ["scarf"] = ("scarf", "ton écharpe"),
            ["curtains"] = ("curtains", "tes rideaux"),
            ["dresser"] = ("dresser", "ta commode"),
            ["trinket_shelf"] = ("wall_shelf", "ton étagère à bibelots"),
        };
    }
}
