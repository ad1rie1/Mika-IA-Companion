using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text.RegularExpressions;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Mika.Editor.Animation
{
    /// <summary>
    /// Les mouvements de l'atelier Blender (<c>frontend/Web/assets-src/blender/atelier_*.py</c>), adaptés sur le squelette
    /// de Mika, deviennent des clips humanoïdes : <c>frontend/Unity/ArtSource/atelier/motions/*.json.gz</c> →
    /// <c>Art/Animations/Atelier/*.anim</c>.
    /// </summary>
    /// <remarks>
    /// Pas de FBX : les repères d'os d'un FBX dépendent du logiciel qui l'écrit, et Unity calcule les muscles d'après
    /// eux. Le fichier donne, pour chaque os humanoïde, sa pose T et son orientation à chaque image (espace monde de
    /// Blender). On accorde les deux espaces une fois (haut, côté, avant mesurés sur la pose T des deux squelettes),
    /// on applique à chaque os d'une copie de Mika son changement d'orientation par rapport à la pose T, et
    /// <see cref="HumanPoseHandler"/> en tire les muscles avec son propre avatar : ce qui a été réglé dans Blender
    /// (un pied posé, une main sur le clavier) arrive tel quel.
    /// </remarks>
    public static class AtelierImporter
    {
        const string AvatarPrefab = "Assets/Mika/Art/Avatars/Mika.prefab";
        public const string Folder = "Assets/Mika/Art/Animations/Atelier";
        static string Source => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "ArtSource", "atelier", "motions"));

        [MenuItem("Mika/Animation/Importer les mouvements de l'atelier Blender", priority = 19)]
        public static void ImportAll()
        {
            if (!Directory.Exists(Source))
            {
                Debug.LogWarning($"[Mika] atelier : aucun mouvement dans {Source}.");
                return;
            }
            Directory.CreateDirectory(Folder);
            var n = 0;
            foreach (var file in Directory.GetFiles(Source, "*.json.gz").OrderBy(f => f))
            {
                Import(file);
                n++;
            }
            AssetDatabase.SaveAssets();
            Debug.Log($"[Mika] atelier : {n} mouvement(s) importé(s) dans {Folder}.");
        }

        /// <summary>Les clips de l'atelier déjà importés, par nom (walking, idle_breathing…).</summary>
        public static Dictionary<string, AnimationClip> Clips()
        {
            var clips = new Dictionary<string, AnimationClip>();
            if (!AssetDatabase.IsValidFolder(Folder)) return clips;
            foreach (var guid in AssetDatabase.FindAssets("t:AnimationClip", new[] { Folder }))
            {
                var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(AssetDatabase.GUIDToAssetPath(guid));
                if (clip != null) clips[clip.name] = clip;
            }
            return clips;
        }

        static AnimationClip Import(string file)
        {
            JObject data;
            using (var gz = new GZipStream(File.OpenRead(file), CompressionMode.Decompress))
            using (var reader = new StreamReader(gz))
                data = JObject.Parse(reader.ReadToEnd());
            var name = data["name"].Value<string>();
            var fps = data["fps"]?.Value<float>() ?? 30f;
            var loop = data["loop"]?.Value<bool>() ?? false;
            var travel = data["travel"]?.Value<bool>() ?? false;
            var names = data["bones"].Values<string>().ToList();
            var rest = (JObject)data["rest"];
            var frames = (JArray)data["frames"];

            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(AvatarPrefab);
            var go = Object.Instantiate(prefab);
            go.hideFlags = HideFlags.HideAndDontSave;
            go.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
            try
            {
                var animator = go.GetComponentInChildren<Animator>();
                var bones = new List<(Transform t, Quaternion restU, Quaternion restB)>();
                var byName = new Dictionary<string, Transform>();
                foreach (var h in names)
                {
                    if (!Enum.TryParse<HumanBodyBones>(char.ToUpperInvariant(h[0]) + h.Substring(1), out var hb)) continue;
                    var t = animator.GetBoneTransform(hb);
                    if (t == null) continue;
                    byName[h] = t;
                    bones.Add((t, t.rotation, Quat(rest[h]["q"])));
                }
                var space = Space.Between(rest, byName);
                var hips = byName["hips"];
                var shift = hips.position - space.Point(Vec(rest["hips"]["p"]));

                var handler = new HumanPoseHandler(animator.avatar, animator.transform);
                var pose = new HumanPose();
                var muscles = HumanTrait.MuscleName.Select(Property).ToArray();
                var curves = new Dictionary<string, AnimationCurve>();
                AnimationCurve Curve(string p) => curves.TryGetValue(p, out var c) ? c : curves[p] = new AnimationCurve();

                for (var i = 0; i < frames.Count; i++)
                {
                    var row = (JArray)frames[i];
                    hips.position = space.Point(new Vector3(row[0].Value<float>(), row[1].Value<float>(), row[2].Value<float>())) + shift;
                    var k = 3;
                    var j = 0;
                    foreach (var h in names)
                    {
                        var q = new Quaternion(row[k + 1].Value<float>(), row[k + 2].Value<float>(), row[k + 3].Value<float>(), row[k].Value<float>());
                        k += 4;
                        if (!byName.ContainsKey(h)) continue;
                        var (t, restU, restB) = bones[j++];
                        t.rotation = space.Rotation(q, restB) * restU;
                    }
                    handler.GetHumanPose(ref pose);
                    var time = i / fps;
                    Curve("RootT.x").AddKey(time, pose.bodyPosition.x);
                    Curve("RootT.y").AddKey(time, pose.bodyPosition.y);
                    Curve("RootT.z").AddKey(time, pose.bodyPosition.z);
                    Curve("RootQ.x").AddKey(time, pose.bodyRotation.x);
                    Curve("RootQ.y").AddKey(time, pose.bodyRotation.y);
                    Curve("RootQ.z").AddKey(time, pose.bodyRotation.z);
                    Curve("RootQ.w").AddKey(time, pose.bodyRotation.w);
                    for (var m = 0; m < muscles.Length; m++) Curve(muscles[m]).AddKey(time, pose.muscles[m]);
                }
                handler.Dispose();
                // Les courbes du geste (la chaise qu'il fait rouler, les mains sur le bureau, l'objet tenu) : des
                // paramètres de l'Animator du même nom, que le jeu lit pour déplacer l'objet avec le geste.
                if (data["curves"] is JObject extra)
                    foreach (var kv in extra)
                    {
                        var values = (JArray)kv.Value;
                        var curve = Curve(GestureCurvePrefix + kv.Key);
                        for (var i = 0; i < values.Count; i++) curve.AddKey(i / fps, values[i].Value<float>());
                    }
                return Save(name, curves, loop, travel, fps);
            }
            finally
            {
                Object.DestroyImmediate(go);
            }
        }

        /// <summary>Le nom de courbe d'un muscle (« Left Thumb 1 Stretched » → « LeftHand.Thumb.1 Stretched »).</summary>
        static string Property(string muscle)
        {
            var m = Regex.Match(muscle, "^(Left|Right) (Thumb|Index|Middle|Ring|Little) (.+)$");
            return m.Success ? $"{m.Groups[1].Value}Hand.{m.Groups[2].Value}.{m.Groups[3].Value}" : muscle;
        }

        static AnimationClip Save(string name, Dictionary<string, AnimationCurve> curves, bool loop, bool travel, float fps)
        {
            var path = $"{Folder}/{name}.anim";
            var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(path);
            if (clip == null)
            {
                clip = new AnimationClip { name = name };
                AssetDatabase.CreateAsset(clip, path);
            }
            clip.ClearCurves();
            clip.frameRate = fps;
            var before = 0;
            var after = 0;
            foreach (var kv in curves)
            {
                before += kv.Value.length;
                var reduced = Reduce(kv.Value, Tolerance(kv.Key));
                after += reduced.length;
                AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve("", typeof(Animator), kv.Key), reduced);
            }
            Debug.Log($"[Mika] atelier : « {name} », {after} clés gardées sur {before}.");
            var s = AnimationUtility.GetAnimationClipSettings(clip);
            s.loopTime = loop;
            s.loopBlend = loop;
            s.loopBlendOrientation = true;
            s.loopBlendPositionY = true;
            // En voyage (la marche), le déplacement reste au centre de masse : le corps le prend (mouvement de racine) ;
            // sur place, il est cuit dans la pose.
            s.loopBlendPositionXZ = !travel;
            s.keepOriginalOrientation = true;
            s.keepOriginalPositionY = true;
            s.keepOriginalPositionXZ = !travel;
            AnimationUtility.SetAnimationClipSettings(clip, s);
            EditorUtility.SetDirty(clip);
            Debug.Log($"[Mika] atelier : « {name} » ({clip.length:0.00} s, {(loop ? "boucle" : "une fois")}{(travel ? ", en voyage" : "")}).");
            return clip;
        }

        /// <summary>L'écart toléré par courbe : un muscle (≈ 0,1°), la position du corps (≈ 0,4 mm), son orientation, une courbe du geste.</summary>
        static float Tolerance(string property) => property.StartsWith("RootT") ? 0.0005f : property.StartsWith("RootQ") ? 0.0002f
            : property.StartsWith(GestureCurvePrefix) ? 0.002f : 0.0015f;

        /// <summary>
        /// Le préfixe des courbes du geste devenues paramètres de l'Animator (« GesteChairDrive ») : leur nom ne doit
        /// pas pouvoir se confondre avec un muscle ni avec un paramètre que le code règle lui-même.
        /// </summary>
        public const string GestureCurvePrefix = "Geste";

        /// <summary>
        /// Une courbe réduite (Ramer–Douglas–Peucker, segments linéaires) : une clé n'est gardée que si la retirer
        /// éloignerait la courbe de plus de <paramref name="epsilon"/> d'une image — même mouvement, fichier bien plus
        /// petit (un clip texte de 10 s pesait 15 Mo).
        /// </summary>
        static AnimationCurve Reduce(AnimationCurve curve, float epsilon)
        {
            var keys = curve.keys;
            var n = keys.Length;
            if (n <= 2) return curve;
            var keep = new bool[n];
            keep[0] = keep[n - 1] = true;
            var stack = new Stack<(int, int)>();
            stack.Push((0, n - 1));
            while (stack.Count > 0)
            {
                var (a, b) = stack.Pop();
                var worst = -1;
                var worstError = epsilon;
                for (var i = a + 1; i < b; i++)
                {
                    var t = (keys[i].time - keys[a].time) / (keys[b].time - keys[a].time);
                    var error = Mathf.Abs(keys[i].value - Mathf.Lerp(keys[a].value, keys[b].value, t));
                    if (error > worstError)
                    {
                        worstError = error;
                        worst = i;
                    }
                }
                if (worst < 0) continue;
                keep[worst] = true;
                stack.Push((a, worst));
                stack.Push((worst, b));
            }
            var result = new AnimationCurve(Enumerable.Range(0, n).Where(i => keep[i]).Select(i => new Keyframe(keys[i].time, keys[i].value)).ToArray());
            for (var i = 0; i < result.length; i++)
            {
                AnimationUtility.SetKeyLeftTangentMode(result, i, AnimationUtility.TangentMode.Linear);
                AnimationUtility.SetKeyRightTangentMode(result, i, AnimationUtility.TangentMode.Linear);
            }
            return result;
        }

        static Vector3 Vec(JToken a) => new Vector3(a[0].Value<float>(), a[1].Value<float>(), a[2].Value<float>());
        static Quaternion Quat(JToken a) => new Quaternion(a[1].Value<float>(), a[2].Value<float>(), a[3].Value<float>(), a[0].Value<float>());

        /// <summary>
        /// Le passage de l'espace monde de Blender à celui d'Unity (rotation, ou rotation et miroir) : trois directions
        /// mesurées sur la pose T des deux squelettes — le haut (hanches → tête), le côté (main droite → main gauche),
        /// l'avant (cheville → orteils) —, orthonormées dans le même ordre des deux côtés.
        /// </summary>
        readonly struct Space
        {
            readonly Vector3 _e1, _e2, _e3, _f1, _f2, _f3;

            Space(Vector3 e1, Vector3 e2, Vector3 e3, Vector3 f1, Vector3 f2, Vector3 f3)
            {
                _e1 = e1; _e2 = e2; _e3 = e3; _f1 = f1; _f2 = f2; _f3 = f3;
            }

            public static Space Between(JObject rest, Dictionary<string, Transform> unity)
            {
                Vector3 B(string h) => Vec(rest[h]["p"]);
                Vector3 U(string h) => unity[h].position;
                var (e1, e2, e3) = Frame(B("head") - B("hips"), B("leftHand") - B("rightHand"), B("leftToes") - B("leftFoot"));
                var (f1, f2, f3) = Frame(U("head") - U("hips"), U("leftHand") - U("rightHand"), U("leftToes") - U("leftFoot"));
                return new Space(e1, e2, e3, f1, f2, f3);
            }

            static (Vector3, Vector3, Vector3) Frame(Vector3 up, Vector3 side, Vector3 ahead)
            {
                var a = up.normalized;
                var b = (side - Vector3.Dot(side, a) * a).normalized;
                var c = (ahead - Vector3.Dot(ahead, a) * a - Vector3.Dot(ahead, b) * b).normalized;
                return (a, b, c);
            }

            /// <summary>Un point (ou une direction) de Blender, dans Unity.</summary>
            public Vector3 Point(Vector3 v) => _f1 * Vector3.Dot(_e1, v) + _f2 * Vector3.Dot(_e2, v) + _f3 * Vector3.Dot(_e3, v);

            Vector3 Back(Vector3 v) => _e1 * Vector3.Dot(_f1, v) + _e2 * Vector3.Dot(_f2, v) + _e3 * Vector3.Dot(_f3, v);

            /// <summary>
            /// Le changement d'orientation d'un os (orientation <paramref name="now"/>, repos <paramref name="rest"/>,
            /// quaternions de Blender), exprimé dans Unity. La formule de rotation est algébrique : les quaternions de
            /// Blender se calculent ici avec les vecteurs d'Unity sans conversion, le passage d'espace venant après.
            /// </summary>
            public Quaternion Rotation(Quaternion now, Quaternion rest)
            {
                var inv = new Quaternion(-rest.x, -rest.y, -rest.z, rest.w);
                Vector3 Delta(Vector3 v) => Rotate(now, Rotate(inv, v));
                var forward = Point(Delta(Back(Vector3.forward)));
                var up = Point(Delta(Back(Vector3.up)));
                return Quaternion.LookRotation(forward, up);
            }

            /// <summary>v tourné par q (convention de Blender : main droite), formule de Rodrigues sur les quaternions.</summary>
            static Vector3 Rotate(Quaternion q, Vector3 v)
            {
                var u = new Vector3(q.x, q.y, q.z);
                var t = 2f * Cross(u, v);
                return v + q.w * t + Cross(u, t);
            }

            static Vector3 Cross(Vector3 a, Vector3 b) => new Vector3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x);
        }
    }
}
