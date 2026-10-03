using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// Les pieds tiennent au sol. Le clip joue la jambe, mais rien ne garantit que le pied d'appui reste où il s'est
    /// posé : la cadence de la marche ne colle jamais exactement à la vitesse du corps (au démarrage, à l'arrêt, dans
    /// un virage), et un corps qui pivote sur place emporte ses pieds avec lui. Un pied posé est donc épinglé (IK) là
    /// où il a touché le sol, jusqu'à ce que le clip le lève. Debout, quand le corps s'en est trop éloigné (il a
    /// tourné, l'attente a changé d'appui), le pied fait un vrai petit pas — levé, porté, reposé —, un pied à la fois.
    /// </summary>
    /// <remarks>
    /// La pose « du clip » est lue sur les os, après l'animation (<see cref="SampleBones"/>), et l'IK des jambes est
    /// la nôtre (<see cref="Solve"/>, deux os, le genou dans le plan où l'animation le plie). Les cibles IK que
    /// l'Animator donne pour les pieds sont celles de l'acteur de la prise, mises à l'échelle de ses hanches, pas
    /// celles de son squelette : jusqu'à 9 cm et 20° d'écart en marchant — tout ce qui en décidait (pied posé, levé,
    /// hauteur du bassin) se trompait.
    /// </remarks>
    sealed class FootPlanter
    {
        sealed class Foot
        {
            public AvatarIKGoal Goal;
            public bool Planted, Stepping;
            public Vector3 Lock;                 // où il s'est posé (la hauteur, elle, suit le clip : talon, pointe)
            public Vector3 LockBall;             // l'avant-pied posé : le point qui ne bouge pas quand le talon monte
            public bool WalkAnchored;            // ancré comme en marchant (la cheville) plutôt que debout (l'avant-pied)
            public bool OnBall;                  // tient sur l'avant-pied (LockBall) plutôt que sur la cheville (Lock)
            public bool Following;               // suit le clip (voir Update) plutôt que de le verrouiller
            public Quaternion LockRot;
            public Vector3 From;
            public Quaternion FromRot;
            public float StepT, Weight;
            public Vector3 Fk;                   // la pose du clip, lue avant que le bassin bouge
            public Vector3 PrevFk;               // la même, à l'image précédente (bassin compris)
            public bool HasPrev;
            public Quaternion FkRot;
            public Vector3 Target;
            public Quaternion TargetRot;
            public float RotWeight;
            public float Floor;                  // 1 : pied libre que le clip ferait passer sous le sol, retenu dessus
            public float Raise;                  // de combien le talon est levé par nous (degrés), autour de RaiseAxis
            public Vector3 RaiseAxis;
        }

        readonly Foot[] _feet = { new Foot { Goal = AvatarIKGoal.LeftFoot }, new Foot { Goal = AvatarIKGoal.RightFoot } };
        float _active;
        // La semelle, dans le repère de la cible IK du pied (la cheville ; avant = la pointe, haut = le dessus du pied
        // posé à plat) : le talon derrière la cheville, l'avant-pied sous l'articulation des orteils. Le point le plus
        // bas des deux touche le sol — la cheville seule ne le dit pas dès que le pied s'incline : sur la pointe des
        // pieds, la cheville monte alors que l'avant-pied reste au sol.
        float _heelBack = 0.05f, _ballFront = 0.09f;
        int _lastStep = -1;

        // Un pied touche le sol sous 1,8 cm (semelle au-dessus du sol), le quitte au-delà de 3 cm.
        const float ContactDown = 0.018f, ContactUp = 0.03f;
        // En marchant, un pied posé que le clip emmène plus loin que ça le suit (il glisse un peu) plutôt que d'être
        // lâché puis reposé plus loin : lâché à 14 cm et reposé aussitôt, la jambe sautait — elle tremblait.
        const float WalkSlack = 0.05f;
        // Debout : un pas dès que le pied est à 7 cm ou 22° de là où le clip le voudrait.
        const float StepDistance = 0.07f, StepAngle = 22f, StepSeconds = 0.3f, StepLift = 0.045f;
        // L'autre pied peut partir quand le premier a fait l'essentiel de son pas.
        const float StepOverlap = 0.6f;
        // Jusqu'où le talon peut monter, pied sur l'avant-pied (degrés).
        const float MaxHeelRaise = 50f;
        // En suivant le clip (voir Update) : l'ancre rejoint le pied du clip à cette vitesse (m/s, °/s) ; au-delà de
        // cet écart (fin d'un fondu entre deux attentes qui ne posent pas les pieds au même endroit), un vrai pas.
        const float FollowSpeed = 0.08f, FollowTurn = 40f, FollowStep = 0.025f;

        /// <summary>La longueur du pied, lue sur le squelette au repos : talon derrière la cheville, avant-pied devant.</summary>
        public void Configure(float heelBack, float ballFront)
        {
            _heelBack = Mathf.Clamp(heelBack, 0.02f, 0.12f);
            _ballFront = Mathf.Clamp(ballFront, 0.04f, 0.2f);
        }

        /// <summary>
        /// La hauteur du point le plus bas de la semelle (talon ou avant-pied), pour un pied dont la cible serait à
        /// <paramref name="ankle"/> orientée <paramref name="rotation"/>.
        /// </summary>
        public float SoleY(Vector3 ankle, Quaternion rotation, float bottom)
        {
            var heel = ankle + rotation * new Vector3(0f, -bottom, -_heelBack);
            var ball = ankle + rotation * new Vector3(0f, -bottom, _ballFront);
            return Mathf.Min(heel.y, ball.y);
        }

        /// <summary>La cheville du clip (lue par <see cref="SampleBones"/>) : 0 gauche, 1 droite.</summary>
        public Vector3 FkPosition(int side) => _feet[side].Fk;

        /// <summary>
        /// De combien la semelle la plus basse du clip est au-dessus du sol sous elle (négatif : dessous), chaque pied
        /// mesuré au-dessus de son propre sol (un pied sur le tapis, l'autre sur le parquet), bassin non corrigé.
        /// </summary>
        public float LowestGap(Animator a, float floorLeft, float floorRight) => Mathf.Min(
            SoleY(_feet[0].Fk, _feet[0].FkRot, a.leftFeetBottomHeight) - floorLeft,
            SoleY(_feet[1].Fk, _feet[1].FkRot, a.rightFeetBottomHeight) - floorRight);

        /// <summary>
        /// Un relevé pour le labo : par pied, la cheville du clip (hauteur), son inclinaison (degrés, + pointe en bas),
        /// l'état (P posé, S en pas, L libre), le talon levé par nous et le poids de l'IK.
        /// </summary>
        public string Describe()
        {
            var sb = new System.Text.StringBuilder();
            foreach (var f in _feet)
            {
                var fwd = f.FkRot * Vector3.forward;
                var pitch = -Mathf.Asin(Mathf.Clamp(fwd.y, -1f, 1f)) * Mathf.Rad2Deg;
                var state = f.Stepping ? "S" : f.Planted ? "P" : "L";
                sb.Append($"{f.Goal}:{f.Fk.y:0.000}/{pitch:0.0}°/{state}/{f.Raise:0.0}°/{f.Weight:0.00} ");
            }
            return sb.ToString();
        }

        /// <summary>Oublie où étaient les pieds (une téléportation, une posture reprise).</summary>
        public void Reset()
        {
            foreach (var f in _feet)
            {
                f.Planted = f.Stepping = f.HasPrev = f.OnBall = f.Following = false;
                f.Weight = 0f;
            }
            _active = 0f;
        }

        /// <summary>
        /// Lit la pose des pieds telle que l'animation l'a écrite sur les os (<paramref name="feet"/>), bassin
        /// <paramref name="lift"/> retiré ; <paramref name="frames"/> passe de l'os au repère du pied (avant = la
        /// pointe, haut = le dessus du pied à plat).
        /// </summary>
        public void SampleBones(Transform[] feet, Quaternion[] frames, float lift)
        {
            for (var s = 0; s < 2; s++)
            {
                if (feet[s] == null) continue;
                _feet[s].Fk = feet[s].position - Vector3.up * lift;
                _feet[s].FkRot = feet[s].rotation * frames[s];
            }
        }

        /// <summary>
        /// Une fois par image : quels pieds tiennent, lesquels font un pas. <paramref name="lift"/> : de combien le
        /// bassin a été monté ou descendu depuis la lecture (l'ancrage au sol), <paramref name="speed"/> : la vitesse
        /// du corps (au-delà de 0,1 m/s, le clip de marche fait lui-même les pas).
        /// </summary>
        /// <param name="follow">
        /// L'animation tient les pieds d'elle-même (debout, hors fondu, sans geste, corps immobile) : les clips de
        /// l'atelier ont leurs appuis cuits, au millimètre. Un pied posé suit alors le clip — sa hauteur, son talon qui
        /// monte, son cap — et n'est que retenu au-dessus du sol ; l'ancre le rejoint en douceur, ou par un pas s'il
        /// est loin. Verrouiller par-dessus un clip déjà juste le faisait se battre avec lui : à chaque rebond de
        /// l'attente joyeuse, le pied lâché puis repris sautait de 2 à 3 cm (il « tremblait »).
        /// </param>
        public void Update(Animator a, bool active, float floorLeft, float floorRight, float lift, float speed, float dt, bool follow = false)
        {
            var walking = speed > 0.1f;
            _active = Mathf.MoveTowards(_active, active ? 1f : 0f, dt / 0.2f);
            if (!active)
            {
                foreach (var f in _feet)
                {
                    f.Planted = f.Stepping = f.HasPrev = false;
                    f.Raise = 0f;
                }
                return;
            }
            for (var s = 0; s < 2; s++)
            {
                var f = _feet[s];
                var fk = f.Fk + Vector3.up * lift;
                var bottom = s == 0 ? a.leftFeetBottomHeight : a.rightFeetBottomHeight;
                var floorY = s == 0 ? floorLeft : floorRight;
                var sole = SoleY(fk, f.FkRot, bottom) - floorY;
                // Aucune cible sous le sol : la cheville assez haut pour que la semelle, inclinée comme dans le clip,
                // s'y pose au plus bas.
                var minY = fk.y - sole;
                // Se poser, se décoller : debout, d'après le point le plus bas de la semelle ; en marchant, d'après
                // la cheville, comme un pas — le pied se libère quand le talon se lève, pas quand la pointe quitte le
                // sol (sinon la cheville restait clouée pendant tout le déroulé du pied et la pointe reculait).
                var height = walking ? fk.y - bottom - floorY : sole;
                var floorHold = false;
                f.Raise = 0f;
                if (!(follow && !walking && f.Planted)) f.Following = false;
                // En marchant, un pied ne se pose que s'il ne file plus : en fin de balancement la cheville passe au
                // ras du sol alors que le pied avance encore — l'épingler là le figerait en arrière de son pas.
                var footSpeed = f.HasPrev && dt > 0f ? Flat(fk - f.PrevFk).magnitude / dt : 0f;
                f.PrevFk = fk;
                f.HasPrev = true;
                var settled = !walking || footSpeed < Mathf.Max(0.3f, 0.9f * speed);
                if (f.Stepping)
                {
                    f.StepT += dt / StepSeconds;
                    var k = Mathf.SmoothStep(0f, 1f, f.StepT);
                    f.Target = Vector3.Lerp(f.From, fk, k) + Vector3.up * (Mathf.Sin(Mathf.PI * Mathf.Clamp01(f.StepT)) * StepLift);
                    f.Target.y = Mathf.Max(f.Target.y, minY);
                    f.TargetRot = KeepHeading(f.FkRot, Quaternion.Slerp(f.FromRot, f.FkRot, k));
                    f.RotWeight = 1f;
                    if (f.StepT >= 1f)
                    {
                        f.Stepping = false;
                        Plant(f, fk, bottom);
                        f.WalkAnchored = walking;
                    }
                }
                else if (f.Planted && follow && !walking)
                {
                    if (sole > ContactUp)
                    {
                        // Le clip lève le pied (un pas, la pointe qui tapote) : il le reprend.
                        f.Planted = false;
                        f.OnBall = false;
                    }
                    else
                    {
                        // On reprend le pied là où il est vraiment : verrouillé pendant un fondu, il a pu s'écarter de
                        // son ancre (l'avant-pied tenu pendant que le talon montait) — repartir de l'ancre le faisait
                        // sauter de 8 cm à la fin du fondu.
                        if (!f.Following)
                        {
                            f.Lock = f.Target;
                            f.LockRot = f.TargetRot;
                            f.Following = true;
                        }
                        // L'ancre rejoint le pied du clip ; la cheville garde la hauteur du clip (talon compris), au-dessus du sol.
                        var to = new Vector3(fk.x, f.Lock.y, fk.z);
                        f.Lock = Vector3.MoveTowards(f.Lock, to, FollowSpeed * dt);
                        f.LockRot = Quaternion.RotateTowards(f.LockRot, f.FkRot, FollowTurn * dt);
                        var rot = KeepHeading(f.FkRot, f.LockRot);
                        f.Target = new Vector3(f.Lock.x, Mathf.Max(fk.y, minY), f.Lock.z);
                        f.TargetRot = rot;
                        f.RotWeight = 1f;
                        // Repris par le verrou (un fondu commence) : l'avant-pied sera ré-ancré là où est le pied.
                        f.OnBall = false;
                        f.WalkAnchored = false;
                    }
                }
                else if (f.Planted)
                {
                    // Debout, on ne fige du pied que son cap (il ne vrille pas avec le corps qui tourne) ; en marchant,
                    // il déroule comme le clip le dit.
                    var rot = walking ? f.FkRot : KeepHeading(f.FkRot, f.LockRot);
                    // Un pied posé que le clip soulève est un talon qui monte : le pied pivote sur l'avant-pied, qui
                    // reste au sol. Debout, sans ça, tout le pied montait et descendait d'un bloc avec le rebond de
                    // l'attente joyeuse, comme une barre ; en marchant, ses jambes (plus courtes que celles de
                    // l'acteur, semelles comprises) décollaient le pied à plat en fin d'appui et le bassin plongeait.
                    if (!HeelRaise(fk.y - floorY, rot, bottom, out var raise))
                    {
                        // Même talon levé, l'avant-pied ne touche plus : le clip lève vraiment le pied, il le reprend.
                        f.Planted = false;
                        f.OnBall = false;
                    }
                    else
                    {
                        // Passer de la marche à l'arrêt (ou l'inverse) change le point d'ancrage : on le reprend
                        // là où est le pied, sans à-coup.
                        if (walking != f.WalkAnchored)
                        {
                            f.Lock = f.Target;
                            f.LockBall = f.Target + f.TargetRot * new Vector3(0f, -bottom, _ballFront);
                            f.WalkAnchored = walking;
                        }
                        // Sur quoi le pied tient : debout, toujours l'avant-pied ; en marchant, le talon (la cheville)
                        // tant que le pied attaque et se pose, l'avant-pied dès qu'il se déroule (talon levé par le
                        // clip ou par nous). Ancré par l'avant-pied encore en l'air à l'attaque, le talon glissait.
                        var fwd = rot * Vector3.forward;
                        var clipPitch = -Mathf.Asin(Mathf.Clamp(fwd.y, -1f, 1f)) * Mathf.Rad2Deg;
                        var onBall = !walking || raise > 0.5f || clipPitch > 5f;
                        if (onBall && !f.OnBall) f.LockBall = f.Target + f.TargetRot * new Vector3(0f, -bottom, _ballFront);
                        if (!onBall && f.OnBall) f.Lock = f.Target;
                        f.OnBall = onBall;
                        if (raise > 0f)
                        {
                            f.Raise = raise;
                            f.RaiseAxis = rot * Vector3.right;
                            rot = Quaternion.AngleAxis(raise, f.RaiseAxis) * rot;
                        }
                        var ball = rot * new Vector3(0f, -bottom, _ballFront);
                        if (walking)
                        {
                            // Le clip emmène le pied plus loin que la tolérance : l'ancre suit (il glisse un peu).
                            var anchor = onBall ? f.LockBall : f.Lock;
                            var drift = Flat((onBall ? fk + ball : fk) - anchor);
                            var away = drift.magnitude;
                            if (away > WalkSlack)
                            {
                                if (onBall) f.LockBall += drift * ((away - WalkSlack) / away);
                                else f.Lock += drift * ((away - WalkSlack) / away);
                            }
                        }
                        Vector3 ankle;
                        if (onBall)
                        {
                            // L'avant-pied reste où il s'est posé ; la cheville se place au-dessus, à la hauteur du clip.
                            ankle = new Vector3(f.LockBall.x - ball.x, fk.y, f.LockBall.z - ball.z);
                            var under = SoleY(ankle, rot, bottom) - floorY;
                            if (under < 0f) ankle.y -= under;
                        }
                        else
                        {
                            ankle = new Vector3(f.Lock.x, Mathf.Max(fk.y, minY), f.Lock.z);
                        }
                        f.Target = ankle;
                        f.TargetRot = rot;
                        // Le pied orienté par nous dès que nous fixons son cap ou levons son talon ; sinon celui du clip.
                        f.RotWeight = !walking || raise > 0f ? 1f : 0f;
                    }
                }
                else if (height < ContactDown && settled)
                {
                    Plant(f, fk, bottom);
                    f.WalkAnchored = walking;
                    f.Target = new Vector3(fk.x, Mathf.Max(fk.y, minY), fk.z);
                    f.TargetRot = f.FkRot;
                    f.RotWeight = walking ? 0f : 1f;
                }
                else if (sole < 0f)
                {
                    // Libre (en l'air dans le clip) mais sous le sol : le talon qui arrive, la pointe qui traîne.
                    f.Target = new Vector3(fk.x, minY, fk.z);
                    f.TargetRot = f.FkRot;
                    f.RotWeight = 0f;
                    floorHold = true;
                }
                else if (f.Weight > 0f)
                {
                    // Rendu au clip : la cible rejoint l'animation en douceur pendant que le poids retombe. Restée où
                    // le pied s'était posé, elle laissait le pied filer d'un coup sec à la fin du fondu.
                    var k = 1f - Mathf.Exp(-dt / 0.05f);
                    f.Target = Vector3.Lerp(f.Target, new Vector3(fk.x, Mathf.Max(fk.y, minY), fk.z), k);
                    f.TargetRot = Quaternion.Slerp(f.TargetRot, f.FkRot, k);
                }
                else
                {
                    f.Target = new Vector3(fk.x, Mathf.Max(fk.y, minY), fk.z);
                    f.TargetRot = f.FkRot;
                    f.RotWeight = 0f;
                }
                // La retenue au-dessus du sol vient et s'en va en quelques images : allumée d'un coup, elle faisait
                // sauter le genou de la jambe presque tendue qui attaque le sol.
                f.Floor = Mathf.MoveTowards(f.Floor, floorHold ? 1f : 0f, dt / 0.04f);
            }
            if (!walking) MaybeStep(lift, follow ? FollowStep : StepDistance);
            foreach (var f in _feet)
            {
                var held = f.Planted || f.Stepping;
                f.Weight = Mathf.MoveTowards(f.Weight, held ? 1f : 0f, dt / (held ? 0.05f : 0.14f));
            }
        }

        /// <summary>
        /// Après l'animation, sur les os : chaque jambe est amenée sur la cible de son pied (IK à deux os, le genou
        /// gardé dans le plan où l'animation le plie), le pied orienté, et les orteils restent à plat quand nous
        /// levons un talon.
        /// </summary>
        public void Solve(Transform[] upper, Transform[] lower, Transform[] feet, Transform[] toes, Quaternion[] frames, Vector3 forward)
        {
            if (_active <= 0f) return;
            for (var s = 0; s < 2; s++)
            {
                var f = _feet[s];
                var w = Mathf.Max(f.Weight, f.Floor) * _active;
                if (w <= 0f || upper[s] == null || lower[s] == null || feet[s] == null) continue;
                var target = Vector3.Lerp(feet[s].position, f.Target, w);
                TwoBone(upper[s], lower[s], feet[s], target, forward);
                var rw = w * f.RotWeight;
                if (rw > 0f) feet[s].rotation = Quaternion.Slerp(feet[s].rotation, f.TargetRot * Quaternion.Inverse(frames[s]), rw);
                if (f.Raise > 0f && toes[s] != null)
                    toes[s].rotation = Quaternion.AngleAxis(-f.Raise * w, f.RaiseAxis) * toes[s].rotation;
            }
        }

        /// <summary>
        /// IK à deux os (hanche, genou, cheville) : la cheville sur <paramref name="target"/>, le genou plié dans le
        /// plan qu'il avait (vers <paramref name="bend"/> si la jambe était tendue). D'après D. Holden, « Simple
        /// Two Joint IK ».
        /// </summary>
        static void TwoBone(Transform a, Transform b, Transform c, Vector3 target, Vector3 bend)
        {
            Vector3 pa = a.position, pb = b.position, pc = c.position;
            var lab = (pb - pa).magnitude;
            var lcb = (pc - pb).magnitude;
            if (lab < 1e-4f || lcb < 1e-4f) return;
            const float eps = 1e-3f;
            var lat = Mathf.Clamp((target - pa).magnitude, eps, lab + lcb - eps);
            float Angle(Vector3 u, Vector3 v) => Mathf.Acos(Mathf.Clamp(Vector3.Dot(u.normalized, v.normalized), -1f, 1f));
            var acAb0 = Angle(pc - pa, pb - pa);
            var baBc0 = Angle(pa - pb, pc - pb);
            var acAt0 = Angle(pc - pa, target - pa);
            var acAb1 = Mathf.Acos(Mathf.Clamp((lcb * lcb - lab * lab - lat * lat) / (-2f * lab * lat), -1f, 1f));
            var baBc1 = Mathf.Acos(Mathf.Clamp((lat * lat - lab * lab - lcb * lcb) / (-2f * lab * lcb), -1f, 1f));
            // L'axe du genou : le plan où l'animation le plie, avec un léger biais vers l'avant. Sans lui, une jambe
            // presque tendue (l'attaque du talon) donnait un plan au hasard, et le genou sautait d'une image à l'autre.
            var hipToAnkle = (pc - pa).normalized;
            var knee = (pb - pa) - Vector3.Dot(pb - pa, hipToAnkle) * hipToAnkle;
            var axis0 = Vector3.Cross(pc - pa, knee + bend.normalized * 0.03f);
            if (axis0.sqrMagnitude < 1e-8f) return;
            axis0.Normalize();
            var axis1 = Vector3.Cross(pc - pa, target - pa);
            Quaternion ra = a.rotation, rb = b.rotation;
            var r0 = Quaternion.AngleAxis((acAb1 - acAb0) * Mathf.Rad2Deg, Quaternion.Inverse(ra) * axis0);
            var r1 = Quaternion.AngleAxis((baBc1 - baBc0) * Mathf.Rad2Deg, Quaternion.Inverse(rb) * axis0);
            var r2 = axis1.sqrMagnitude > 1e-10f
                ? Quaternion.AngleAxis(acAt0 * Mathf.Rad2Deg, Quaternion.Inverse(ra) * axis1.normalized)
                : Quaternion.identity;
            var cRot = c.rotation;
            a.localRotation = a.localRotation * r0 * r2;
            b.localRotation = b.localRotation * r1;
            c.rotation = cRot;
        }

        void Plant(Foot f, Vector3 fk, float bottom)
        {
            f.Planted = true;
            f.OnBall = false;
            f.Lock = fk;
            f.LockRot = f.FkRot;
            f.LockBall = fk + f.FkRot * new Vector3(0f, -bottom, _ballFront);
        }

        /// <summary>
        /// Debout, cheville à <paramref name="ankleHeight"/> au-dessus du sol : de combien lever le talon
        /// (<paramref name="degrees"/>, pied pivotant autour de la cheville vers l'avant) pour que l'avant-pied touche
        /// le sol. Faux : même talon levé au maximum, l'avant-pied reste en l'air — le clip lève le pied pour de bon.
        /// </summary>
        bool HeelRaise(float ankleHeight, Quaternion rot, float bottom, out float degrees)
        {
            degrees = 0f;
            var heel = rot * new Vector3(0f, -bottom, -_heelBack);
            var ball = rot * new Vector3(0f, -bottom, _ballFront);
            // Déjà au sol (à plat, talon ou pointe) : rien à lever.
            if (ankleHeight + Mathf.Min(heel.y, ball.y) <= 0f) return true;
            var fwd = Flat(rot * Vector3.forward);
            if (fwd.sqrMagnitude < 1e-6f) return ankleHeight + ball.y <= ContactUp;
            fwd.Normalize();
            // Dans le plan du pied : l'avant-pied à rho de la cheville, à phi de la verticale, vers l'avant.
            var along = Vector3.Dot(ball, fwd);
            var rho = Mathf.Sqrt(along * along + ball.y * ball.y);
            var phi = Mathf.Atan2(along, -ball.y);
            // Il touche quand rho·cos(phi − θ) = hauteur de la cheville.
            var theta = ankleHeight >= rho ? phi : phi - Mathf.Acos(ankleHeight / rho);
            theta = Mathf.Clamp(theta, 0f, MaxHeelRaise * Mathf.Deg2Rad);
            degrees = theta * Mathf.Rad2Deg;
            return ankleHeight - rho * Mathf.Cos(phi - theta) <= ContactUp;
        }

        /// <summary>
        /// Debout : le pied le plus en retard sur le clip fait un pas, si l'autre n'est pas en l'air — dès
        /// <paramref name="distance"/> d'écart (ou <see cref="StepAngle"/>).
        /// </summary>
        void MaybeStep(float lift, float distance)
        {
            var best = -1;
            var bestNeed = 1f;
            for (var s = 0; s < 2; s++)
            {
                var f = _feet[s];
                var other = _feet[1 - s];
                if (!f.Planted || f.Stepping) continue;
                if (other.Stepping && other.StepT < StepOverlap) continue;
                var fk = f.Fk + Vector3.up * lift;
                var d = Flat(fk - f.Lock).magnitude / distance;
                var ang = Vector3.Angle(Flat(f.LockRot * Vector3.forward), Flat(f.FkRot * Vector3.forward)) / StepAngle;
                var need = Mathf.Max(d, ang);
                // À besoin égal, on alterne : on ne repart pas du pied qui vient de se poser.
                if (s == _lastStep) need *= 0.9f;
                if (need > bestNeed)
                {
                    bestNeed = need;
                    best = s;
                }
            }
            if (best < 0) return;
            var foot = _feet[best];
            foot.Stepping = true;
            foot.Planted = false;
            foot.StepT = 0f;
            foot.From = foot.Target;
            foot.FromRot = foot.RotWeight > 0f ? foot.TargetRot : foot.FkRot;
            _lastStep = best;
        }

        /// <summary>L'orientation du clip (<paramref name="clip"/>), tournée autour de la verticale vers le cap de <paramref name="heading"/>.</summary>
        static Quaternion KeepHeading(Quaternion clip, Quaternion heading)
        {
            var from = Flat(clip * Vector3.forward);
            var to = Flat(heading * Vector3.forward);
            if (from.sqrMagnitude < 1e-4f || to.sqrMagnitude < 1e-4f) return clip;
            return Quaternion.AngleAxis(Vector3.SignedAngle(from, to, Vector3.up), Vector3.up) * clip;
        }

        static Vector3 Flat(Vector3 v)
        {
            v.y = 0f;
            return v;
        }
    }
}
