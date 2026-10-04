using System;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// La lumière du dehors à l'heure réelle (locale), comme le client web (Daylight.ts) : l'aube, le plein jour,
    /// le soir doré, la nuit bleutée, qui entrent par la fenêtre. Elle ne dépend pas du sommeil de Mika (le
    /// dehors ne s'éteint pas quand elle dort) ; l'ambiance de la pièce, elle, suit ses lampes.
    /// </summary>
    [AddComponentMenu("Mika/Décor/Lumière du jour")]
    public sealed class Daylight : MonoBehaviour
    {
        public Light sun;
        [Tooltip("Direction (Unity, horizontale) dans laquelle la lumière entre par la fenêtre.")]
        public Vector3 windowDirection = Vector3.left;
        [Tooltip("Heure forcée (0–24) pour essayer une ambiance ; négative : l'heure réelle.")]
        public float forceHour = -1f;
        [Tooltip("Ambiance réglée en même temps (lumière d'ambiance trichrome).")]
        public bool driveAmbient = true;

        static readonly (float hour, Color color, float intensity, float elevation, Color ambient)[] Keys =
        {
            (0f, new Color(0.45f, 0.55f, 0.85f), 0.08f, 25f, new Color(0.16f, 0.16f, 0.24f)),
            (5.5f, new Color(0.55f, 0.6f, 0.9f), 0.10f, 5f, new Color(0.18f, 0.18f, 0.26f)),
            (7f, new Color(1f, 0.72f, 0.5f), 0.55f, 10f, new Color(0.33f, 0.28f, 0.30f)),
            (10f, new Color(1f, 0.94f, 0.86f), 1.05f, 35f, new Color(0.42f, 0.44f, 0.52f)),
            (14f, new Color(1f, 0.97f, 0.92f), 1.15f, 45f, new Color(0.45f, 0.47f, 0.55f)),
            (18f, new Color(1f, 0.74f, 0.48f), 0.75f, 14f, new Color(0.38f, 0.30f, 0.30f)),
            (20f, new Color(0.85f, 0.5f, 0.55f), 0.25f, 3f, new Color(0.20f, 0.16f, 0.24f)),
            (21.5f, new Color(0.45f, 0.55f, 0.85f), 0.08f, 25f, new Color(0.16f, 0.16f, 0.24f)),
            (24f, new Color(0.45f, 0.55f, 0.85f), 0.08f, 25f, new Color(0.16f, 0.16f, 0.24f)),
        };

        void Update()
        {
            if (sun == null) return;
            var now = DateTime.Now;
            var h = forceHour >= 0 ? forceHour % 24f : now.Hour + now.Minute / 60f + now.Second / 3600f;
            var i = 0;
            while (i < Keys.Length - 2 && Keys[i + 1].hour <= h) i++;
            var a = Keys[i];
            var b = Keys[i + 1];
            var t = Mathf.SmoothStep(0, 1, Mathf.InverseLerp(a.hour, b.hour, h));
            sun.color = Color.Lerp(a.color, b.color, t);
            sun.intensity = Mathf.Lerp(a.intensity, b.intensity, t);
            var elevation = Mathf.Lerp(a.elevation, b.elevation, t);
            var horizontal = windowDirection.sqrMagnitude > 0 ? windowDirection.normalized : Vector3.left;
            // Le soleil glisse le long de la journée : un peu de travers le matin, de l'autre côté le soir.
            var sweep = Quaternion.AngleAxis(Mathf.Lerp(-35f, 35f, Mathf.InverseLerp(6f, 21f, h)), Vector3.up);
            var flat = sweep * horizontal;
            var e = elevation * Mathf.Deg2Rad;
            var dir = flat * Mathf.Cos(e) + Vector3.down * Mathf.Sin(e); // vers l'intérieur, et vers le bas
            sun.transform.rotation = Quaternion.LookRotation(dir, Vector3.up);
            if (driveAmbient)
            {
                var amb = Color.Lerp(a.ambient, b.ambient, t);
                RenderSettings.ambientSkyColor = amb * 1.1f;
                RenderSettings.ambientEquatorColor = amb * 0.85f;
                RenderSettings.ambientGroundColor = amb * 0.45f;
            }
        }
    }
}
