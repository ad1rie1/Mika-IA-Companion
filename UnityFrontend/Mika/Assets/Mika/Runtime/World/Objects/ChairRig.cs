using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// Une chaise qu'on fait pivoter et rouler sans la déplacer dans le monde : le modèle tourne sur son pied et
    /// avance ou recule le long de son assise, et le siège décrit par la scène (où vont les hanches) le suit —
    /// si bien que la personne assise tourne et roule avec elle. Le noyau ne voit rien de tout cela : la chaise
    /// reste à sa place, seul son modèle bouge.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Monde/Chaise pivotante")]
    public sealed class ChairRig : MonoBehaviour
    {
        [Tooltip("Ce qui tourne et roule (le modèle de la chaise).")]
        public Transform model;
        [Tooltip("Vitesse de rotation (°/s) et de roulement (m/s).")]
        public float swivelSpeed = 70f, rollSpeed = 0.35f;
        [Tooltip("Débattement maximal (°) de part et d'autre de la position d'origine.")]
        public float maxSwivel = 150f;

        Vector3 _homePos, _rollAxis = Vector3.forward;
        Quaternion _homeRot;
        float _yaw, _yawTarget, _roll, _rollTarget;
        float _yawVel, _rollVel;
        bool _ready;

        public float Yaw => _yaw;
        public float Roll => _roll;

        void Awake() => Init();

        void Init()
        {
            if (_ready) return;
            if (model == null) model = transform.childCount > 0 ? transform.GetChild(0) : transform;
            _homePos = model.localPosition;
            _homeRot = model.localRotation;
            _ready = true;
        }

        /// <summary>Emporte le siège (et donc la personne assise) avec le modèle.</summary>
        public void Carry(Transform seat)
        {
            Init();
            if (seat == null) return;
            if (seat.parent != model)
            {
                // Le sens du roulement : celui de l'assise (vers le bureau) — le modèle, lui, peut regarder ailleurs.
                var parent = model.parent != null ? model.parent : transform;
                var f = seat.forward;
                f.y = 0;
                if (f.sqrMagnitude > 1e-4f) _rollAxis = parent.InverseTransformDirection(f.normalized);
                seat.SetParent(model, true);
            }
        }

        /// <summary>Pivote de <paramref name="degrees"/> par rapport à la position d'origine (positif : vers sa droite).</summary>
        public void SwivelTo(float degrees) => _yawTarget = Mathf.Clamp(degrees, -maxSwivel, maxSwivel);

        /// <summary>Avance (positif, vers le bureau) ou recule le long de l'assise d'origine, en mètres.</summary>
        public void RollTo(float meters) => _rollTarget = Mathf.Clamp(meters, -0.4f, 0.4f);

        /// <summary>Le pivot qui amène le dos de la chaise face à un point (l'assise regarde vers lui).</summary>
        public float YawToward(Vector3 point, Quaternion seatHome)
        {
            var fwd = seatHome * Vector3.forward;
            var to = point - model.position;
            fwd.y = 0;
            to.y = 0;
            return to.sqrMagnitude < 1e-4f ? 0f : Vector3.SignedAngle(fwd, to, Vector3.up);
        }

        void Update()
        {
            Init();
            _yaw = Mathf.SmoothDamp(_yaw, _yawTarget, ref _yawVel, 0.45f, swivelSpeed);
            _roll = Mathf.SmoothDamp(_roll, _rollTarget, ref _rollVel, 0.35f, rollSpeed);
            var rot = Quaternion.AngleAxis(_yaw, Vector3.up) * _homeRot;
            // Le roulement suit le sens d'origine de l'assise (vers le bureau), pas le pivot.
            model.localRotation = rot;
            model.localPosition = _homePos + _rollAxis * _roll;
        }
    }
}
