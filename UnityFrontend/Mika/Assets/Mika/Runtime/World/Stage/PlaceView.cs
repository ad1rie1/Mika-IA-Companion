using Mika.World.Engine.Authoring;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>Une pièce à l'écran : sa racine (l'origine de son espace) et, si la scène la décrit, son authoring.</summary>
    public sealed class RoomView
    {
        public string Id;
        public RoomDef Def;
        public Transform Root;
        public RoomAuthoring Authoring;
        /// <summary>Vrai quand la scène n'a pas cette pièce : une racine vide a été créée (et le noyau en est averti).</summary>
        public bool Placeholder;

        public Vector3 ToWorld(Vector3 local) => Root.TransformPoint(local);
        public Vector3 ToLocal(Vector3 world) => Root.InverseTransformPoint(world);
    }

    /// <summary>
    /// Un lieu à l'écran : le point d'approche (où l'on arrive à pied, et dans quel sens on s'y tient), et pour
    /// une assise ou un lit, où vont les hanches et la pose allongée. Vient de la scène (<see cref="PlaceAuthoring"/>)
    /// ou, à défaut, de la position grossière de la définition.
    /// </summary>
    public sealed class PlaceView
    {
        public string Id;
        public PlaceDef Def;
        public RoomView Room;
        public Transform Approach;
        public PlaceAuthoring Authoring;

        public Vector3 Position => Approach.position;
        public Quaternion Rotation => Approach.rotation;

        public PlaceKind Kind => Def?.PlaceKind ?? PlaceKind.Spot;

        /// <summary>Où vont les hanches assises (orientation : le sens assis).</summary>
        public Pose Seat
        {
            get
            {
                if (Authoring != null && Authoring.seat != null)
                    return new Pose(Authoring.seat.position, Authoring.seat.rotation);
                // Sans siège décrit : à 45 cm au-dessus du point d'approche, un pas plus loin dans son sens.
                return new Pose(Approach.position + Approach.forward * 0.15f + Vector3.up * 0.45f, Approach.rotation);
            }
        }

        /// <summary>La racine du corps allongé (orientation : le sens de la tête).</summary>
        public Pose Lie
        {
            get
            {
                if (Authoring != null && Authoring.lie != null)
                    return new Pose(Authoring.lie.position, Authoring.lie.rotation);
                var seat = Seat;
                return new Pose(seat.position + Vector3.up * 0.1f, seat.rotation);
            }
        }
    }
}
