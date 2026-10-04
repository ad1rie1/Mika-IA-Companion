using System;
using System.Collections.Generic;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>Allume ou éteint une lumière (et l'émission de ses matériaux) selon l'état.</summary>
    [AddComponentMenu("Mika/Monde/État · Lumière")]
    public sealed class StateLight : StateVisual
    {
        [Serializable]
        public sealed class Level
        {
            public string state = "on";
            [Range(0, 1)] public float level = 1f;
        }

        public List<Light> lights = new List<Light>();
        [Tooltip("Rendus dont l'émission suit la lumière (abat-jour, ampoule).")]
        public List<Renderer> emissive = new List<Renderer>();
        public List<Level> levels = new List<Level> { new Level { state = "on", level = 1f }, new Level { state = "off", level = 0f } };
        public float fade = 0.25f;

        readonly Dictionary<Light, float> _full = new Dictionary<Light, float>();
        readonly Dictionary<Material, Color> _emission = new Dictionary<Material, Color>();
        float _current = 1f, _target = 1f;
        static readonly int EmissionColor = Shader.PropertyToID("_EmissionColor");

        void Awake()
        {
            foreach (var l in lights) if (l != null) _full[l] = l.intensity;
            foreach (var r in emissive)
                if (r != null)
                    foreach (var m in r.materials)
                        if (m.HasProperty(EmissionColor))
                            _emission[m] = m.GetColor(EmissionColor);
        }

        public override void Apply(string state, bool instant)
        {
            var level = levels.Find(l => l.state == state);
            if (level == null) return;
            _target = level.level;
            if (instant || fade <= 0) Set(_target);
        }

        void Update()
        {
            if (Mathf.Approximately(_current, _target)) return;
            Set(Mathf.MoveTowards(_current, _target, Time.deltaTime / Mathf.Max(0.01f, fade)));
        }

        void Set(float v)
        {
            _current = v;
            foreach (var kv in _full)
            {
                kv.Key.intensity = kv.Value * v;
                kv.Key.enabled = v > 0.001f;
            }
            foreach (var kv in _emission)
                kv.Key.SetColor(EmissionColor, kv.Value * v);
        }
    }
}
