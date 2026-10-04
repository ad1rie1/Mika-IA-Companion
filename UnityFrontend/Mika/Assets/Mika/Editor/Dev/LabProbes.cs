using System.Collections;
using System.Globalization;
using System.IO;
using System.Text;
using Mika.World.Engine;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.Editor.Dev
{
    /// <summary>
    /// Des relevés du labo d'animation (<see cref="AnimLab"/>), en mode jeu : la cinématique des jambes pendant une
    /// marche (un CSV, une ligne par image à 30 i/s) pour trouver ce qui saute d'une image à l'autre ; et la place
    /// réelle des objets autour d'un lieu (le bureau, le lit, la fenêtre, la bibliothèque), dans le repère où l'atelier
    /// d'animation Blender construit les gestes (UnityFrontend/ArtSource/atelier/*_layout.json).
    /// </summary>
    public static class LabProbes
    {
        static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        /// <summary>Marche du lieu <paramref name="from"/> au lieu <paramref name="to"/>, relevé dans Temp/lab/&lt;name&gt;.csv.</summary>
        public static void Walk(string name, string from = "desk", string to = "bed") => AnimLab.Run(WalkScenario(AnimLab.Body, name, from, to));

        static IEnumerator WalkScenario(ActorBody b, string name, string fromId, string toId)
        {
            var st = AnimLab.Stage;
            var a = b.animator;
            // Sans caméra qui le voie, l'Animator du corps d'essai ne s'évalue pas : les os resteraient figés.
            a.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            var from = st.Place(fromId);
            var to = st.Place(toId);
            b.Snap(from.Position, from.Rotation, Posture.Stand);
            yield return new WaitForSeconds(0.5f);
            var previous = Time.captureFramerate;
            Time.captureFramerate = 30;
            var sb = new StringBuilder();
            sb.AppendLine("i;t;speed;lthigh;rthigh;lknee;rknee;lfoot_y;rfoot_y;hips_y;lfoot_x;lfoot_z;rfoot_x;rfoot_z;state");
            var walking = true;
            b.StartCoroutine(Go(b, from, to, () => walking = false));
            var i = 0;
            try
            {
                while (walking && i < 900)
                {
                    yield return new WaitForEndOfFrame();
                    sb.AppendLine(string.Join(";", i.ToString(), F(Time.time), F(b.Speed),
                        F(Thigh(b, HumanBodyBones.LeftUpperLeg, HumanBodyBones.LeftLowerLeg)),
                        F(Thigh(b, HumanBodyBones.RightUpperLeg, HumanBodyBones.RightLowerLeg)),
                        F(Knee(a, HumanBodyBones.LeftUpperLeg, HumanBodyBones.LeftLowerLeg, HumanBodyBones.LeftFoot)),
                        F(Knee(a, HumanBodyBones.RightUpperLeg, HumanBodyBones.RightLowerLeg, HumanBodyBones.RightFoot)),
                        F(a.GetBoneTransform(HumanBodyBones.LeftFoot).position.y),
                        F(a.GetBoneTransform(HumanBodyBones.RightFoot).position.y),
                        F(a.GetBoneTransform(HumanBodyBones.Hips).position.y),
                        F(a.GetBoneTransform(HumanBodyBones.LeftFoot).position.x), F(a.GetBoneTransform(HumanBodyBones.LeftFoot).position.z),
                        F(a.GetBoneTransform(HumanBodyBones.RightFoot).position.x), F(a.GetBoneTransform(HumanBodyBones.RightFoot).position.z),
                        b.FeetState().Replace(';', ',')));
                    i++;
                    yield return null;
                }
            }
            finally
            {
                Time.captureFramerate = previous;
                File.WriteAllText(AnimLab.Folder(name + ".csv"), sb.ToString());
            }
        }

        /// <summary>
        /// Le bureau d'un bout à l'autre — s'asseoir, travailler, boire, prendre son stylo, pivoter vers quelqu'un,
        /// écrire, se lever —, relevé dans Temp/lab/&lt;name&gt;.csv, une ligne par image à 30 i/s : où en est la chaise
        /// (position nommée, pivot, roulement), l'état du calque d'occupation et les courbes du geste, où sont la tasse,
        /// le stylo, le carnet et la souris, les mains, les pieds et les hanches. Rien ne doit bouger sans geste.
        /// </summary>
        public static void Desk(string name = "bureau") => AnimLab.Run(DeskScenario(AnimLab.Body, name));

        static IEnumerator DeskScenario(ActorBody b, string name)
        {
            var st = AnimLab.Stage;
            var a = b.animator;
            a.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            var act = b.GetComponent<BodyActivity>();
            var desk = st.Place("desk");
            var chair = desk.Chair;
            WorldObject Obj(string id)
            {
                foreach (var o in Object.FindObjectsByType<WorldObject>(FindObjectsInactive.Exclude))
                    if (o.id == id)
                        return o;
                return null;
            }
            var mug = Obj("mug");
            var pen = Obj("pen");
            var notebook = Obj("notebook");
            var mouse = Obj("mouse");
            var mate = new GameObject("Compagnon d'essai").transform;
            mate.position = desk.Position - desk.Rotation * Vector3.forward * 1.2f + desk.Rotation * Vector3.right * 1.0f + Vector3.up * 1.4f;
            act.companion = mate;
            act.Set(null, null);
            b.Snap(desk.Position, desk.Rotation, Posture.Stand);
            yield return new WaitForSeconds(0.5f);
            var previous = Time.captureFramerate;
            Time.captureFramerate = 30;
            var sb = new StringBuilder();
            sb.AppendLine("i;t;step;stop;mode;state;trans;pyaw;proll;phold;cyaw;croll;mug;pen;notebook;mouse;lhand;rhand;lfoot;rfoot;hips;seat");
            var step = "assise";
            var running = true;
            var layer = a.GetLayerIndex(BodyAnim.PoseLayer);
            string V(Vector3 v) => $"{F(v.x)},{F(v.y)},{F(v.z)}";
            string P(WorldObject o) => o != null ? V(o.transform.position) : "-";
            string Bone(HumanBodyBones h) => V(a.GetBoneTransform(h).position);
            string State()
            {
                if (layer < 0) return "-";
                var h = a.GetCurrentAnimatorStateInfo(layer).shortNameHash;
                foreach (var p in BodyAnim.Poses)
                    if (Animator.StringToHash(p) == h)
                        return p;
                return h == Animator.StringToHash("Rien") ? "Rien" : h.ToString();
            }
            IEnumerator Log()
            {
                var i = 0;
                while (running && i < 6000)
                {
                    yield return new WaitForEndOfFrame();
                    var seat = b.Anchor.HasValue ? V(b.Anchor.Value.position) : "-";
                    sb.AppendLine(string.Join(";", i.ToString(), F(Time.time), step, act.ChairStop, act.ModeName, State(),
                        layer >= 0 && a.IsInTransition(layer) ? "1" : "0",
                        F(a.GetFloat(BodyAnim.ChairYaw)), F(a.GetFloat(BodyAnim.ChairRoll)), F(a.GetFloat(BodyAnim.Hold)),
                        F(chair != null ? chair.Yaw : 0f), F(chair != null ? chair.Roll : 0f),
                        P(mug), P(pen), P(notebook), P(mouse),
                        Bone(HumanBodyBones.LeftHand), Bone(HumanBodyBones.RightHand),
                        Bone(HumanBodyBones.LeftFoot), Bone(HumanBodyBones.RightFoot), Bone(HumanBodyBones.Hips), seat));
                    i++;
                    yield return null;
                }
            }
            b.StartCoroutine(Log());
            try
            {
                yield return b.ChangePosture(Posture.Sit, desk, 1f);
                step = "travail";
                act.Set("work", null);
                yield return new WaitForSeconds(16f);
                step = "repos";
                act.Set(null, null);
                yield return new WaitForSeconds(3f);
                step = "boire";
                act.PlayDeskGesture("drink");
                yield return new WaitForSeconds(7f);
                step = "stylo";
                act.PlayDeskGesture("take");
                yield return new WaitForSeconds(7f);
                step = "parler";
                act.Engage(6f);
                yield return new WaitForSeconds(16f);
                step = "ecrire";
                act.Set("draw", null);
                yield return new WaitForSeconds(15f);
                step = "fin_ecrire";
                act.Set(null, null);
                yield return new WaitForSeconds(12f);
                step = "lever";
                yield return b.ChangePosture(Posture.Stand, desk, 1f);
                yield return new WaitForSeconds(1f);
            }
            finally
            {
                running = false;
                Time.captureFramerate = previous;
                File.WriteAllText(AnimLab.Folder(name + ".csv"), sb.ToString());
                Object.Destroy(mate.gameObject);
                Debug.Log("[labo] relevé du bureau : " + AnimLab.Folder(name + ".csv"));
            }
        }

        /// <summary>
        /// Des rafales d'images des gestes du bureau (Temp/lab/&lt;name&gt;_*/) : se tirer au bureau, boire (la tasse par
        /// l'anse), prendre son stylo, pivoter vers quelqu'un, écrire, se repousser — pour juger les prises à l'œil.
        /// </summary>
        public static void DeskShots(string name = "geste") => AnimLab.Run(DeskShotsScenario(AnimLab.Body, name));

        static IEnumerator DeskShotsScenario(ActorBody b, string name)
        {
            var st = AnimLab.Stage;
            b.animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            var act = b.GetComponent<BodyActivity>();
            var desk = st.Place("desk");
            var mate = new GameObject("Compagnon d'essai").transform;
            mate.position = desk.Position - desk.Rotation * Vector3.forward * 1.2f + desk.Rotation * Vector3.right * 1.0f + Vector3.up * 1.4f;
            act.companion = mate;
            act.Set(null, null);
            AnimLab.Lamp(true);
            // La lampe de bureau et l'écran passent devant les mains : masqués pendant les gros plans.
            var hidden = new System.Collections.Generic.List<Renderer>();
            void Hide(bool on)
            {
                if (on)
                    foreach (var o in Object.FindObjectsByType<WorldObject>(FindObjectsInactive.Exclude))
                        if (o.id == "desk_lamp" || o.id == "monitor")
                            foreach (var r in o.GetComponentsInChildren<Renderer>())
                                if (r.enabled)
                                {
                                    r.enabled = false;
                                    hidden.Add(r);
                                }
                if (!on)
                {
                    foreach (var r in hidden)
                        if (r != null) r.enabled = true;
                    hidden.Clear();
                }
            }
            b.Snap(desk.Position, desk.Rotation, Posture.Stand);
            yield return new WaitForSeconds(0.5f);
            yield return b.ChangePosture(Posture.Sit, desk, 1f);
            // Le repère du siège, chaise à sa place (relevé une fois : les plans ne tournent pas avec la chaise).
            var s0 = b.Anchor ?? new Pose(b.transform.position, b.transform.rotation);
            var f0 = s0.rotation * Vector3.forward;
            f0.y = 0f;
            var q0 = Quaternion.LookRotation(f0.normalized, Vector3.up);
            var o0 = new Vector3(s0.position.x, b.FloorY, s0.position.z);
            System.Func<(Vector3, Vector3)> Seat(Vector3 eye, Vector3 at) => AnimLab.Fixed(o0 + q0 * eye, o0 + q0 * at);
            try
            {
                act.Set("work", null);
                yield return new WaitForSeconds(0.8f);
                yield return AnimLab.Burst(name + "_tirer", 10, 9, Seat(new Vector3(1.3f, 1.2f, 0.1f), new Vector3(0f, 0.7f, 0.35f)));
                yield return new WaitForSeconds(2f);
                act.Set(null, null);
                yield return new WaitForSeconds(7f);
                Hide(true);
                act.PlayDeskGesture("drink");
                yield return new WaitForSeconds(0.6f);
                yield return AnimLab.Burst(name + "_boire", 12, 11, Seat(new Vector3(-0.85f, 1.05f, 0.75f), new Vector3(-0.2f, 0.9f, 0.4f)), 640, 480, 35f);
                yield return new WaitForSeconds(1.5f);
                act.PlayDeskGesture("take");
                yield return new WaitForSeconds(0.6f);
                yield return AnimLab.Burst(name + "_stylo", 12, 11, Seat(new Vector3(-0.8f, 1.1f, 0.8f), new Vector3(-0.05f, 0.88f, 0.45f)), 640, 480, 35f);
                Hide(false);
                yield return new WaitForSeconds(1.5f);
                act.Engage(5f);
                yield return AnimLab.Burst(name + "_pivot", 12, 12, AnimLab.Fixed(desk.Position + desk.Rotation * new Vector3(1.4f, 1.4f, -0.9f), desk.Position + Vector3.up * 0.6f));
                yield return new WaitForSeconds(8f);
                act.Set("draw", null);
                Hide(true);
                yield return new WaitForSeconds(5f);
                yield return AnimLab.Burst(name + "_ecrire", 12, 12, Seat(new Vector3(0.3f, 1.15f, 0.95f), new Vector3(-0.12f, 0.79f, 0.6f)), 640, 480, 30f);
                act.Set(null, null);
                yield return AnimLab.Burst(name + "_reposer", 12, 12, Seat(new Vector3(0.3f, 1.15f, 0.95f), new Vector3(-0.12f, 0.79f, 0.6f)), 640, 480, 30f);
                Hide(false);
                yield return new WaitForSeconds(6f);
                b.StartCoroutine(b.ChangePosture(Posture.Stand, desk, 1f));
                yield return AnimLab.Burst(name + "_repousser", 12, 10, AnimLab.Fixed(desk.Position + desk.Rotation * new Vector3(1.4f, 1.2f, 0.2f), desk.Position + Vector3.up * 0.6f));
            }
            finally
            {
                Hide(false);
                Object.Destroy(mate.gameObject);
                Debug.Log("[labo] images du bureau : " + AnimLab.Folder(name + "_*"));
            }
        }

        /// <summary>
        /// Le lit : s'asseoir au bord, s'allonger (endormie : la couette), se retourner, se relever et se lever — relevé
        /// dans Temp/lab/&lt;name&gt;.csv (pieds, tête, peluche, couette) et rafales Temp/lab/&lt;name&gt;_*/.
        /// </summary>
        public static void Bed(string name = "lit") => AnimLab.Run(BedScenario(AnimLab.Body, name));

        static IEnumerator BedScenario(ActorBody b, string name)
        {
            var st = AnimLab.Stage;
            var a = b.animator;
            a.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            var act = b.GetComponent<BodyActivity>();
            act.Set(null, null);
            act.turnEvery = new Vector2(1000f, 1000f);
            var bed = st.Place("bed");
            var duvet = bed.Furniture != null ? bed.Furniture.GetComponentInChildren<DuvetRig>() : null;
            if (duvet != null) duvet.SetState(DuvetState.Made, 0f);
            WorldObject plush = null;
            foreach (var o in Object.FindObjectsByType<WorldObject>(FindObjectsInactive.Exclude))
                if (o.id == "plushie")
                    plush = o;
            AnimLab.Lamp(true);
            b.SetAsleep(false);
            b.Snap(bed.Position, bed.Rotation, Posture.Stand);
            yield return new WaitForSeconds(0.5f);
            var sb = new StringBuilder();
            sb.AppendLine("i;t;step;posture;lfoot;rfoot;head;hips;plush;head_plush;duvet");
            var step = "assise";
            var running = true;
            string V(Vector3 v) => $"{F(v.x)},{F(v.y)},{F(v.z)}";
            IEnumerator Log()
            {
                var i = 0;
                while (running && i < 4000)
                {
                    yield return new WaitForEndOfFrame();
                    var head = a.GetBoneTransform(HumanBodyBones.Head).position;
                    var pb = plush != null ? plush.Bounds() : new Bounds();
                    sb.AppendLine(string.Join(";", i.ToString(), F(Time.time), step, b.Posture.ToString(),
                        V(a.GetBoneTransform(HumanBodyBones.LeftFoot).position), V(a.GetBoneTransform(HumanBodyBones.RightFoot).position),
                        V(head), V(a.GetBoneTransform(HumanBodyBones.Hips).position), plush != null ? V(pb.center) : "-",
                        plush != null ? F(Mathf.Sqrt(pb.SqrDistance(head))) : "-", duvet != null ? duvet.State.ToString() : "-"));
                    i++;
                    yield return null;
                }
            }
            var previous = Time.captureFramerate;
            Time.captureFramerate = 30;
            b.StartCoroutine(Log());
            var bf = bed.Rotation * Vector3.forward;
            var br = bed.Rotation * Vector3.right;
            var side = AnimLab.Fixed(bed.Position + bf * 1.3f + br * 1.1f + Vector3.up * 1.1f, bed.Position - bf * 0.3f + Vector3.up * 0.45f);
            var feet = AnimLab.Fixed(bed.Position + bf * 1.2f - br * 0.4f + Vector3.up * 0.6f, bed.Position - bf * 0.1f + Vector3.up * 0.15f);
            try
            {
                b.StartCoroutine(b.ChangePosture(Posture.Sit, bed, 1f));
                yield return AnimLab.Burst(name + "_assise", 12, 5, feet);
                yield return new WaitForSeconds(1.5f);
                step = "coucher";
                b.SetAsleep(true);
                b.StartCoroutine(b.ChangePosture(Posture.Lie, bed, 2f));
                yield return AnimLab.Burst(name + "_coucher", 12, 10, side);
                yield return new WaitForSeconds(6f);
                step = "lever";
                b.SetAsleep(false);
                b.StartCoroutine(b.ChangePosture(Posture.Stand, bed, 2f));
                yield return AnimLab.Burst(name + "_lever", 16, 8, feet);
                yield return new WaitForSeconds(1f);
            }
            finally
            {
                running = false;
                Time.captureFramerate = previous;
                File.WriteAllText(AnimLab.Folder(name + ".csv"), sb.ToString());
                Debug.Log("[labo] relevé du lit : " + AnimLab.Folder(name + ".csv"));
            }
        }

        /// <summary>
        /// Des gros plans des gestes du bureau à l'instant où ils se jouent (l'état du calque d'occupation atteint) : la
        /// main sur la souris, boire, lire un livre tenu, écrire — Temp/lab/&lt;name&gt;_*/, et dans frames.txt l'écart
        /// paume–souris à chaque image.
        /// </summary>
        public static void DeskLook(string name = "regard") => AnimLab.Run(DeskLookScenario(AnimLab.Body, name));

        static IEnumerator DeskLookScenario(ActorBody b, string name)
        {
            var st = AnimLab.Stage;
            var a = b.animator;
            a.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            var act = b.GetComponent<BodyActivity>();
            var desk = st.Place("desk");
            act.Set(null, null);
            AnimLab.Lamp(true);
            WorldObject Obj(string id)
            {
                foreach (var o in Object.FindObjectsByType<WorldObject>(FindObjectsInactive.Exclude))
                    if (o.id == id)
                        return o;
                return null;
            }
            var layer = a.GetLayerIndex(BodyAnim.PoseLayer);
            IEnumerator Until(string pose, float timeout)
            {
                var h = Animator.StringToHash(pose);
                for (var t = 0f; t < timeout; t += Time.deltaTime)
                {
                    if (!a.IsInTransition(layer) && a.GetCurrentAnimatorStateInfo(layer).shortNameHash == h) yield break;
                    yield return null;
                }
                Debug.LogWarning($"[labo] pose « {pose} » pas atteinte en {timeout} s");
            }
            b.Snap(desk.Position, desk.Rotation, Posture.Stand);
            yield return new WaitForSeconds(0.5f);
            yield return b.ChangePosture(Posture.Sit, desk, 1f);
            var s0 = b.Anchor ?? new Pose(b.transform.position, b.transform.rotation);
            var f0 = s0.rotation * Vector3.forward;
            f0.y = 0f;
            var q0 = Quaternion.LookRotation(f0.normalized, Vector3.up);
            var o0 = new Vector3(s0.position.x, b.FloorY, s0.position.z);
            System.Func<(Vector3, Vector3)> Seat(Vector3 eye, Vector3 at) => AnimLab.Fixed(o0 + q0 * eye, o0 + q0 * at);
            var mouse = Obj("mouse");
            var log = new StringBuilder();
            try
            {
                act.Set("work", null);
                yield return Until("mouse", 40f);
                yield return new WaitForSeconds(0.3f);
                for (var i = 0; i < 8; i++)
                {
                    var hand = a.GetBoneTransform(HumanBodyBones.RightHand);
                    var knuckles = a.GetBoneTransform(HumanBodyBones.RightMiddleProximal);
                    var palm = Vector3.Lerp(hand.position, knuckles.position, 0.6f);
                    var m = mouse.Bounds().center;
                    log.AppendLine($"souris {i} paume–souris horiz {Vector2.Distance(new Vector2(palm.x, palm.z), new Vector2(m.x, m.z)):0.000} haut {palm.y - mouse.Bounds().max.y:0.000}");
                    yield return null;
                }
                yield return AnimLab.Burst(name + "_souris", 6, 20, Seat(new Vector3(0.75f, 1.1f, 0.75f), new Vector3(0.38f, 0.76f, 0.38f)), 640, 480, 35f);
                act.Set(null, null);
                yield return Until("desk", 20f);
                act.PlayDeskGesture("drink");
                yield return Until("drink", 20f);
                yield return AnimLab.Burst(name + "_boire", 10, 12, Seat(new Vector3(-0.85f, 1.05f, 0.75f), new Vector3(-0.2f, 0.9f, 0.4f)), 640, 480, 35f);
                yield return new WaitForSeconds(1f);
                var book = Obj("book_desk_2");
                if (book != null)
                {
                    var bookPos = book.transform.position;
                    var bookRot = book.transform.rotation;
                    b.Hold(book, Hand.Right);
                    act.Set("read", book.id);
                    yield return Until("read", 20f);
                    yield return new WaitForSeconds(0.5f);
                    yield return AnimLab.Burst(name + "_lire", 6, 20, Seat(new Vector3(0.55f, 1.15f, 0.95f), new Vector3(0.05f, 0.88f, 0.3f)), 640, 480, 35f);
                    act.Set(null, null);
                    yield return new WaitForSeconds(0.6f);
                    b.Release(book);
                    book.transform.SetPositionAndRotation(bookPos, bookRot);
                }
                act.Set("draw", null);
                yield return Until("write", 30f);
                yield return AnimLab.Burst(name + "_ecrire", 6, 20, Seat(new Vector3(0.05f, 1.45f, 0.35f), new Vector3(-0.12f, 0.77f, 0.62f)), 640, 480, 40f);
                act.Set(null, null);
            }
            finally
            {
                File.WriteAllText(AnimLab.Folder(name + ".txt"), log.ToString());
                Debug.Log("[labo] gros plans du bureau : " + AnimLab.Folder(name + "_*"));
            }
        }

        static IEnumerator Go(ActorBody b, PlaceView from, PlaceView to, System.Action done)
        {
            yield return b.WalkTo(to.Position, to.Rotation, Vector3.Distance(from.Position, to.Position) / 0.85f);
            yield return new WaitForSeconds(0.5f);
            done();
        }

        /// <summary>La cuisse dans le plan sagittal du corps (degrés, + en avant).</summary>
        static float Thigh(ActorBody b, HumanBodyBones up, HumanBodyBones lo)
        {
            var a = b.animator;
            var d = b.transform.InverseTransformDirection(a.GetBoneTransform(lo).position - a.GetBoneTransform(up).position);
            return Mathf.Atan2(d.z, -d.y) * Mathf.Rad2Deg;
        }

        static float Knee(Animator a, HumanBodyBones up, HumanBodyBones lo, HumanBodyBones ft)
        {
            var u = a.GetBoneTransform(up).position;
            var l = a.GetBoneTransform(lo).position;
            var f = a.GetBoneTransform(ft).position;
            return Vector3.Angle(l - u, f - l);
        }

        static string F(float v) => v.ToString("0.0000", Inv);

        static string Atelier(string file) => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "ArtSource", "atelier", file));

        /// <summary>
        /// Relève les objets autour des lieux où l'atelier construit des gestes : le bureau (repère du siège, chaise à
        /// sa place d'origine), le lit (repère de son assise), la fenêtre et la bibliothèque (repère du lieu debout :
        /// origine au sol, z vers le meuble). Une ligne par maillage (un objet à plusieurs pièces en donne plusieurs).
        /// </summary>
        [UnityEditor.MenuItem("Mika/Animation/Relever les lieux pour l'atelier (mode jeu)", priority = 45)]
        public static void SurveyPlaces()
        {
            if (!Application.isPlaying)
            {
                Debug.LogWarning("[Mika] relevé : lancer d'abord le mode jeu.");
                return;
            }
            var stage = AnimLab.Stage;
            var desk = stage.Place("desk");
            var chair = desk.Chair;
            if (chair != null) chair.Set(0f, 0f);
            var seat = desk.SeatTransform;
            Write("desk_layout.json", "repère du siège (Unity) : origine au sol sous les hanches, x à droite, y en haut, z devant ; chaise ni tournée ni roulée ; position et yaw du transform qui porte le maillage ; yaw en degrés (Unity, + vers la droite)",
                new Pose(new Vector3(seat.position.x, desk.Position.y, seat.position.z), Flat(seat.rotation)), seat.position.y - desk.Position.y, 2.2f);
            var bed = stage.Place("bed");
            var bedSeat = bed.SeatTransform;
            Write("bed_layout.json", "repère de l'assise du lit (Unity) : origine au sol sous les hanches, x à droite, y en haut, z devant",
                new Pose(new Vector3(bedSeat.position.x, bed.Position.y, bedSeat.position.z), Flat(bedSeat.rotation)), bedSeat.position.y - bed.Position.y, 2.5f);
            foreach (var (id, file) in new[] { ("window", "window_layout.json"), ("bookshelf", "shelf_layout.json") })
            {
                var place = stage.Place(id);
                Write(file, "repère du lieu (Unity) : origine au sol là où elle se tient, x à droite, y en haut, z devant elle",
                    new Pose(place.Position, Flat(place.Rotation)), 0f, 2.0f);
            }
            Debug.Log("[Mika] lieux relevés pour l'atelier (ArtSource/atelier/*_layout.json)");
        }

        static Quaternion Flat(Quaternion q)
        {
            var f = q * Vector3.forward;
            f.y = 0f;
            return Quaternion.LookRotation(f.sqrMagnitude > 1e-6f ? f.normalized : Vector3.forward, Vector3.up);
        }

        static void Write(string file, string note, Pose frame, float hips, float radius)
        {
            var inv = Quaternion.Inverse(frame.rotation);
            var sb = new StringBuilder();
            sb.Append("{\n  \"format\": \"mika.desk-layout/2\",\n");
            sb.Append($"  \"note\": \"{note}\",\n");
            sb.Append($"  \"seat_hips\": [0, {F(hips)}, 0],\n  \"objects\": [\n");
            var first = true;
            foreach (var o in Object.FindObjectsByType<WorldObject>(FindObjectsSortMode.InstanceID))
            {
                var model = o.GetComponentInChildren<MeshFilter>();
                foreach (var r in o.GetComponentsInChildren<Renderer>())
                {
                    var t = r.transform;
                    var p = inv * (t.position - frame.position);
                    if (new Vector2(p.x, p.z).magnitude > radius) continue;
                    var e = (inv * t.rotation).eulerAngles;
                    var tilt = Mathf.Max(Mathf.Abs(Mathf.DeltaAngle(e.x, 0)), Mathf.Abs(Mathf.DeltaAngle(e.z, 0)));
                    var s = t.lossyScale;
                    var part = model != null && t == model.transform ? "Modèle" : r.name;
                    if (!first) sb.Append(",\n");
                    first = false;
                    sb.Append($"    {{\"id\": \"{o.id}\", \"part\": \"{part}\", \"origin\": [{F(p.x)}, {F(p.y)}, {F(p.z)}], \"yaw\": {F(Mathf.DeltaAngle(0, e.y))}, \"tilt\": {F(tilt)}, \"scale\": [{F(s.x)}, {F(s.y)}, {F(s.z)}], \"skinned\": {(r is SkinnedMeshRenderer ? "true" : "false")}}}");
                }
            }
            sb.Append("\n  ]\n}\n");
            File.WriteAllText(Atelier(file), sb.ToString());
        }
    }
}
