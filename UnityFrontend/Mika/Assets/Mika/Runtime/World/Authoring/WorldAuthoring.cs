using System;
using System.Collections.Generic;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.World.Engine.Authoring
{
    /// <summary>
    /// La racine d'un monde dans une scène : ce que le créateur pose ici (pièces, lieux, objets, personnages)
    /// devient la définition que le noyau tient (<see cref="WorldDefExporter"/>), et c'est aussi ce que le jeu
    /// montre — la même scène sert à écrire le monde et à le jouer.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Monde/Monde (racine)")]
    public sealed class WorldAuthoring : MonoBehaviour
    {
        [Tooltip("Identifiant du monde (« chambre »).")]
        public string worldId = "chambre";
        [Tooltip("Comment elle le nomme (« sa chambre »).")]
        public string label = "sa chambre";
        [Tooltip("La révision du noyau sur laquelle cette scène a été écrite (pour éditer sans écraser).")]
        public long baseRev;
        [Tooltip("Ce que le moteur sait montrer : archétypes et prefabs.")]
        public AssetCatalog catalog;
    }
}
