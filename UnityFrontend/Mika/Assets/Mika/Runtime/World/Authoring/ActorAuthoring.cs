using System;
using System.Collections.Generic;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.World.Engine.Authoring
{
    /// <summary>Un personnage déclaré : Mika (« mika »), ou un personnage du monde que le moteur fait vivre (« npc:moka »).</summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Monde/Personnage")]
    public sealed class ActorAuthoring : MonoBehaviour
    {
        public string id = "mika";
        public string label = "Mika";
        [Tooltip("Clé d'asset de son corps (« avatars/mika »).")]
        public string assetKey = "avatars/mika";
        public PlaceAuthoring home;
        public Controller controller = Controller.Kernel;
        public List<string> tags = new List<string>();
    }
}
