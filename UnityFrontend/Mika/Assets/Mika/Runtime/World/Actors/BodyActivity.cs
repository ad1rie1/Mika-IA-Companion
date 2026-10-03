using System.Collections.Generic;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// Ce que le corps fait de ses mains et de son regard pendant une occupation : taper au clavier (et passer à
    /// la souris), écrire dans un carnet, lire un livre tenu à deux mains, poser les mains sur les cuisses ou sur
    /// le matelas, s'accouder au rebord d'une fenêtre, parcourir des rayonnages, arroser une plante — et faire
    /// pivoter sa chaise vers quelqu'un qui lui parle.
    /// </summary>
    /// <remarks>
    /// L'occupation vient du noyau (<c>actor_activity</c>), la posture et le lieu du corps (<see cref="ActorBody"/>) ;
    /// ce composant ne décide rien de nouveau, il donne une forme crédible à ce qui est. Le contrôleur fournit
    /// l'attitude du buste (paramètre <see cref="BodyAnim.Pose"/>), l'IK pose les mains au point exact des objets
    /// réels de la scène : un clavier déplacé reste sous ses doigts.
    /// </remarks>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Monde/Occupation du corps")]
    public sealed class BodyActivity : MonoBehaviour
    {
        enum Mode
        {
            None,
            DeskRest,
            DeskType,
            DeskWrite,
            DeskLean,
            ReadHeld,
            BedEdge,
            Sill,
            Browse,
            Pour,
            Lying,
        }

        [Tooltip("La personne vers qui se tourner quand on lui parle (la vue de la joueuse).")]
        public Transform companion;
        [Tooltip("Au-delà (m), la personne est trop loin pour qu'elle pivote vers elle.")]
        public float engageRange = 4.5f;

        ActorBody _body;
        WorldStage _stage;
        Animator _animator;
        readonly List<WorldObject> _objects = new List<WorldObject>();
        float _objectsScannedAt = -100f;

        string _activity, _activityObject;
        Mode _mode;
        float _modeT;
        float _engagedUntil;
        ChairRig _chair;
        WorldObject _book;          // un livre tenu à deux mains pendant la lecture
        Hand _bookHand;

        // Taper : chaque main tape à son rythme, par rafales ; la droite part parfois à la souris.
        readonly Typist _left = new Typist(), _right = new Typist();
        float _burstUntil, _pauseUntil, _mouseUntil;
        bool _bursting;
        // Écrire : une ligne qui avance, puis la suivante.
        float _line, _lineX;
        // Regard qui flâne (fenêtre, rayonnages) et page qu'on tourne.
        Vector3 _gaze, _gazeTarget;
        Vector3 _workPoint;         // où travaillent les mains (le clavier, la page) : règle la distance au bureau
        float _workYaw;             // de combien la chaise se tourne vers le travail (un carnet à droite du clavier)
        WorldObject _pulled;        // un objet ramené devant elle (le carnet pour écrire), et d'où il venait
        Vector3 _pulledFrom;
        Quaternion _pulledRot;
        float _gazeNext, _pageNext, _pageT = -1f;
        float _reachNext, _reachT = -1f;
        Vector3 _reachPoint;
        int _variant;

        public string Activity => _activity;
        public string ModeName => _mode.ToString();

        sealed class Typist
        {
            public float Next, Dip, Lateral, LateralTarget, Depth, DepthTarget;
        }

        public void Bind(ActorBody body, WorldStage stage)
        {
            _body = body;
            _stage = stage;
            _animator = body.animator;
        }

        /// <summary>L'occupation que le noyau prête à l'acteur (<c>null</c> : aucune).</summary>
        public void Set(string activity, string objectId)
        {
            _activity = string.IsNullOrEmpty(activity) ? null : activity;
            _activityObject = objectId;
        }

        /// <summary>Quelqu'un lui parle (ou elle lui répond) : elle se tourne vers lui un moment.</summary>
        public void Engage(float seconds) => _engagedUntil = Mathf.Max(_engagedUntil, Time.time + seconds);

        public bool Engaged => Time.time < _engagedUntil && CompanionInRange;

        bool CompanionInRange => companion != null && _body != null &&
                                 Vector3.Distance(Flat(companion.position), Flat(_body.transform.position)) < engageRange;

        void Update()
        {
            if (_body == null || _animator == null || _animator.runtimeAnimatorController == null) return;
            var mode = Decide();
            if (mode != _mode)
            {
                Leave(_mode);
                _mode = mode;
                _modeT = 0f;
                _variant = Random.Range(0, 3);
            }
            _modeT += Time.deltaTime;
            Run(_mode);
            if (BodyAnim.HasParameter(_animator, BodyAnim.Pose))
                _animator.SetInteger(BodyAnim.Pose, BodyAnim.PoseId(PoseOf(_mode)));
        }

        // --- quelle occupation, maintenant ------------------------------------------------------------------
        Mode Decide()
        {
            // Pendant qu'elle s'assoit, se lève ou s'allonge, le corps a besoin de ses mains.
            if (_body.Choreographing)
            {
                _sawChoreography = true;
                Choreography();
                return Mode.None;
            }
            var place = _body.Place;
            var holdingBook = HeldBook() != null;
            switch (_body.Posture)
            {
                case Posture.Sit when _body.Seatedness > 0.6f && place != null:
                    if (holdingBook && (_activity == null || _activity == "read" || _activity == "browse_books")) return Mode.ReadHeld;
                    if (place.Kind == PlaceKind.Bed) return Mode.BedEdge;
                    if (Engaged) return Mode.DeskRest;
                    if (_activity == "work" && Find(KeyboardKeys, 1.6f) != null) return Mode.DeskType;
                    if (_activity == "draw") return Mode.DeskWrite;
                    if (_activity == "read" && Find(BookKeys, 1.4f) != null) return Mode.DeskWrite;
                    return Desk() != null && _variant == 2 && !Engaged ? Mode.DeskLean : Mode.DeskRest;
                case Posture.Lie:
                    return Mode.Lying;
                case Posture.Stand when _body.Speed < 0.12f:
                    if (holdingBook && (_activity == "read" || _activity == "browse_books")) return Mode.ReadHeld;
                    if (_activity == "look_outside") return Mode.Sill;
                    if (_activity == "browse_books") return Mode.Browse;
                    if (_activity == "water_plant") return Mode.Pour;
                    return Mode.None;
                default:
                    return Mode.None;
            }
        }

        /// <summary>
        /// Pendant un changement de posture au lit : elle ouvre la couette en s'y glissant, la repousse en se
        /// redressant.
        /// </summary>
        void Choreography()
        {
            var duvet = _body.Place != null && _body.Place.Kind == PlaceKind.Bed ? BedDuvet() : null;
            if (duvet == null) return;
            duvet.lastOccupied = Time.time;
            if (_body.Posture == Posture.Lie && duvet.State == DuvetState.Made && Asleep)
                duvet.SetState(DuvetState.Open, 1.2f);
            else if (_body.Posture != Posture.Lie && duvet.Covered)
                duvet.SetState(DuvetState.Open, 1.1f);
        }

        bool Asleep => BodyAnim.HasParameter(_animator, BodyAnim.Asleep) && _animator.GetBool(BodyAnim.Asleep);

        static string PoseOf(Mode m) => m switch
        {
            Mode.DeskType => "type",
            Mode.DeskWrite => "write",
            Mode.ReadHeld => "read",
            Mode.DeskRest => "lap",
            Mode.DeskLean => "lean_desk",
            Mode.BedEdge => "mattress",
            Mode.Sill => "sill",
            Mode.Browse => "none",
            Mode.Pour => "pour",
            _ => "none",
        };

        void Leave(Mode m)
        {
            _body.Unpin(AvatarIKGoal.LeftHand, 0.45f);
            _body.Unpin(AvatarIKGoal.RightHand, 0.45f);
            _body.SetActivityLook(null);
            if (m == Mode.ReadHeld && _book != null)
            {
                // Le livre retourne dans la main qui le tenait.
                if (_body.IsHolding(_book)) _body.Hold(_book, _bookHand);
                _book = null;
            }
            _pageT = -1f;
            _reachT = -1f;
            if (m == Mode.DeskWrite) PutBack();
            if (m == Mode.Lying)
            {
                _tidied = false;
                _pullT = -1f;
            }
            // Quitter une occupation (pas l'attente pendant un geste) oublie qu'un geste a eu lieu.
            if (m != Mode.None) _sawChoreography = false;
        }

        void Run(Mode m)
        {
            var chair = SeatChair();
            if (chair != null && !_body.Choreographing && _body.Seatedness > 0.95f)
            {
                // La chaise : avancée au bureau pour travailler, reculée un peu au repos, tournée vers la personne qui parle.
                var engaged = Engaged && (m == Mode.DeskRest || m == Mode.DeskLean);
                var yaw = engaged ? Mathf.Clamp(chair.YawToward(companion.position, SeatHomeRotation()), -125f, 125f) : 0f;
                // Elle ne pivote pas pour quelques degrés vers quelqu'un : en dessous de 20°, la tête suffit. Vers son
                // travail (un carnet décalé), si : un léger quart de tour.
                yaw = Mathf.Abs(yaw) < 20f ? 0f : yaw;
                if (!engaged && m == Mode.DeskWrite) yaw = _workYaw;
                chair.SwivelTo(yaw);
                chair.RollTo(m == Mode.DeskType || m == Mode.DeskWrite || m == Mode.DeskLean ? DeskRoll(_workPoint) : engaged ? -0.05f : 0f);
            }
            switch (m)
            {
                case Mode.DeskType: Type(); break;
                case Mode.DeskWrite: Write(); break;
                case Mode.DeskRest: Lap(); break;
                case Mode.DeskLean: Lean(); break;
                case Mode.ReadHeld: Read(); break;
                case Mode.BedEdge: Mattress(); break;
                case Mode.Sill: Sill(); break;
                case Mode.Browse: Browse(); break;
                case Mode.Pour: Pour(); break;
                case Mode.Lying: Lying(); break;
            }
        }

        // --- le repère du siège -------------------------------------------------------------------------------
        Vector3 Fwd
        {
            get
            {
                var a = _body.Anchor;
                var f = a.HasValue && _body.Posture == Posture.Sit ? a.Value.rotation * Vector3.forward : _body.transform.forward;
                f.y = 0;
                return f.sqrMagnitude > 1e-4f ? f.normalized : Vector3.forward;
            }
        }

        Vector3 Right => Vector3.Cross(Vector3.up, Fwd);

        Vector3 HipsPos => _body.Hips != null ? _body.Hips.position : _body.transform.position + Vector3.up * 0.9f;

        Vector3 Chest
        {
            get
            {
                var c = _animator.GetBoneTransform(HumanBodyBones.UpperChest);
                if (c == null) c = _animator.GetBoneTransform(HumanBodyBones.Chest);
                return c != null ? c.position : HipsPos + Vector3.up * 0.3f;
            }
        }

        /// <summary>
        /// L'orientation d'une main posée à plat, doigts vers <paramref name="fingers"/> : la cible IK d'une main
        /// humanoïde est la main elle-même, doigts sur +Z, paume vers −Y (repère Mecanim).
        /// </summary>
        static Quaternion Palm(Vector3 fingers, float roll = 0f, float pitch = 0f)
        {
            fingers.y = 0;
            if (fingers.sqrMagnitude < 1e-4f) fingers = Vector3.forward;
            return Quaternion.LookRotation(fingers.normalized, Vector3.up) * Quaternion.Euler(pitch, 0f, roll);
        }

        /// <summary>
        /// Où plier le coude : sous l'épaule, contre le flanc (<paramref name="outward"/> l'écarte du corps,
        /// <paramref name="forward"/> l'avance). Des coudes guidés loin du corps donnaient des bras en ailes de
        /// poulet et des mains rabattues dans la poitrine.
        /// </summary>
        Vector3 Elbow(bool left, float outward = 0.05f, float forward = 0.02f)
        {
            var arm = _animator.GetBoneTransform(left ? HumanBodyBones.LeftUpperArm : HumanBodyBones.RightUpperArm);
            var shoulder = arm != null ? arm.position : HipsPos + Vector3.up * 0.28f + Right * (left ? -0.12f : 0.12f);
            return shoulder - Vector3.up * 0.24f + Fwd * forward + Right * (left ? -outward : outward);
        }

        // --- au bureau -----------------------------------------------------------------------------------------
        void Type()
        {
            var kb = Find(KeyboardKeys, 1.6f);
            if (kb == null) return;
            var b = Bounds(kb);
            var fwd = Fwd;
            var right = Right;
            var now = Time.time;
            var talking = _animator.GetBool(BodyAnim.Talking);

            // Rafales et pauses : on tape par phrases, on relit, on va à la souris.
            if (_bursting && now > _burstUntil)
            {
                _bursting = false;
                _pauseUntil = now + Random.Range(0.6f, 2.8f);
                if (Random.value < 0.35f) _mouseUntil = now + Random.Range(1.5f, 4f);
            }
            else if (!_bursting && now > _pauseUntil && now > _mouseUntil && !talking)
            {
                _bursting = true;
                _burstUntil = now + Random.Range(1.8f, 6f);
            }
            var typing = _bursting && !talking;

            // Les poignets en retrait des touches (la cible IK est le poignet : les doigts dépassent devant).
            var home = new Vector3(b.center.x, b.max.y, b.center.z) - fwd * 0.075f + Vector3.up * 0.035f;
            _workPoint = home;
            Step(_left, typing, now);
            Step(_right, typing && now > _mouseUntil, now);
            var l = home - right * 0.085f + right * _left.Lateral + fwd * _left.Depth - Vector3.up * (0.014f * _left.Dip);
            _body.Pin(AvatarIKGoal.LeftHand, l, Palm(fwd + right * 0.25f, -10f, 8f), Elbow(true), 1f, 0.5f);

            var mouse = Find(MouseKeys, 1.6f);
            if (now < _mouseUntil && mouse != null)
            {
                var mb = Bounds(mouse);
                var drift = new Vector3(Mathf.PerlinNoise(now * 0.6f, 3.1f) - 0.5f, 0, Mathf.PerlinNoise(now * 0.6f, 7.7f) - 0.5f) * 0.04f;
                var r = new Vector3(mb.center.x, mb.max.y, mb.center.z) - fwd * 0.06f + Vector3.up * 0.02f + drift;
                _body.Pin(AvatarIKGoal.RightHand, r, Palm(fwd - right * 0.1f, 15f, 5f), Elbow(false, 0.1f), 1f, 0.45f);
            }
            else
            {
                var r = home + right * 0.085f + right * _right.Lateral + fwd * _right.Depth - Vector3.up * (0.014f * _right.Dip);
                _body.Pin(AvatarIKGoal.RightHand, r, Palm(fwd - right * 0.25f, 10f, 8f), Elbow(false), 1f, 0.5f);
            }

            // L'écran, et de temps en temps un coup d'œil aux touches.
            var screen = Find(ScreenKeys, 2f);
            var look = screen != null ? Bounds(screen).center + Vector3.up * 0.04f : home + fwd * 0.6f + Vector3.up * 0.35f;
            if (Mathf.PerlinNoise(now * 0.25f, 1.3f) > 0.72f) look = home + fwd * 0.05f;
            Gaze(look + Saccade(now, 0.04f), 6f);
        }

        void Step(Typist t, bool typing, float now)
        {
            var dt = Time.deltaTime;
            t.Dip = Mathf.MoveTowards(t.Dip, 0f, dt / 0.07f);
            if (typing && now >= t.Next)
            {
                t.Dip = 1f;
                t.Next = now + Random.Range(0.09f, 0.26f);
                // Une touche plus loin de temps en temps (rangée du haut, du bas, vers le centre).
                t.LateralTarget = Random.Range(-0.03f, 0.03f);
                t.DepthTarget = Random.value < 0.25f ? Random.Range(-0.02f, 0.03f) : 0f;
            }
            if (!typing)
            {
                t.LateralTarget = 0f;
                t.DepthTarget = -0.015f;
            }
            t.Lateral = Mathf.MoveTowards(t.Lateral, t.LateralTarget, dt * 0.35f);
            t.Depth = Mathf.MoveTowards(t.Depth, t.DepthTarget, dt * 0.3f);
        }

        void Write()
        {
            var pad = _pulled != null ? _pulled : Find(NotebookKeys, 1.4f);
            if (pad == null) pad = Find(BookKeys, 1.4f);
            if (pad == null) pad = Find(KeyboardKeys, 1.6f);
            if (pad == null) return;
            if (_pulled == null && pad.id != null && !Matches(pad.id, KeyboardKeys)) Pull(pad);
            var b = BoundsNow(pad);
            var home = SeatHomeRotation();
            var fwd = Flat(home * Vector3.forward).normalized;
            var right = Vector3.Cross(Vector3.up, fwd);
            var now = Time.time;
            var top = new Vector3(b.center.x, b.max.y, b.center.z);
            // La main droite parcourt une ligne (petites boucles d'écriture), puis revient à la ligne suivante.
            _lineX += Time.deltaTime * 0.035f;
            if (_lineX > 0.11f)
            {
                _lineX = 0f;
                _line = (_line + 1) % 8;
            }
            var loops = new Vector3(Mathf.Sin(now * 13f) * 0.006f, Mathf.Max(0f, Mathf.Sin(now * 9f)) * 0.004f, Mathf.Cos(now * 11f) * 0.004f);
            var pen = top - fwd * 0.04f + right * (0.02f + _lineX - 0.05f) - fwd * (_line * 0.012f) + Vector3.up * 0.045f;
            _workPoint = top - fwd * 0.08f;
            _body.Pin(AvatarIKGoal.RightHand, pen + right * loops.x + Vector3.up * loops.y + fwd * loops.z, Palm(fwd - right * 0.4f, 25f, 15f), Elbow(false, 0.07f), 1f, 0.5f);
            // La gauche tient le carnet à plat, sur le côté.
            var hold = top - right * 0.14f - fwd * 0.02f + Vector3.up * 0.03f;
            _body.Pin(AvatarIKGoal.LeftHand, hold, Palm(fwd + right * 0.5f, -5f, 5f), Elbow(true, 0.07f), 1f, 0.5f);
            Gaze(pen + Vector3.up * 0.01f + Saccade(now, 0.015f), 8f);
        }

        void Lap()
        {
            // Les mains sur les cuisses, à mi-longueur, un peu tournées vers l'intérieur.
            var fwd = Fwd;
            var right = Right;
            var hips = HipsPos;
            var along = _body.ThighLength * 0.62f;
            var lift = 0.085f;
            var l = hips + fwd * along - right * 0.07f + Vector3.up * lift;
            var r = hips + fwd * along + right * 0.07f + Vector3.up * lift;
            _body.Pin(AvatarIKGoal.LeftHand, l, Palm(fwd + right * 0.6f, -20f, 10f), Elbow(true, 0.04f, 0.06f), 0.9f, 0.6f);
            _body.Pin(AvatarIKGoal.RightHand, r, Palm(fwd - right * 0.6f, 20f, 10f), Elbow(false, 0.04f, 0.06f), 0.9f, 0.6f);
            _body.SetActivityLook(null);
        }

        void Lean()
        {
            // Accoudée au bureau, le menton dans la main gauche, la droite à plat.
            var desk = Desk();
            if (desk == null)
            {
                Lap();
                return;
            }
            var fwd = Fwd;
            var right = Right;
            var top = Bounds(desk).max.y;
            var head = _body.Head.position;
            var chin = head - Vector3.up * 0.13f + fwd * 0.05f;
            _body.Pin(AvatarIKGoal.LeftHand, chin, Quaternion.LookRotation(Vector3.up + fwd * 0.3f, -fwd) * Quaternion.Euler(0, 0, -30f),
                new Vector3(chin.x, top + 0.03f, chin.z) + fwd * 0.12f - right * 0.12f, 1f, 0.8f);
            var flat = HipsPos + fwd * 0.42f + right * 0.12f;
            flat.y = top + 0.03f;
            _workPoint = Bounds(desk).ClosestPoint(HipsPos) + fwd * 0.12f;
            _body.Pin(AvatarIKGoal.RightHand, flat, Palm(fwd - right * 0.3f, 0f, 5f), Elbow(false, 0.08f), 1f, 0.8f);
            var screen = Find(ScreenKeys, 2f);
            Gaze((screen != null ? Bounds(screen).center : head + fwd * 2f) + Saccade(Time.time, 0.08f), 2f);
        }

        /// <summary>
        /// Ramène un objet de travail (un carnet) devant elle : à droite du clavier, à portée de la main droite, tourné
        /// vers elle. Il retournera à sa place quand elle aura fini.
        /// </summary>
        void Pull(WorldObject o)
        {
            var a = _body.Anchor;
            if (!a.HasValue) return;
            var home = SeatHomeRotation();
            var fwd = Flat(home * Vector3.forward).normalized;
            var right = Vector3.Cross(Vector3.up, fwd);
            var kb = Find(KeyboardKeys, 1.6f);
            var kbRight = kb != null ? Vector3.Dot(Flat(Bounds(kb).center) - Flat(a.Value.position), right) + Bounds(kb).extents.magnitude * 0.55f : 0.3f;
            var t = o.transform;
            _pulled = o;
            _pulledFrom = t.position;
            _pulledRot = t.rotation;
            var target = Flat(a.Value.position) + fwd * 0.52f + right * Mathf.Clamp(kbRight + 0.12f, 0.25f, 0.42f);
            target.y = t.position.y;
            var yaw = Quaternion.LookRotation(fwd, Vector3.up) * Quaternion.Euler(0f, -12f, 0f);
            StartCoroutine(SlideTo(t, target, yaw * Quaternion.Inverse(Quaternion.Euler(0f, home.eulerAngles.y, 0f)) * t.rotation, 0.7f));
            // La chaise se tourne d'un petit quart vers le carnet.
            _workYaw = Mathf.Clamp(Vector3.SignedAngle(fwd, Flat(target - a.Value.position), Vector3.up) * 0.5f, -25f, 25f);
            _bounds.Remove(o);
        }

        void PutBack()
        {
            if (_pulled == null) return;
            StartCoroutine(SlideTo(_pulled.transform, _pulledFrom, _pulledRot, 0.7f));
            _bounds.Remove(_pulled);
            _pulled = null;
            _workYaw = 0f;
        }

        static System.Collections.IEnumerator SlideTo(Transform t, Vector3 to, Quaternion rot, float duration)
        {
            var from = t.position;
            var r0 = t.rotation;
            for (var k = 0f; k < 1f; k += Time.deltaTime / duration)
            {
                if (t == null) yield break;
                var e = Mathf.SmoothStep(0f, 1f, k);
                t.SetPositionAndRotation(Vector3.Lerp(from, to, e), Quaternion.Slerp(r0, rot, e));
                yield return null;
            }
            if (t != null) t.SetPositionAndRotation(to, rot);
        }

        /// <summary>La boîte d'un objet qui bouge (pas de cache).</summary>
        static Bounds BoundsNow(WorldObject o)
        {
            var rs = o.GetComponentsInChildren<Renderer>();
            if (rs.Length == 0) return new Bounds(o.transform.position, Vector3.one * 0.1f);
            var b = rs[0].bounds;
            for (var i = 1; i < rs.Length; i++) b.Encapsulate(rs[i].bounds);
            return b;
        }

        /// <summary>
        /// Le roulement de la chaise qui met le point de travail à une distance confortable des hanches : les
        /// coudes pliés près du corps, pas les bras tendus ni les mains contre la poitrine (34 cm pour sa taille, à l'horizontale).
        /// </summary>
        float DeskRoll(Vector3 work)
        {
            var a = _body.Anchor;
            if (!a.HasValue || _chair == null || work == Vector3.zero) return _chair != null ? _chair.Roll : 0f;
            var reach = Vector3.Dot(Flat(work) - Flat(a.Value.position), Fwd);
            return Mathf.Clamp(_chair.Roll + reach - 0.34f, 0f, 0.38f);
        }

        // --- lire un livre tenu --------------------------------------------------------------------------------
        void Read()
        {
            var book = HeldBook();
            if (book == null) return;
            if (_book != book)
            {
                _book = book;
                _bookHand = _body.Held.TryGetValue(book, out var h) ? h : Hand.Right;
                // Tenu à deux mains devant elle : le livre quitte l'os de la main pour une place stable.
                book.transform.SetParent(_body.transform, true);
            }
            var fwd = Fwd;
            var right = Right;
            var head = _body.Head.position;
            var seated = _body.Posture == Posture.Sit;
            var pos = Chest + fwd * (seated ? 0.26f : 0.3f) - Vector3.up * (seated ? 0.14f : 0.1f);
            var toEyes = (head - pos).normalized;
            var up = Vector3.ProjectOnPlane(Vector3.up, toEyes).normalized;
            // Couché à plat dans son modèle (épaisseur sur Y) : la couverture vers les yeux, le haut du livre en haut.
            var rot = Quaternion.LookRotation(up, toEyes);
            var t = book.transform;
            var k = 1f - Mathf.Exp(-Time.deltaTime * 6f);
            t.position = Vector3.Lerp(t.position, pos, k);
            t.rotation = Quaternion.Slerp(t.rotation, rot, k);
            var b = BoundsLocal(book);
            var half = Mathf.Max(b.extents.x, 0.07f);
            var lHand = pos - right * (half - 0.01f) - toEyes * 0.01f - up * 0.02f;
            var rHand = pos + right * (half - 0.01f) - toEyes * 0.01f - up * 0.02f;
            // Tourner la page : la main droite passe à gauche et revient.
            var now = Time.time;
            if (_pageT < 0f && now > _pageNext)
            {
                _pageT = 0f;
                _pageNext = now + Random.Range(12f, 30f);
            }
            if (_pageT >= 0f)
            {
                _pageT += Time.deltaTime / 0.9f;
                var s = Mathf.Sin(Mathf.Clamp01(_pageT) * Mathf.PI);
                rHand = Vector3.Lerp(rHand, pos + toEyes * 0.04f + up * 0.03f, s);
                if (_pageT >= 1f) _pageT = -1f;
            }
            _body.Pin(AvatarIKGoal.LeftHand, lHand, Quaternion.LookRotation(up, right) * Quaternion.Euler(0, 0, 0), Elbow(true, 0.06f, -0.02f), 1f, 0.5f);
            _body.Pin(AvatarIKGoal.RightHand, rHand, Quaternion.LookRotation(up, -right), Elbow(false, 0.06f, -0.02f), 1f, 0.5f);
            // Les yeux suivent les lignes.
            var line = pos + up * (0.06f - Mathf.Repeat(now * 0.02f, 0.12f)) + right * (Mathf.Repeat(now * 0.25f, 0.1f) - 0.05f);
            Gaze(line, 10f);
        }

        // --- sur le bord du lit -------------------------------------------------------------------------------
        void Mattress()
        {
            var a = _body.Anchor;
            if (!a.HasValue) return;
            var fwd = Fwd;
            var right = Right;
            for (var s = 0; s < 2; s++)
            {
                var left = s == 0;
                var p = a.Value.position + right * (left ? -0.27f : 0.27f) - fwd * 0.06f;
                var surface = Surface(p, a.Value.position.y - 0.04f);
                var target = new Vector3(p.x, surface + 0.035f, p.z);
                var goal = left ? AvatarIKGoal.LeftHand : AvatarIKGoal.RightHand;
                _body.Pin(goal, target, Palm(fwd + right * (left ? -0.35f : 0.35f), left ? -10f : 10f, 0f),
                    target + Vector3.up * 0.2f - fwd * 0.12f + right * (left ? -0.12f : 0.12f), 1f, 0.6f);
            }
            _body.SetActivityLook(null);
        }

        // --- au lit -------------------------------------------------------------------------------------------
        [Tooltip("Endormie, elle se retourne toutes les… (s, entre min et max).")]
        public Vector2 turnEvery = new Vector2(150f, 480f);
        float _nextTurn = -1f;

        /// <summary>
        /// Allongée : endormie, elle se retourne de temps en temps (dos, gauche, droite) ; éveillée et qu'on lui
        /// parle, elle se tourne vers la personne ; sinon elle reste comme elle est.
        /// </summary>
        bool _tidied;
        bool _sawChoreography;      // la posture vient d'un geste (s'allonger) et pas d'un instantané
        DuvetRig _duvet;
        float _pullT = -1f;         // tirer la couette : 0 → 1
        int _coveredSide = -1;

        void Lying()
        {
            if (!_tidied)
            {
                _tidied = true;
                Tidy();
                _duvet = BedDuvet();
                _coveredSide = -1;
            }
            if (_duvet != null) Bedding();
            var now = Time.time;
            var asleep = BodyAnim.HasParameter(_animator, BodyAnim.Asleep) && _animator.GetBool(BodyAnim.Asleep);
            if (_nextTurn < 0f) _nextTurn = now + Random.Range(turnEvery.x, turnEvery.y) * 0.5f;
            if (!asleep && Engaged && companion != null && _body.Hips != null)
            {
                var toward = companion.position - _body.Hips.position;
                toward.y = 0f;
                _body.SetLieSide(Vector3.Dot(toward, _body.LyingRight) > 0f ? 2 : 1);
                _nextTurn = now + Random.Range(turnEvery.x, turnEvery.y);
            }
            else if (now > _nextTurn && (asleep || Random.value < 0.3f))
            {
                // Se retourner : jamais deux fois la même position de suite, le dos un peu moins souvent.
                var current = _body.LieSide;
                int next;
                do next = Random.value < 0.25f ? 0 : Random.value < 0.5f ? 1 : 2;
                while (next == current);
                _body.SetLieSide(next);
                _nextTurn = now + Random.Range(turnEvery.x, turnEvery.y);
            }
            else if (now > _nextTurn)
            {
                _nextTurn = now + Random.Range(turnEvery.x, turnEvery.y);
            }
            _body.SetActivityLook(null);
        }

        DuvetRig BedDuvet()
        {
            var f = _body.Place != null ? _body.Place.Furniture : null;
            return f != null ? f.GetComponentInChildren<DuvetRig>() : null;
        }

        /// <summary>
        /// La couette : endormie, elle la tire sur elle (la main droite accompagne le bord, des hanches à la
        /// poitrine) ; dessous, elle la suit quand elle se retourne. Arrivée déjà couchée (un instantané au démarrage),
        /// la couette est déjà sur elle.
        /// </summary>
        void Bedding()
        {
            _duvet.lastOccupied = Time.time;
            var asleep = BodyAnim.HasParameter(_animator, BodyAnim.Asleep) && _animator.GetBool(BodyAnim.Asleep);
            var side = _body.LieSide;
            if (_pullT >= 0f)
            {
                // La main va chercher le bord vers la hanche, puis le remonte jusqu'à la poitrine.
                _pullT += Time.deltaTime / 2.2f;
                var hips = HipsPos;
                var chest = Chest;
                var right = _body.LyingRight;
                var edgeLow = hips + right * 0.22f + Vector3.up * 0.06f;
                var edgeHigh = chest + right * 0.08f + Vector3.up * 0.1f;
                var reach = Mathf.Clamp01(_pullT / 0.3f);
                var pull = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01((_pullT - 0.3f) / 0.55f));
                var hand = Vector3.Lerp(edgeLow, edgeHigh, pull);
                var w = _pullT < 0.85f ? reach : Mathf.Clamp01(1f - (_pullT - 0.85f) / 0.15f);
                _body.Pin(AvatarIKGoal.RightHand, hand, null, hand + right * 0.15f + Vector3.up * 0.1f, w, 0.05f);
                if (_pullT >= 0.3f && _duvet.State != DuvetRig.CoveredFor(side))
                {
                    _duvet.SetState(DuvetRig.CoveredFor(side), 2.2f * 0.55f);
                    _coveredSide = side;
                }
                if (_pullT >= 1f)
                {
                    _pullT = -1f;
                    _body.Unpin(AvatarIKGoal.RightHand);
                }
                return;
            }
            if (_duvet.Covered)
            {
                // Dessous, elle se retourne : la couette roule avec elle.
                if (side != _coveredSide && !_duvet.Moving)
                {
                    _duvet.SetState(DuvetRig.CoveredFor(side), 1.6f);
                    _coveredSide = side;
                }
                return;
            }
            if (!asleep) return;
            if (!_sawChoreography)
            {
                // Déjà couchée et endormie quand on arrive : la couette est déjà sur elle.
                _duvet.SetState(DuvetRig.CoveredFor(side), 0f);
                _coveredSide = side;
                return;
            }
            if (_duvet.State == DuvetState.Made)
            {
                _duvet.SetState(DuvetState.Open, 0.8f);
                return;
            }
            if (!_duvet.Moving) _pullT = 0f;
        }

        /// <summary>
        /// Ce qui traîne là où va sa tête (une peluche sur l'oreiller) est poussé sur le côté, vers le mur plutôt
        /// que vers la chambre — on ne pose pas la tête sur son lapin.
        /// </summary>
        void Tidy()
        {
            var place = _body.Place;
            if (place == null || place.Kind != PlaceKind.Bed) return;
            var lie = place.Lie;
            var head = lie.position + lie.rotation * Vector3.forward * 0.55f;
            var right = _body.LyingRight;
            // Le côté du lit loin du point d'approche (la chambre) : là on ne gêne rien.
            var side = Vector3.Dot(place.Position - lie.position, right) > 0f ? -right : right;
            Rescan();
            foreach (var o in _objects)
            {
                if (o == null || o == place.Furniture || _body.IsHolding(o)) continue;
                var b = Bounds(o);
                if (b.size.magnitude > 0.8f) continue;
                var d = Flat(b.center) - Flat(head);
                if (d.magnitude > 0.42f || Mathf.Abs(b.center.y - head.y) > 0.45f) continue;
                StartCoroutine(Slide(o.transform, o.transform.position + side * 0.36f, 0.6f));
                _bounds.Remove(o);
            }
        }

        static System.Collections.IEnumerator Slide(Transform t, Vector3 to, float duration)
        {
            var from = t.position;
            for (var k = 0f; k < 1f; k += Time.deltaTime / duration)
            {
                if (t == null) yield break;
                t.position = Vector3.Lerp(from, to, Mathf.SmoothStep(0f, 1f, k));
                yield return null;
            }
            if (t != null) t.position = to;
        }

        // --- debout -------------------------------------------------------------------------------------------
        void Sill()
        {
            var window = Find(WindowKeys, 2.2f);
            if (window == null) return;
            var b = Bounds(window);
            var fwd = _body.transform.forward;
            var right = _body.transform.right;
            // Les mains sur le rebord, de part et d'autre, à l'aplomb des épaules.
            var sillY = Mathf.Clamp(b.min.y + 0.02f, 0.75f, 1.15f);
            var front = Flat(_body.transform.position) + fwd * 0.32f;
            for (var s = 0; s < 2; s++)
            {
                var left = s == 0;
                var p = front + right * (left ? -0.22f : 0.22f);
                p.y = sillY + 0.03f;
                _body.Pin(left ? AvatarIKGoal.LeftHand : AvatarIKGoal.RightHand, p, Palm(fwd, left ? -5f : 5f, 0f),
                    p - fwd * 0.2f + Vector3.up * 0.05f + right * (left ? -0.2f : 0.2f), 1f, 0.8f);
            }
            // Le regard flâne dehors : le ciel, la rue, un point, puis un autre.
            var now = Time.time;
            if (now > _gazeNext)
            {
                _gazeNext = now + Random.Range(2.5f, 7f);
                _gazeTarget = b.center + fwd * 6f + right * Random.Range(-3f, 3f) + Vector3.up * Random.Range(-1.5f, 2f);
            }
            Gaze(_gazeTarget, 1.2f);
        }

        void Browse()
        {
            var shelf = Find(ShelfKeys, 2.2f);
            if (shelf == null) return;
            var b = Bounds(shelf);
            var fwd = _body.transform.forward;
            var right = _body.transform.right;
            var now = Time.time;
            // Le regard parcourt les tranches ; de temps en temps la main en effleure une.
            if (now > _gazeNext)
            {
                _gazeNext = now + Random.Range(1.2f, 3.5f);
                var face = b.ClosestPoint(_body.transform.position + Vector3.up * 1.3f);
                _gazeTarget = new Vector3(face.x, Random.Range(Mathf.Max(b.min.y, 0.5f), Mathf.Min(b.max.y, 1.75f)), face.z) + right * Random.Range(-0.5f, 0.5f);
            }
            Gaze(_gazeTarget, 2f);
            if (_reachT < 0f && now > _reachNext)
            {
                _reachT = 0f;
                _reachNext = now + Random.Range(4f, 9f);
                _reachPoint = _gazeTarget - fwd * 0.08f;
                _reachPoint.y = Mathf.Clamp(_reachPoint.y, 0.8f, 1.6f);
            }
            if (_reachT >= 0f)
            {
                _reachT += Time.deltaTime / 2.2f;
                var w = Mathf.Sin(Mathf.Clamp01(_reachT) * Mathf.PI);
                _body.Pin(AvatarIKGoal.RightHand, _reachPoint, Palm(fwd, 70f, -10f), _reachPoint - fwd * 0.25f + right * 0.25f - Vector3.up * 0.2f, w, 0.05f);
                if (_reachT >= 1f)
                {
                    _reachT = -1f;
                    _body.Unpin(AvatarIKGoal.RightHand);
                }
            }
        }

        void Pour()
        {
            var plant = Find(PlantKeys, 2.2f);
            if (plant == null) return;
            var b = Bounds(plant);
            var fwd = _body.transform.forward;
            var right = _body.transform.right;
            var p = new Vector3(b.center.x, b.max.y + 0.22f, b.center.z) - fwd * 0.12f + right * 0.05f;
            _body.Pin(AvatarIKGoal.RightHand, p, Palm(fwd, 35f, 20f), p - fwd * 0.3f + right * 0.25f - Vector3.up * 0.15f, 1f, 0.8f);
            Gaze(new Vector3(b.center.x, b.max.y, b.center.z), 3f);
        }

        // --- le regard -----------------------------------------------------------------------------------------
        void Gaze(Vector3 target, float speed)
        {
            _gaze = _gaze == Vector3.zero ? target : Vector3.Lerp(_gaze, target, 1f - Mathf.Exp(-Time.deltaTime * speed));
            _body.SetActivityLook(_gaze);
        }

        static Vector3 Saccade(float now, float amount) =>
            new Vector3(Mathf.PerlinNoise(now * 1.7f, 0.3f) - 0.5f, Mathf.PerlinNoise(now * 1.3f, 5.1f) - 0.5f, 0f) * (2f * amount);

        // --- ce qui l'entoure ---------------------------------------------------------------------------------
        // « =id » : cet objet précisément ; sinon un identifiant qui contient le mot. Les exacts passent avant.
        static readonly string[] KeyboardKeys = { "=keyboard", "keyboard", "clavier" };
        static readonly string[] MouseKeys = { "=mouse", "souris" };
        static readonly string[] ScreenKeys = { "=monitor", "monitor", "screen", "ecran", "laptop" };
        static readonly string[] NotebookKeys = { "=notebook", "notebook", "sketchbook", "carnet" };
        static readonly string[] BookKeys = { "book", "livre" };
        static readonly string[] WindowKeys = { "=window_pane", "=window", "window_pane" };
        static readonly string[] ShelfKeys = { "=shelves", "=bookshelf", "shelves" };
        static readonly string[] PlantKeys = { "snake_plant", "ficus", "pothos", "plant", "plante" };

        WorldObject HeldBook()
        {
            foreach (var kv in _body.Held)
                if (kv.Key != null && Matches(kv.Key.id, BookKeys))
                    return kv.Key;
            return null;
        }

        /// <summary>L'objet le plus proche du corps dont l'identifiant évoque <paramref name="keys"/> (les « =id » d'abord).</summary>
        WorldObject Find(string[] keys, float radius)
        {
            Rescan();
            var from = From;
            foreach (var exact in new[] { true, false })
            {
                WorldObject best = null;
                var bestD = radius * radius;
                foreach (var o in _objects)
                {
                    if (o == null || _body.IsHolding(o) || !Matches(string.IsNullOrEmpty(o.id) ? o.name : o.id, keys, exact)) continue;
                    var d = (Flat(Bounds(o).center) - Flat(from)).sqrMagnitude;
                    if (d < bestD)
                    {
                        bestD = d;
                        best = o;
                    }
                }
                if (best != null) return best;
            }
            return null;
        }

        /// <summary>Le plan de travail devant elle : un meuble à surfaces (des emplacements), à hauteur de table.</summary>
        WorldObject Desk()
        {
            Rescan();
            var from = From;
            var fwd = Fwd;
            WorldObject best = null;
            var bestD = 1.6f * 1.6f;
            foreach (var o in _objects)
            {
                if (o == null || o.surfaceSlots == null || o.surfaceSlots.Count == 0) continue;
                var b = Bounds(o);
                if (b.max.y < 0.55f || b.max.y > 1.05f) continue;
                var to = Flat(b.ClosestPoint(from)) - Flat(from);
                if (Vector3.Dot(to, fwd) < -0.05f) continue;
                var d = to.sqrMagnitude;
                if (d < bestD)
                {
                    bestD = d;
                    best = o;
                }
            }
            return best;
        }

        Vector3 From => _body.Posture == Posture.Sit && _body.Anchor.HasValue ? _body.Anchor.Value.position : _body.transform.position;

        void Rescan()
        {
            if (Time.time - _objectsScannedAt < 5f && _objects.Count > 0) return;
            _objects.Clear();
            _objects.AddRange(FindObjectsByType<WorldObject>(FindObjectsInactive.Exclude));
            _bounds.Clear();
            _objectsScannedAt = Time.time;
        }

        static bool Matches(string id, string[] keys, bool exact)
        {
            if (string.IsNullOrEmpty(id)) return false;
            var s = id.ToLowerInvariant();
            foreach (var k in keys)
            {
                var isExact = k.StartsWith("=");
                if (isExact != exact) continue;
                if (isExact ? s == k.Substring(1) : s.Contains(k)) return true;
            }
            return false;
        }

        static bool Matches(string id, string[] keys) => Matches(id, keys, true) || Matches(id, keys, false);

        readonly Dictionary<WorldObject, Bounds> _bounds = new Dictionary<WorldObject, Bounds>();

        /// <summary>La boîte d'un objet (mise en cache : les meubles ne bougent pas ; un objet tenu est ignoré).</summary>
        Bounds Bounds(WorldObject o)
        {
            if (_bounds.TryGetValue(o, out var cached)) return cached;
            var rs = o.GetComponentsInChildren<Renderer>();
            var b = rs.Length == 0 ? new Bounds(o.transform.position, Vector3.one * 0.1f) : rs[0].bounds;
            for (var i = 1; i < rs.Length; i++) b.Encapsulate(rs[i].bounds);
            _bounds[o] = b;
            return b;
        }

        static Bounds BoundsLocal(WorldObject o)
        {
            var mf = o.GetComponentInChildren<MeshFilter>();
            return mf != null && mf.sharedMesh != null ? mf.sharedMesh.bounds : new Bounds(Vector3.zero, new Vector3(0.18f, 0.03f, 0.24f));
        }

        /// <summary>La surface sous un point (le matelas, une table), sinon la hauteur proposée.</summary>
        float Surface(Vector3 p, float fallback)
        {
            var origin = new Vector3(p.x, fallback + 0.4f, p.z);
            foreach (var hit in Physics.RaycastAll(origin, Vector3.down, 0.8f, ~0, QueryTriggerInteraction.Ignore))
            {
                if (hit.transform.IsChildOf(_body.transform)) continue;
                return hit.point.y;
            }
            return fallback;
        }

        /// <summary>La chaise à roulettes où elle est assise (rien debout, sur un lit ou une chaise fixe).</summary>
        ChairRig SeatChair()
        {
            var place = _body.Place;
            _chair = _body.Posture == Posture.Sit && place != null ? place.Chair : null;
            if (_chair != null) _chair.Carry(place.SeatTransform);
            return _chair;
        }

        Quaternion SeatHomeRotation()
        {
            var place = _body.Place;
            return place != null ? place.Rotation : _body.transform.rotation;
        }

        static Vector3 Flat(Vector3 v) => new Vector3(v.x, 0f, v.z);
    }
}
