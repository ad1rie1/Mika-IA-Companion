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
        [Tooltip("Ce que le contrôleur sait jouer (clips capturés : reculs, hauteurs) — posé par la scène.")]
        public BodyClipSet clips;
        [Tooltip("Garder les pieds plantés au sol pendant qu'elle s'assoit ou se lève.")]
        public bool plantFeet = true;

        NavMeshAgent _agent;
        HumanoidPoser _poser;
        bool _procedural;
        Transform _hips, _rightHand, _leftHand, _head;

        Posture _posture = Posture.Stand;
        PlaceView _place;
        float _sit, _lie, _walk, _phase, _reach, _breathT;
        float _sitTarget, _lieTarget, _reachTarget;
        Pose? _anchor;                 // où recaler les hanches (assise) ou le corps (allongée)
        Transform _anchorLive;         // le siège lui-même quand la scène le décrit : il peut pivoter, rouler
        float _anchorBlend;
        float _floorY;                 // le sol sous le siège (les pieds s'y posent)
        float _seated;                 // 0 → 1 : la posture assise atteinte (les pieds se posent)

        bool _rootMotion;              // appliquer le déplacement horizontal du clip (s'asseoir, se lever capturés)
        Vector3? _ikPoint;
        AvatarIKGoal _ikGoal = AvatarIKGoal.RightHand;
        float _ikWeight, _ikWeightTarget;
        Vector3? _look, _activityLook;
        float _lookWeight;
        Vector3 _lastPos;
        float _speed;

        // Ce que le squelette mesure au repos (pour poser pieds et mains sans clip dédié).
        float _thigh = 0.38f, _shin = 0.38f, _ankle = 0.08f, _hipHalfWidth = 0.08f;

        readonly Dictionary<WorldObject, Hand> _held = new Dictionary<WorldObject, Hand>();
        readonly Limb[] _limbs = { new Limb(), new Limb(), new Limb(), new Limb() };

        public Posture Posture => _posture;
        /// <summary>Le lieu où le corps se tient (assis, allongé, debout à son point d'approche), s'il est connu.</summary>
        public PlaceView Place => _place;
        public bool Procedural => _procedural;
        public float Speed => _speed;
        public IReadOnlyDictionary<WorldObject, Hand> Held => _held;
        public Transform Head => _head != null ? _head : transform;
        public Transform Hips => _hips;
        /// <summary>0 → 1 : la posture assise est atteinte (transition finie), les pieds sont posés.</summary>
        public float Seatedness => _seated;
        /// <summary>Le siège ou le lit actuel, tel qu'il est maintenant (une chaise qui pivote l'emporte).</summary>
        public Pose? Anchor => _anchorLive != null ? new Pose(_anchorLive.position, _anchorLive.rotation) : _anchor;
        public float FloorY => _floorY;
        public float ThighLength => _thigh;
        public float ShinLength => _shin;

        /// <summary>Une épingle IK : une main ou un pied tenu à un point (un clavier, un livre, le sol).</summary>
        sealed class Limb
        {
            public Vector3 Position;
            public Quaternion Rotation;
            public bool HasRotation;
            public Vector3? Hint;
            public float Target, Weight;
            public float FadeS = 0.35f;
        }

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
            _neck = a.GetBoneTransform(HumanBodyBones.Neck);
            var lArm = a.GetBoneTransform(HumanBodyBones.LeftUpperArm);
            var rArm = a.GetBoneTransform(HumanBodyBones.RightUpperArm);
            // La largeur du buste : celle des épaules, plus l'épaisseur du sweat.
            if (lArm != null && rArm != null) _torsoHalfWidth = Vector3.Distance(lArm.position, rArm.position) * 0.5f + 0.02f;
            MeasureLegs(a);
            _procedural =a.runtimeAnimatorController == null || !BodyAnim.HasParameter(a, BodyAnim.Speed);
            _poser?.Dispose();
            _poser = _procedural ? new HumanoidPoser(a) : null;
            if (_procedural)
                a.enabled = false; // le poseur écrit les os lui-même
            var relay = a.gameObject.GetOrAdd<IkRelay>();
            relay.Body = this;
        }

        void OnDestroy() => _poser?.Dispose();

        /// <summary>Longueurs des jambes et largeur du bassin, lues sur le squelette au repos.</summary>
        void MeasureLegs(Animator a)
        {
            var lu = a.GetBoneTransform(HumanBodyBones.LeftUpperLeg);
            var ll = a.GetBoneTransform(HumanBodyBones.LeftLowerLeg);
            var lf = a.GetBoneTransform(HumanBodyBones.LeftFoot);
            var ru = a.GetBoneTransform(HumanBodyBones.RightUpperLeg);
            if (lu == null || ll == null || lf == null) return;
            _thigh = Vector3.Distance(lu.position, ll.position);
            _shin = Vector3.Distance(ll.position, lf.position);
            if (ru != null) _hipHalfWidth = Vector3.Distance(lu.position, ru.position) * 0.5f;
            // La cheville au-dessus de la plante du pied : la hauteur de l'os du pied au-dessus des orteils, au repos.
            var toes = a.GetBoneTransform(HumanBodyBones.LeftToes);
            _ankle = toes != null ? Mathf.Clamp(lf.position.y - toes.position.y + 0.03f, 0.05f, 0.14f) : 0.08f;
            // L'avant-pied (l'articulation des orteils) devant la cheville, le talon un peu plus de moitié moins loin derrière.
            if (toes != null)
            {
                var ball = Vector3.ProjectOnPlane(toes.position - lf.position, Vector3.up).magnitude;
                _planter.Configure(ball * 0.55f, ball);
            }
            for (var s = 0; s < 2; s++)
            {
                _legUpper[s] = a.GetBoneTransform(s == 0 ? HumanBodyBones.LeftUpperLeg : HumanBodyBones.RightUpperLeg);
                _legLower[s] = a.GetBoneTransform(s == 0 ? HumanBodyBones.LeftLowerLeg : HumanBodyBones.RightLowerLeg);
                _legFoot[s] = a.GetBoneTransform(s == 0 ? HumanBodyBones.LeftFoot : HumanBodyBones.RightFoot);
                _legToes[s] = a.GetBoneTransform(s == 0 ? HumanBodyBones.LeftToes : HumanBodyBones.RightToes);
                if (_legFoot[s] == null) continue;
                // Au repos le pied est à plat : son repère regarde vers ses orteils (ou devant elle), le dessus en haut.
                var along = _legToes[s] != null ? Vector3.ProjectOnPlane(_legToes[s].position - _legFoot[s].position, Vector3.up) : Vector3.zero;
                var heading = along.sqrMagnitude > 1e-6f ? along.normalized : FlatDir(a.transform.forward);
                _footFrame[s] = Quaternion.Inverse(_legFoot[s].rotation) * Quaternion.LookRotation(heading, Vector3.up);
            }
        }

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
            var seatedNow = _posture == Posture.Sit && _anchor.HasValue && (_procedural ? _sit > 0.9f : InPostureState());
            // Les pieds se posent pendant la fin de la transition, et quittent le sol dès qu'elle se lève.
            _seated = Mathf.MoveTowards(_seated, seatedNow ? 1f : 0f, dt / (seatedNow ? 0.45f : 0.25f));
            foreach (var l in _limbs)
                l.Weight = Mathf.MoveTowards(l.Weight, l.Target, dt / Mathf.Max(0.05f, l.FadeS));

            if (!_procedural && animator != null && animator.runtimeAnimatorController != null)
            {
                animator.SetFloat(BodyAnim.Speed, StepSpeed);
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
            if (!_procedural && animator != null) FeetOnFloor();
            RecalAnchor();
        }

        /// <summary>Assise ou allongée : amène les hanches sur le siège, le corps sur le lit, quel que soit le clip.</summary>
        void RecalAnchor()
        {
            if (!_anchor.HasValue || _hips == null) return;
            // On ne recale que quand la posture est atteinte (états marqués « seated », « lying » par le
            // constructeur), transition terminée : pendant un fondu, les hanches sont encore à hauteur debout, et
            // les amener sur le siège enfonçait tout le corps dans le sol.
            if (!_procedural && animator != null && animator.runtimeAnimatorController != null && !InPostureState()) return;
            var a = Anchor.Value;
            var k = 1f - Mathf.Exp(-Time.deltaTime * 8f);
            if (_posture == Posture.Sit && _sit > 0.5f)
            {
                // Assise sur une chaise que ses gestes déplacent (BodyActivity la mène juste avant) : le corps suit le siège
                // sans retard — lissé, il glissait sur l'assise pendant qu'elle roulait ou pivotait.
                if (_anchorLive != null && _seated >= 1f) k = 1f;
                // Le corps suit le siège qui pivote (tournée vers quelqu'un, vers son carnet) ; d'abord l'orientation,
                // puis les hanches ramenées sur le siège.
                if (_anchorLive != null)
                    transform.rotation = Quaternion.Slerp(transform.rotation, a.rotation, k * _anchorBlend);
                var delta = a.position - _hips.position;
                transform.position += delta * k * _anchorBlend;
                if (_seated >= 1f)
                {
                    var above = _hips.position.y - transform.position.y;
                    _seatedHips = _seatedHips > 0f ? Mathf.Lerp(_seatedHips, above, 0.05f) : above;
                }
            }
            else if (_posture == Posture.Lie && _lie > 0.5f)
            {
                // Sur le côté, les hanches sont plus hautes que sur le dos (la largeur du bassin) : sans ce relèvement
                // elle s'enfoncerait dans le matelas.
                _lieLift = Mathf.MoveTowards(_lieLift, _lieSide != 0 ? 0.07f : 0f, Time.deltaTime / 1.6f * 0.07f);
                var delta = a.position + Vector3.up * _lieLift - _hips.position;
                transform.position += delta * k * _anchorBlend;
            }
        }

        static readonly int SeatedTag = Animator.StringToHash("seated");
        static readonly int LyingTag = Animator.StringToHash("lying");

        bool InPostureState()
        {
            var tag = _posture == Posture.Sit ? SeatedTag : LyingTag;
            return !animator.IsInTransition(0) && animator.GetCurrentAnimatorStateInfo(0).tagHash == tag;
        }

        // --- primitives ---------------------------------------------------------------------------------------
        /// <summary>Pose le corps sans rien jouer (un instantané, une arrivée tardive).</summary>
        public void Snap(Vector3 position, Quaternion rotation, Posture posture, PlaceView place = null)
        {
            AbandonChoreography();
            StopAgent(keepEnabled: false);
            _posture = posture;
            _place = place;
            _sit = _sitTarget = posture == Posture.Sit ? 1f : 0f;
            _lie = _lieTarget = posture == Posture.Lie ? 1f : 0f;
            _anchor = null;
            _anchorLive = null;
            _anchorBlend = 0;
            _floorY = place != null ? GroundUnder(place.Position) : GroundUnder(position);
            if (place != null && posture == Posture.Sit)
            {
                var seat = place.Seat;
                _anchor = seat;
                _anchorLive = place.SeatTransform;
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
            _planter.Reset();
            ApplyAnimatorPostureNow();
            JumpToPostureState();
            // Les cheveux et les vêtements à ressorts prendraient ce saut pour une vitesse : on les remet au repos.
            BroadcastMessage("OnTeleported", SendMessageOptions.DontRequireReceiver);
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
            // Les pieds restent plantés pendant que le corps pivote, et font de petits pas pour suivre
            // (FootPlanter) : la marche jouée sur place faisait pédaler les jambes, pieds glissant en arrière.
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

        /// <summary>La vitesse de marche à jouer : celle du corps.</summary>
        public float StepSpeed => _speed;

        /// <summary>
        /// Change de posture sur un lieu (s'asseoir, s'allonger, se lever). Avec un contrôleur d'animation, le
        /// geste est chorégraphié comme le ferait quelqu'un : reculer la chaise, faire un pas devant l'assise, s'y
        /// asseoir, rouler vers le bureau ; s'asseoir au bord du lit avant de s'y allonger ; l'inverse pour se
        /// lever. <paramref name="duration"/> (celle du noyau) est un minimum : un geste plus court attend la fin.
        /// </summary>
        public IEnumerator ChangePosture(Posture to, PlaceView place, float duration)
        {
            if (to == _posture && (place == null || _anchor.HasValue)) yield break;
            StopAgent(keepEnabled: false); // la transition déplace le corps hors du sol navigable
            var started = Time.time;
            var from = _posture;
            if (!_procedural && animator != null && animator.runtimeAnimatorController != null)
            {
                var here = place ?? _place;
                // Se lever d'une chaise de bureau : elle la ramène d'abord à sa place par ses propres gestes (elle se
                // tourne vers le bureau, le repousse des mains) — la chaise ne bouge jamais d'elle-même.
                if (from == Posture.Sit && to != Posture.Sit && BeforeStanding != null)
                    yield return BeforeStanding();
                Choreographing = true;
                try
                {
                    if (from == Posture.Stand && to == Posture.Sit && here != null) yield return SitDown(here);
                    else if (from == Posture.Stand && to == Posture.Lie && here != null)
                    {
                        yield return SitDown(here);
                        yield return LieDown(here);
                    }
                    else if (from == Posture.Sit && to == Posture.Lie && here != null) yield return LieDown(here);
                    else if (from == Posture.Lie && to == Posture.Sit && here != null) yield return SitUp(here);
                    else if (from == Posture.Lie && to == Posture.Stand && here != null)
                    {
                        yield return SitUp(here);
                        yield return StandUp(here);
                    }
                    else if (from == Posture.Sit && to == Posture.Stand) yield return StandUp(here);
                    else yield return Blend(to, place, duration);
                }
                finally
                {
                    Choreographing = false;
                }
                var rest = duration - (Time.time - started);
                if (rest > 0.05f) yield return new WaitForSeconds(rest);
                yield break;
            }
            yield return Blend(to, place, duration);
        }

        /// <summary>Vrai pendant un changement de posture : l'occupation lâche les mains et ne touche pas la chaise.</summary>
        public bool Choreographing { get; private set; }

        /// <summary>
        /// Avant de se lever d'un siège : ce que l'occupation doit d'abord défaire (ramener la chaise de bureau à sa
        /// place, par les gestes qui la déplacent). Posé par <see cref="BodyActivity"/>.
        /// </summary>
        public Func<IEnumerator> BeforeStanding { get; set; }

        /// <summary>
        /// Une chorégraphie interrompue (l'action remplacée en cours de route, un saut d'état) : Unity arrête une
        /// coroutine sans passer par ses <c>finally</c>, si bien qu'une assise abandonnée laissait le corps
        /// « chorégraphié » pour de bon — pieds jamais rendus au sol, mouvement de racine du clip toujours appliqué,
        /// posture à moitié ancrée. On rend ce qu'elle tenait et on achève l'ancrage là où elle allait.
        /// </summary>
        public void AbandonChoreography()
        {
            _stepping = false;
            // Une main tendue coupée en route (Reach) : sans cela le bras restait tendu vers l'ancien point, et
            // l'épingle de cette main (clavier, arrosoir, couette…) était sautée pour de bon par OnIK.
            if (_ikPoint.HasValue)
            {
                if (_look == _ikPoint) _look = null;
                _ikPoint = null;
            }
            _ikWeightTarget = 0f;
            _reachTarget = 0f;
            if (!Choreographing && !_rootMotion) return;
            Choreographing = false;
            _rootMotion = false;
            if (_anchor.HasValue) _anchorBlend = 1f;
            ReleaseFeet(0.2f);
        }

        /// <summary>Où l'on se tient avant de s'asseoir : un peu devant l'assise, dos à elle.</summary>
        const float StandOff = 0.2f;

        /// <summary>
        /// S'asseoir : faire un pas devant l'assise (dos à elle), descendre dessus en une seconde — le buste penché, les
        /// hanches vers l'arrière. Une chaise de bureau est prise là où elle est (à sa place, où elle l'a laissée en se
        /// levant) : c'est ensuite l'occupation qui la rapproche du bureau, par ses gestes (<see cref="BodyActivity"/>).
        /// </summary>
        IEnumerator SitDown(PlaceView place)
        {
            var chair = place.Chair;
            var seatT = place.SeatTransform;
            if (chair != null) chair.Carry(seatT);
            _floorY = GroundUnder(transform.position);
            var seat = place.Seat;
            var fwd = FlatDir(seat.rotation * Vector3.forward);
            // Le clip capturé recule les hanches d'une longueur connue : on se place d'autant devant l'assise, dos à elle.
            var captured = Captured(clips != null ? clips.sitTravelNorm : 0f);
            var travel = captured ? clips.sitTravelNorm * animator.humanScale : StandOff;
            var stand = new Vector3(seat.position.x, _floorY, seat.position.z) + fwd * travel;
            // À une chaise à accoudoirs, elle passe à côté d'elle puis entre devant le siège (ligne droite : à travers l'accoudoir).
            if (chair != null && AroundChair(seat, stand, transform.position, out var corner))
                yield return Step(corner, Quaternion.LookRotation(FlatDir(stand - corner)), 0.75f);
            yield return Step(stand, Quaternion.LookRotation(fwd), 0.75f);

            _place = place;
            _posture = Posture.Sit;
            _anchor = seat;
            _anchorLive = seatT;
            _sitTarget = 1f;
            _lieTarget = 0f;
            _anchorBlend = 0f;
            // Sur un siège à la hauteur des clips (la chaise, le lit), la capture tient ses pieds elle-même ; épinglés
            // côte à côte sous elle, ils glissaient vers leur place de la capture pendant la descente.
            if (!SeatFitsClips) PlantFeet();
            ApplyAnimatorPostureNow();
            var start = transform.position;
            var startRot = transform.rotation;
            var d = captured && clips.sitDownSeconds > 0.3f ? clips.sitDownSeconds : 1.05f;
            _rootMotion = captured;
            var t = 0f;
            while (t < d + 0.3f)
            {
                t += Time.deltaTime;
                var now = Anchor.Value;
                var p = Mathf.Clamp01(t / d);
                // Le siège est plus haut (ou plus bas) que celui de la prise : la racine monte d'autant pendant que
                // les hanches descendent (seconde moitié), les pieds restent plantés.
                var rootY = Mathf.Max(_floorY, now.position.y - SeatedHipsAboveRoot);
                var y = Mathf.Lerp(start.y, rootY, Mathf.SmoothStep(0f, 1f, Mathf.Clamp01((p - 0.35f) / 0.6f)));
                if (captured)
                {
                    // Le clip recule les hanches ; on ne corrige que l'écart restant à la toute fin.
                    var pos = transform.position;
                    var late = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01((p - 0.8f) / 0.2f));
                    var onSeat = new Vector3(now.position.x, pos.y, now.position.z);
                    var xz = Vector3.Lerp(pos, onSeat, late * 0.25f);
                    transform.SetPositionAndRotation(new Vector3(xz.x, y, xz.z), Quaternion.Slerp(startRot, now.rotation, Mathf.SmoothStep(0f, 1f, p)));
                }
                else
                {
                    var root = new Vector3(now.position.x, rootY, now.position.z);
                    var k = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01((p - 0.15f) / 0.85f));
                    var xz = Vector3.Lerp(start, root, k);
                    transform.SetPositionAndRotation(new Vector3(xz.x, y, xz.z), Quaternion.Slerp(startRot, now.rotation, k));
                }
                _anchorBlend = p;
                if (p >= 1f && InPostureState()) break;
                yield return null;
            }
            _rootMotion = false;
            _anchorBlend = 1f;
            // Assise : les pieds passent de leur appui debout à leur place devant le siège.
            ReleaseFeet(0.5f);
        }

        /// <summary>
        /// Se lever : se redresser au-dessus de ses pieds — la capture avance les hanches d'une longueur connue —, puis
        /// s'écarter vers le point d'approche. La chaise reste là où ses gestes l'ont ramenée (<see cref="BeforeStanding"/>).
        /// </summary>
        IEnumerator StandUp(PlaceView place)
        {
            var a = Anchor ?? new Pose(transform.position, transform.rotation);
            var fwd = FlatDir(a.rotation * Vector3.forward);
            var floor = _floorY != 0f || place == null ? _floorY : GroundUnder(place.Position);
            var captured = Captured(clips != null ? clips.standTravelNorm : 0f);
            var travel = captured ? clips.standTravelNorm * animator.humanScale : StandOff;
            var stand = new Vector3(a.position.x, floor, a.position.z) + fwd * travel;
            // Les pieds restent où l'assise les a mis (devant le siège, devant le lit) : la capture se lève au-dessus
            // d'eux. Sur un siège à la hauteur des clips (la chaise, le lit), le clip les tient lui-même (appuis cuits
            // dans l'atelier) ; ailleurs on les épingle là où ils sont. Replacés sous le corps, ils partaient sous le lit
            // pendant qu'elle se levait.
            if (!SeatFitsClips) PlantFeet(whereTheyAre: true);
            _posture = Posture.Stand;
            _anchor = null;
            _anchorLive = null;
            _sitTarget = 0f;
            _lieTarget = 0f;
            _anchorBlend = 0f;
            ApplyAnimatorPostureNow();
            var start = transform.position;
            var startRot = transform.rotation;
            var face = Quaternion.LookRotation(fwd);
            var d = captured && clips.standUpSeconds > 0.3f ? clips.standUpSeconds : 0.95f;
            _rootMotion = captured;
            var t = 0f;
            while (t < d)
            {
                t += Time.deltaTime;
                var p = Mathf.Clamp01(t / d);
                // La racine redescend au sol pendant que les jambes poussent (première moitié).
                var y = Mathf.Lerp(start.y, floor, Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(p / 0.6f)));
                Vector3 xz;
                if (captured)
                {
                    // Le mouvement de racine du clip seul (ses appuis sont cuits dans l'atelier) : tirée vers le point
                    // calculé en fin de geste, la racine faisait glisser les pieds de 5 cm. Le pas qui suit rejoint le lieu.
                    xz = transform.position;
                }
                else
                {
                    xz = Vector3.Lerp(start, stand, Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(p * 1.15f)));
                }
                transform.SetPositionAndRotation(new Vector3(xz.x, y, xz.z), Quaternion.Slerp(startRot, face, Mathf.SmoothStep(0f, 1f, p)));
                yield return null;
            }
            _rootMotion = false;
            ReleaseFeet(0.3f);
            // Debout : les pieds tiennent d'eux-mêmes dès la fin du clip (le fondu vers l'attente déplaçait l'appui de 5 cm).
            _speed = 0f;
            _planter.Still();
            _stepping = true;
            if (place != null && Vector3.Distance(Ground(place.Position), Ground(transform.position)) > 0.12f)
            {
                // De devant le siège, elle ressort par le côté de la chaise (pas à travers l'accoudoir).
                var approach = new Vector3(place.Position.x, floor, place.Position.z);
                if (place.Chair != null && AroundChair(a, transform.position, approach, out var corner))
                    yield return Step(new Vector3(corner.x, floor, corner.z), Quaternion.LookRotation(FlatDir(approach - corner)), 0.75f);
                yield return Step(approach, place.Rotation, 0.75f);
            }
            _stepping = false;
            EnsureAgent();
            WarpAgent(transform.position);
        }

        /// <summary>S'allonger depuis le bord du lit : pivoter, ramener les jambes, se laisser aller sur le dos.</summary>
        IEnumerator LieDown(PlaceView place)
        {
            var lie = place.Lie;
            var start = transform.position;
            var startRot = transform.rotation;
            var end = LieRootPosition(lie);
            var endRot = LieRootRotation(lie);
            _place = place;
            _posture = Posture.Lie;
            _anchor = lie;
            _anchorLive = null;
            _lieTarget = 1f;
            _sitTarget = 0f;
            _anchorBlend = 0f;
            ApplyAnimatorPostureNow();
            const float d = 1.6f;
            var t = 0f;
            while (t < d)
            {
                t += Time.deltaTime;
                var k = Mathf.SmoothStep(0f, 1f, t / d);
                // Le corps pivote d'abord (les jambes montent sur le lit), puis s'allonge.
                var turn = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(t / d * 1.4f));
                transform.SetPositionAndRotation(Vector3.Lerp(start, end, k), Quaternion.Slerp(startRot, endRot, turn));
                _anchorBlend = k;
                yield return null;
            }
            _anchorBlend = 1f;
        }

        /// <summary>Se redresser au bord du lit : l'inverse de <see cref="LieDown"/>.</summary>
        IEnumerator SitUp(PlaceView place)
        {
            SetLieSide(0);
            var seat = place.Seat;
            var start = transform.position;
            var startRot = transform.rotation;
            _place = place;
            _posture = Posture.Sit;
            _anchor = seat;
            _anchorLive = place.SeatTransform;
            _sitTarget = 1f;
            _lieTarget = 0f;
            _anchorBlend = 0f;
            ApplyAnimatorPostureNow();
            var end = new Vector3(seat.position.x, Mathf.Max(_floorY, seat.position.y - SeatedHipsAboveRoot), seat.position.z);
            const float d = 1.5f;
            var t = 0f;
            while (t < d)
            {
                t += Time.deltaTime;
                var k = Mathf.SmoothStep(0f, 1f, t / d);
                var turn = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01((t / d - 0.25f) / 0.75f));
                transform.SetPositionAndRotation(Vector3.Lerp(start, end, k), Quaternion.Slerp(startRot, seat.rotation, turn));
                _anchorBlend = k;
                yield return null;
            }
            _anchorBlend = 1f;
        }

        /// <summary>
        /// Quelques pas courts jusqu'à un point proche (devant une chaise, à côté d'un lit), sans navmesh. Au-delà de
        /// <see cref="ShuffleMax"/>, une vraie marche : se tourner d'abord sur place (les pieds suivent à petits pas), puis
        /// marcher droit, la vitesse mesurée enclenchant la marche — tourner en avançant faisait glisser les pieds pendant
        /// que la marche démarrait. En deçà, se décaler sans se retourner, lentement, sous le seuil de la marche : les pieds
        /// restent plantés et suivent par petits pas (<see cref="FootPlanter"/>) ; à la vitesse d'une marche, la marche
        /// jouée de face pendant un pas de côté les faisait glisser d'autant.
        /// </summary>
        IEnumerator Step(Vector3 target, Quaternion facing, float speed)
        {
            _stepping = true;
            var start = transform.position;
            target.y = start.y;
            var delta = Ground(target - start);
            var dist = delta.magnitude;
            if (dist > 0.04f)
            {
                float d;
                if (dist > ShuffleMax)
                {
                    var walkFacing = Quaternion.LookRotation(delta.normalized);
                    var turn = Quaternion.Angle(transform.rotation, walkFacing);
                    if (turn > 10f) yield return TurnTo(walkFacing, Mathf.Clamp(turn / 160f, 0.3f, 1.1f));
                    d = Mathf.Max(0.45f, dist / speed);
                }
                else
                {
                    // D'abord immobile un instant (au sortir d'un lever, le corps vient de bouger : le planteur se croirait
                    // encore en marche et laisserait les pieds au clip), puis le décalage.
                    for (var w = 0f; w < 1f && _speed > 0.04f; w += Time.deltaTime) yield return null;
                    yield return new WaitForSeconds(0.5f);
                    d = dist / ShuffleSpeed;
                }
                var t = 0f;
                while (t < d)
                {
                    t += Time.deltaTime;
                    transform.position = Vector3.Lerp(start, target, Trapezoid(t / d, 0.2f));
                    yield return null;
                }
                transform.position = target;
            }
            if (Quaternion.Angle(transform.rotation, facing) > 2f)
                yield return TurnTo(facing, Mathf.Clamp(Quaternion.Angle(transform.rotation, facing) / 220f, 0.2f, 0.6f));
            _stepping = false;
        }

        /// <summary>
        /// Entre le point devant le siège (<paramref name="front"/>) et un point à côté de la chaise (<paramref name="side"/>),
        /// le coin par où passer : à côté de l'accoudoir, à la hauteur du point devant le siège. Faux si le point est
        /// devant ou derrière la chaise (la ligne droite ne la traverse pas).
        /// </summary>
        static bool AroundChair(Pose seat, Vector3 front, Vector3 side, out Vector3 corner)
        {
            var fwd = FlatDir(seat.rotation * Vector3.forward);
            var right = Vector3.Cross(Vector3.up, fwd);
            var lateral = Vector3.Dot(Ground(side - seat.position), right);
            corner = front;
            if (Mathf.Abs(lateral) < ChairClear) return false;
            corner = front + right * (Mathf.Sign(lateral) * ChairClear);
            corner.y = front.y;
            return true;
        }

        /// <summary>
        /// À quelle distance du milieu du siège elle passe à côté de la chaise (m) : l'accoudoir s'étend à 0,34 m, son
        /// corps à 0,14 m de part et d'autre.
        /// </summary>
        const float ChairClear = 0.48f;

        /// <summary>Au-delà (m), on marche pour rejoindre un point proche ; en deçà, on se décale à petits pas.</summary>
        const float ShuffleMax = 0.3f;
        /// <summary>La vitesse d'un décalage à petits pas (m/s) : au plus haut, sous le seuil où le FootPlanter marche (0,1).</summary>
        const float ShuffleSpeed = 0.06f;

        /// <summary>
        /// Une course à vitesse constante, qui démarre et s'arrête en douceur (accélération sur la fraction
        /// <paramref name="ramp"/> au début et à la fin) : u (0 → 1) → le chemin fait (0 → 1).
        /// </summary>
        static float Trapezoid(float u, float ramp)
        {
            u = Mathf.Clamp01(u);
            var v = 1f / (1f - ramp);
            if (u < ramp) return v * u * u / (2f * ramp);
            if (u > 1f - ramp) return 1f - v * (1f - u) * (1f - u) / (2f * ramp);
            return v * (u - ramp * 0.5f);
        }

        /// <summary>Une direction ramenée à l'horizontale, normée (devant soi si elle est verticale).</summary>
        static Vector3 FlatDir(Vector3 v)
        {
            v.y = 0f;
            return v.sqrMagnitude > 1e-6f ? v.normalized : Vector3.forward;
        }

        static Vector3 Ground(Vector3 p) => new Vector3(p.x, 0f, p.z);

        /// <summary>Le changement de posture sans chorégraphie (poseur procédural, cas imprévus) : un fondu sur place.</summary>
        IEnumerator Blend(Posture to, PlaceView place, float duration)
        {
            var fromPos = transform.position;
            var fromRot = transform.rotation;
            Vector3 toPos;
            Quaternion toRot;
            if (_posture == Posture.Stand) _floorY = GroundUnder(fromPos);
            switch (to)
            {
                case Posture.Sit when place != null:
                    var seat = place.Seat;
                    toPos = new Vector3(seat.position.x, Mathf.Max(fromPos.y, seat.position.y - SeatedHipsAboveRoot), seat.position.z);
                    toRot = seat.rotation;
                    _anchor = seat;
                    _anchorLive = place.SeatTransform;
                    break;
                case Posture.Lie when place != null:
                    var lie = place.Lie;
                    toPos = LieRootPosition(lie);
                    toRot = LieRootRotation(lie);
                    _anchor = lie;
                    _anchorLive = null;
                    break;
                default:
                    toPos = place != null ? place.Position : new Vector3(fromPos.x, GroundUnder(fromPos), fromPos.z);
                    toRot = place != null ? place.Rotation : Quaternion.Euler(0, fromRot.eulerAngles.y, 0);
                    _anchor = null;
                    _anchorLive = null;
                    break;
            }
            _place = place;
            _posture = to;
            _sitTarget = to == Posture.Sit ? 1f : 0f;
            _lieTarget = to == Posture.Lie ? 1f : 0f;
            _anchorBlend = 0;
            ApplyAnimatorPostureNow();
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

        int _lieSide;
        float _lieLift;

        /// <summary>Allongée : 0 sur le dos, 1 sur le côté gauche, 2 sur le côté droit.</summary>
        public int LieSide => _lieSide;

        /// <summary>Se retourner (allongée) : le contrôleur fait rouler le corps d'un côté à l'autre.</summary>
        public void SetLieSide(int side)
        {
            _lieSide = Mathf.Clamp(side, 0, 2);
            if (!_procedural && animator != null && BodyAnim.HasParameter(animator, BodyAnim.LieSide))
                animator.SetInteger(BodyAnim.LieSide, _lieSide);
        }

        /// <summary>La droite du corps allongé (dans le monde) : sur le dos, sa droite est le −X de la racine.</summary>
        public Vector3 LyingRight => transform.TransformDirection(Vector3.left);

        /// <summary>Où regarder (une personne, un objet) ; <c>null</c> : devant soi.</summary>
        public void LookAt(Vector3? point) => _look = point;

        float _groundOffset, _floorLeft, _floorRight;
        static readonly RaycastHit[] FloorHits = new RaycastHit[8];
        readonly FootPlanter _planter = new FootPlanter();

        /// <summary>Pour le labo : la correction du bassin et l'état des pieds (voir <see cref="FootPlanter.Describe"/>).</summary>
        public string FeetState() => $"bassin {_groundOffset:+0.000;-0.000} sol {_floorLeft:0.000}/{_floorRight:0.000} {_planter.Describe()}";

        /// <summary>
        /// Debout, rien ne dirige les pieds (ni une chorégraphie, ni l'assise) : ils tiennent au sol d'eux-mêmes. Les pas
        /// d'une chorégraphie (<see cref="Step"/> : s'approcher d'un siège, s'en écarter) aussi — coupé, le planteur
        /// laissait les pieds suivre la racine et ils glissaient sur le sol pendant le pas.
        /// </summary>
        bool FeetFree => _posture == Posture.Stand && (!Choreographing || _stepping) && !_procedural && plantFeet && _seated <= 0f;

        bool _stepping;

        /// <summary>
        /// Ancrage au sol (debout, en marchant) : les clips capturés sont ramenés à sa taille par la hauteur des
        /// hanches, mais ses jambes sont plus courtes que celles de l'acteur par rapport à ses hanches — sans
        /// correction ses pieds flottaient de 4 cm. À chaque image, le bassin descend (ou monte) pour que le pied le
        /// plus bas de l'animation touche le sol.
        /// </summary>
        /// <remarks>
        /// Asymétrique : une semelle sous le sol remonte le bassin tout de suite ; des pieds au-dessus ne le font
        /// redescendre que lentement debout (plus vite en marchant, où le pied d'appui change à chaque pas). Lissé
        /// dans les deux sens, l'ancrage écrasait le rebond de l'attente joyeuse et, en retard, enfonçait les pieds
        /// dans le sol au bas du rebond. En haut du rebond, ce sont les talons qui montent (<see cref="FootPlanter"/>).
        /// </remarks>
        void FeetOnFloor()
        {
            if (_legFoot[0] == null || _legFoot[1] == null) return;
            // Les os portent la pose de l'animation, bassin compris tel que la passe IK l'a placé à cette image.
            var applied = _groundOffset;
            _planter.SampleBones(_legFoot, _footFrame, applied);
            var active = FeetFree;
            var target = 0f;
            if (active)
            {
                // Le sol sous chaque pied, pas sous le corps : sondé sous son centre, il sautait de la hauteur du
                // tapis d'un coup quand elle y entrait, et les deux pieds avec.
                _floorLeft = FloorUnderFoot(_planter.FkPosition(0));
                _floorRight = FloorUnderFoot(_planter.FkPosition(1));
                // Le point le plus bas des semelles (talon ou avant-pied), pas la cheville : sur la pointe des
                // pieds, descendre le bassin d'après la cheville enfonçait l'avant-pied dans le sol.
                target = Mathf.Clamp(-_planter.LowestGap(animator, _floorLeft, _floorRight), -0.12f, 0.06f);
            }
            // En marchant, le bassin ne suit que la moyenne du pas (le talon qui se lève, l'IK des jambes font le
            // reste) : suivre chaque pied le faisait plonger de 5 cm en fin d'appui et remonter d'un coup à
            // l'attaque suivante, un hoquet à chaque pas. Un pied franchement sous le sol le remonte tout de suite.
            float tau;
            if (_speed > 0.1f) tau = target - _groundOffset > 0.03f ? 0.02f : 0.4f;
            else tau = target > _groundOffset ? 0.02f : 1.5f;
            _groundOffset = Mathf.Lerp(_groundOffset, target, 1f - Mathf.Exp(-Time.deltaTime / tau));
            // Les pieds, eux, sont placés tout de suite, sur la pose de cette image.
            _planter.Update(animator, active, _floorLeft, _floorRight, applied, _speed, Time.deltaTime, active && ClipHoldsFeet());
            _planter.Solve(_legUpper, _legLower, _legFoot, _legToes, _footFrame, FlatDir(transform.forward));
        }

        Vector3 _stillPos;
        float _stillYaw, _stillFor;
        int _gestureLayer = -2, _handLayer = -2;

        /// <summary>
        /// L'animation tient-elle les pieds d'elle-même ? Debout et à l'arrêt, hors fondu entre deux clips, sans geste
        /// ni bras tendu en cours (ces couches touchent au bassin), le corps immobile depuis un quart de seconde (un
        /// demi-tour sur place emporte les pieds) : les clips de l'atelier ont alors leurs appuis justes, et
        /// <see cref="FootPlanter"/> les suit au lieu de les verrouiller.
        /// </summary>
        bool ClipHoldsFeet()
        {
            var dt = Mathf.Max(Time.deltaTime, 1e-4f);
            var pos = transform.position;
            var yaw = transform.eulerAngles.y;
            var moving = Ground(pos - _stillPos).magnitude / dt > 0.05f || Mathf.Abs(Mathf.DeltaAngle(yaw, _stillYaw)) / dt > 8f;
            _stillPos = pos;
            _stillYaw = yaw;
            _stillFor = moving ? 0f : _stillFor + Time.deltaTime;
            if (_speed > 0.1f || _stillFor < 0.25f || animator.IsInTransition(0)) return false;
            if (_gestureLayer == -2) _gestureLayer = animator.GetLayerIndex("Gestes");
            if (_handLayer == -2) _handLayer = animator.GetLayerIndex("Main");
            return !LayerBusy(_gestureLayer) && !LayerBusy(_handLayer);
        }

        bool LayerBusy(int layer) => layer >= 0 && (animator.IsInTransition(layer) || animator.GetCurrentAnimatorClipInfoCount(layer) > 0);

        // Les jambes, pour l'IK des pieds (voir FootPlanter) ; le repère de chaque pied (avant = la pointe, haut = le
        // dessus du pied à plat), relevé sur le squelette au repos.
        readonly Transform[] _legUpper = new Transform[2], _legLower = new Transform[2], _legFoot = new Transform[2], _legToes = new Transform[2];
        readonly Quaternion[] _footFrame = { Quaternion.identity, Quaternion.identity };

        /// <summary>Où regarde l'occupation en cours (l'écran, le livre) quand personne n'attire son regard.</summary>
        public void SetActivityLook(Vector3? point) => _activityLook = point;

        /// <summary>
        /// Tient une main ou un pied à un point (un clavier, un livre, le matelas) ; <paramref name="rotation"/> :
        /// l'orientation de la main ou du pied, <paramref name="hint"/> : vers où plier le coude ou le genou.
        /// À rappeler à chaque image tant que le point bouge ; le poids monte et descend en douceur.
        /// </summary>
        public void Pin(AvatarIKGoal goal, Vector3 position, Quaternion? rotation = null, Vector3? hint = null, float weight = 1f, float fadeS = 0.35f)
        {
            var l = _limbs[(int)goal];
            l.Position = position;
            l.HasRotation = rotation.HasValue;
            if (rotation.HasValue) l.Rotation = rotation.Value;
            l.Hint = hint;
            l.Target = Mathf.Clamp01(weight);
            l.FadeS = fadeS;
        }

        public void Unpin(AvatarIKGoal goal, float fadeS = 0.35f)
        {
            var l = _limbs[(int)goal];
            l.Target = 0f;
            l.FadeS = fadeS;
        }

        public float PinWeight(AvatarIKGoal goal) => _limbs[(int)goal].Weight;

        /// <summary>Le déplacement du clip pour cette image (relayé par <see cref="IkRelay"/>) : appliqué à l'horizontale si demandé.</summary>
        internal void OnRootMotion(Vector3 delta)
        {
            if (!_rootMotion) return;
            delta.y = 0f;
            transform.position += delta;
        }

        /// <summary>
        /// Plante les pieds (on s'assoit, on se lève sans qu'ils glissent) : côte à côte sous elle avant de s'asseoir —
        /// pas là où le dernier pas les a laissés (un pied encore en arrière resterait coincé sous la chaise pendant toute
        /// la descente) —, ou là où ils sont (<paramref name="whereTheyAre"/> : assise, devant le siège, pour se lever).
        /// </summary>
        void PlantFeet(bool whereTheyAre = false)
        {
            if (!plantFeet) return;
            for (var s = 0; s < 2; s++)
            {
                var goal = s == 0 ? AvatarIKGoal.LeftFoot : AvatarIKGoal.RightFoot;
                var bone = animator.GetBoneTransform(s == 0 ? HumanBodyBones.LeftFoot : HumanBodyBones.RightFoot);
                if (bone == null) continue;
                var fwd = FlatDir(transform.forward);
                var toe = Quaternion.AngleAxis(s == 0 ? -8f : 8f, Vector3.up) * fwd;
                var right = Vector3.Cross(Vector3.up, fwd);
                var p = whereTheyAre ? bone.position : transform.position + fwd * 0.04f + right * ((s == 0 ? -1f : 1f) * (_hipHalfWidth + 0.02f));
                if (!whereTheyAre) p.y = _floorY + _ankle;
                if (whereTheyAre) toe = FlatDir(bone.rotation * _footFrame[s] * Vector3.forward);
                var l = _limbs[(int)goal];
                l.Position = p;
                l.Rotation = Quaternion.LookRotation(toe, Vector3.up);
                l.HasRotation = true;
                l.Hint = p + fwd * 0.35f + Vector3.up * 0.45f;
                l.Target = 1f;
                l.Weight = Mathf.Max(l.Weight, 0.6f);
                l.FadeS = 0.2f;
            }
        }

        void ReleaseFeet(float fadeS)
        {
            Unpin(AvatarIKGoal.LeftFoot, fadeS);
            Unpin(AvatarIKGoal.RightFoot, fadeS);
        }

        bool Captured(float norm) => clips != null && norm > 0f && animator != null && animator.humanScale > 0f;

        /// <summary>La hauteur des hanches au-dessus de la racine en posture assise (mesurée une fois assise).</summary>
        float SeatedHipsAboveRoot => _seatedHips > 0f ? _seatedHips
            : Captured(clips != null ? clips.sitHipsNorm : 0f) ? clips.sitHipsNorm * animator.humanScale : _shin + _ankle;
        float _seatedHips;

        // --- IK (appelé par IkRelay depuis l'objet qui porte l'Animator) -------------------------------------
        internal void OnIK(int layer = 0)
        {
            if (animator == null) return;
            // Le bassin, monté ou descendu pour que les pieds touchent le sol (calculé après l'animation, à l'image
            // précédente : voir FeetOnFloor) ; les mains épinglées en tiennent compte.
            if (layer == 0 && Mathf.Abs(_groundOffset) > 1e-4f)
                animator.bodyPosition += Vector3.up * _groundOffset;
            for (var g = 0; g < 4; g++)
            {
                var goal = (AvatarIKGoal)g;
                var l = _limbs[g];
                var w = l.Weight;
                // Tendre la main (prendre, poser) passe avant une épingle de la même main.
                if (_ikPoint.HasValue && goal == _ikGoal) continue;
                animator.SetIKPositionWeight(goal, w);
                animator.SetIKRotationWeight(goal, l.HasRotation ? w : 0f);
                if (w <= 0f) continue;
                var target = goal == AvatarIKGoal.LeftHand || goal == AvatarIKGoal.RightHand ? OutsideTorso(l.Position) : l.Position;
                animator.SetIKPosition(goal, target);
                if (l.HasRotation) animator.SetIKRotation(goal, l.Rotation);
                var hint = HintOf(goal);
                if (l.Hint.HasValue)
                {
                    animator.SetIKHintPositionWeight(hint, w);
                    animator.SetIKHintPosition(hint, l.Hint.Value);
                }
                else
                {
                    animator.SetIKHintPositionWeight(hint, 0f);
                }
            }
            SeatedFeet();
            if (_ikPoint.HasValue)
            {
                animator.SetIKPositionWeight(_ikGoal, _ikWeight);
                animator.SetIKPosition(_ikGoal, OutsideTorso(_ikPoint.Value));
            }
            var look = _look ?? _activityLook;
            if (look.HasValue)
            {
                var w = _look.HasValue ? _lookWeight : 1f;
                // Regarder son travail (l'écran, la page) penche aussi le buste ; regarder quelqu'un, surtout la tête.
                animator.SetLookAtWeight(w, _look.HasValue ? 0.25f : 0.4f, 0.8f, 1f, 0.6f);
                animator.SetLookAtPosition(look.Value);
            }
            else
            {
                animator.SetLookAtWeight(0);
            }
        }

        /// <summary>
        /// Une main ne traverse pas son propre buste : le torse est une boîte arrondie autour de la colonne (des
        /// hanches au cou, largeur des épaules, épaisseur du sweat) ; une cible de main dedans est repoussée devant,
        /// à la distance d'une main posée contre le ventre.
        /// </summary>
        Vector3 OutsideTorso(Vector3 p)
        {
            if (_hips == null || _neck == null) return p;
            var bottom = _hips.position;
            var top = _neck.position;
            var axis = top - bottom;
            var len = axis.magnitude;
            if (len < 1e-3f) return p;
            var up = axis / len;
            var along = Mathf.Clamp(Vector3.Dot(p - bottom, up), 0f, len);
            var center = bottom + up * along;
            // Le devant du buste : l'avant du corps, ramené perpendiculaire à la colonne (qui peut se pencher).
            var fwd = Vector3.ProjectOnPlane(transform.forward, up).normalized;
            if (_posture == Posture.Lie) return p;
            var side = Vector3.Cross(up, fwd);
            var d = p - center;
            var x = Vector3.Dot(d, side);
            var z = Vector3.Dot(d, fwd);
            const float hand = 0.05f;
            var halfWidth = _torsoHalfWidth + hand;
            var halfDepth = _torsoHalfDepth + hand;
            if (Mathf.Abs(x) >= halfWidth || z >= halfDepth || z <= -halfDepth) return p;
            // Dedans : vers l'avant (là où vont les mains), jamais à travers le dos.
            return p + fwd * (halfDepth - z);
        }

        Transform _neck;
        float _torsoHalfWidth = 0.15f, _torsoHalfDepth = 0.12f;

        static AvatarIKHint HintOf(AvatarIKGoal goal) => goal switch
        {
            AvatarIKGoal.LeftFoot => AvatarIKHint.LeftKnee,
            AvatarIKGoal.RightFoot => AvatarIKHint.RightKnee,
            AvatarIKGoal.LeftHand => AvatarIKHint.LeftElbow,
            _ => AvatarIKHint.RightElbow,
        };

        /// <summary>
        /// Assise, les pieds viennent du clip (pivoter la chaise : ils se lèvent et tournent avec elle) plutôt que de
        /// l'IK qui les pose devant le siège.
        /// </summary>
        public bool FeetFromClip { get; set; }

        /// <summary>
        /// Le siège est à la hauteur pour laquelle les clips assis sont faits (leurs hanches au-dessus du sol, à 3 cm
        /// près) : leurs pieds sont déjà au sol, vérifiés dans l'atelier contre la vraie chaise (entre les branches du
        /// piètement, talons un peu levés). L'IK les replaçait à sa façon, sur les branches.
        /// </summary>
        bool SeatFitsClips => _anchor.HasValue && Mathf.Abs(_anchor.Value.position.y - _floorY - SeatedHipsAboveRoot) < 0.03f;

        /// <summary>
        /// Assise : les pieds à plat sur le sol devant le siège, genoux au-dessus, quand le siège n'est pas à la
        /// hauteur des clips (un siège d'une autre hauteur que la chaise et le lit). Une épingle de pied explicite
        /// passe avant.
        /// </summary>
        void SeatedFeet()
        {
            if (_seated <= 0f || !_anchor.HasValue || _hips == null) return;
            if (FeetFromClip || SeatFitsClips)
            {
                foreach (var goal in new[] { AvatarIKGoal.LeftFoot, AvatarIKGoal.RightFoot })
                {
                    if (_limbs[(int)goal].Weight > 0f) continue;
                    animator.SetIKPositionWeight(goal, 0f);
                    animator.SetIKRotationWeight(goal, 0f);
                }
                return;
            }
            var a = Anchor.Value;
            var fwd = a.rotation * Vector3.forward;
            fwd.y = 0;
            fwd = fwd.sqrMagnitude > 1e-4f ? fwd.normalized : transform.forward;
            var right = Vector3.Cross(Vector3.up, fwd);
            var drop = Mathf.Max(0f, a.position.y - _floorY);
            // Les genoux à une cuisse devant les hanches, les pieds sous les genoux (un peu en avant si le siège
            // est bas, un peu en arrière s'il est haut : les talons reviennent sous le siège).
            var knee = _thigh * 0.92f;
            var under = Mathf.Clamp(drop - _shin - _ankle, -0.15f, 0.2f);
            var forward = knee - under * 0.6f;
            for (var s = 0; s < 2; s++)
            {
                var goal = s == 0 ? AvatarIKGoal.LeftFoot : AvatarIKGoal.RightFoot;
                var l = _limbs[(int)goal];
                // Un pied épinglé à fond (planté pendant qu'elle s'assoit) garde son épingle.
                if (l.Target > 0f && l.Weight >= 0.999f) continue;
                var side = (s == 0 ? -1f : 1f) * (_hipHalfWidth + 0.03f);
                var pos = new Vector3(a.position.x, _floorY + _ankle, a.position.z) + fwd * forward + right * side;
                var toe = Quaternion.AngleAxis(s == 0 ? -8f : 8f, Vector3.up) * fwd;
                var rot = Quaternion.LookRotation(toe, Vector3.up);
                var ws = Mathf.SmoothStep(0f, 1f, _seated);
                // Une épingle qui s'efface (le pied quitte son appui debout) glisse vers la place assise.
                var wl = l.Weight;
                if (wl > 0f)
                {
                    pos = Vector3.Lerp(pos, l.Position, wl);
                    if (l.HasRotation) rot = Quaternion.Slerp(rot, l.Rotation, wl);
                }
                var w = Mathf.Max(ws, wl);
                animator.SetIKPositionWeight(goal, w);
                animator.SetIKRotationWeight(goal, w);
                animator.SetIKPosition(goal, pos);
                animator.SetIKRotation(goal, rot);
                var hint = HintOf(goal);
                animator.SetIKHintPositionWeight(hint, w);
                animator.SetIKHintPosition(hint, new Vector3(pos.x, a.position.y + 0.05f, pos.z) + fwd * 0.25f);
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
            // Le maillage de navigation flotte au-dessus du vrai sol (3,3 cm ici) : posé dessus, le corps marchait
            // jambes fléchies, l'ancrage abaissant le bassin à chaque pas. On le pose sur le sol lui-même.
            _agent.baseOffset = Mathf.Clamp(FloorBelow(hit.position) - hit.position.y, -0.1f, 0f);
            _agent.Warp(hit.position);
            return _agent;
        }

        /// <summary>Le vrai sol sous un point du maillage de navigation : la surface la plus basse juste en dessous (sous un tapis, le parquet).</summary>
        float FloorBelow(Vector3 p)
        {
            var n = Physics.RaycastNonAlloc(p + Vector3.up * 0.3f, Vector3.down, FloorHits, 0.6f, ~0, QueryTriggerInteraction.Ignore);
            var floor = p.y;
            for (var i = 0; i < n; i++)
            {
                var hit = FloorHits[i];
                if (hit.normal.y > 0.7f && !hit.transform.IsChildOf(transform) && hit.point.y < floor) floor = hit.point.y;
            }
            return floor;
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

        /// <summary>
        /// Le sol sous un point : la première surface horizontale touchée en descendant (le plancher, un tapis),
        /// sinon le navmesh — qui flotte de quelques centimètres au-dessus du sol réel.
        /// </summary>
        /// <summary>Le sol sous un pied (le plus haut sol praticable sous lui, sans allocation : à chaque image).</summary>
        float FloorUnderFoot(Vector3 foot)
        {
            // Depuis 30 cm : un pied ne monte pas sur plus haut (une assise, le bord du lit au-dessus de lui ne comptent pas).
            var origin = new Vector3(foot.x, transform.position.y + 0.3f, foot.z);
            var n = Physics.RaycastNonAlloc(origin, Vector3.down, FloorHits, 1.3f, ~0, QueryTriggerInteraction.Ignore);
            var best = float.NegativeInfinity;
            var bestDistance = float.MaxValue;
            for (var i = 0; i < n; i++)
            {
                var hit = FloorHits[i];
                if (hit.normal.y <= 0.7f || hit.transform.IsChildOf(transform) || hit.distance >= bestDistance) continue;
                bestDistance = hit.distance;
                best = hit.point.y;
            }
            return float.IsNegativeInfinity(best) ? transform.position.y : best;
        }

        float GroundUnder(Vector3 p)
        {
            var hits = Physics.RaycastAll(p + Vector3.up * 0.6f, Vector3.down, 3f, ~0, QueryTriggerInteraction.Ignore);
            System.Array.Sort(hits, (x, y) => x.distance.CompareTo(y.distance));
            foreach (var hit in hits)
                if (hit.normal.y > 0.7f && !hit.transform.IsChildOf(transform))
                    return hit.point.y;
            return NavMesh.SamplePosition(p, out var nav, 2f, NavMesh.AllAreas) ? nav.position.y : 0f;
        }

        Vector3 LieRootPosition(Pose lie) => _procedural ? lie.position : new Vector3(lie.position.x, lie.position.y - (_hips != null ? 0.1f : 0f), lie.position.z);

        Quaternion LieRootRotation(Pose lie) => _procedural ? lie.rotation * Quaternion.Euler(-90f, 0f, 0f) : lie.rotation;

        void ApplyAnimatorPostureNow()
        {
            if (_procedural || animator == null || animator.runtimeAnimatorController == null) return;
            animator.SetInteger(BodyAnim.Posture, BodyAnim.PostureValue(_posture));
        }

        /// <summary>
        /// Un saut d'état saute aussi l'animation : l'Animator joue tout de suite la boucle de la posture (l'attente
        /// par défaut, l'assise, l'allongée). Sans ça, il finissait le geste en cours — s'asseoir, rester assise, se
        /// lever — là où l'on venait de la poser debout.
        /// </summary>
        void JumpToPostureState()
        {
            if (_procedural || animator == null || animator.runtimeAnimatorController == null) return;
            var state = _posture switch
            {
                Posture.Sit => "Assise",
                Posture.Lie => "Allongée",
                _ => clips != null && clips.idles.Count > 0 ? "Attente · " + clips.idles[0].clip : null,
            };
            if (state == null) return;
            var hash = Animator.StringToHash(state);
            if (animator.HasState(0, hash)) animator.Play(hash, 0, 0f);
        }
    }
}
