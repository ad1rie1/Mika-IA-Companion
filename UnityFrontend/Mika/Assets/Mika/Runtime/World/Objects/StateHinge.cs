using System;
using System.Collections.Generic;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// Fait tourner une pièce mobile sur sa charnière selon l'état (porte, fenêtre, battant d'armoire, tiroir en
    /// translation). L'ouverture se joue en douceur ; un instantané la pose d'un coup.
    /// </summary>
    [AddComponentMenu("Mika/Monde/État · Charnière")]
    public sealed class StateHinge : StateVisual
    {
        [Serializable]
        public sealed class Pose
        {
            public string state = "open";
            public Vector3 localEuler;
            public Vector3 localOffset;
        }

        [Tooltip("La pièce qui bouge (son pivot sur la charnière).")]
        public Transform leaf;
        public List<Pose> poses = new List<Pose>
        {
            new Pose { state = "closed" },
            new Pose { state = "open", localEuler = new Vector3(0, 95, 0) },
        };
        [Tooltip("Durée de l'ouverture (s).")]
        public float duration = 1.2f;

        Quaternion _restRotation;
        Vector3 _restPosition;
        bool _captured;
        Quaternion _fromRot, _toRot;
        Vector3 _fromPos, _toPos;
        float _t = 1f;

        void Capture()
        {
            if (_captured || leaf == null) return;
            _restRotation = leaf.localRotation;
            _restPosition = leaf.localPosition;
            _captured = true;
        }

        public override void Apply(string state, bool instant)
        {
            if (leaf == null) return;
            Capture();
            var pose = poses.Find(p => p.state == state);
            if (pose == null) return;
            _fromRot = leaf.localRotation;
            _fromPos = leaf.localPosition;
            _toRot = _restRotation * Quaternion.Euler(pose.localEuler);
            _toPos = _restPosition + pose.localOffset;
            _t = instant || duration <= 0 ? 1f : 0f;
            if (_t >= 1f)
            {
                leaf.localRotation = _toRot;
                leaf.localPosition = _toPos;
            }
        }

        void Update()
        {
            if (_t >= 1f || leaf == null) return;
            _t = Mathf.Min(1f, _t + Time.deltaTime / duration);
            var k = Mathf.SmoothStep(0f, 1f, _t);
            leaf.localRotation = Quaternion.Slerp(_fromRot, _toRot, k);
            leaf.localPosition = Vector3.Lerp(_fromPos, _toPos, k);
        }
    }
}
