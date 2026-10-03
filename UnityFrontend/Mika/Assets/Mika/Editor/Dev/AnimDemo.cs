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
    /// (<see cref="AnimLab"/>) enchaîne marche, chaise, clavier, carnet, livre, lit, couette, fenêtre et
    /// bibliothèque, filmé par une caméra de démo qui passe devant celle de la joueuse, une légende par étape.
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
            // Une démo interrompue par l'arrêt du jeu laisse _running levé, mais sa caméra a disparu.
            if (_running && _cam != null) return;
            _running = true;
            AnimLab.Run(Tour(AnimLab.Body));
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
        static void Follow(ActorBody b, float side, float front, float up)
        {
            _follow = () =>
            {
                var t = b.transform;
                var chest = b.animator.GetBoneTransform(HumanBodyBones.Chest);
                var at = chest != null ? chest.position : t.position + Vector3.up;
                var basis = Quaternion.Euler(0, t.eulerAngles.y, 0);
                return (at + basis * new Vector3(side, up, front), at);
            };
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
                    var (e, a) = _follow();
                    _targetEye = e;
                    _targetAt = a;
                }
                _eye = Vector3.SmoothDamp(_eye, _targetEye, ref _eyeVel, 0.8f);
                _at = Vector3.SmoothDamp(_at, _targetAt, ref _atVel, 0.5f);
                _cam.transform.SetPositionAndRotation(_eye, Quaternion.LookRotation(_at - _eye, Vector3.up));
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
            b.StartCoroutine(Drive());
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
            Say("Démo des animations — le corps de Mika, sans le noyau");
            yield return Wait(3f);

            // 1. La marche capturée
            Say("Marche : capture de mouvement réelle (CMU), lente ou normale selon la vitesse");
            Follow(b, 1.8f, 0.6f, 0.25f);
            yield return b.WalkTo(desk.Position, desk.Rotation, Vector3.Distance(center.Position, desk.Position) / 0.85f);

            // 2. S'asseoir au bureau
            Say("S'asseoir : elle recule la chaise, fait un pas devant, s'assoit (capture), puis roule au bureau");
            Shot(new Vector3(2.75f, 1.05f, -2.95f), new Vector3(1.3f, 0.65f, -3.35f));
            yield return b.ChangePosture(Posture.Sit, desk, 1f);
            Say("Pieds à plat au sol en IK : la chaise est haute pour elle");
            Shot(new Vector3(1.9f, 0.55f, -2.55f), new Vector3(1.4f, 0.35f, -3.35f));
            yield return Wait(4f);

            // 3. Taper
            Say("Travailler : elle tape par rafales, va à la souris, regarde l'écran");
            act.Set("work", null);
            Shot(new Vector3(2.6f, 1.5f, -2.6f), new Vector3(1.35f, 0.75f, -3.6f));
            yield return Wait(4f);
            Shot(new Vector3(2.15f, 1.25f, -3.05f), new Vector3(1.4f, 0.82f, -3.65f));
            yield return Wait(6f);

            // 4. On lui parle
            Say("On lui parle : elle recule et fait pivoter sa chaise vers toi");
            Shot(new Vector3(0.55f, 1.4f, -1.85f), new Vector3(1.3f, 0.8f, -3.3f));
            yield return Wait(1.2f);
            act.Engage(9f);
            yield return Wait(10f);

            // 5. Écrire
            Say("Écrire : elle ramène son carnet et tourne un peu la chaise vers lui");
            act.Set("draw", null);
            Shot(new Vector3(0.6f, 1.35f, -2.95f), new Vector3(1.5f, 0.8f, -3.6f));
            yield return Wait(8f);
            act.Set(null, null);
            yield return Wait(1.5f);

            // 6. Lire
            WorldObject book = null;
            foreach (var o in Object.FindObjectsByType<WorldObject>(FindObjectsInactive.Exclude))
                if (o.id == "book_desk_1") book = o;
            var bookPos = book != null ? book.transform.position : Vector3.zero;
            var bookRot = book != null ? book.transform.rotation : Quaternion.identity;
            if (book != null)
            {
                Say("Lire : elle prend un livre et le tient à deux mains, tourne les pages");
                Shot(new Vector3(2.2f, 1.3f, -2.85f), new Vector3(1.4f, 0.85f, -3.5f));
                yield return b.Reach(book.GripPoint, 1.2f, () => b.Hold(book, Hand.Right));
                act.Set("read", book.id);
                yield return Wait(8f);
                act.Set(null, null);
                yield return Wait(0.5f);
                b.Release(book);
                book.transform.SetPositionAndRotation(bookPos, bookRot);
            }

            // 7. Le lit
            Say("Se lever : la chaise recule avec elle, elle se redresse et s'écarte");
            Shot(new Vector3(2.75f, 1.05f, -2.95f), new Vector3(1.2f, 0.7f, -3.3f));
            yield return b.ChangePosture(Posture.Stand, desk, 1f);
            Follow(b, 1.8f, 0.6f, 0.25f);
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
            Follow(b, 1.6f, 0.4f, 0.3f);
            yield return b.WalkTo(window.Position, window.Rotation, Vector3.Distance(bed.Position, window.Position) / 0.85f);
            act.Set("look_outside", null);
            var wf = window.Rotation * Vector3.forward;
            var wr = window.Rotation * Vector3.right;
            Shot(window.Position - wf * 1.5f + wr * 1.0f + Vector3.up * 1.45f, window.Position + wf * 0.3f + Vector3.up * 1.0f);
            yield return Wait(7f);
            act.Set(null, null);
            Say("À la bibliothèque : elle parcourt les rayons et effleure les livres");
            Follow(b, 1.6f, 0.4f, 0.3f);
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
