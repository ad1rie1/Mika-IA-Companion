using System;
using System.Collections.Generic;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.World.Engine.Authoring
{
    /// <summary>
    /// Un endroit où se tenir : sa position est le point d'approche (où l'on arrive à pied), son orientation est
    /// le sens dans lequel on s'y tient. Une assise ou un lit portent en plus où vont les hanches (<see cref="seat"/>)
    /// et la pose allongée (<see cref="lie"/>).
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Monde/Lieu")]
    public sealed class PlaceAuthoring : MonoBehaviour
    {
        public string id = "center";
        [Tooltip("Ce qu'elle lit (« à la fenêtre »).")]
        public string label = "au milieu de la pièce";
        public PlaceKind kind = PlaceKind.Spot;
        [Min(1)] public int capacity = 1;
        [Tooltip("Le meuble qui porte ce lieu (une chaise, un lit).")]
        public ObjectAuthoring ofObject;
        [Tooltip("sleep : où elle dort ; work : où elle travaille ; spawn : où entre une personne.")]
        public List<string> tags = new List<string>();
        [Tooltip("Assise / lit : où vont les hanches (orientation = sens assis).")]
        public Transform seat;
        [Tooltip("Lit : la racine du corps allongé (orientation = sens de la tête).")]
        public Transform lie;

        public Vector3 SeatPosition => seat != null ? seat.position : transform.position + Vector3.up * 0.45f;
        public Quaternion SeatRotation => seat != null ? seat.rotation : transform.rotation;

        void OnDrawGizmos()
        {
            Gizmos.color = kind == PlaceKind.Spot ? new Color(0.3f, 0.8f, 1f, 0.8f) : kind == PlaceKind.Seat ? new Color(1f, 0.75f, 0.2f, 0.8f) : new Color(0.8f, 0.4f, 1f, 0.8f);
            Gizmos.DrawWireSphere(transform.position + Vector3.up * 0.02f, 0.25f);
            Gizmos.DrawLine(transform.position + Vector3.up * 0.02f, transform.position + Vector3.up * 0.02f + transform.forward * 0.5f);
            if (seat != null) Gizmos.DrawWireCube(seat.position, new Vector3(0.35f, 0.05f, 0.35f));
        }
    }
}
