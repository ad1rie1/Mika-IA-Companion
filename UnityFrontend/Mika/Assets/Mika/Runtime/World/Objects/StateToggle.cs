using System;
using System.Collections.Generic;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>Montre certains enfants dans un état, d'autres dans un autre (une tasse pleine ou vide).</summary>
    [AddComponentMenu("Mika/Monde/État · Afficher / masquer")]
    public sealed class StateToggle : StateVisual
    {
        [Serializable]
        public sealed class Entry
        {
            public string state;
            public List<GameObject> show = new List<GameObject>();
            public List<GameObject> hide = new List<GameObject>();
        }

        public List<Entry> states = new List<Entry>();

        public override void Apply(string state, bool instant)
        {
            foreach (var e in states)
            {
                if (e.state != state) continue;
                foreach (var g in e.show) if (g != null) g.SetActive(true);
                foreach (var g in e.hide) if (g != null) g.SetActive(false);
            }
        }
    }
}
