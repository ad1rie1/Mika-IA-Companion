using System;
using System.Collections;
using System.Collections.Generic;
using Mika.World.Protocol;
using UnityEngine;
using UnityEngine.AI;

namespace Mika.World.Engine
{
    /// <summary>
    /// Le corps d'un acteur du monde (Mika, un personnage, une personne vue par les autres) : marcher sur le
    /// navmesh, s'asseoir, s'allonger, tendre la main, tenir, faire un geste, regarder. Il ne décide rien : il
    /// joue ce qu'on lui demande (<see cref="IntentPlayer"/>, la vue d'un acteur), le plus naturellement possible.
    /// </summary>
    /// <remarks>
    /// Deux façons d'animer, choisies d'après ce qui est disponible : le contrôleur d'animation (clips humanoïdes
    /// Mixamo, retargetés par Mecanim) avec l'IK de Mecanim pour les mains et le regard ; ou, sans clips, le
    /// <see cref="HumanoidPoser"/> en muscles. Dans les deux cas les hanches sont recalées sur le siège ou le lit
    /// décrit par le lieu, si bien qu'un clip d'assise quelconque tombe juste sur n'importe quelle chaise.
    /// </remarks>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Monde/Corps d'acteur")]
    public sealed class ActorBody : MonoBehaviour
    {
        public string actorId;
        public Animator animator;
        [Tooltip("Vitesse de marche nominale (m/s) — celle que le noyau utilise pour dater un trajet.")]
        public float walkSpeed = 0.9f;
        [Tooltip("Longueur d'une foulée (m) : règle la cadence des pas sur la vitesse.")]
        public float stride = 1.1f;
        public float turnSpeedDeg = 360f;

        NavMeshAgent _agent;
        HumanoidPoser _poser;
        bool _procedural;
        Transform _hips, _rightHand, _leftHand, _head;

        Posture _posture = Posture.Stand;
        float _sit, _lie, _walk, _phase, _reach, _breathT;
        float _sitTarget, _lieTarget, _reachTarget;
        Pose? _anchor;                 // où recaler les hanches (assise) ou le corps (allongée)
        float _anchorBlend;

        Vector3? _ikPoint;
        AvatarIKGoal _ikGoal = AvatarIKGoal.RightHand;
        float _ikWeight, _ikWeightTarget;
        Vector3? _look;
        float _lookWeight;
        Vector3 _lastPos;
        float _speed;

        readonly Dictionary<WorldObject, Hand> _held = new Dictionary<WorldObject, Hand>();

        public Posture Posture => _posture;
        public bool Procedural => _procedural;
        public float Speed => _speed;
        public IReadOnlyDictionary<WorldObject, Hand> Held => _held;
        public Transform Head => _head != null ? _head : transform;

        /// <summary>Un geste demandé au corps (pour que le visage suive : un clin d'œil avec le signe de la main).</summary>
        public event Action<string> GesturePlayed;

        void Awake()
        {
            if (animator == null) animator = GetComponentInChildren<Animator>();
            if (animator != null) Bind(animator);
            _lastPos = transform.position;
        }

        /// <summary>Relie le corps à son squelette (appelé à nouveau quand l'avatar est chargé après coup).</summary>
        public void Bind(Animator a)
        {
            animator = a;
            if (a == null || !a.isHuman)
                return;
            _hips = a.GetBoneTransform(HumanBodyBones.Hips);
            _rightHand = a.GetBoneTransform(HumanBodyBones.RightHand);
            _leftHand = a.GetBoneTransform(HumanBodyBones.LeftHand);
            _head = a.GetBoneTransform(HumanBodyBones.Head);
            _procedural = a.runtimeAnimatorController == null || !BodyAnim.HasParameter(a, BodyAnim.Speed);
            _poser?.Dispose();
            _poser = _procedural ? new HumanoidPoser(a) : null;
            if (_procedural)
                a.enabled = false; // le poseur écrit les os lui-même
            var relay = a.gameObject.GetOrAdd<IkRelay>();
            relay.Body = this;
        }

        void OnDestroy() => _poser?.Dispose();

        // --- état de chaque image ---------------------------------------------------------------------------
        void Update()
        {
            var dt = Time.deltaTime;
            var v = (transform.position - _lastPos) / Mathf.Max(dt, 1e-4f);
            v.y = 0;
            _lastPos = transform.position;
            _speed = Mathf.Lerp(_speed, v.magnitude, 1f - Mathf.Exp(-dt * 10f));

            _sit = Mathf.MoveTowards(_sit, _sitTarget, dt / 0.9f);
            _lie = Mathf.MoveTowards(_lie, _lieTarget, dt / 1.2f);
            _reach = Mathf.MoveTowards(_reach, _reachTarget, dt / 0.35f);
            _ikWeight = Mathf.MoveTowards(_ikWeight, _ikWeightTarget, dt / 0.35f);
            _lookWeight = Mathf.MoveTowards(_lookWeight, _look.HasValue ? 1f : 0f, dt / 0.5f);
            _walk = Mathf.MoveTowards(_walk, Mathf.Clamp01(_speed / Mathf.Max(0.1f, walkSpeed)), dt / 0.25f);
            _phase += _speed / Mathf.Max(0.2f, stride) * Mathf.PI * dt;
            _breathT += dt;

            if (!_procedural && animator != null && animator.runtimeAnimatorController != null)
            {
                animator.SetFloat(BodyAnim.Speed, _speed);
                animator.SetInteger(BodyAnim.Posture, BodyAnim.PostureValue(_posture));
                if (BodyAnim.HasParameter(animator, BodyAnim.Holding))
                    animator.SetBool(BodyAnim.Holding, _held.Count > 0);
            }
        }

        void LateUpdate()
        {
            if (_procedural && _poser != null)
            {
                var seatHeight = _anchor.HasValue ? Mathf.Max(0.25f, _anchor.Value.position.y - transform.position.y) : 0.45f;
                _poser.Apply(_sit, _lie, _walk, _phase, seatHeight, Mathf.Sin(_breathT * 1.6f), _reach);
            }
            RecalAnchor();
        }

        /// <summary>Assise ou allongée : amène les hanches sur le siège, le corps sur le lit, quel que soit le clip.</summary>
        void RecalAnchor()
        {
            if (!_anchor.HasValue || _hips == null) return;
            var a = _anchor.Value;
            var k = 1f - Mathf.Exp(-Time.deltaTime * 8f);
            if (_posture == Posture.Sit && _sit > 0.5f)
            {
                var delta = a.position - _hips.position;
                transform.position += delta * k * _anchorBlend;
            }
            else if (_posture == Posture.Lie && _lie > 0.5f)
            {
                var delta = a.position - _hips.position;
                transform.position += delta * k * _anchorBlend;
            }
        }

        // --- primitives ---------------------------------------------------------------------------------------
        /// <summary>Pose le corps sans rien jouer (un instantané, une arrivée tardive).</summary>
        public void Snap(Vector3 position, Quaternion rotation, Posture posture, PlaceView place = null)
        {
            StopAgent(keepEnabled: false);
            _posture = posture;
            _sit = _sitTarget = posture == Posture.Sit ? 1f : 0f;
            _lie = _lieTarget = posture == Posture.Lie ? 1f : 0f;
            _anchor = null;
            _anchorBlend = 0;
            if (place != null && posture == Posture.Sit)
            {
                var seat = place.Seat;
                _anchor = seat;
                _anchorBlend = 1;
                transform.SetPositionAndRotation(new Vector3(seat.position.x, position.y, seat.position.z), seat.rotation);
            }
            else if (place != null && posture == Posture.Lie)
            {
                var lie = place.Lie;
                _anchor = lie;
                _anchorBlend = 1;
                transform.SetPositionAndRotation(LieRootPosition(lie), LieRootRotation(lie));
            }
            else
            {
                transform.SetPositionAndRotation(position, rotation);
                WarpAgent(position);
            }
            _lastPos = transform.position;
            ApplyAnimatorPostureNow();
        }

        /// <summary>
        /// Marche jusqu'à un point en <paramref name="duration"/> secondes environ (la durée nominale du noyau), puis
        /// se tourne. <paramref name="arrived"/> dit si le point a été atteint (sinon : bloqué, pas de chemin).
        /// </summary>
        public IEnumerator WalkTo(Vector3 target, Quaternion facing, float duration, Action<bool> arrived = null)
        {
            if (_posture != Posture.Stand)
                yield return ChangePosture(Posture.Stand, null, 0.8f);
            var start = transform.position;
            var agent = EnsureAgent();
            var reached = false;
            var timeout = Mathf.Max(2f, duration * 1.8f + 2f);
            var t = 0f;
            if (agent != null && agent.isOnNavMesh)
            {
                var path = new NavMeshPath();
                if (agent.CalculatePath(target, path) && path.status != NavMeshPathStatus.PathInvalid)
                {
                    var length = PathLength(path);
                    agent.speed = Mathf.Clamp(length / Mathf.Max(0.3f, duration), 0.35f, 2.2f);
                    agent.SetPath(path);
                    agent.isStopped = false;
                    while (t < timeout)
                    {
                        t += Time.deltaTime;
                        if (!agent.pathPending && agent.remainingDistance <= Mathf.Max(agent.stoppingDistance, 0.05f))
                            break;
                        yield return null;
                    }
                    reached = path.status == NavMeshPathStatus.PathComplete && (transform.position - target).sqrMagnitude < 0.35f * 0.35f;
                    agent.isStopped = true;
                    agent.ResetPath();
                }
            }
            else
            {
                // Sans navmesh (scène sans géométrie de navigation) : ligne droite, au rythme demandé.
                var dir = target - start;
                dir.y = 0;
                var face = dir.sqrMagnitude > 1e-4f ? Quaternion.LookRotation(dir) : transform.rotation;
                var d = Mathf.Max(0.3f, duration);
                while (t < d)
                {
                    t += Time.deltaTime;
                    var k = Mathf.SmoothStep(0, 1, t / d);
                    transform.position = Vector3.Lerp(start, target, k);
                    transform.rotation = Quaternion.RotateTowards(transform.rotation, face, turnSpeedDeg * Time.deltaTime);
                    yield return null;
                }
                reached = true;
            }
            yield return TurnTo(facing, 0.35f);
            arrived?.Invoke(reached);
        }

        public IEnumerator TurnTo(Quaternion facing, float duration)
        {
            var from = transform.rotation;
            var t = 0f;
            while (t < duration)
            {
                t += Time.deltaTime;
                transform.rotation = Quaternion.Slerp(from, facing, Mathf.SmoothStep(0, 1, t / duration));
                yield return null;
            }
            transform.rotation = facing;
        }

        /// <summary>Change de posture sur un lieu (s'asseoir, s'allonger, se lever) en <paramref name="duration"/> secondes.</summary>
        public IEnumerator ChangePosture(Posture to, PlaceView place, float duration)
        {
            if (to == _posture && (place == null || _anchor.HasValue)) yield break;
            StopAgent(keepEnabled: false); // la transition déplace le corps hors du sol navigable
            var fromPos = transform.position;
            var fromRot = transform.rotation;
            Vector3 toPos;
            Quaternion toRot;
            switch (to)
            {
                case Posture.Sit when place != null:
                    var seat = place.Seat;
                    toPos = new Vector3(seat.position.x, fromPos.y, seat.position.z);
                    toRot = seat.rotation;
                    _anchor = seat;
                    break;
                case Posture.Lie when place != null:
                    var lie = place.Lie;
                    toPos = LieRootPosition(lie);
                    toRot = LieRootRotation(lie);
                    _anchor = lie;
                    break;
                default:
                    // Se lever : un pas vers le point d'approche du lieu.
                    toPos = place != null ? place.Position : new Vector3(fromPos.x, FloorY(fromPos), fromPos.z);
                    toRot = place != null ? place.Rotation : Quaternion.Euler(0, fromRot.eulerAngles.y, 0);
                    _anchor = null;
                    break;
            }
            _posture = to;
            _sitTarget = to == Posture.Sit ? 1f : 0f;
            _lieTarget = to == Posture.Lie ? 1f : 0f;
            _anchorBlend = 0;
            var d = Mathf.Max(0.2f, duration);
            var t = 0f;
            while (t < d)
            {
                t += Time.deltaTime;
                var k = Mathf.SmoothStep(0, 1, t / d);
                transform.SetPositionAndRotation(Vector3.Lerp(fromPos, toPos, k), Quaternion.Slerp(fromRot, toRot, k));
                _anchorBlend = k;
                yield return null;
            }
            transform.SetPositionAndRotation(toPos, toRot);
            _anchorBlend = 1;
            if (to == Posture.Stand)
                WarpAgent(transform.position);
        }

        /// <summary>
        /// Tend la main vers un point (prendre, poser, donner) : la main y va, <paramref name="atContact"/> est
        /// appelé au contact (l'objet change de main à ce moment), puis la main revient.
        /// </summary>
        public IEnumerator Reach(Vector3 point, float duration, Action atContact, Hand hand = Hand.Right)
        {
            _ikPoint = point;
            _ikGoal = hand == Hand.Left ? AvatarIKGoal.LeftHand : AvatarIKGoal.RightHand;
            _ikWeightTarget = 1f;
            _reachTarget = 1f;
            _look = point;
            if (!_procedural && animator != null && BodyAnim.HasParameter(animator, BodyAnim.Reach))
                animator.SetTrigger(BodyAnim.Reach);
            var d = Mathf.Max(0.4f, duration);
            yield return new WaitForSeconds(d * 0.5f);
            atContact?.Invoke();
            _ikWeightTarget = 0f;
            _reachTarget = 0f;
            yield return new WaitForSeconds(d * 0.5f);
            _ikPoint = null;
            _look = null;
        }

        /// <summary>Met l'objet dans une main : il suit l'os de la main, la physique le lâche.</summary>
        public void Hold(WorldObject o, Hand hand)
        {
            if (o == null) return;
            var bone = hand == Hand.Left ? _leftHand : _rightHand;
            var parent = bone != null ? bone : transform;
            o.SetPhysics(ObjectPhysics.Held);
            o.SetVisible(true);
            o.transform.SetParent(parent, true);
            // La prise : le point de saisie dans la paume (un peu vers les doigts).
            var palm = parent.position + (bone != null ? parent.TransformDirection(Vector3.right * (hand == Hand.Left ? -0.07f : 0.07f)) : transform.forward * 0.3f + Vector3.up * 1f);
            o.transform.position += palm - o.GripPoint;
            _held[o] = hand;
        }

        public void Release(WorldObject o)
        {
            if (o == null || !_held.Remove(o)) return;
            o.transform.SetParent(null, true);
        }

        public bool IsHolding(WorldObject o) => o != null && _held.ContainsKey(o);

        public void PlayGesture(string gesture)
        {
            GesturePlayed?.Invoke(gesture);
            if (_procedural || animator == null || !BodyAnim.HasParameter(animator, BodyAnim.Gesture))
                return;
            animator.SetInteger(BodyAnim.GestureId, BodyAnim.GestureIdOf(gesture));
            animator.SetTrigger(BodyAnim.Gesture);
        }

        public void SetActivity(string activity)
        {
            if (!_procedural && animator != null && BodyAnim.HasParameter(animator, BodyAnim.Activity))
                animator.SetInteger(BodyAnim.Activity, BodyAnim.ActivityId(activity));
        }

        public void SetTalking(bool talking)
        {
            if (!_procedural && animator != null && BodyAnim.HasParameter(animator, BodyAnim.Talking))
                animator.SetBool(BodyAnim.Talking, talking);
        }

        public void SetAsleep(bool asleep)
        {
            if (!_procedural && animator != null && BodyAnim.HasParameter(animator, BodyAnim.Asleep))
                animator.SetBool(BodyAnim.Asleep, asleep);
        }

        /// <summary>Où regarder (une personne, un objet) ; <c>null</c> : devant soi.</summary>
        public void LookAt(Vector3? point) => _look = point;

        // --- IK (appelé par IkRelay depuis l'objet qui porte l'Animator) -------------------------------------
        internal void OnIK()
        {
            if (animator == null) return;
            if (_ikPoint.HasValue)
            {
                animator.SetIKPositionWeight(_ikGoal, _ikWeight);
                animator.SetIKPosition(_ikGoal, _ikPoint.Value);
            }
            else
            {
                animator.SetIKPositionWeight(_ikGoal, 0);
            }
            if (_look.HasValue)
            {
                animator.SetLookAtWeight(_lookWeight, 0.25f, 0.8f, 1f, 0.6f);
                animator.SetLookAtPosition(_look.Value);
            }
            else
            {
                animator.SetLookAtWeight(0);
            }
        }

        // --- navigation ---------------------------------------------------------------------------------------
        NavMeshAgent EnsureAgent()
        {
            if (_agent != null)
            {
                if (!_agent.enabled)
                {
                    _agent.enabled = true;
                    if (NavMesh.SamplePosition(transform.position, out var back, 1.5f, NavMesh.AllAreas)) _agent.Warp(back.position);
                }
                return _agent;
            }
            if (!NavMesh.SamplePosition(transform.position, out var hit, 1.5f, NavMesh.AllAreas))
                return null;
            _agent = gameObject.GetOrAdd<NavMeshAgent>();
            _agent.radius = 0.22f;
            _agent.height = 1.6f;
            _agent.acceleration = 6f;
            _agent.angularSpeed = turnSpeedDeg;
            _agent.stoppingDistance = 0.04f;
            _agent.autoBraking = true;
            _agent.obstacleAvoidanceType = ObstacleAvoidanceType.LowQualityObstacleAvoidance;
            _agent.Warp(hit.position);
            return _agent;
        }

        void WarpAgent(Vector3 position)
        {
            if (_agent != null && _agent.enabled && NavMesh.SamplePosition(position, out var hit, 1f, NavMesh.AllAreas))
                _agent.Warp(hit.position);
        }

        /// <summary>
        /// Arrête la marche. Actif, l'agent recloue le corps sur le sol navigable à chaque image : on le coupe dès
        /// que le corps doit le quitter (une transition de posture, une assise, un lit) ; la marche suivante le
        /// rallume (<see cref="EnsureAgent"/>).
        /// </summary>
        void StopAgent(bool keepEnabled)
        {
            if (_agent != null && _agent.enabled && _agent.isOnNavMesh)
            {
                _agent.isStopped = true;
                _agent.ResetPath();
            }
            if (_agent != null)
                _agent.enabled = keepEnabled;
        }

        static float PathLength(NavMeshPath path)
        {
            var c = path.corners;
            var l = 0f;
            for (var i = 1; i < c.Length; i++) l += Vector3.Distance(c[i - 1], c[i]);
            return l;
        }

        static float FloorY(Vector3 p) => NavMesh.SamplePosition(p, out var hit, 2f, NavMesh.AllAreas) ? hit.position.y : 0f;

        Vector3 LieRootPosition(Pose lie) => _procedural ? lie.position : new Vector3(lie.position.x, lie.position.y - (_hips != null ? 0.1f : 0f), lie.position.z);

        Quaternion LieRootRotation(Pose lie) => _procedural ? lie.rotation * Quaternion.Euler(-90f, 0f, 0f) : lie.rotation;

        void ApplyAnimatorPostureNow()
        {
            if (_procedural || animator == null || animator.runtimeAnimatorController == null) return;
            animator.SetInteger(BodyAnim.Posture, BodyAnim.PostureValue(_posture));
        }
    }
}
