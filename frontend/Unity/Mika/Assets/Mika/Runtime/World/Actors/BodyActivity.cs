using System.Collections;
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
    /// ce composant ne décide rien de nouveau, il donne une forme crédible à ce qui est. Au bureau, devant la fenêtre et
    /// la bibliothèque, ce sont les clips de l'atelier Blender qui jouent le corps entier (réglés contre les vrais
    /// meubles) ; ailleurs, le contrôleur fournit l'attitude du buste et l'IK pose les mains au point exact des objets.
    /// Aucun objet ne bouge sans le geste qui le déplace : la chaise suit les courbes du geste qui la roule ou la fait
    /// pivoter (mains sur le bord du bureau, pieds qui poussent le sol), la tasse et le stylo suivent la main qui les a
    /// pris et sont rendus là où elle les repose.
    /// </remarks>
    [DisallowMultipleComponent]
    [DefaultExecutionOrder(-50)]    // avant ActorBody : la chaise menée par le geste, puis le corps recalé sur le siège
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

        // Taper (sans clip) : chaque main tape à son rythme, par rafales ; la droite part parfois à la souris.
        readonly Typist _left = new Typist(), _right = new Typist();
        float _burstUntil, _pauseUntil, _mouseUntil;
        bool _bursting;
        // Écrire (sans clip) : une ligne qui avance, puis la suivante.
        float _line, _lineX;
        // Regard qui flâne et page qu'on tourne.
        Vector3 _gaze, _gazeTarget;
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
            _clipLengths.Clear();
            body.BeforeStanding = LeaveSeat;
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
                Leave(_mode, mode);
                _mode = mode;
                _modeT = 0f;
                _variant = Random.Range(0, 3);
            }
            _modeT += Time.deltaTime;
            Run(_mode);
            if (BodyAnim.HasParameter(_animator, BodyAnim.Pose))
                _animator.SetInteger(BodyAnim.Pose, BodyAnim.PoseId(_clipPose ?? PoseOf(_mode)));
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
        /// Pendant un changement de posture au lit : elle ouvre la couette en s'y glissant — la main droite en écarte le
        /// bord — et la repousse en se redressant (la couette ne bouge jamais sans sa main).
        /// </summary>
        void Choreography()
        {
            var duvet = _body.Place != null && _body.Place.Kind == PlaceKind.Bed ? BedDuvet() : null;
            if (duvet == null) return;
            duvet.lastOccupied = Time.time;
            if (_body.Posture == Posture.Lie && duvet.State == DuvetState.Made && Asleep)
            {
                duvet.SetState(DuvetState.Open, DuvetHandSeconds);
                _duvetHandT = 0f;
            }
            else if (_body.Posture != Posture.Lie && duvet.Covered)
            {
                duvet.SetState(DuvetState.Open, DuvetHandSeconds);
                _duvetHandT = 0f;
            }
            DuvetHand();
        }

        // La main qui ouvre la couette ou la repousse : du bord (à la hanche) vers le côté, le temps que la couette bouge.
        const float DuvetHandSeconds = 1.2f;
        float _duvetHandT = -1f;

        void DuvetHand()
        {
            if (_duvetHandT < 0f) return;
            _duvetHandT += Time.deltaTime / DuvetHandSeconds;
            var hips = HipsPos;
            var right = _body.Posture == Posture.Lie ? _body.LyingRight : Right;
            var from = hips + right * 0.12f + Vector3.up * 0.12f;
            var to = hips + right * 0.38f + Vector3.up * 0.08f;
            var k = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01((_duvetHandT - 0.15f) / 0.7f));
            var w = Mathf.Sin(Mathf.Clamp01(_duvetHandT) * Mathf.PI);
            var hand = Vector3.Lerp(from, to, k);
            _body.Pin(AvatarIKGoal.RightHand, hand, null, hand + right * 0.12f + Vector3.up * 0.15f, w, 0.05f);
            if (_duvetHandT >= 1f)
            {
                _duvetHandT = -1f;
                _body.Unpin(AvatarIKGoal.RightHand, 0.2f);
            }
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
            Mode.Browse => "browse",
            Mode.Pour => "pour",
            _ => "none",
        };

        void Leave(Mode m, Mode next)
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
            // Debout : la pose de clip (fenêtre, bibliothèque) s'arrête avec l'occupation.
            if (_body.Posture != Posture.Sit) _clipPose = null;
            if (m == Mode.Lying)
            {
                _pullT = -1f;
                _duvet = null;
            }
            // Quitter une occupation (pas l'attente pendant un geste) oublie qu'un geste a eu lieu.
            if (m != Mode.None) _sawChoreography = false;
        }

        void Run(Mode m)
        {
            var chair = SeatChair();
            if (DeskClipped(m, chair))
            {
                DeskClip(m, chair);
                return;
            }
            if (_body.Posture != Posture.Sit) ForgetDesk();
            if (StandClipped(m))
            {
                // À la fenêtre, devant la bibliothèque : le clip de l'atelier joue le corps entier (mains sur l'appui,
                // regard sur les tranches) ; rien à épingler.
                SetPose(PoseOf(m));
                _body.SetActivityLook(null);
                return;
            }
            if (_clipPose != null && _body.Posture != Posture.Sit) _clipPose = null;
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

        // --- au bureau : les clips de l'atelier ----------------------------------------------------------------
        // Faits contre le vrai bureau (frontend/assets-src/blender/atelier_desk.py, atelier_desk_gestures.py) pour des
        // positions nommées de la chaise (relevé : ArtSource/atelier/desk_plan.json, repère du siège) :
        //   - « home » : là où elle s'assoit et se lève, la chaise à sa place ;
        //   - « type » : la chaise pivotée et avancée qui lui présente le clavier (taper, la souris, boire, prendre son
        //     stylo, lire, réfléchir, s'étirer) ;
        //   - « write » : pivotée de 45° vers sa gauche depuis « type », le carnet devant elle ;
        //   - tournée de ±45° ou ±90° depuis « type » ou « home », vers quelqu'un qui lui parle.
        // On passe de l'une à l'autre par un geste : se tirer vers le bureau ou s'en repousser, les mains sur son bord
        // (chair_pull_in, chair_push_out) ; pivoter, les pieds poussant le sol (chair_turn_*). La chaise suit, image par
        // image, la course du geste (courbes GesteChairYaw, GesteChairRoll) : elle ne bouge jamais sans lui. La tasse
        // et le stylo restent à leur place sur le bureau (build_desk.py) : la main les y prend et les y repose (courbe
        // GesteHold) ; la souris suit la paume.
        enum Stop { Unknown, Home, Type, Write }

        const float TypeYaw = 19.45f, TypeRoll = 0.2549f, WriteTurn = -45f, TurnStep = 45f;
        const int MaxTurnSteps = 2;             // ±90° depuis « type » ou « home » (les pivots vérifiés dans l'atelier)
        const float SettleSeconds = 0.5f;       // entre deux gestes, la pose de départ du suivant (le fondu fait 0,45 s)
        const float EngageLinger = 3f;          // tournée vers quelqu'un, elle le reste un peu après qu'il s'est tu (s)
        const float CarryHold = 0.25f;          // la courbe « Hold » au-delà de laquelle l'objet est dans la main
        // Le livre tenu (desk_read, atelier_desk.READ_CENTER/READ_TILT) : son centre (à droite, hauteur au-dessus du sol,
        // devant) et sa pente — le haut s'éloigne, la face regarde ses yeux.
        static readonly Vector3 BookHeld = new Vector3(0.02f, 0.85f, 0.29f);
        const float BookTilt = 45f;

        static float BaseYaw(Stop s) => s == Stop.Type ? TypeYaw : s == Stop.Write ? TypeYaw + WriteTurn : 0f;
        static float BaseRoll(Stop s) => s == Stop.Type || s == Stop.Write ? TypeRoll : 0f;

        /// <summary>Un geste qui déplace la chaise (ou le stylo) : d'où à où, et ce qu'il en a déjà fait.</summary>
        sealed class Gesture
        {
            public string Pose;
            public float Start, Seconds;
            public float Yaw0, Roll0, Yaw1, Roll1;
            public float YawK, RollK;
            public bool MovesChair, Trust;
            public Stop To;
            public int ToSteps;
        }

        Stop _stop;                 // où est la chaise (Unknown : à relever)
        int _steps;                 // tournée de tant de pas de 45° depuis _stop (« home » ou « type »)
        bool _penWriting;           // le stylo dans la main qui écrit (entre desk_write_start et desk_write_end)
        bool _leaving;              // elle va se lever : la chaise d'abord ramenée à sa place
        Gesture _gesture;
        ChairRig _deskChair;
        float _engagedSeen = -100f;
        int _wantSteps;
        string _clipPose;           // la pose de clip jouée (null : aucune, l'IK et le calque de base décident)
        float _clipStart, _clipUntil;
        float _workSwitch;
        bool _onMouse;
        float _idleActAt;
        string _idleAct, _requestedAct;
        readonly Dictionary<string, float> _clipLengths = new Dictionary<string, float>();
        int _poseLayer = -2;

        int PoseLayer
        {
            get
            {
                if (_poseLayer == -2) _poseLayer = _animator.GetLayerIndex(BodyAnim.PoseLayer);
                return _poseLayer;
            }
        }

        bool DeskClipsReady => PoseLayer >= 0 && _animator.HasState(PoseLayer, Animator.StringToHash("type")) &&
                               _animator.HasState(PoseLayer, Animator.StringToHash("pull_in"));

        bool DeskClipped(Mode m, ChairRig chair) =>
            chair != null && !_body.Choreographing && _body.Posture == Posture.Sit && DeskClipsReady &&
            (m == Mode.DeskType || m == Mode.DeskWrite || m == Mode.DeskRest || m == Mode.DeskLean || m == Mode.ReadHeld);

        bool StandClipped(Mode m) =>
            (m == Mode.Sill || m == Mode.Browse) && _body.Posture == Posture.Stand && PoseLayer >= 0 &&
            _animator.HasState(PoseLayer, Animator.StringToHash(PoseOf(m)));

        void DeskClip(Mode m, ChairRig chair)
        {
            var now = Time.time;
            _body.SetActivityLook(null);
            _body.Unpin(AvatarIKGoal.LeftHand, 0.3f);
            _body.Unpin(AvatarIKGoal.RightHand, 0.3f);
            _deskChair = chair;
            // Pendant qu'elle finit de s'asseoir : la pose assise du calque de base (celle où finit le clip d'assise).
            if (_body.Seatedness < 0.95f)
            {
                SetPose("none");
                return;
            }
            if (_stop == Stop.Unknown) Survey(chair);
            if (_gesture != null)
            {
                if (now - _gesture.Start >= _gesture.Seconds) Finish(_gesture);
                return;
            }
            // Un geste de la main en cours (boire, prendre son stylo, s'étirer) se finit avant tout le reste.
            if (_idleAct != null && _idleAct != "think" && now < _clipUntil) return;
            Want(m, chair, out var target, out var steps, out var pen);
            var g = Next(target, steps, pen);
            if (g != null)
            {
                Approach(g, now);
                return;
            }
            Occupy(m, now);
        }

        /// <summary>Où la chaise doit être : vers la personne qui parle, sinon devant le travail.</summary>
        void Want(Mode m, ChairRig chair, out Stop target, out int steps, out bool pen)
        {
            target = Stop.Type;
            steps = 0;
            pen = false;
            if (_leaving)
            {
                target = Stop.Home;
                return;
            }
            var now = Time.time;
            if (Engaged) _engagedSeen = now;
            if (now - _engagedSeen < EngageLinger && companion != null)
            {
                // Pivoter de 45° ou 90° (les pas des pieds) depuis « type » ou « home » : en dessous de 30°, la tête suffit.
                target = _stop == Stop.Home ? Stop.Home : Stop.Type;
                var baseYaw = BaseYaw(target);
                var rel = Mathf.DeltaAngle(baseYaw, chair.YawToward(companion.position, SeatHome()));
                var current = target == _stop ? _steps : 0;
                // Garder le pas en cours tant que la personne n'en sort pas franchement.
                if (Mathf.Abs(rel - current * TurnStep) < TurnStep * 0.78f) steps = current;
                else steps = Mathf.Abs(rel) < 30f ? 0 : Mathf.Clamp(Mathf.RoundToInt(rel / TurnStep), -MaxTurnSteps, MaxTurnSteps);
                while (steps != 0 && Mathf.Abs(baseYaw + steps * TurnStep) > chair.maxSwivel) steps -= System.Math.Sign(steps);
                _wantSteps = steps;
                return;
            }
            if (m == Mode.DeskWrite)
            {
                target = Stop.Write;
                pen = true;
            }
        }

        /// <summary>Le prochain geste pour amener la chaise (et le stylo) où elle doit être ; null : elle y est.</summary>
        Gesture Next(Stop target, int steps, bool pen)
        {
            // Le stylo d'abord reposé sur le carnet, avant de faire autre chose qu'écrire.
            if (_penWriting && !(target == Stop.Write && steps == 0 && pen)) return Stay("write_end", _stop, _steps);
            if (_steps != 0)
            {
                var d = target == _stop ? steps - _steps : -_steps;
                return d != 0 ? Turn(d) : null;
            }
            switch (_stop)
            {
                case Stop.Home:
                    if (target == Stop.Home) return steps != 0 ? Turn(steps) : null;
                    return Roll("pull_in", Stop.Home, Stop.Type);
                case Stop.Type:
                    if (target == Stop.Type) return steps != 0 ? Turn(steps) : null;
                    if (target == Stop.Write) return Swivel("turn_left_45", Stop.Type, Stop.Write);
                    return Roll("push_out", Stop.Type, Stop.Home);
                case Stop.Write:
                    if (target == Stop.Write) return pen && !_penWriting ? Stay("write_start", Stop.Write, 0) : null;
                    return Swivel("turn_right_45", Stop.Write, Stop.Type);
            }
            return null;
        }

        Gesture Turn(int d)
        {
            var n = Mathf.Clamp(d, -MaxTurnSteps, MaxTurnSteps);
            var pose = (n > 0 ? "turn_right_" : "turn_left_") + (Mathf.Abs(n) == 1 ? "45" : "90");
            var y0 = BaseYaw(_stop) + _steps * TurnStep;
            var r = BaseRoll(_stop);
            return Make(pose, y0, r, y0 + n * TurnStep, r, _stop, _steps + n);
        }

        Gesture Swivel(string pose, Stop from, Stop to) => Make(pose, BaseYaw(from), BaseRoll(from), BaseYaw(to), BaseRoll(to), to, 0);

        Gesture Roll(string pose, Stop from, Stop to) => Make(pose, BaseYaw(from), BaseRoll(from), BaseYaw(to), BaseRoll(to), to, 0);

        Gesture Stay(string pose, Stop at, int steps)
        {
            var y = BaseYaw(at) + steps * TurnStep;
            var g = Make(pose, y, BaseRoll(at), y, BaseRoll(at), at, steps);
            g.MovesChair = false;
            return g;
        }

        Gesture Make(string pose, float y0, float r0, float y1, float r1, Stop to, int toSteps) => new Gesture
        {
            Pose = pose, Seconds = ClipSeconds(pose), Yaw0 = y0, Roll0 = r0, Yaw1 = y1, Roll1 = r1, To = to, ToSteps = toSteps,
            MovesChair = true,
        };

        /// <summary>La pose où commence un geste : on s'y installe avant de le lancer (le geste part d'elle).</summary>
        static string StartPose(string gesture) => gesture switch
        {
            "push_out" => "desk",
            "write_end" => "write",
            _ => "lap",
        };

        /// <summary>
        /// S'installer dans la pose de départ du geste, puis le lancer. Le stylo n'est reposé qu'en fin de ligne (la
        /// boucle d'écriture au début d'une de ses deux lignes), la souris lâchée qu'à l'endroit où la main l'a prise.
        /// </summary>
        void Approach(Gesture g, float now)
        {
            if (_book != null) BookBackInHand();
            if (_clipPose == "mouse" && !MouseAtGrabPhase()) return;
            var start = StartPose(g.Pose);
            if (!PoseLayerHas(g.Pose))
            {
                // Un contrôleur sans ce geste (assets incomplets) : la chaise prend sa place d'un coup, signalé une fois.
                if (!_warnedMissing)
                {
                    _warnedMissing = true;
                    Debug.LogWarning($"[BodyActivity] geste « {g.Pose} » absent du contrôleur : reconstruire les animations du corps.");
                }
                Finish(g);
                return;
            }
            if (_clipPose != start || !InPose(start) || now - _clipStart < SettleSeconds)
            {
                SetPose(start);
                return;
            }
            if (g.Pose == "write_end" && !LoopAt("write", 0.04f, 0.5f)) return;
            g.Start = now;
            // Les courbes d'un état qui n'en a pas valent 0 (par défaut) : on peut les lire dès le fondu d'entrée. Si
            // elles gardaient la dernière valeur d'un geste précédent, on attend que l'état du geste soit seul.
            g.Trust = _animator.GetFloat(BodyAnim.ChairYaw) < 0.01f && _animator.GetFloat(BodyAnim.ChairRoll) < 0.01f;
            _gesture = g;
            SetPose(g.Pose);
        }

        bool _warnedMissing;

        void Finish(Gesture g)
        {
            if (g.MovesChair && _deskChair != null) _deskChair.Set(g.Yaw1, g.Roll1);
            _stop = g.To;
            _steps = g.ToSteps;
            if (g.Pose == "write_start") _penWriting = true;
            if (g.Pose == "write_end") _penWriting = false;
            if (_gesture == g) _gesture = null;
        }

        /// <summary>
        /// Arrivée à la place voulue : ce que font ses mains. Tournée vers quelqu'un ou à sa place d'origine, les mains
        /// sur les cuisses ; devant le carnet, elle écrit ; devant le clavier, l'occupation.
        /// </summary>
        void Occupy(Mode m, float now)
        {
            if (_stop == Stop.Home || _steps != 0)
            {
                SetPose("lap");
                return;
            }
            if (_stop == Stop.Write)
            {
                SetPose(_penWriting ? "write" : "lap");
                return;
            }
            var engaged = now - _engagedSeen < EngageLinger;
            // La souris n'est lâchée qu'au point de sa boucle où la main l'a prise : elle reste là où elle était.
            var onMouse = m == Mode.DeskType && _onMouse && now < _workSwitch && !engaged;
            if (_clipPose == "mouse" && !onMouse && !MouseAtGrabPhase()) return;
            if (engaged)
            {
                SetPose("desk");
                return;
            }
            switch (m)
            {
                case Mode.DeskType:
                    if (now >= _workSwitch)
                    {
                        _onMouse = !_onMouse && Find(MouseKeys, 1.6f) != null;
                        _workSwitch = now + (_onMouse ? Random.Range(3f, 7f) : Random.Range(8f, 18f));
                    }
                    SetPose(_onMouse ? "mouse" : "type");
                    break;
                case Mode.ReadHeld:
                    SetPose("read");
                    HoldBook();
                    break;
                case Mode.DeskLean:
                    // Accoudée : la même vie que le repos (boire, prendre son stylo, s'étirer), réfléchir pour attitude.
                    Idle(now, "lean_desk");
                    break;
                default:
                    Idle(now, "desk");
                    break;
            }
        }

        /// <summary>
        /// Au repos au bureau : les mains posées (<paramref name="rest"/> : « desk », ou accoudée « lean_desk »), et de
        /// temps en temps réfléchir, s'étirer, boire une gorgée, prendre son stylo — ou le geste demandé.
        /// </summary>
        void Idle(float now, string rest)
        {
            // Réfléchir s'interrompt pour un geste demandé ; un geste de la main, lui, se finit.
            if (_idleAct != null && now < _clipUntil && !(_idleAct == "think" && _requestedAct != null)) return;
            if (_idleAct != null)
            {
                _idleAct = null;
                _idleActAt = now + Random.Range(15f, 35f);
            }
            if (_idleActAt <= 0f) _idleActAt = now + Random.Range(8f, 20f);
            var act = _requestedAct;
            if (act == null && now >= _idleActAt)
            {
                var roll = Random.value;
                act = roll < 0.45f ? "think" : roll < 0.62f && Mug() != null ? "drink" : roll < 0.8f && Pen() != null ? "take" : "stretch";
            }
            // Déjà accoudée, réfléchir n'est pas un geste de plus.
            if (act == "think" && rest == "lean_desk")
            {
                _requestedAct = null;
                _idleActAt = now + Random.Range(15f, 35f);
                act = null;
            }
            if (act != null)
            {
                var pose = act == "think" ? "lean_desk" : act;
                // Rejouer le même geste : repasser d'abord par les mains posées (un état ne se relance pas sur lui-même).
                if (_clipPose == pose || AnimatorAt(pose))
                {
                    SetPose(rest == pose ? "desk" : rest);
                    _requestedAct = act;
                    return;
                }
                _requestedAct = null;
                _idleAct = act;
                SetPose(pose, true);
                _clipUntil = now + (act == "think" ? Random.Range(9f, 16f) : ClipSeconds(act));
                return;
            }
            SetPose(rest);
        }

        /// <summary>
        /// Joue tout de suite un petit geste du repos au bureau (« think », « drink », « take », « stretch ») au lieu
        /// d'attendre le tirage : pour le labo d'animation et les démos. Il attend, s'il le faut, que la chaise soit
        /// devant le clavier.
        /// </summary>
        public void PlayDeskGesture(string gesture)
        {
            if (gesture == "think" || gesture == "drink" || gesture == "take" || gesture == "stretch") _requestedAct = gesture;
        }

        /// <summary>Où en est la chaise, pour les démos et les sondes : « type », « write », « home+90 »…</summary>
        public string ChairStop => _gesture != null ? _gesture.Pose
            : _stop == Stop.Unknown ? "?" : _stop.ToString().ToLowerInvariant() + (_steps != 0 ? (_steps > 0 ? "+" : "") + (_steps * 45) : "");

        void SetPose(string pose, bool restart = false)
        {
            if (_clipPose == pose && !restart) return;
            _clipPose = pose;
            _clipStart = Time.time;
        }

        /// <summary>L'état de la pose est sur le calque (seul, ou en train d'entrer ou de sortir).</summary>
        bool AnimatorAt(string pose)
        {
            if (PoseLayer < 0) return false;
            var h = Animator.StringToHash(pose);
            return _animator.GetCurrentAnimatorStateInfo(PoseLayer).shortNameHash == h ||
                   (_animator.IsInTransition(PoseLayer) && _animator.GetNextAnimatorStateInfo(PoseLayer).shortNameHash == h);
        }

        bool PoseLayerHas(string pose) => PoseLayer >= 0 && _animator.HasState(PoseLayer, Animator.StringToHash(pose));

        /// <summary>L'état de la pose est seul sur le calque (fondu d'entrée fini).</summary>
        bool InPose(string pose)
        {
            if (PoseLayer < 0) return false;
            if (pose == "none") return !_animator.IsInTransition(PoseLayer);
            return !_animator.IsInTransition(PoseLayer) && _animator.GetCurrentAnimatorStateInfo(PoseLayer).shortNameHash == Animator.StringToHash(pose);
        }

        /// <summary>La boucle de la pose est au début d'un de ses cycles (ou d'une fraction <paramref name="also"/>).</summary>
        bool LoopAt(string pose, float window, float also = -1f)
        {
            if (!InPose(pose)) return true;
            var f = Mathf.Repeat(_animator.GetCurrentAnimatorStateInfo(PoseLayer).normalizedTime, 1f);
            return f < window || (also >= 0f && f >= also && f < also + window);
        }

        float ClipSeconds(string pose)
        {
            string clip = null;
            foreach (var (p, c) in BodyAnim.DeskClips)
                if (p == pose)
                    clip = c;
            if (clip == null) return 3f;
            if (_clipLengths.Count == 0 && _animator.runtimeAnimatorController != null)
                foreach (var c in _animator.runtimeAnimatorController.animationClips)
                    if (c != null)
                        _clipLengths[c.name] = c.length;
            return _clipLengths.TryGetValue(clip, out var s) ? s : 3f;
        }

        /// <summary>
        /// Relève où est la chaise en arrivant (une position nommée, à peu près) ; ailleurs — un instantané l'a laissée
        /// n'importe où —, elle est posée à sa place d'origine.
        /// </summary>
        void Survey(ChairRig chair)
        {
            foreach (var s in new[] { Stop.Home, Stop.Type, Stop.Write })
                for (var k = -MaxTurnSteps; k <= MaxTurnSteps; k++)
                {
                    if (s == Stop.Write && k != 0) continue;
                    if (Mathf.Abs(Mathf.DeltaAngle(chair.Yaw, BaseYaw(s) + k * TurnStep)) > 2f || Mathf.Abs(chair.Roll - BaseRoll(s)) > 0.01f) continue;
                    _stop = s;
                    _steps = k;
                    return;
                }
            chair.Set(0f, 0f);
            _stop = Stop.Home;
            _steps = 0;
        }

        /// <summary>
        /// Avant de se lever (<see cref="ActorBody.BeforeStanding"/>) : le stylo reposé, la chaise ramenée à sa place par
        /// ses gestes — tournée vers le bureau, repoussée des mains.
        /// </summary>
        IEnumerator LeaveSeat()
        {
            var chair = SeatChair();
            if (chair == null || !DeskClipsReady || !enabled) yield break;
            if (_stop == Stop.Unknown) Survey(chair);
            _leaving = true;
            var deadline = Time.time + 30f;
            while (Time.time < deadline && _body.Posture == Posture.Sit)
            {
                // Arrivée, et un temps posée (les mains sur les cuisses) avant de se lever.
                if (_gesture == null && !_penWriting && _stop == Stop.Home && _steps == 0 &&
                    ((_clipPose == "lap" && Time.time - _clipStart > 0.4f) || _clipPose == "none" || _clipPose == null)) break;
                yield return null;
            }
            if (_stop != Stop.Home || _steps != 0)
            {
                Debug.LogWarning("[BodyActivity] la chaise n'a pas pu être ramenée par ses gestes : posée à sa place.");
                chair.Set(0f, 0f);
                _stop = Stop.Home;
                _steps = 0;
            }
            _leaving = false;
        }

        /// <summary>Elle n'est plus assise au bureau : ce qu'elle tenait retourne à sa place, l'état est oublié.</summary>
        void ForgetDesk()
        {
            if (_stop == Stop.Unknown && _gesture == null && _carried == null && !_mouseHeld) return;
            ReleaseCarried();
            ReleaseMouse();
            // Partie sans ses gestes (un saut d'état) : la chaise retourne à sa place, où elle se rassiéra.
            if (_deskChair != null && (_stop != Stop.Home || _steps != 0 || _gesture != null) && !_body.Choreographing)
                _deskChair.Set(0f, 0f);
            _stop = Stop.Unknown;
            _steps = 0;
            _gesture = null;
            _penWriting = false;
            _leaving = false;
            _clipPose = null;
            _idleAct = null;
            _requestedAct = null;
            _idleActAt = 0f;
            _onMouse = false;
        }

        /// <summary>
        /// Le siège tel qu'il est chaise ni tournée ni avancée : son orientation. Le lieu donne l'orientation du point
        /// d'approche, qui ne regarde pas forcément dans l'axe de la chaise ; c'est l'assise, ramenée de son pivot, qui
        /// fait foi.
        /// </summary>
        Quaternion SeatHome()
        {
            var a = _body.Anchor;
            if (!a.HasValue) return SeatHomeRotation();
            var f = Flat(a.Value.rotation * Vector3.forward);
            if (f.sqrMagnitude < 1e-4f) return SeatHomeRotation();
            return Quaternion.AngleAxis(-(_chair != null ? _chair.Yaw : 0f), Vector3.up) * Quaternion.LookRotation(f.normalized, Vector3.up);
        }

        // --- ce que le geste fait bouger (après l'animation) ---------------------------------------------------
        void LateUpdate()
        {
            if (_body == null || _animator == null || _animator.runtimeAnimatorController == null) return;
            DriveChair();
            CarryObjects();
            CarryMouse();
        }

        /// <summary>La chaise suit la course du geste en cours (courbes de pivot et de roulement, 0 → 1).</summary>
        void DriveChair()
        {
            var g = _gesture;
            if (g == null || !g.MovesChair || _deskChair == null || PoseLayer < 0) return;
            var h = Animator.StringToHash(g.Pose);
            var transition = _animator.IsInTransition(PoseLayer);
            var current = _animator.GetCurrentAnimatorStateInfo(PoseLayer).shortNameHash == h;
            var next = transition && _animator.GetNextAnimatorStateInfo(PoseLayer).shortNameHash == h;
            if (!(current || (next && g.Trust))) return;
            // La course ne revient jamais en arrière (le fondu de sortie mélange la courbe avec 0).
            g.YawK = Mathf.Max(g.YawK, Mathf.Clamp01(_animator.GetFloat(BodyAnim.ChairYaw)));
            if (!Mathf.Approximately(g.Roll0, g.Roll1)) g.RollK = Mathf.Max(g.RollK, Mathf.Clamp01(_animator.GetFloat(BodyAnim.ChairRoll)));
            _deskChair.Set(Mathf.Lerp(g.Yaw0, g.Yaw1, g.YawK), Mathf.Lerp(g.Roll0, g.Roll1, g.RollK));
        }

        /// <summary>Un objet pris par la main : d'où il vient (il y retourne), et comment la main l'a pris.</summary>
        sealed class Carried
        {
            public WorldObject Obj;
            public Transform Hand, RestParent;
            public Vector3 RestPos, LocalPos;
            public Quaternion RestRot, LocalRot;
            public ObjectPhysics Physics;
            public RigidbodyInterpolation Interpolation;
        }

        Carried _carried;

        /// <summary>
        /// Les gestes qui prennent un objet : boire (la tasse, main gauche), prendre son stylo pour le regarder (main
        /// gauche), écrire (le stylo, main droite). La courbe « Hold » dit quand il est dans la main : 0,5 tenu tel que la
        /// main l'a pris, 1 tenu pour écrire (entre le pouce et l'index, la pointe vers la page).
        /// </summary>
        void CarryObjects()
        {
            var pose = CarryPose(out var hold);
            var obj = pose == null ? null : pose == "drink" ? Mug() : Pen();
            if (_carried != null && (hold < CarryHold || obj != _carried.Obj)) ReleaseCarried();
            if (_carried == null && obj != null && hold >= CarryHold)
            {
                var hand = _animator.GetBoneTransform(pose == "drink" || pose == "take" ? HumanBodyBones.LeftHand : HumanBodyBones.RightHand);
                if (hand != null) Grasp(obj, hand);
            }
            if (_carried == null) return;
            var c = _carried;
            var pos = c.Hand.TransformPoint(c.LocalPos);
            var rot = c.Hand.rotation * c.LocalRot;
            if (pose != null && pose.StartsWith("write") && hold > 0.5f && WritingGrip(rot, out var wp, out var wr))
            {
                var k = Mathf.Clamp01((hold - 0.5f) / 0.5f);
                pos = Vector3.Lerp(pos, wp, k);
                rot = Quaternion.Slerp(rot, wr, k);
            }
            c.Obj.transform.SetPositionAndRotation(pos, rot);
        }

        /// <summary>La pose de prise en cours (état seul, ou celui qui entre) et la valeur de « Hold ».</summary>
        string CarryPose(out float hold)
        {
            hold = 0f;
            if (PoseLayer < 0 || _body.Posture != Posture.Sit) return null;
            string found = null;
            var cur = _animator.GetCurrentAnimatorStateInfo(PoseLayer).shortNameHash;
            var next = _animator.IsInTransition(PoseLayer) ? _animator.GetNextAnimatorStateInfo(PoseLayer).shortNameHash : 0;
            foreach (var p in CarryPoses)
                if (cur == Animator.StringToHash(p) || next == Animator.StringToHash(p))
                {
                    found = p;
                    break;
                }
            if (found == null) return null;
            hold = _animator.GetFloat(BodyAnim.Hold);
            return found;
        }

        static readonly string[] CarryPoses = { "write_end", "write", "write_start", "drink", "take" };

        void Grasp(WorldObject o, Transform hand)
        {
            var t = o.transform;
            var rb = o.GetComponent<Rigidbody>();
            _carried = new Carried
            {
                Obj = o, Hand = hand, RestParent = t.parent, RestPos = t.position, RestRot = t.rotation, Physics = o.Physics,
                Interpolation = rb != null ? rb.interpolation : RigidbodyInterpolation.None,
            };
            o.SetPhysics(ObjectPhysics.Held);
            if (rb != null) rb.interpolation = RigidbodyInterpolation.None;
            t.SetParent(hand, true);
            _carried.LocalPos = hand.InverseTransformPoint(t.position);
            _carried.LocalRot = Quaternion.Inverse(hand.rotation) * t.rotation;
            _bounds.Remove(o);
        }

        /// <summary>Reposé là où la main l'a pris (le geste l'y ramène : on efface les millimètres).</summary>
        void ReleaseCarried()
        {
            var c = _carried;
            _carried = null;
            if (c == null || c.Obj == null) return;
            var t = c.Obj.transform;
            t.SetParent(c.RestParent, true);
            t.SetPositionAndRotation(c.RestPos, c.RestRot);
            c.Obj.SetPhysics(c.Physics);
            var rb = c.Obj.GetComponent<Rigidbody>();
            if (rb != null) rb.interpolation = c.Interpolation;
            _bounds.Remove(c.Obj);
        }

        /// <summary>
        /// Le stylo tenu pour écrire (comme dans l'atelier, atelier_desk.stylus) : son centre à 2 cm de la prise (entre le
        /// pouce et l'index) vers la page, son axe vers le papier, à mi-chemin entre l'avant-bras et la verticale.
        /// </summary>
        bool WritingGrip(Quaternion held, out Vector3 pos, out Quaternion rot)
        {
            pos = Vector3.zero;
            rot = held;
            var wrist = _animator.GetBoneTransform(HumanBodyBones.RightHand);
            var index = _animator.GetBoneTransform(HumanBodyBones.RightIndexDistal);
            var thumb = _animator.GetBoneTransform(HumanBodyBones.RightThumbDistal);
            if (wrist == null || index == null || thumb == null || Pen() == null) return false;
            var grip = (index.position + thumb.position) * 0.5f;
            var dir = ((grip - wrist.position).normalized * 0.4f + Vector3.down * 0.6f).normalized;
            var center = grip + dir * 0.02f;
            var axis = held * _penAxis;
            var want = Vector3.Dot(axis, -dir) >= 0f ? -dir : dir;
            rot = Quaternion.FromToRotation(axis, want) * held;
            pos = center - rot * Vector3.Scale(_penCenter, _pen.transform.lossyScale);
            return true;
        }

        // La souris sous la paume (desk_mouse) : pendant que la main s'en sert, son centre suit le point sous la paume (un
        // peu vers les doigts) et son grand axe le sens des doigts — comme la main la tient. Sa place de repos est ce
        // point même au moment où la main la prend (build_desk.py, à 1,5 cm près) : elle n'y fait pas de saut. Si la main
        // la quitte (un geste du haut du corps par-dessus), elle reste où elle est.
        WorldObject _mouse;
        bool _mouseHeld;
        Vector3 _mouseFrom;
        float _mousePhase, _mouseT;
        RigidbodyInterpolation _mouseInterp;
        Vector3 _mouseAxis = Vector3.forward;
        const float MouseUnderPalm = 0.025f;    // le centre de la souris, vers les doigts depuis la paume (m)
        const float MouseLetGo = 0.08f;         // la paume plus haut que ça au-dessus de la souris : la main l'a quittée (m)

        void CarryMouse()
        {
            var using_ = _clipPose == "mouse" && _body.Posture == Posture.Sit && InPose("mouse");
            if (!using_)
            {
                ReleaseMouse();
                return;
            }
            var hand = _animator.GetBoneTransform(HumanBodyBones.RightHand);
            var knuckles = _animator.GetBoneTransform(HumanBodyBones.RightMiddleProximal);
            if (hand == null || knuckles == null) return;
            if (!_mouseHeld)
            {
                _mouse = Find(MouseKeys, 1.6f);
                if (_mouse == null) return;
                _mouseHeld = true;
                _mouseT = 0f;
                _mouseFrom = _mouse.transform.position;
                _mouseAxis = LongAxis(_mouse);
                // Menée image par image : sans l'interpolation du corps physique, qui la ferait traîner d'un pas.
                var rb = _mouse.GetComponent<Rigidbody>();
                if (rb != null)
                {
                    _mouseInterp = rb.interpolation;
                    rb.interpolation = RigidbodyInterpolation.None;
                }
                _mousePhase = Mathf.Repeat(_animator.GetCurrentAnimatorStateInfo(PoseLayer).normalizedTime, 1f);
            }
            var t = _mouse.transform;
            var palm = Vector3.Lerp(hand.position, knuckles.position, 0.6f);
            if (palm.y - _mouse.Bounds().max.y > MouseLetGo) return;
            var fingers = Flat(knuckles.position - hand.position);
            if (fingers.sqrMagnitude < 1e-6f) return;
            fingers.Normalize();
            var target = Flat(palm) + fingers * MouseUnderPalm;
            // Le centre visé est celui du modèle : on déplace son origine d'autant.
            var center = Flat(_mouse.Bounds().center);
            var rot = AlongFingers(t.rotation, fingers);
            // La main s'y pose : un quart de seconde pour rejoindre la paume (au plus 1,5 cm), puis elle la suit.
            _mouseT += Time.deltaTime;
            var k = _mouseT < 0.25f ? 1f - Mathf.Exp(-Time.deltaTime * 12f) : 1f;
            var move = (target - center) * k;
            t.SetPositionAndRotation(new Vector3(t.position.x + move.x, _mouseFrom.y, t.position.z + move.z), Quaternion.Slerp(t.rotation, rot, k));
            _bounds.Remove(_mouse);
        }

        /// <summary>L'orientation qui met le grand axe de la souris dans le sens des doigts (à plat ; le plus proche des deux sens).</summary>
        Quaternion AlongFingers(Quaternion now, Vector3 fingers)
        {
            var axisNow = Flat(now * _mouseAxis);
            if (axisNow.sqrMagnitude < 1e-6f) return now;
            axisNow.Normalize();
            var turn = Vector3.SignedAngle(axisNow, fingers, Vector3.up);
            if (turn > 90f) turn -= 180f;
            if (turn < -90f) turn += 180f;
            return Quaternion.AngleAxis(turn, Vector3.up) * now;
        }

        /// <summary>Le grand axe (horizontal) d'un objet ovale dans son repère : vers son sommet le plus éloigné du centre.</summary>
        static Vector3 LongAxis(WorldObject o)
        {
            var mf = o.GetComponentInChildren<MeshFilter>();
            if (mf == null || mf.sharedMesh == null || !mf.sharedMesh.isReadable) return Vector3.forward;
            var c = mf.sharedMesh.bounds.center;
            var best = 0f;
            var far = c;
            foreach (var v in mf.sharedMesh.vertices)
            {
                var d = new Vector2(v.x - c.x, v.z - c.z).sqrMagnitude;
                if (d <= best) continue;
                best = d;
                far = v;
            }
            var w = mf.transform.TransformDirection(far - c);
            var local = o.transform.InverseTransformDirection(w);
            local.y = 0f;
            return local.sqrMagnitude > 1e-8f ? local.normalized : Vector3.forward;
        }

        /// <summary>La boucle de la souris est revenue où la main l'a prise (on peut la lâcher : elle est à sa place).</summary>
        bool MouseAtGrabPhase()
        {
            if (!_mouseHeld || !InPose("mouse")) return true;
            var f = Mathf.Repeat(_animator.GetCurrentAnimatorStateInfo(PoseLayer).normalizedTime, 1f);
            var d = Mathf.Abs(Mathf.DeltaAngle(f * 360f, _mousePhase * 360f)) / 360f;
            return d < 0.02f;
        }

        void ReleaseMouse()
        {
            if (!_mouseHeld) return;
            _mouseHeld = false;
            // Lâchée au point de sa boucle où la main l'a prise : elle est là où elle était (rien à corriger).
            if (_mouse != null)
            {
                _bounds.Remove(_mouse);
                var rb = _mouse.GetComponent<Rigidbody>();
                if (rb != null) rb.interpolation = _mouseInterp;
            }
            _mouse = null;
        }

        // --- les objets du bureau ------------------------------------------------------------------------------
        static readonly string[] MugKeys = { "=mug", "mug", "tasse" };
        static readonly string[] PenKeys = { "=pen", "=pencil", "stylo", "crayon" };
        WorldObject _mug, _pen;
        Vector3 _penAxis = Vector3.forward, _penCenter;

        WorldObject Mug()
        {
            if (_carried != null && _carried.Obj != null && Matches(_carried.Obj.id, MugKeys)) return _carried.Obj;
            if (_mug == null) _mug = Find(MugKeys, 1.6f);
            return _mug;
        }

        WorldObject Pen()
        {
            if (_carried != null && _carried.Obj != null && Matches(_carried.Obj.id, PenKeys)) return _carried.Obj;
            if (_pen == null)
            {
                _pen = Find(PenKeys, 1.6f);
                if (_pen != null) PenShape(_pen, out _penAxis, out _penCenter);
            }
            return _pen;
        }

        /// <summary>L'axe long d'un stylo (vers son sommet le plus éloigné du centre) et son centre, dans son repère.</summary>
        static void PenShape(WorldObject pen, out Vector3 axis, out Vector3 center)
        {
            axis = Vector3.forward;
            center = Vector3.zero;
            var mf = pen.GetComponentInChildren<MeshFilter>();
            if (mf == null || mf.sharedMesh == null) return;
            var mesh = mf.sharedMesh;
            var c = mesh.bounds.center;
            center = pen.transform.InverseTransformPoint(mf.transform.TransformPoint(c));
            if (!mesh.isReadable) return;
            var best = 0f;
            var far = Vector3.zero;
            foreach (var v in mesh.vertices)
            {
                var d = (v - c).sqrMagnitude;
                if (d <= best) continue;
                best = d;
                far = v;
            }
            if (best <= 1e-8f) return;
            axis = (pen.transform.InverseTransformPoint(mf.transform.TransformPoint(far)) - center).normalized;
        }

        /// <summary>
        /// Le livre entre ses mains, à la place que lui donne le clip de lecture (desk_read) : son centre devant elle, sa
        /// grande dimension d'une main à l'autre (elle le tient par ces bords), sa face penchée vers ses yeux.
        /// </summary>
        void HoldBook()
        {
            var book = HeldBook();
            if (book == null) return;
            if (_book != book)
            {
                _book = book;
                _bookHand = _body.Held.TryGetValue(book, out var h) ? h : Hand.Right;
                book.transform.SetParent(_body.transform, true);
                BookShape(book, out _bookAcross, out _bookFace, out _bookCenter);
            }
            var a = _body.Anchor.Value;
            var fwd = Flat(a.rotation * Vector3.forward).normalized;
            var right = Vector3.Cross(Vector3.up, fwd);
            var center = Flat(a.position) + right * BookHeld.x + fwd * BookHeld.z + Vector3.up * (_body.FloorY + BookHeld.y);
            var tilt = BookTilt * Mathf.Deg2Rad;
            var face = Vector3.up * Mathf.Sin(tilt) - fwd * Mathf.Cos(tilt);
            // La rotation qui envoie l'axe « d'une main à l'autre » du modèle sur sa droite et son épaisseur sur la face.
            var model = Quaternion.LookRotation(_bookAcross, _bookFace);
            var world = Quaternion.LookRotation(right, face);
            var rot = world * Quaternion.Inverse(model);
            var pos = center - rot * Vector3.Scale(_bookCenter, book.transform.lossyScale);
            var k = 1f - Mathf.Exp(-Time.deltaTime * 8f);
            book.transform.SetPositionAndRotation(Vector3.Lerp(book.transform.position, pos, k), Quaternion.Slerp(book.transform.rotation, rot, k));
        }

        Vector3 _bookAcross = Vector3.forward, _bookFace = Vector3.up, _bookCenter;

        /// <summary>
        /// Les axes d'un livre fermé dans son repère : sa plus petite étendue est son épaisseur (la face), sa plus grande
        /// à plat celle qui va d'une main à l'autre ; et son centre.
        /// </summary>
        static void BookShape(WorldObject book, out Vector3 across, out Vector3 face, out Vector3 center)
        {
            across = Vector3.forward;
            face = Vector3.up;
            center = Vector3.zero;
            var mf = book.GetComponentInChildren<MeshFilter>();
            if (mf == null || mf.sharedMesh == null) return;
            var b = mf.sharedMesh.bounds;
            center = book.transform.InverseTransformPoint(mf.transform.TransformPoint(b.center));
            var axes = new[] { Vector3.right, Vector3.up, Vector3.forward };
            var sizes = new float[3];
            for (var i = 0; i < 3; i++)
                sizes[i] = book.transform.InverseTransformVector(mf.transform.TransformVector(Vector3.Scale(b.size, axes[i]))).magnitude;
            var thin = 0;
            for (var i = 1; i < 3; i++)
                if (sizes[i] < sizes[thin]) thin = i;
            var wide = thin == 0 ? 1 : 0;
            for (var i = 0; i < 3; i++)
                if (i != thin && sizes[i] > sizes[wide]) wide = i;
            face = axes[thin];
            across = axes[wide];
        }

        /// <summary>Le livre retourne dans la main qui le tenait (un geste de la chaise, la fin de la lecture).</summary>
        void BookBackInHand()
        {
            if (_book != null && _body.IsHolding(_book)) _body.Hold(_book, _bookHand);
            _book = null;
        }

        // --- au bureau, sans clips de l'atelier : l'IK pose les mains sur les objets là où ils sont -------------
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
            var pad = Find(NotebookKeys, 1.4f);
            if (pad == null) pad = Find(BookKeys, 1.4f);
            if (pad == null) pad = Find(KeyboardKeys, 1.6f);
            if (pad == null) return;
            var b = Bounds(pad);
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
            _body.Pin(AvatarIKGoal.RightHand, flat, Palm(fwd - right * 0.3f, 0f, 5f), Elbow(false, 0.08f), 1f, 0.8f);
            var screen = Find(ScreenKeys, 2f);
            Gaze((screen != null ? Bounds(screen).center : head + fwd * 2f) + Saccade(Time.time, 0.08f), 2f);
        }

        /// <summary>
        /// Ramène un objet de travail (un carnet) devant elle : à droite du clavier, à portée de la main droite, tourné
        /// vers elle. Il retournera à sa place quand elle aura fini.

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

        bool _sawChoreography;      // la posture vient d'un geste (s'allonger) et pas d'un instantané
        DuvetRig _duvet;
        float _pullT = -1f;         // tirer la couette : 0 → 1
        int _coveredSide = -1;

        /// <summary>
        /// Allongée : endormie, elle se retourne de temps en temps (dos, gauche, droite) ; éveillée et qu'on lui
        /// parle, elle se tourne vers la personne ; sinon elle reste comme elle est.
        /// </summary>
        void Lying()
        {
            if (_duvet == null)
            {
                _duvet = BedDuvet();
                _coveredSide = -1;
            }
            if (_duvet != null) Bedding();
            var now = Time.time;
            if (_nextTurn < 0f) _nextTurn = now + Random.Range(turnEvery.x, turnEvery.y) * 0.5f;
            // Pas de retournement pendant qu'une main tient la couette.
            if (_pullT >= 0f || _duvetHandT >= 0f) return;
            if (!Asleep && Engaged && companion != null && _body.Hips != null)
            {
                var toward = companion.position - _body.Hips.position;
                toward.y = 0f;
                _body.SetLieSide(Vector3.Dot(toward, _body.LyingRight) > 0f ? 2 : 1);
                _nextTurn = now + Random.Range(turnEvery.x, turnEvery.y);
            }
            else if (now > _nextTurn && (Asleep || Random.value < 0.3f))
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
        /// La couette : endormie, elle l'ouvre de la main (encore faite, elle s'est couchée dessus) puis la tire sur elle
        /// (la main droite accompagne le bord, des hanches à la poitrine) ; dessous, elle la suit quand elle se retourne.
        /// Arrivée déjà couchée (un instantané au démarrage), la couette est déjà sur elle.
        /// </summary>
        void Bedding()
        {
            _duvet.lastOccupied = Time.time;
            var side = _body.LieSide;
            if (_duvetHandT >= 0f)
            {
                DuvetHand();
                return;
            }
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
            if (!Asleep) return;
            if (!_sawChoreography)
            {
                // Déjà couchée et endormie quand on arrive : la couette est déjà sur elle.
                _duvet.SetState(DuvetRig.CoveredFor(side), 0f);
                _coveredSide = side;
                return;
            }
            if (_duvet.State == DuvetState.Made)
            {
                // Endormie sur la couette faite : la main en écarte le bord avant de la tirer sur elle.
                _duvet.SetState(DuvetState.Open, DuvetHandSeconds);
                _duvetHandT = 0f;
                DuvetHand();
                return;
            }
            if (!_duvet.Moving) _pullT = 0f;
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
