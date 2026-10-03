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
    sealed class FootPlanter
    {
        sealed class Foot
        {
            public AvatarIKGoal Goal;
            public bool Planted, Stepping;
            public Vector3 Lock;                 // où il s'est posé (la hauteur, elle, suit le clip : talon, pointe)
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
        }

        readonly Foot[] _feet = { new Foot { Goal = AvatarIKGoal.LeftFoot }, new Foot { Goal = AvatarIKGoal.RightFoot } };
        float _active;
        int _lastStep = -1;

        // Un pied touche le sol sous 1,8 cm (semelle au-dessus du sol), le quitte au-delà de 3 cm.
        const float ContactDown = 0.018f, ContactUp = 0.03f;
        // En marchant, un pied épinglé que le clip a déjà emmené plus loin que ça est rendu au clip.
        const float WalkSlip = 0.14f;
        // Debout : un pas dès que le pied est à 7 cm ou 22° de là où le clip le voudrait.
        const float StepDistance = 0.07f, StepAngle = 22f, StepSeconds = 0.3f, StepLift = 0.045f;
        // L'autre pied peut partir quand le premier a fait l'essentiel de son pas.
        const float StepOverlap = 0.6f;

        /// <summary>Oublie où étaient les pieds (une téléportation, une posture reprise).</summary>
        public void Reset()
        {
            foreach (var f in _feet)
            {
                f.Planted = f.Stepping = f.HasPrev = false;
                f.Weight = 0f;
            }
            _active = 0f;
        }

        /// <summary>Lit la pose des pieds du clip, avant tout changement du bassin.</summary>
        public void Sample(Animator a)
        {
            foreach (var f in _feet)
            {
                f.Fk = a.GetIKPosition(f.Goal);
                f.FkRot = a.GetIKRotation(f.Goal);
            }
        }

        /// <summary>
        /// Une fois par image : quels pieds tiennent, lesquels font un pas. <paramref name="lift"/> : de combien le
        /// bassin a été monté ou descendu depuis la lecture (l'ancrage au sol), <paramref name="speed"/> : la vitesse
        /// du corps (au-delà de 0,1 m/s, le clip de marche fait lui-même les pas).
        /// </summary>
        public void Update(Animator a, bool active, float floorY, float lift, float speed, float dt)
        {
            var walking = speed > 0.1f;
            _active = Mathf.MoveTowards(_active, active ? 1f : 0f, dt / 0.2f);
            if (!active)
            {
                foreach (var f in _feet) f.Planted = f.Stepping = f.HasPrev = false;
                return;
            }
            for (var s = 0; s < 2; s++)
            {
                var f = _feet[s];
                var fk = f.Fk + Vector3.up * lift;
                var bottom = s == 0 ? a.leftFeetBottomHeight : a.rightFeetBottomHeight;
                var height = fk.y - bottom - floorY;
                // Aucune cible sous le sol : la semelle s'y pose au plus bas.
                var minY = floorY + bottom;
                f.Floor = 0f;
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
                    f.TargetRot = Quaternion.Slerp(f.FromRot, f.FkRot, k);
                    f.RotWeight = 1f;
                    if (f.StepT >= 1f)
                    {
                        f.Stepping = false;
                        Plant(f, fk);
                    }
                }
                else if (f.Planted)
                {
                    var slip = Flat(fk - f.Lock).magnitude;
                    if (height > ContactUp || (walking && slip > WalkSlip))
                    {
                        // Le clip lève le pied (ou l'a déjà emmené ailleurs) : il le reprend, en douceur.
                        f.Planted = false;
                    }
                    else
                    {
                        f.Target = new Vector3(f.Lock.x, Mathf.Max(fk.y, minY), f.Lock.z);
                        f.TargetRot = f.LockRot;
                        // En marchant, le pied déroule (talon, pointe) comme le clip le dit ; debout, il ne vrille pas
                        // avec le corps qui tourne.
                        f.RotWeight = walking ? 0f : 1f;
                    }
                }
                else if (height < ContactDown && settled)
                {
                    Plant(f, fk);
                    f.Target = new Vector3(fk.x, Mathf.Max(fk.y, minY), fk.z);
                    f.TargetRot = f.FkRot;
                    f.RotWeight = walking ? 0f : 1f;
                }
                else if (height < 0f)
                {
                    // Libre (en l'air dans le clip) mais sous le sol : le talon qui arrive, la pointe qui traîne.
                    f.Target = new Vector3(fk.x, minY, fk.z);
                    f.TargetRot = f.FkRot;
                    f.RotWeight = 0f;
                    f.Floor = 1f;
                }
            }
            if (!walking) MaybeStep(lift);
            foreach (var f in _feet)
            {
                var held = f.Planted || f.Stepping;
                f.Weight = Mathf.MoveTowards(f.Weight, held ? 1f : 0f, dt / (held ? 0.05f : 0.14f));
            }
        }

        /// <summary>Écrit les cibles des pieds ; un pied épinglé par ailleurs (assise, chorégraphie) est laissé.</summary>
        public void Apply(Animator a, bool skipLeft, bool skipRight)
        {
            if (_active <= 0f) return;
            for (var s = 0; s < 2; s++)
            {
                if (s == 0 ? skipLeft : skipRight) continue;
                var f = _feet[s];
                var w = Mathf.Max(f.Weight, f.Floor) * _active;
                a.SetIKPositionWeight(f.Goal, w);
                a.SetIKRotationWeight(f.Goal, w * f.RotWeight);
                if (w <= 0f) continue;
                a.SetIKPosition(f.Goal, f.Target);
                a.SetIKRotation(f.Goal, f.TargetRot);
            }
        }

        void Plant(Foot f, Vector3 fk)
        {
            f.Planted = true;
            f.Lock = fk;
            f.LockRot = f.FkRot;
        }

        /// <summary>Debout : le pied le plus en retard sur le clip fait un pas, si l'autre n'est pas en l'air.</summary>
        void MaybeStep(float lift)
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
                var d = Flat(fk - f.Lock).magnitude / StepDistance;
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

        static Vector3 Flat(Vector3 v)
        {
            v.y = 0f;
            return v;
        }
    }
}
