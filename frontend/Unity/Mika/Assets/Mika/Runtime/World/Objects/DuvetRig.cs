using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>Les formes d'une couette (et du plaid posé dessus), simulées en tissu dans Blender.</summary>
    public enum DuvetState
    {
        /// <summary>Le lit fait.</summary>
        Made,
        /// <summary>Repliée vers le pied du lit (on va s'y glisser, on vient d'en sortir).</summary>
        Open,
        /// <summary>Sur la personne couchée sur le dos, jusqu'aux épaules.</summary>
        CoveredBack,
        CoveredLeft,
        CoveredRight,
    }

    /// <summary>
    /// La couette d'un lit : ses formes viennent d'une simulation de tissu (frontend/assets-src/blender/duvet_states.py),
    /// une par état, sur le même maillage — passer de l'une à l'autre est un fondu de formes. Le corps qui s'y couche
    /// (<see cref="BodyActivity"/>) dit quand l'ouvrir, la tirer sur lui, se retourner dessous ou la repousser.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Monde/Couette")]
    public sealed class DuvetRig : MonoBehaviour
    {
        public SkinnedMeshRenderer duvet;
        [Tooltip("Le plaid posé au pied du lit : il suit la couette (mêmes noms de formes).")]
        public SkinnedMeshRenderer throwBlanket;

        static readonly string[] ShapeNames = { null, "Ouverte", "Couverte_Dos", "Couverte_Gauche", "Couverte_Droite" };

        int[] _duvetIndex, _throwIndex;
        Mesh _duvetMesh, _throwMesh;
        readonly float[] _from = new float[5], _to = new float[5], _now = new float[5];
        float _t = 1f, _duration = 1f;
        DuvetState _state = DuvetState.Made;

        public DuvetState State => _state;
        public bool Covered => _state >= DuvetState.CoveredBack;
        /// <summary>Vrai pendant un changement de forme.</summary>
        public bool Moving => _t < 1f;
        /// <summary>0 → 1 pendant le changement en cours.</summary>
        public float Progress => Mathf.Clamp01(_t);

        void Awake() => Resolve();

        bool _started;

        /// <summary>Les indices des formes, recalculés dès que le maillage relié change (il peut l'être après Awake).</summary>
        void Resolve()
        {
            if (!_started)
            {
                _started = true;
                _now[0] = _to[0] = 1f;
            }
            var dm = duvet != null ? duvet.sharedMesh : null;
            var tm = throwBlanket != null ? throwBlanket.sharedMesh : null;
            if (_duvetIndex == null || dm != _duvetMesh)
            {
                _duvetMesh = dm;
                _duvetIndex = Indices(duvet);
            }
            if (_throwIndex == null || tm != _throwMesh)
            {
                _throwMesh = tm;
                _throwIndex = Indices(throwBlanket);
            }
        }

        static int[] Indices(SkinnedMeshRenderer r)
        {
            var idx = new int[ShapeNames.Length];
            for (var i = 0; i < idx.Length; i++)
                idx[i] = r != null && r.sharedMesh != null && ShapeNames[i] != null ? r.sharedMesh.GetBlendShapeIndex(ShapeNames[i]) : -1;
            return idx;
        }

        /// <summary>Va vers une forme en <paramref name="seconds"/> secondes (0 : tout de suite).</summary>
        public void SetState(DuvetState state, float seconds)
        {
            Resolve();
            if (state == _state && _t >= 1f) return;
            _state = state;
            for (var i = 0; i < _now.Length; i++)
            {
                _from[i] = _now[i];
                _to[i] = i == (int)state ? 1f : 0f;
            }
            _duration = Mathf.Max(0.01f, seconds);
            _t = seconds <= 0f ? 1f : 0f;
            Apply(_t >= 1f ? 1f : 0f);
        }

        /// <summary>La forme « couverte » qui va avec un côté couché (0 dos, 1 gauche, 2 droite).</summary>
        public static DuvetState CoveredFor(int lieSide) => lieSide switch
        {
            1 => DuvetState.CoveredLeft,
            2 => DuvetState.CoveredRight,
            _ => DuvetState.CoveredBack,
        };

        /// <summary>La dernière fois que quelqu'un était couché dessous ou dessus (posé par le corps couché).</summary>
        [System.NonSerialized] public float lastOccupied = -1000f;
        [Tooltip("Personne au lit depuis… (s) : le lit est refait, à un moment où personne ne le regarde.")]
        public float remakeAfter = 150f;

        void Update()
        {
            // Le lit défait se refait tout seul, mais jamais sous les yeux de quelqu'un.
            if (_state != DuvetState.Made && _t >= 1f && Time.time - lastOccupied > remakeAfter && duvet != null && !duvet.isVisible)
                SetState(DuvetState.Made, 0f);
            if (_t >= 1f) return;
            _t += Time.deltaTime / _duration;
            Apply(Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(_t)));
        }

        void Apply(float k)
        {
            Resolve();
            // La forme de base (le lit fait) est l'absence des autres : seules les formes 1 à 4 ont un poids.
            for (var i = 0; i < _now.Length; i++)
                _now[i] = Mathf.Lerp(_from[i], _to[i], k);
            Write(duvet, _duvetIndex);
            Write(throwBlanket, _throwIndex);
        }

        void Write(SkinnedMeshRenderer r, int[] idx)
        {
            if (r == null || idx == null) return;
            for (var i = 1; i < idx.Length; i++)
                if (idx[i] >= 0)
                    r.SetBlendShapeWeight(idx[i], _now[i] * 100f);
        }
    }
}
