using System;
using System.Collections.Generic;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.World.Engine.Authoring
{
    public enum HomeKind
    {
        /// <summary>Déduit de la scène : posé dans la place d'une surface, rangé dans un contenant, sinon au sol de la pièce.</summary>
        Auto,
        Room,
        On,
        In,
    }

    /// <summary>
    /// Un objet du monde. Son archétype dit ce qu'il est ; son emplacement de départ se déduit de la scène
    /// (posé sur la place d'une surface, rangé dans un contenant, ou dans la pièce près du lieu le plus proche).
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Monde/Objet")]
    public sealed class ObjectAuthoring : MonoBehaviour
    {
        public string id;
        public ArchetypeAsset archetype;
        [Tooltip("Ce qu'elle lit (« ta tasse rose ») ; vide : le nom de l'archétype.")]
        public string label;
        [Tooltip("État de départ (vide : celui de l'archétype).")]
        public string state;
        [Tooltip("À qui il est (« mika », un handle).")]
        public string owner;
        [Tooltip("Qui le lui a offert (un handle).")]
        public string givenBy;
        public Access access = Access.Anyone;
        public bool overrideSalience;
        [Range(0, 1)] public float salience = 0.3f;
        public List<string> tags = new List<string>();

        [Header("Emplacement de départ")]
        public HomeKind home = HomeKind.Auto;
        [Tooltip("Room : près de quel lieu (vide : le plus proche).")]
        public PlaceAuthoring near;
        [Tooltip("On / In : sur ou dans quel objet.")]
        public ObjectAuthoring support;
        [Tooltip("On : quelle place de la surface.")]
        [Min(0)] public int slot;
    }
}
