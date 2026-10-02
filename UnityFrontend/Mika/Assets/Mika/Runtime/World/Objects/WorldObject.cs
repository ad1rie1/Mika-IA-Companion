using System.Collections.Generic;
using System.Linq;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>Comment la physique traite un objet, selon où le monde dit qu'il est.</summary>
    public enum ObjectPhysics
    {
        /// <summary>Un meuble : il ne bouge pas, il sert d'obstacle.</summary>
        Fixed,
        /// <summary>Posé à sa place (surface, contenant) : tenu en place, sans gravité.</summary>
        Placed,
        /// <summary>Au sol de la pièce : la physique le laisse tomber et rouler, le moteur constate où il s'arrête.</summary>
        Free,
        /// <summary>Dans une main : suit la main.</summary>
        Held,
    }

    /// <summary>
    /// Un objet du monde à l'écran : ses places de surface, son contenant, où la main le saisit, et ce que ses
    /// états montrent. Le monde (le noyau) dit où il est ; ce composant sait l'y mettre.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Monde/Objet du monde (rendu)")]
    public sealed class WorldObject : MonoBehaviour
    {
        [Tooltip("Identifiant de l'objet dans le monde (fixé par la scène ou à l'apparition).")]
        public string id;
        [Tooltip("Places de surface, dans l'ordre des index du protocole (vide : les SurfaceSlot enfants).")]
        public List<Transform> surfaceSlots = new List<Transform>();
        [Tooltip("Où vont les objets rangés dedans (vide : l'objet lui-même).")]
        public Transform container;
        [Tooltip("Les objets rangés sont-ils cachés ?")]
        public bool hideContents = true;
        [Tooltip("Où la main le saisit (vide : le centre de ses rendus).")]
        public Transform grip;

        Rigidbody _body;
        StateVisual[] _visuals;
        string _state;
        bool _initialized;

        public string State => _state;
        public ObjectPhysics Physics { get; private set; } = ObjectPhysics.Fixed;
        public Rigidbody Body => _body;

        void Awake() => Init();

        void Init()
        {
            if (_initialized) return;
            _initialized = true;
            _visuals = GetComponentsInChildren<StateVisual>(true);
            _body = GetComponent<Rigidbody>();
            if (surfaceSlots.Count == 0)
            {
                surfaceSlots = GetComponentsInChildren<SurfaceSlot>(true)
                    .OrderBy(s => s.index)
                    .Select(s => s.transform)
                    .ToList();
            }
        }

        public Transform Slot(int index)
        {
            Init();
            return index >= 0 && index < surfaceSlots.Count ? surfaceSlots[index] : null;
        }

        public Transform Container => container != null ? container : transform;

        /// <summary>Le point que vise la main pour le prendre.</summary>
        public Vector3 GripPoint => grip != null ? grip.position : Bounds().center;

        public void ApplyState(string state, bool instant)
        {
            Init();
            if (state == _state && !instant) return;
            _state = state;
            foreach (var v in _visuals)
                if (v != null)
                    v.Apply(state, instant);
        }

        public void SetPhysics(ObjectPhysics mode)
        {
            Init();
            Physics = mode;
            if (mode == ObjectPhysics.Fixed)
            {
                if (_body != null) _body.isKinematic = true;
                return;
            }
            if (_body == null)
            {
                _body = gameObject.AddComponent<Rigidbody>();
                _body.mass = 0.4f;
                _body.interpolation = RigidbodyInterpolation.Interpolate;
                _body.collisionDetectionMode = CollisionDetectionMode.ContinuousSpeculative;
                EnsureCollider();
            }
            var free = mode == ObjectPhysics.Free;
            _body.isKinematic = !free;
            _body.useGravity = free;
            if (!free)
            {
                _body.linearVelocity = Vector3.zero;
                _body.angularVelocity = Vector3.zero;
            }
            foreach (var c in GetComponentsInChildren<Collider>())
                c.enabled = mode != ObjectPhysics.Held;
        }

        void EnsureCollider()
        {
            if (GetComponentInChildren<Collider>() != null) return;
            var b = Bounds();
            var box = gameObject.AddComponent<BoxCollider>();
            box.center = transform.InverseTransformPoint(b.center);
            var s = transform.lossyScale;
            box.size = new Vector3(b.size.x / Mathf.Max(1e-4f, s.x), b.size.y / Mathf.Max(1e-4f, s.y), b.size.z / Mathf.Max(1e-4f, s.z));
        }

        /// <summary>La boîte englobante de ses rendus, en coordonnées du monde.</summary>
        public Bounds Bounds()
        {
            var renderers = GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0) return new Bounds(transform.position, Vector3.one * 0.1f);
            var b = renderers[0].bounds;
            for (var i = 1; i < renderers.Length; i++) b.Encapsulate(renderers[i].bounds);
            return b;
        }

        /// <summary>Pose son bas sur un point (une place de surface), orienté comme lui.</summary>
        public void RestOn(Transform anchor)
        {
            var b = Bounds();
            var bottomOffset = transform.position.y - b.min.y;
            transform.SetPositionAndRotation(anchor.position + Vector3.up * bottomOffset, anchor.rotation);
        }

        public void SetVisible(bool visible)
        {
            foreach (var r in GetComponentsInChildren<Renderer>(true))
                r.enabled = visible;
        }

        public static Size SizeOf(ArchetypeDef def) => def?.Size ?? Size.Fixed;
    }
}
