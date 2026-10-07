using System;
using System.Collections.Generic;
using System.Linq;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>Une action qu'un archétype permet (allumer, arroser, lire) — l'affordance du protocole, éditable.</summary>
    [Serializable]
    public sealed class AffordanceSpec
    {
        [Tooltip("Identifiant libre, en minuscules (« allumer »).")]
        public string id;
        [Tooltip("Ce qu'elle lit (« allumer »).")]
        public string label;
        public Effect effect = Effect.State;
        [Tooltip("État d'arrivée (effet « state »).")]
        public string toState;
        [Tooltip("États où l'action est possible (vide : toujours).")]
        public List<string> requiresState = new List<string>();
        [Tooltip("Occupation (effet « activity ») : read, look_outside…")]
        public string activity;
        [Tooltip("Il faut tenir l'objet.")]
        public bool held;
        [Tooltip("Durée nominale (s).")]
        public float durationS = 2f;
        [Tooltip("Coché : l'occupation dure jusqu'à ce qu'on l'interrompe (durée nulle).")]
        public bool untilInterrupted;
        [Tooltip("Qui d'autre qu'elle a le droit (vide : celui de l'objet).")]
        public bool overrideAccess;
        public Access access = Access.Anyone;
        [Range(0, 1)] public float noise;
        [Tooltip("Clé d'animation du moteur (état de l'Animator).")]
        public string animation;
        [Tooltip("Occupation (effet « activity ») : les besoins qu'elle nourrit chez Mika (expression, curiosity).")]
        public List<Nourished> nourishes = new List<Nourished>();

        public Affordance ToDef() => new Affordance
        {
            Id = id,
            Label = label,
            Effect = effect,
            ToState = effect == Effect.State ? NullIfEmpty(toState) : null,
            RequiresState = requiresState?.Where(s => !string.IsNullOrWhiteSpace(s)).ToList() ?? new List<string>(),
            Activity = effect == Effect.Activity ? NullIfEmpty(activity) : null,
            Held = held,
            DurationS = untilInterrupted ? (double?)null : Round(durationS),
            Access = overrideAccess ? access : (Access?)null,
            Noise = Round(noise),
            Animation = NullIfEmpty(animation),
            Nourishes = effect == Effect.Activity ? nourishes?.ToList() ?? new List<Nourished>() : new List<Nourished>(),
        };

        public static AffordanceSpec From(Affordance a) => new AffordanceSpec
        {
            id = a.Id,
            label = a.Label,
            effect = a.Effect,
            toState = a.ToState,
            requiresState = a.RequiresState?.ToList() ?? new List<string>(),
            activity = a.Activity,
            held = a.Held,
            durationS = (float)(a.DurationS ?? 0),
            untilInterrupted = a.DurationS == null,
            overrideAccess = a.Access != null,
            access = a.Access ?? Access.Anyone,
            noise = (float)a.Noise,
            animation = a.Animation,
            nourishes = a.Nourishes?.ToList() ?? new List<Nourished>(),
        };

        internal static string NullIfEmpty(string s) => string.IsNullOrWhiteSpace(s) ? null : s.Trim();

        /// <summary>Un réglage d'inspecteur (float) tel qu'on l'a tapé : 0.7, pas 0.699999988.</summary>
        internal static double Round(float v) => Math.Round((double)v, 4);
    }

    [Serializable]
    public sealed class StateLabel
    {
        public string state;
        public string label;
    }

    /// <summary>
    /// Une sorte d'objet — la tasse, la lampe, l'étagère — telle que le créateur la décrit : ce que le noyau en
    /// sait (états, actions, places, saillance) et ce que le moteur en montre (le prefab). Le noyau ne reçoit
    /// que la première moitié (<see cref="ToDef"/>) ; le prefab reste ici, désigné par sa clé <see cref="assetKey"/>.
    /// </summary>
    [CreateAssetMenu(menuName = "Mika/Monde/Archétype d'objet", fileName = "Archetype")]
    public sealed class ArchetypeAsset : ScriptableObject
    {
        [Tooltip("Identifiant de l'archétype ([a-z][a-z0-9_]*).")]
        public string id;
        [Tooltip("Ce qu'elle lit (« lampe de bureau »), 60 caractères au plus.")]
        public string label;
        [Tooltip("Clé d'asset du moteur (« props/mug ») : c'est elle que le noyau garde.")]
        public string assetKey;
        [Tooltip("Ce qui est montré : le prefab de l'objet (avec son WorldObject).")]
        public GameObject prefab;
        public Size size = Size.Hand;
        public List<string> states = new List<string>();
        public string initialState;
        public List<StateLabel> stateLabels = new List<StateLabel>();
        public List<AffordanceSpec> affordances = new List<AffordanceSpec>();
        [Min(0)] public int surfaceSlots;
        [Min(0)] public int containerSlots;
        [Range(0, 1)] public float salience = 0.3f;
        public List<string> tags = new List<string>();

        public ArchetypeDef ToDef() => new ArchetypeDef
        {
            Id = id,
            Label = label,
            Asset = assetKey,
            Size = size,
            States = states?.Where(s => !string.IsNullOrWhiteSpace(s)).ToList() ?? new List<string>(),
            InitialState = AffordanceSpec.NullIfEmpty(initialState),
            StateLabels = stateLabels?.Where(l => !string.IsNullOrWhiteSpace(l.state) && !string.IsNullOrWhiteSpace(l.label))
                .ToDictionary(l => l.state, l => l.label) ?? new Dictionary<string, string>(),
            Affordances = affordances?.Select(a => a.ToDef()).ToList() ?? new List<Affordance>(),
            SurfaceSlots = surfaceSlots,
            ContainerSlots = containerSlots,
            Salience = AffordanceSpec.Round(salience),
            Tags = tags?.ToList() ?? new List<string>(),
        };

        /// <summary>Recopie une définition reçue (import d'un monde) ; le prefab, lui, reste celui du moteur.</summary>
        public void CopyFrom(ArchetypeDef def)
        {
            id = def.Id;
            label = def.Label;
            assetKey = def.Asset;
            size = def.Size;
            states = def.States?.ToList() ?? new List<string>();
            initialState = def.InitialState;
            stateLabels = def.StateLabels?.Select(kv => new StateLabel { state = kv.Key, label = kv.Value }).ToList() ?? new List<StateLabel>();
            affordances = def.Affordances?.Select(AffordanceSpec.From).ToList() ?? new List<AffordanceSpec>();
            surfaceSlots = def.SurfaceSlots;
            containerSlots = def.ContainerSlots;
            salience = (float)def.Salience;
            tags = def.Tags?.ToList() ?? new List<string>();
        }
    }
}
