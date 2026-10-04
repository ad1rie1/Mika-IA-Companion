using System;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// Le corps sans clips : debout, marcher, s'asseoir, s'allonger, respirer — écrits en muscles humanoïdes
    /// (<see cref="HumanPoseHandler"/>), donc valables pour n'importe quel avatar humanoïde. C'est le repli quand
    /// le contrôleur d'animation n'a pas (encore) les clips de marche ou d'assise ; avec eux, ce poseur se tait.
    /// </summary>
    /// <remarks>
    /// Les muscles vont de -1 à 1 sur l'amplitude réglée dans l'avatar ; les valeurs ci-dessous sont des poses
    /// raisonnables, pas des mesures. Le client web fait la même chose en rotations d'os (proceduralClips.ts).
    /// </remarks>
    public sealed class HumanoidPoser : IDisposable
    {
        readonly HumanPoseHandler _handler;
        readonly Transform _root;
        HumanPose _pose;
        readonly float[] _rest;
        readonly float _standBodyY;
        readonly float _hipHeight;

        readonly int _lUpperLeg, _rUpperLeg, _lLowerLeg, _rLowerLeg, _lFoot, _rFoot;
        readonly int _lArmDown, _rArmDown, _lArmFront, _rArmFront, _lForearm, _rForearm;
        readonly int _spine, _chest, _neck, _head;

        public HumanoidPoser(Animator animator)
        {
            _root = animator.transform;
            _handler = new HumanPoseHandler(animator.avatar, _root);
            _handler.GetHumanPose(ref _pose);
            _rest = (float[])_pose.muscles.Clone();
            _standBodyY = _pose.bodyPosition.y;
            var hips = animator.GetBoneTransform(HumanBodyBones.Hips);
            _hipHeight = hips != null ? Mathf.Max(0.3f, hips.position.y - _root.position.y) : 0.9f;

            _lUpperLeg = M("Left Upper Leg Front-Back");
            _rUpperLeg = M("Right Upper Leg Front-Back");
            _lLowerLeg = M("Left Lower Leg Stretch");
            _rLowerLeg = M("Right Lower Leg Stretch");
            _lFoot = M("Left Foot Up-Down");
            _rFoot = M("Right Foot Up-Down");
            _lArmDown = M("Left Arm Down-Up");
            _rArmDown = M("Right Arm Down-Up");
            _lArmFront = M("Left Arm Front-Back");
            _rArmFront = M("Right Arm Front-Back");
            _lForearm = M("Left Forearm Stretch");
            _rForearm = M("Right Forearm Stretch");
            _spine = M("Spine Front-Back");
            _chest = M("Chest Front-Back");
            _neck = M("Neck Nod Down-Up");
            _head = M("Head Nod Down-Up");
        }

        static int M(string name) => Array.IndexOf(HumanTrait.MuscleName, name);

        /// <summary>La hauteur des hanches debout (m) : sert à poser les hanches assises sur un siège.</summary>
        public float HipHeight => _hipHeight;

        /// <param name="sit">0 debout → 1 assise.</param>
        /// <param name="lie">0 → 1 allongée (sur le dos, jambes tendues).</param>
        /// <param name="walk">0 → 1 : amplitude de la marche ; <paramref name="phase"/> en radians.</param>
        /// <param name="seatHeight">Hauteur des hanches assises au-dessus de la racine (m).</param>
        /// <param name="breath">-1 → 1 : le souffle.</param>
        /// <param name="reach">0 → 1 : le bras droit tendu vers l'avant et le bas (prendre, poser).</param>
        public void Apply(float sit, float lie, float walk, float phase, float seatHeight, float breath, float reach)
        {
            var m = _pose.muscles;
            Array.Copy(_rest, m, m.Length);

            // Bras le long du corps (l'avatar se repose en T ou en A).
            Set(m, _lArmDown, -0.55f);
            Set(m, _rArmDown, -0.55f);
            Set(m, _lForearm, 0.75f);
            Set(m, _rForearm, 0.75f);

            // Marche : jambes en opposition, bras en contre-temps.
            var s = Mathf.Sin(phase) * walk;
            var k = Mathf.Max(0f, Mathf.Sin(phase + 1.2f)) * walk;
            var k2 = Mathf.Max(0f, Mathf.Sin(phase + Mathf.PI + 1.2f)) * walk;
            Add(m, _lUpperLeg, -0.42f * s);
            Add(m, _rUpperLeg, 0.42f * s);
            Add(m, _lLowerLeg, -0.6f * k);
            Add(m, _rLowerLeg, -0.6f * k2);
            Add(m, _lArmFront, -0.25f * s);
            Add(m, _rArmFront, 0.25f * s);

            // Assise : cuisses à l'horizontale, genoux à angle droit, buste droit. Valeurs absolues mesurées sur
            // l'avatar (−0,62 : genou à hauteur de hanche ; 0 : pied sous le genou) — un muscle négatif avance la cuisse.
            Blend(m, _lUpperLeg, -0.62f, sit);
            Blend(m, _rUpperLeg, -0.62f, sit);
            Blend(m, _lLowerLeg, 0f, sit);
            Blend(m, _rLowerLeg, 0f, sit);
            Add(m, _lArmFront, 0.25f * sit);
            Add(m, _rArmFront, 0.25f * sit);

            // Allongée : jambes tendues, bras le long, tête posée.
            Add(m, _head, -0.15f * lie);

            // Respirer : le buste.
            Add(m, _spine, 0.03f * breath);
            Add(m, _chest, 0.04f * breath);
            Add(m, _neck, -0.02f * breath);

            // Tendre le bras droit (l'IK, quand il y en a, fait le reste).
            Add(m, _rArmFront, 0.7f * reach);
            Add(m, _rArmDown, 0.35f * reach);
            Add(m, _rForearm, 0.2f * reach);
            Add(m, _spine, 0.25f * reach);

            var bodyY = Mathf.Lerp(_standBodyY, _standBodyY * seatHeight / _hipHeight, sit);
            bodyY += 0.012f * Mathf.Abs(Mathf.Sin(phase)) * walk;
            _pose.bodyPosition = new Vector3(0f, bodyY, 0f);
            _pose.bodyRotation = Quaternion.identity;
            _handler.SetHumanPose(ref _pose);
        }

        static void Set(float[] m, int i, float v)
        {
            if (i >= 0) m[i] = v;
        }

        static void Blend(float[] m, int i, float target, float k)
        {
            if (i >= 0) m[i] = Mathf.Lerp(m[i], target, Mathf.Clamp01(k));
        }

        static void Add(float[] m, int i, float v)
        {
            if (i >= 0) m[i] = Mathf.Clamp(m[i] + v, -1f, 1f);
        }

        public void Dispose() => _handler.Dispose();
    }
}
