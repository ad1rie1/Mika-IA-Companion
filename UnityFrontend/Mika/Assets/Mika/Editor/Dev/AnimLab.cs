using System;
using System.Collections;
using System.IO;
using Mika.World.Engine;
using UnityEngine;
using UnityEngine.Rendering.Universal;
using Object = UnityEngine.Object;

namespace Mika.Editor.Dev
{
    /// <summary>
    /// Banc d'essai des animations, en mode jeu : un corps de Mika monté comme celui du monde mais que le noyau ne
    /// pilote pas (la vraie Mika est masquée le temps des essais), et des rafales d'images prises à cadence fixe
    /// — le temps du jeu avance d'exactement 1/30 s par image, quelle que soit la lenteur du rendu, si bien
    /// qu'une rafale montre l'animation telle qu'elle se joue. Les images vont dans <c>Temp/lab/&lt;nom&gt;/</c>.
    /// </summary>
    public static class AnimLab
    {
        public const string BodyId = "lab";
        static ActorBody _body;
        static Camera _camera;

        public static string Folder(string name) => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "Temp", "lab", name));

        public static WorldStage Stage => Object.FindAnyObjectByType<WorldStage>();

        /// <summary>Le corps d'essai (créé au premier appel), la vraie Mika masquée.</summary>
        public static ActorBody Body
        {
            get
            {
                if (_body != null) return _body;
                if (!Application.isPlaying) throw new InvalidOperationException("AnimLab : en mode jeu seulement.");
                var stage = Stage;
                _body = stage.SpawnUnlisted(BodyId, "avatars/mika", "Labo");
                ShowReal(false);
                return _body;
            }
        }

        /// <summary>Masque (ou remontre) la Mika du monde, pour qu'elle ne se mêle pas aux images.</summary>
        public static void ShowReal(bool visible)
        {
            var real = Stage != null ? Stage.Actor("mika") : null;
            if (real == null) return;
            foreach (var r in real.GetComponentsInChildren<Renderer>(true)) r.enabled = visible;
            // Son occupation aussi : couchée dans le lit, elle tiendrait la couette sur elle pendant nos essais.
            if (real.TryGetComponent<BodyActivity>(out var activity)) activity.enabled = visible;
        }

        /// <summary>Retire le corps d'essai et rend la vraie Mika.</summary>
        public static void Clear()
        {
            if (_body != null) Object.Destroy(_body.gameObject);
            _body = null;
            ShowReal(true);
        }

        /// <summary>Lance un scénario sur le corps d'essai (une coroutine).</summary>
        public static Coroutine Run(IEnumerator scenario) => Body.StartCoroutine(scenario);

        /// <summary>
        /// Une rafale : <paramref name="frames"/> images, une toutes les <paramref name="every"/> images de jeu
        /// (à 30 images/s : every = 2 → une image toutes les 66 ms). <paramref name="view"/> donne, à chaque prise,
        /// la position de la caméra et le point visé.
        /// </summary>
        public static IEnumerator Burst(string name, int frames, int every, Func<(Vector3 eye, Vector3 at)> view, int width = 400, int height = 300, float fov = 50f)
        {
            var dir = Folder(name);
            if (Directory.Exists(dir))
                foreach (var f in Directory.GetFiles(dir, "*.png"))
                    File.Delete(f);
            Directory.CreateDirectory(dir);
            var previous = Time.captureFramerate;
            Time.captureFramerate = 30;
            var log = new System.Text.StringBuilder();
            try
            {
                for (var i = 0; i < frames; i++)
                {
                    yield return new WaitForEndOfFrame();
                    var (eye, at) = view();
                    Shoot(Path.Combine(dir, $"{i:000}.png"), eye, at, width, height, fov);
                    log.AppendLine($"{i:000} t={Time.time:0.000} {Describe(_body)}");
                    // Après la fin d'une image, chaque « null » reprend dans l'image suivante : every images d'écart.
                    for (var k = 0; k < every; k++) yield return null;
                }
            }
            finally
            {
                Time.captureFramerate = previous;
                File.WriteAllText(Path.Combine(dir, "frames.txt"), log.ToString());
            }
        }

        /// <summary>Une caméra qui suit le corps : de côté (<paramref name="side"/>), devant, en hauteur, visant un os.</summary>
        public static Func<(Vector3, Vector3)> Follow(ActorBody body, float side, float front, float up, HumanBodyBones target = HumanBodyBones.Hips, float lift = 0f)
        {
            return () =>
            {
                var t = body.transform;
                var bone = body.animator != null ? body.animator.GetBoneTransform(target) : null;
                var at = (bone != null ? bone.position : t.position + Vector3.up) + Vector3.up * lift;
                var basis = Quaternion.Euler(0, t.eulerAngles.y, 0);
                var eye = at + basis * new Vector3(side, up, front);
                return (eye, at);
            };
        }

        /// <summary>
        /// Le corps d'essai tel qu'il est à cet instant (peau, vêtements, cheveux), en un seul OBJ en coordonnées
        /// Blender de la chambre : Unity (x, y, z) → glTF (−x, y, z) → Blender (−x, −z, y). Sert de collision aux
        /// simulations de tissu (la couette qui retombe sur elle).
        /// </summary>
        public static string ExportPose(string name)
        {
            var dir = Folder("poses");
            Directory.CreateDirectory(dir);
            var path = Path.Combine(dir, name + ".obj");
            var sb = new System.Text.StringBuilder();
            sb.AppendLine("# Mika, pose " + name + " (coordonnées Blender de la chambre)");
            var offset = 1;
            var baked = new Mesh();
            foreach (var smr in Body.GetComponentsInChildren<SkinnedMeshRenderer>())
            {
                if (!smr.enabled || smr.sharedMesh == null) continue;
                smr.BakeMesh(baked, false);
                var t = smr.transform;
                var verts = baked.vertices;
                sb.AppendLine("o " + smr.name);
                foreach (var v in verts)
                {
                    var w = t.localToWorldMatrix.MultiplyPoint3x4(v);
                    sb.Append("v ").Append((-w.x).ToString("0.####", System.Globalization.CultureInfo.InvariantCulture)).Append(' ')
                      .Append((-w.z).ToString("0.####", System.Globalization.CultureInfo.InvariantCulture)).Append(' ')
                      .Append(w.y.ToString("0.####", System.Globalization.CultureInfo.InvariantCulture)).AppendLine();
                }
                // Le changement de repère (−x) inverse l'orientation : on retourne l'ordre des sommets.
                for (var sm = 0; sm < baked.subMeshCount; sm++)
                {
                    var tris = baked.GetTriangles(sm);
                    for (var i = 0; i < tris.Length; i += 3)
                        sb.Append("f ").Append(tris[i] + offset).Append(' ').Append(tris[i + 2] + offset).Append(' ').Append(tris[i + 1] + offset).AppendLine();
                }
                offset += verts.Length;
            }
            Object.Destroy(baked);
            File.WriteAllText(path, sb.ToString());
            return path;
        }

        static Light _light;

        /// <summary>Une lampe d'appoint près de la caméra (la chambre est sombre la nuit) ; false l'éteint.</summary>
        public static void Lamp(bool on, float intensity = 2.5f)
        {
            if (_light == null)
            {
                var go = new GameObject("__AnimLabLamp") { hideFlags = HideFlags.HideAndDontSave };
                _light = go.AddComponent<Light>();
                _light.type = LightType.Point;
                _light.range = 8f;
                _light.shadows = LightShadows.Soft;
            }
            _light.intensity = intensity;
            _light.enabled = on;
        }

        /// <summary>Une caméra fixe.</summary>
        public static Func<(Vector3, Vector3)> Fixed(Vector3 eye, Vector3 at) => () => (eye, at);

        static string Describe(ActorBody b)
        {
            if (b == null || b.animator == null) return "";
            var a = b.animator;
            var y = b.FloorY;
            float H(HumanBodyBones bone) => a.GetBoneTransform(bone) is { } t ? t.position.y - y : float.NaN;
            var st = a.GetCurrentAnimatorStateInfo(0);
            var act = b.GetComponent<BodyActivity>();
            var hips = a.GetBoneTransform(HumanBodyBones.Hips);
            var neck = a.GetBoneTransform(HumanBodyBones.Neck);
            var torso = hips != null && neck != null ? Vector3.Angle(neck.position - hips.position, Vector3.up) : float.NaN;
            var clips = "";
            foreach (var ci in a.GetCurrentAnimatorClipInfo(0)) clips += $"{ci.clip.name}:{ci.weight:0.0} ";
            foreach (var ci in a.GetNextAnimatorClipInfo(0)) clips += $"→{ci.clip.name}:{ci.weight:0.0} ";
            return $"posture={b.Posture} seated={b.Seatedness:0.00} hips={H(HumanBodyBones.Hips):0.00} torso={torso:0}° feet={H(HumanBodyBones.LeftFoot):0.00}/{H(HumanBodyBones.RightFoot):0.00} " +
                   $"hands={H(HumanBodyBones.LeftHand):0.00}/{H(HumanBodyBones.RightHand):0.00} state={st.normalizedTime:0.00} trans={a.IsInTransition(0)} mode={(act != null ? act.ModeName : "-")} {clips}";
        }

        static void Shoot(string path, Vector3 eye, Vector3 at, int width, int height, float fov)
        {
            if (_camera == null)
            {
                var go = new GameObject("__AnimLabCamera") { hideFlags = HideFlags.HideAndDontSave };
                _camera = go.AddComponent<Camera>();
                _camera.enabled = false;
                _camera.nearClipPlane = 0.02f;
                var urp = go.AddComponent<UniversalAdditionalCameraData>();
                urp.renderPostProcessing = true;
                urp.antialiasing = AntialiasingMode.SubpixelMorphologicalAntiAliasing;
            }
            _camera.fieldOfView = fov;
            _camera.transform.SetPositionAndRotation(eye, Quaternion.LookRotation(at - eye, Vector3.up));
            if (_light != null && _light.enabled) _light.transform.position = eye + Vector3.up * 0.4f + (at - eye).normalized * 0.3f;
            var rt = RenderTexture.GetTemporary(width, height, 24, RenderTextureFormat.ARGB32);
            _camera.targetTexture = rt;
            _camera.Render();
            var active = RenderTexture.active;
            RenderTexture.active = rt;
            var tex = new Texture2D(width, height, TextureFormat.RGB24, false);
            tex.ReadPixels(new Rect(0, 0, width, height), 0, 0);
            tex.Apply();
            RenderTexture.active = active;
            _camera.targetTexture = null;
            RenderTexture.ReleaseTemporary(rt);
            File.WriteAllBytes(path, tex.EncodeToPNG());
            Object.Destroy(tex);
        }
    }
}
