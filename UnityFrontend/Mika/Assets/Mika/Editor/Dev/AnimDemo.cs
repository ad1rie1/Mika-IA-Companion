using System.Collections;
using System.Collections.Generic;
using Mika.UI;
using Mika.World.Engine;
using Mika.World.Protocol;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering.Universal;
using Object = UnityEngine.Object;

namespace Mika.Editor.Dev
{
    /// <summary>
    /// Une visite guidée des animations du corps, en mode jeu, dans la fenêtre Game : le corps d'essai du labo
    /// (<see cref="AnimLab"/>) enchaîne marche, chaise, tout le bureau (clavier, souris, réfléchir, boire, prendre son
    /// stylo, s'étirer, pivoter vers la personne qui parle, écrire, lire), lit, couette, fenêtre et bibliothèque, filmé par une caméra de démo qui passe devant celle de la joueuse, une légende par étape.
    /// La vraie Mika est masquée le temps de la visite et rendue à la fin.
    /// </summary>
    public static class AnimDemo
    {
        static Camera _cam;
        static Vector3 _eye, _at, _eyeVel, _atVel;
        static System.Func<(Vector3 eye, Vector3 at)> _follow;
        static bool _running;

        [MenuItem("Mika/Animation/Démo des animations (mode jeu)", priority = 40)]
        public static void Start()
        {
            if (!Application.isPlaying)
            {
                Debug.LogWarning("[Mika] démo : lancer d'abord le mode jeu.");
                return;
            }
            if (_running && _cam != null) return;
            ResetState();
            _running = true;
            AnimLab.Run(Tour(AnimLab.Body));
        }

        /// <summary>
        /// L'état de la démo remis à zéro. Le projet entre en mode jeu sans recharger les scripts (Enter Play Mode
        /// Options) : les statiques survivent d'une session à l'autre, et la boucle de caméra rappelait le plan de suivi
        /// de la démo précédente, sur un corps détruit — elle s'arrêtait sur l'exception, la caméra figée à l'origine.
        /// </summary>
        [InitializeOnEnterPlayMode]
        static void ResetState()
        {
            _running = false;
            _cam = null;
            _follow = null;
            _eye = _at = _eyeVel = _atVel = _targetEye = _targetAt = Vector3.zero;
            _room = null;
        }

        [MenuItem("Mika/Animation/Arrêter la démo", priority = 41)]
        public static void Stop()
        {
            _running = false;
            if (_cam != null) Object.Destroy(_cam.gameObject);
            _cam = null;
            AnimLab.Clear();
        }

        // --- la caméra -----------------------------------------------------------------------------------------
        static void MakeCamera()
        {
            if (_cam != null) return;
            var go = new GameObject("Caméra de démo");
            _cam = go.AddComponent<Camera>();
            _cam.depth = 100;
            _cam.fieldOfView = 50f;
            _cam.nearClipPlane = 0.03f;
            var urp = go.AddComponent<UniversalAdditionalCameraData>();
            urp.renderPostProcessing = true;
            urp.antialiasing = AntialiasingMode.SubpixelMorphologicalAntiAliasing;
        }

        /// <summary>Un plan fixe (<paramref name="cut"/> : sans glissement depuis le précédent).</summary>
        static void Shot(Vector3 eye, Vector3 at, bool cut = false)
        {
            _follow = null;
            Aim(eye, at, cut);
        }

        /// <summary>Un plan qui suit le corps (de côté, à hauteur d'épaule).</summary>
        /// <summary>
        /// Un plan qui l'accompagne pendant qu'elle marche de <paramref name="from"/> à <paramref name="to"/> : de côté
        /// par rapport au trajet (pas par rapport à son corps — quand elle tournait, la caméra balayait à travers
        /// elle), du côté où la pièce laisse le plus de place, un peu en avant d'elle.
        /// </summary>
        static void Follow(ActorBody b, Vector3 from, Vector3 to, float side, float front, float up)
        {
            var dir = to - from;
            dir.y = 0f;
            var basis = Quaternion.LookRotation(dir.sqrMagnitude > 1e-4f ? dir.normalized : b.transform.forward, Vector3.up);
            var mid = (from + to) * 0.5f;
            var room = RoomBounds();
            if (room.HasValue)
            {
                var c = room.Value.center;
                var right = basis * Vector3.right;
                if (Vector3.Dot(new Vector3(c.x - mid.x, 0f, c.z - mid.z), right) < 0f) side = -side;
            }
            _follow = () =>
            {
                var chest = b.animator.GetBoneTransform(HumanBodyBones.Chest);
                var at = chest != null ? chest.position : b.transform.position + Vector3.up;
                return (at + basis * new Vector3(side, up, front), at);
            };
        }

        static Bounds? _room;

        /// <summary>L'intérieur de la pièce (le sol, sur toute la hauteur), pour y garder la caméra.</summary>
        static Bounds? RoomBounds()
        {
            if (_room.HasValue) return _room;
            foreach (var r in Object.FindObjectsByType<MeshRenderer>(FindObjectsInactive.Exclude))
                if (r.name.Contains("room_floor") || (r.transform.parent != null && r.transform.parent.name.Contains("room_floor")))
                {
                    var b = r.bounds;
                    _room = new Bounds(new Vector3(b.center.x, 1.4f, b.center.z), new Vector3(b.size.x, 2.8f, b.size.z));
                    break;
                }
            return _room;
        }

        static Vector3 InsideRoom(Vector3 p)
        {
            var room = RoomBounds();
            if (!room.HasValue) return p;
            var b = room.Value;
            const float margin = 0.25f;
            return new Vector3(Mathf.Clamp(p.x, b.min.x + margin, b.max.x - margin), Mathf.Clamp(p.y, 0.3f, b.max.y - margin),
                Mathf.Clamp(p.z, b.min.z + margin, b.max.z - margin));
        }

        /// <summary>
        /// Un plan attaché au siège (qui tourne et roule avec la chaise) : œil et cible dans son repère (x à droite,
        /// y en haut, z devant).
        /// </summary>
        static void SeatShot(ActorBody b, Vector3 eye, Vector3 at, bool cut = false)
        {
            _follow = () =>
            {
                var s = b.Anchor ?? new Pose(b.transform.position, b.transform.rotation);
                var f = s.rotation * Vector3.forward;
                f.y = 0f;
                var q = Quaternion.LookRotation(f.sqrMagnitude > 1e-4f ? f.normalized : Vector3.forward, Vector3.up);
                var floor = new Vector3(s.position.x, b.FloorY, s.position.z);
                return (floor + q * eye, floor + q * at);
            };
            if (cut)
            {
                var (e, a) = _follow();
                Aim(e, a, true);
            }
        }

        static void Aim(Vector3 eye, Vector3 at, bool cut)
        {
            if (cut || _eye == Vector3.zero)
            {
                _eye = eye;
                _at = at;
                _eyeVel = _atVel = Vector3.zero;
            }
            _targetEye = eye;
            _targetAt = at;
        }

        static Vector3 _targetEye, _targetAt;

        static IEnumerator Drive()
        {
            while (_running && _cam != null)
            {
                if (_follow != null)
                {
                    // Un plan dont la cible a disparu ne doit pas arrêter la caméra : on garde le dernier cadrage.
                    try
                    {
                        var (e, a) = _follow();
                        _targetEye = e;
                        _targetAt = a;
                    }
                    catch (System.Exception ex)
                    {
                        Debug.LogWarning("[démo] plan de suivi abandonné : " + ex.Message);
                        _follow = null;
                    }
                }
                _eye = Vector3.SmoothDamp(_eye, InsideRoom(_targetEye), ref _eyeVel, 0.8f);
                _at = Vector3.SmoothDamp(_at, _targetAt, ref _atVel, 0.5f);
                var look = _at - _eye;
                if (look.sqrMagnitude > 1e-6f)
                    _cam.transform.SetPositionAndRotation(_eye, Quaternion.LookRotation(look, Vector3.up));
                yield return null;
            }
        }

        static void Say(string text)
        {
            var hud = Object.FindAnyObjectByType<WorldHud>();
            if (hud != null) hud.Toast(text);
            Debug.Log("[démo] " + text);
        }

        static IEnumerator Wait(float s)
        {
            for (var t = 0f; t < s && _running; t += Time.deltaTime) yield return null;
        }

        // --- la visite -----------------------------------------------------------------------------------------
        static IEnumerator Tour(ActorBody b)
        {
            MakeCamera();
            _eye = Vector3.zero;
            _follow = null;
            var stage = AnimLab.Stage;
            var act = b.GetComponent<BodyActivity>();
            act.turnEvery = new Vector2(1000f, 1000f);
            act.companion = _cam.transform;
            b.SetAsleep(false);
            var center = stage.Place("center");
            var desk = stage.Place("desk");
            var bed = stage.Place("bed");
            var window = stage.Place("window");
            var shelf = stage.Place("bookshelf");
            var duvet = bed != null && bed.Furniture != null ? bed.Furniture.GetComponentInChildren<DuvetRig>() : null;
            if (duvet != null) duvet.SetState(DuvetState.Made, 0f);

            b.Snap(center.Position, center.Rotation, Posture.Stand);
            Shot(center.Position + new Vector3(1.6f, 1.4f, 1.8f), center.Position + Vector3.up * 0.9f, cut: true);
            // La caméra ne part qu'une fois le premier plan posé.
            b.StartCoroutine(Drive());
            Say("Démo des animations — le corps de Mika, sans le noyau");
            yield return Wait(3f);

            // 1. La marche capturée
            Say("Marche : capture de mouvement réelle (CMU), lente ou normale selon la vitesse");
            Follow(b, center.Position, desk.Position, 1.8f, 0.6f, 0.25f);
            yield return b.WalkTo(desk.Position, desk.Rotation, Vector3.Distance(center.Position, desk.Position) / 0.85f);

            // 2. S'asseoir au bureau
            Say("S'asseoir : un pas devant la chaise, laissée à sa place, et elle s'assoit (capture)");
            Shot(new Vector3(2.75f, 1.05f, -2.95f), new Vector3(1.3f, 0.65f, -3.35f));
            yield return b.ChangePosture(Posture.Sit, desk, 1f);
            Say("Assise : la chaise réglée pour elle, les talons un peu levés, les pieds entre les branches du piètement");
            Shot(new Vector3(1.9f, 0.55f, -2.55f), new Vector3(1.4f, 0.35f, -3.35f));
            yield return Wait(4f);

            // 3. Le travail : clavier et souris (la chaise pivote et roule pour lui présenter le clavier)
            Say("Travailler : ses pieds font rouler la chaise, puis ses mains sur le bord du bureau l'amènent au clavier");
            act.Set("work", null);
            SeatShot(b, new Vector3(0.95f, 1.15f, 0.9f), new Vector3(0.05f, 0.75f, 0.35f), cut: true);
            yield return Wait(4.5f);
            Say("Elle tape par rafales");
            yield return Wait(4f);
            Say("… et passe de temps en temps à la souris (main droite)");
            SeatShot(b, new Vector3(0.75f, 1.3f, 0.75f), new Vector3(0.15f, 0.75f, 0.4f));
            yield return Wait(9f);

            // 4. Au repos : les petits gestes (d'ordinaire tirés au hasard, ici à la suite)
            act.Set(null, null);
            Say("Au repos : réfléchir, le menton sur le poing");
            // De face, côté souris : la lampe de bureau, à sa gauche, masquerait les gestes de la main gauche.
            SeatShot(b, new Vector3(0.9f, 1.25f, 0.95f), new Vector3(-0.05f, 0.95f, 0.2f));
            yield return Wait(2.5f);
            act.PlayDeskGesture("think");
            yield return Wait(5f);
            Say("Boire une gorgée : la tasse prise par l'anse, de la main gauche, et reposée à sa place");
            act.PlayDeskGesture("drink");
            yield return Wait(6f);
            Say("Prendre son stylo sur le carnet, le regarder, le reposer où il était");
            act.PlayDeskGesture("take");
            yield return Wait(6f);
            Say("S'étirer sur sa chaise");
            SeatShot(b, new Vector3(1.05f, 1.35f, 1.15f), new Vector3(0f, 1.05f, 0.1f));
            act.PlayDeskGesture("stretch");
            yield return Wait(5f);

            // 5. On lui parle
            Say("On lui parle : ses pieds poussent le sol et font pivoter sa chaise vers toi");
            Shot(new Vector3(0.55f, 1.4f, -1.85f), new Vector3(1.3f, 0.8f, -3.3f), cut: true);
            yield return Wait(1.2f);
            act.Engage(9f);
            yield return Wait(10f);
            Say("La conversation finie, elle se retourne vers son bureau");
            yield return Wait(6f);

            // 6. Écrire
            Say("Écrire : elle fait pivoter sa chaise vers le carnet, prend le stylo posé dessus");
            act.Set("draw", null);
            // Par-dessus son épaule droite : de face à gauche, le bras de la lampe passait au premier plan ; de face à
            // droite, la chaise tournée vers le carnet, l'écran bouchait tout.
            SeatShot(b, new Vector3(0.55f, 1.55f, -0.25f), new Vector3(0f, 0.75f, 0.4f), cut: true);
            yield return Wait(13f);
            act.Set(null, null);
            Say("En fin de ligne, elle repose le stylo sur le carnet et se tourne vers le clavier");
            yield return Wait(10f);

            // 6 bis. Lire
            WorldObject book = null;
            foreach (var o in Object.FindObjectsByType<WorldObject>(FindObjectsInactive.Exclude))
                if (o.id == "book_desk_2") book = o;
            var bookPos = book != null ? book.transform.position : Vector3.zero;
            var bookRot = book != null ? book.transform.rotation : Quaternion.identity;
            if (book != null)
            {
                // Le livre est au bout du bureau, hors de portée assise : on le lui met dans les mains (plan coupé).
                b.Hold(book, Hand.Right);
                act.Set("read", book.id);
                Say("Lire : le livre tenu à deux mains, une page tournée de temps en temps");
                SeatShot(b, new Vector3(0.9f, 1.15f, 0.9f), new Vector3(0f, 0.85f, 0.25f), cut: true);
                yield return Wait(10f);
                act.Set(null, null);
                yield return Wait(0.5f);
                b.Release(book);
                book.transform.SetPositionAndRotation(bookPos, bookRot);
            }

            // 7. Le lit
            Say("Se lever : elle repousse la chaise des mains et des pieds, se redresse et s'écarte");
            Shot(new Vector3(2.75f, 1.05f, -2.95f), new Vector3(1.2f, 0.7f, -3.3f));
            yield return b.ChangePosture(Posture.Stand, desk, 1f);
            Follow(b, desk.Position, bed.Position, 1.8f, 0.6f, 0.25f);
            yield return b.WalkTo(bed.Position, bed.Rotation, Vector3.Distance(desk.Position, bed.Position) / 0.85f);
            Say("Le soir : elle s'assoit au bord du lit, s'allonge en se glissant dessous…");
            Shot(new Vector3(1.75f, 1.5f, 0.15f), new Vector3(3.2f, 0.55f, 1.45f));
            b.SetAsleep(true);
            yield return b.ChangePosture(Posture.Lie, bed, 2f);
            Say("… et tire la couette jusqu'aux épaules (couette simulée dans Blender sur son corps)");
            yield return Wait(4f);
            Shot(new Vector3(2.2f, 1.25f, 2.35f), new Vector3(3.3f, 0.55f, 1.6f));
            yield return Wait(3f);
            Say("Endormie, elle se retourne : sur le côté gauche…");
            b.SetLieSide(1);
            yield return Wait(5f);
            Say("… puis sur le côté droit — la couette roule avec elle");
            b.SetLieSide(2);
            yield return Wait(6f);
            Say("Le matin : elle repousse la couette, se redresse et se lève");
            Shot(new Vector3(1.75f, 1.5f, 0.15f), new Vector3(3.0f, 0.6f, 1.4f));
            b.SetAsleep(false);
            yield return b.ChangePosture(Posture.Stand, bed, 2f);
            yield return Wait(1f);

            // 8. Debout
            Say("À la fenêtre : les mains sur le rebord, le regard qui flâne dehors");
            Follow(b, bed.Position, window.Position, 1.6f, 0.4f, 0.3f);
            yield return b.WalkTo(window.Position, window.Rotation, Vector3.Distance(bed.Position, window.Position) / 0.85f);
            act.Set("look_outside", null);
            var wf = window.Rotation * Vector3.forward;
            var wr = window.Rotation * Vector3.right;
            Shot(window.Position - wf * 1.5f + wr * 1.0f + Vector3.up * 1.45f, window.Position + wf * 0.3f + Vector3.up * 1.0f);
            yield return Wait(7f);
            act.Set(null, null);
            Say("À la bibliothèque : elle parcourt les rayons et effleure les livres");
            Follow(b, window.Position, shelf.Position, 1.6f, 0.4f, 0.3f);
            yield return b.WalkTo(shelf.Position, shelf.Rotation, Vector3.Distance(window.Position, shelf.Position) / 0.85f);
            act.Set("browse_books", null);
            var sf = shelf.Rotation * Vector3.forward;
            var sr = shelf.Rotation * Vector3.right;
            Shot(shelf.Position - sf * 1.4f + sr * 1.1f + Vector3.up * 1.45f, shelf.Position + sf * 0.4f + Vector3.up * 1.1f);
            yield return Wait(9f);
            act.Set(null, null);
            Say("Fin de la démo — la vraie Mika reprend sa place");
            yield return Wait(3f);
            Stop();
        }
    }
}
