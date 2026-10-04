using Mika.World.Protocol;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// L'espace de la pièce du protocole (celui du client web et de glTF : main droite, Y vers le haut, l'avant
    /// d'un lacet φ est <c>(sin φ, cos φ)</c>) et l'espace de Unity (main gauche). Passer de l'un à l'autre
    /// retourne l'axe X — exactement ce que font les importeurs FBX et glTF de Unity, si bien qu'un objet exporté
    /// de Blender et une position lue du noyau tombent au même endroit.
    /// </summary>
    /// <remarks>
    /// C'est le seul endroit qui connaît cette convention : tout le reste parle Unity. Les positions sont
    /// relatives à la racine de la pièce (<see cref="Authoring.RoomAuthoring"/>), qui peut être n'importe où
    /// dans la scène — plusieurs pièces se posent côte à côte.
    /// </remarks>
    public static class RoomSpace
    {
        public static Vector3 ToUnity(double x, double y, double z) => new Vector3((float)-x, (float)y, (float)z);

        public static Vector3 ToUnity(Pos p, float y = 0f) => ToUnity(p.X, y, p.Z);

        public static Vector3 ToUnity(Vec3 v) => ToUnity(v.X, v.Y, v.Z);

        public static Pos ToPos(Vector3 local) => new Pos { X = Round(-local.x), Z = Round(local.z) };

        public static Vec3 ToVec3(Vector3 local) => new Vec3 { X = -local.x, Y = local.y, Z = local.z };

        /// <summary>L'orientation Unity (autour de Y) d'un lacet du protocole.</summary>
        public static Quaternion Facing(double phi) => Quaternion.Euler(0f, (float)(-phi * Mathf.Rad2Deg), 0f);

        /// <summary>Le lacet du protocole (radians, dans ]-π, π]) d'une orientation Unity.</summary>
        public static double FacingOf(Quaternion rotation)
        {
            var forward = rotation * Vector3.forward;
            // avant Unity (fx, fz) = (-sin φ, cos φ)
            return Round(Mathf.Atan2(-forward.x, forward.z), 4);
        }

        static double Round(double v, int digits = 3) => System.Math.Round(v, digits);
    }
}
