using System;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// Une horloge à l'heure réelle (locale), comme celle du client web. Ses aiguilles tournent autour de l'axe Z
    /// local ; l'export Blender met leur pivot au centre du cadran.
    /// </summary>
    [AddComponentMenu("Mika/Décor/Horloge")]
    public sealed class WallClock : MonoBehaviour
    {
        public Transform hourHand;
        public Transform minuteHand;
        [Tooltip("Sens de rotation (+1 / -1) : à inverser si le cadran tourne à l'envers.")]
        public float direction = 1f;

        Quaternion _hourRest, _minuteRest;

        void Awake()
        {
            if (hourHand != null) _hourRest = hourHand.localRotation;
            if (minuteHand != null) _minuteRest = minuteHand.localRotation;
        }

        void Update()
        {
            var now = DateTime.Now;
            var minutes = now.Minute + now.Second / 60f;
            var hours = (now.Hour % 12) + minutes / 60f;
            if (hourHand != null) hourHand.localRotation = _hourRest * Quaternion.Euler(0, 0, direction * 360f * hours / 12f);
            if (minuteHand != null) minuteHand.localRotation = _minuteRest * Quaternion.Euler(0, 0, direction * 360f * minutes / 60f);
        }
    }
}
