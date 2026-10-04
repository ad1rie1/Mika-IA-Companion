using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// Ce qu'un état d'objet change à l'écran (une porte ouverte, une lampe allumée). Le noyau ne connaît que le
    /// nom de l'état ; chaque visuel décide de ce qu'il montre pour ce nom, et ignore ceux qu'il ne connaît pas.
    /// </summary>
    public abstract class StateVisual : MonoBehaviour
    {
        /// <param name="instant">Vrai pour poser l'état sans le jouer (un instantané, une scène qui s'ouvre).</param>
        public abstract void Apply(string state, bool instant);
    }
}
