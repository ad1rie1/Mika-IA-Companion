using System;
using System.Collections.Generic;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.World.Engine.Authoring
{
    /// <summary>Un passage d'une pièce à une autre : depuis le lieu <c>via</c>, on arrive au lieu <c>arrives</c> de la pièce <c>to</c>.</summary>
    [Serializable]
    public sealed class ExitSpec
    {
        public PlaceAuthoring via;
        public RoomAuthoring to;
        public PlaceAuthoring arrives;
    }

    /// <summary>
    /// Une pièce. Sa transformation est l'origine de l'« espace de la pièce » du protocole : les lieux et les
    /// objets qu'elle contient (ses enfants) y sont mesurés.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Monde/Pièce")]
    public sealed class RoomAuthoring : MonoBehaviour
    {
        public string id = "bedroom";
        [Tooltip("Ce qu'elle lit (« ta chambre »).")]
        public string label = "ta chambre";
        public List<ExitSpec> exits = new List<ExitSpec>();
        public List<string> tags = new List<string>();

        /// <summary>Une position Unity (monde) dans l'espace de cette pièce.</summary>
        public Vector3 ToRoom(Vector3 world) => transform.InverseTransformPoint(world);

        /// <summary>Une position de l'espace de la pièce en position Unity (monde).</summary>
        public Vector3 ToWorld(Vector3 local) => transform.TransformPoint(local);

        public static RoomAuthoring Of(Component c) => c.GetComponentInParent<RoomAuthoring>(true);
    }
}
