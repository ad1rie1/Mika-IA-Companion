using UnityEngine;

namespace Mika.Player
{
    /// <summary>
    /// Le corps de la joueuse : marcher dans le monde (contrôleur de personnage, collisions réelles), regarder,
    /// à la première personne ou derrière l'épaule. Elle se déplace librement ; le noyau n'apprend que ses
    /// arrivées (<see cref="PlayerPresence"/>).
    /// </summary>
    [RequireComponent(typeof(CharacterController))]
    [AddComponentMenu("Mika/Joueuse/Déplacement")]
    public sealed class PlayerController : MonoBehaviour
    {
        public Camera view;
        [Tooltip("Hauteur des yeux (m).")]
        public float eyeHeight = 1.55f;
        public float walkSpeed = 1.6f;
        public float runSpeed = 3.2f;
        public float lookSensitivity = 0.12f;
        [Tooltip("Distance de la caméra en vue à la troisième personne.")]
        public float thirdPersonDistance = 2.2f;

        CharacterController _cc;
        PlayerInputs _inputs;
        float _pitch, _yaw, _vy;
        bool _third;
        bool _cursorFree;

        public PlayerInputs Inputs => _inputs;
        public bool CursorFree => _cursorFree;
        public Vector3 Velocity { get; private set; }
        public bool ThirdPerson => _third;
        /// <summary>Le corps visible (à masquer à la première personne).</summary>
        public GameObject bodyVisual;

        void Awake()
        {
            _cc = GetComponent<CharacterController>();
            _cc.height = 1.65f;
            _cc.radius = 0.22f;
            _cc.center = new Vector3(0, 0.83f, 0);
            _cc.stepOffset = 0.25f;
            _inputs = new PlayerInputs();
            _yaw = transform.eulerAngles.y;
            if (view == null) view = GetComponentInChildren<Camera>();
        }

        void OnEnable()
        {
            _inputs.Enable(true);
            SetCursorFree(false);
        }

        void OnDisable() => _inputs.Enable(false);

        void OnDestroy() => _inputs.Dispose();

        public void SetCursorFree(bool free)
        {
            _cursorFree = free;
            Cursor.lockState = free ? CursorLockMode.None : CursorLockMode.Locked;
            Cursor.visible = free;
        }

        /// <summary>Pose le corps à un endroit (arrivée dans le monde).</summary>
        public void Teleport(Vector3 position, Quaternion rotation)
        {
            _cc.enabled = false;
            transform.SetPositionAndRotation(position, Quaternion.Euler(0, rotation.eulerAngles.y, 0));
            _yaw = transform.eulerAngles.y;
            _cc.enabled = true;
        }

        void Update()
        {
            if (_inputs.Cursor.WasPressedThisFrame())
                SetCursorFree(!_cursorFree);
            if (_inputs.View.WasPressedThisFrame())
                _third = !_third;

            if (!_cursorFree && Time.timeSinceLevelLoad > 0.5f) // la souris saute au lancement : on l'ignore un instant
            {
                var look = _inputs.Look.ReadValue<Vector2>() * lookSensitivity;
                _yaw += look.x;
                _pitch = Mathf.Clamp(_pitch - look.y, -80f, 80f);
            }
            transform.rotation = Quaternion.Euler(0, _yaw, 0);

            var move = _inputs.Move.ReadValue<Vector2>();
            var speed = _inputs.Run.IsPressed() ? runSpeed : walkSpeed;
            var wish = transform.TransformDirection(new Vector3(move.x, 0, move.y)) * speed;
            _vy = _cc.isGrounded ? -0.5f : _vy + Physics.gravity.y * Time.deltaTime;
            var delta = (wish + Vector3.up * _vy) * Time.deltaTime;
            var before = transform.position;
            _cc.Move(delta);
            Velocity = (transform.position - before) / Mathf.Max(Time.deltaTime, 1e-4f);

            PlaceCamera();
        }

        void PlaceCamera()
        {
            if (view == null) return;
            var eye = transform.position + Vector3.up * eyeHeight;
            var rot = Quaternion.Euler(_pitch, _yaw, 0);
            if (_third)
            {
                var back = rot * Vector3.back * thirdPersonDistance + Vector3.up * 0.15f;
                var wanted = eye + back;
                // La caméra ne traverse pas les murs.
                if (Physics.SphereCast(eye, 0.15f, back.normalized, out var hit, back.magnitude, ~0, QueryTriggerInteraction.Ignore))
                    wanted = eye + back.normalized * Mathf.Max(0.2f, hit.distance - 0.05f);
                view.transform.SetPositionAndRotation(wanted, rot);
            }
            else
            {
                view.transform.SetPositionAndRotation(eye, rot);
            }
            if (bodyVisual != null) bodyVisual.SetActive(_third);
        }
    }
}
