using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// Une chaise qu'on fait pivoter et rouler sans la déplacer dans le monde : le modèle tourne sur son pied et
    /// avance ou recule le long de son assise, et le siège décrit par la scène (où vont les hanches) le suit —
    /// si bien que la personne assise tourne et roule avec elle. Le noyau ne voit rien de tout cela : la chaise
    /// reste à sa place, seul son modèle bouge.
    /// </summary>
    /// <remarks>
    /// La chaise ne bouge jamais d'elle-même : elle est menée, image par image, par le geste qui la déplace — les mains
    /// sur le bord du bureau qui la tirent ou la repoussent, les pieds qui poussent le sol pour la faire pivoter
    /// (<see cref="BodyActivity"/>, courbes du geste « ChairYaw », « ChairRoll »). Lissée vers une cible, elle roulait et
    /// pivotait seule pendant que le corps ne faisait rien.
    /// </remarks>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Monde/Chaise pivotante")]
    public sealed class ChairRig : MonoBehaviour
    {
        [Tooltip("Ce qui tourne et roule (le modèle de la chaise).")]
        public Transform model;
        [Tooltip("Débattement maximal (°) de part et d'autre de la position d'origine.")]
        public float maxSwivel = 150f;
        [Tooltip("Roulement maximal (m), en avant (vers le bureau) comme en arrière.")]
        public float maxRoll = 0.4f;

        Vector3 _homePos, _rollAxis = Vector3.forward;
        Quaternion _homeRot;
        float _yaw, _roll;
        bool _ready;

        /// <summary>Le pivot actuel (°, positif : vers la droite de qui est assis).</summary>
        public float Yaw => _yaw;
        /// <summary>Le roulement actuel (m, positif : vers le bureau).</summary>
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

        /// <summary>
        /// Place la chaise : pivotée de <paramref name="yaw"/>° (positif : vers sa droite) et roulée de
        /// <paramref name="roll"/> m. Appelé à chaque image par le geste qui la déplace, ou une fois pour un instantané.
        /// </summary>
        public void Set(float yaw, float roll)
        {
            Init();
            _yaw = Mathf.Clamp(yaw, -maxSwivel, maxSwivel);
            _roll = Mathf.Clamp(roll, -maxRoll, maxRoll);
            // Le roulement suit le sens d'origine de l'assise (vers le bureau), pas le pivot.
            model.localRotation = Quaternion.AngleAxis(_yaw, Vector3.up) * _homeRot;
            model.localPosition = _homePos + _rollAxis * _roll;
        }

        /// <summary>Le pivot qui amène le dos de la chaise face à un point (l'assise regarde vers lui).</summary>
        public float YawToward(Vector3 point, Quaternion seatHome)
        {
            var fwd = seatHome * Vector3.forward;
            var to = point - model.position;
            fwd.y = 0;
            to.y = 0;
            return to.sqrMagnitude < 1e-4f ? 0f : Vector3.SignedAngle(fwd, to, Vector3.up);
        }
    }
}
