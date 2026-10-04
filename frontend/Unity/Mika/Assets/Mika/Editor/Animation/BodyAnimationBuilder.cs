using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Mika.World.Engine;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace Mika.Editor.Animation
{
    /// <summary>
    /// Les animations du corps de Mika, et le contrôleur qui les joue selon le contrat <see cref="BodyAnim"/> :
    /// <list type="bullet">
    /// <item>les clips Mixamo du client web (attentes, paroles, gestes) et les clips de motion capture réelle
    /// (base CMU, préparés par <c>frontend/Web/assets-src/blender/mocap_unity.py</c> dans <c>frontend/Unity/ArtSource/mocap</c> :
    /// marche, s'asseoir, assise, se lever, allongée…), importés en humanoïde — Mecanim les retarget sur
    /// n'importe quel avatar ;</item>
    /// <item>à défaut, des clips générés en muscles humanoïdes à partir de sa vraie pose de repos ;</item>
    /// <item>un calque additif de « vie » (souffle, micro-mouvements) pour qu'aucune pose ne soit figée ;</item>
    /// <item>la description de ce qui a été construit (<see cref="BodyClipSet"/>) que lit <see cref="BodyExpression"/>.</item>
    /// </list>
    /// Un clip déposé plus tard (motion capture, Mixamo) prend la place du clip généré au prochain passage.
    /// </summary>
    public static class BodyAnimationBuilder
    {
        const string Root = "Assets/Mika/Art/Animations";
        const string Generated = Root + "/Generated";
        const string ControllerPath = Root + "/MikaBody.controller";
        const string ClipSetPath = Root + "/BodyClipSet.asset";
        const string UpperMaskPath = Root + "/UpperBody.mask";
        const string ArmMaskPath = Root + "/RightArm.mask";
        static string RepoRoot => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "..", ".."));
        static string WebSource => Path.Combine(RepoRoot, "frontend", "Web", "public", "animations");
        static string MocapSource => Path.Combine(RepoRoot, "frontend", "Unity", "ArtSource", "mocap");

        /// <summary>Les catégories du client web qui bouclent (une attente, une parole, une marche).</summary>
        static readonly HashSet<string> Looping = new HashSet<string> { "idle", "talk", "locomotion", "sleep" };

        /// <summary>Le clip réel qui remplace un clip généré, s'il existe (nom de fichier sans extension, par ordre de préférence).</summary>
        static readonly Dictionary<string, string[]> Preferred = new Dictionary<string, string[]>
        {
            ["walk"] = new[] { "walking", "female_walk", "walk" },
            ["sit"] = new[] { "sitting_idle", "sitting" },
            // Pas « lying_idle » (113_08) : capturé au sol sans oreiller, le corps y est incliné (pieds plus hauts que la
            // tête) — sur un lit, elle flottait. Le clip généré est à plat, et cohérent avec les clips sur le côté.
            ["lie"] = new[] { "sleeping_idle", "laying_idle" },
            ["reach"] = new[] { "picking_up_object" },
        };

        /// <summary>Quel geste du protocole joue quel clip (les gestes sans clip ne bougent que le visage).</summary>
        static readonly Dictionary<string, string> GestureClips = new Dictionary<string, string>
        {
            ["wave"] = "gesture_wave", ["nod"] = "gesture_nod", ["shake_head"] = "gesture_headshake",
            ["headshake"] = "gesture_headshake", ["think"] = "gesture_think", ["laugh"] = "gesture_laugh",
            ["sigh"] = "gesture_sigh", ["stretch"] = "gesture_stretch", ["yawn"] = "gesture_yawn",
            ["surprised"] = "gesture_surprised", ["bashful"] = "gesture_bashful", ["excited"] = "gesture_excited",
            ["angry"] = "gesture_angry", ["clap"] = "gesture_excited", ["bow"] = "gesture_nod",
            ["point"] = "gesture_think", ["poke"] = "gesture_laugh", ["pat_head"] = "gesture_bashful",
        };

        [MenuItem("Mika/Animation/Construire les animations du corps", priority = 20)]
        public static void BuildAll()
        {
            var loops = MocapLoops();
            var clips = ImportFolder(WebSource, Root, category => Looping.Contains(category), travel: false);
            foreach (var kv in ImportFolder(MocapSource, Root + "/mocap", _ => false, travel: true, loops)) clips[kv.Key] = kv.Value;
            // La vitesse de la prise (sa racine) se lit sur le clip importé.
            _rawWalk = clips.TryGetValue("walking", out var rawWalk) ? rawWalk : null;
            // Les mouvements de l'atelier Blender (adaptés sur son squelette, au sol, appuis bloqués) remplacent les
            // prises du même nom ; les autres marches restent des copies aux pieds redressés, rendues symétriques.
            _atelier = AtelierImporter.Clips();
            foreach (var kv in _atelier) clips[kv.Key] = kv.Value;
            foreach (var n in new[] { "walking", "walking_slow" })
                if (!_atelier.ContainsKey(n) && clips.TryGetValue(n, out var raw))
                    clips[n] = FlatFeet(raw, $"{n}_pieds_a_plat");
            var base_ = BasePose(clips.TryGetValue("idle_breathing", out var idle) ? idle : clips.Values.FirstOrDefault());
            var body = GenerateClips(base_);
            foreach (var kv in Preferred)
            {
                var found = kv.Value.Select(n => clips.TryGetValue(n, out var c) ? c : null).FirstOrDefault(c => c != null);
                if (found != null) body[kv.Key] = found;
            }
            var set = ClipSet(clips);
            var controller = BuildController(clips, body, set);
            AssignToCatalog(controller, set);
            AssetDatabase.SaveAssets();
            Debug.Log($"[Mika] animations : {clips.Count} clips importés, attentes {set.idles.Count}, paroles {set.talks.Count}, gestes {set.gestures.Count}, marche « {body["walk"].name} », contrôleur {ControllerPath}.");
        }

        // --- import ----------------------------------------------------------------------------------------------
        /// <summary>Quels clips de motion capture bouclent (<c>clips.json</c> de l'export Blender).</summary>
        static Dictionary<string, bool> MocapLoops()
        {
            var result = new Dictionary<string, bool>();
            var path = Path.Combine(MocapSource, "clips.json");
            if (!File.Exists(path)) return result;
            var token = JToken.Parse(File.ReadAllText(path));
            var list = token is JArray a ? a : (JArray)(token["clips"] ?? new JArray());
            foreach (var c in list)
                if (c["name"] != null)
                    result[c["name"].Value<string>()] = c["loop"]?.Value<bool>() ?? false;
            return result;
        }

        static Dictionary<string, AnimationClip> ImportFolder(string source, string destination, Func<string, bool> loopByCategory, bool travel, Dictionary<string, bool> loops = null)
        {
            var result = new Dictionary<string, AnimationClip>();
            if (!Directory.Exists(source)) return result;
            foreach (var file in Directory.GetFiles(source, "*.fbx", SearchOption.AllDirectories))
            {
                var name = Path.GetFileNameWithoutExtension(file);
                var category = Path.GetFileName(Path.GetDirectoryName(file));
                var dir = source == WebSource ? $"{destination}/{category}" : destination;
                Import.RoomImporter.Ensure(dir);
                var dst = $"{dir}/{Path.GetFileName(file)}";
                var full = Path.GetFullPath(Path.Combine(Application.dataPath, "..", dst));
                if (!File.Exists(full) || File.GetLastWriteTimeUtc(full) < File.GetLastWriteTimeUtc(file))
                {
                    File.Copy(file, full, true);
                    AssetDatabase.ImportAsset(dst, ImportAssetOptions.ForceSynchronousImport);
                }
                var loop = loops != null && loops.TryGetValue(name, out var l) ? l : loopByCategory(category);
                ConfigureClip(dst, loop, travel && Travelling.Contains(name), RotationOffsets.TryGetValue(name, out var yaw) ? yaw : 0f);
                var clip = AssetDatabase.LoadAllAssetsAtPath(dst).OfType<AnimationClip>().FirstOrDefault(c => !c.name.StartsWith("__preview__"));
                if (clip != null) result[name] = clip;
            }
            return result;
        }

        /// <summary>
        /// Un clip capturé allongé garde l'orientation de la prise : on la tourne pour que la tête aille vers l'avant
        /// de la racine, comme le clip allongé généré. Mesuré sur l'avatar : sans décalage la tête de 113_08 part à
        /// ≈103° de l'avant ; −103° la mettait vers l'arrière (tête au pied du lit), +77° la met devant.
        /// </summary>
        /// <summary>
        /// Les clips capturés qui se déplacent vraiment (marcher, s'asseoir en reculant, se lever en avançant) :
        /// leur déplacement part dans le mouvement de racine. Les autres (attendre, rester assise, s'étirer) restent
        /// cuits « d'après l'original » : recentrer une attente sur son centre de masse ferait glisser les pieds à
        /// chaque transfert de poids.
        /// </summary>
        static readonly HashSet<string> Travelling = new HashSet<string> { "walking", "walking_slow", "sit_down", "stand_up" };

        static readonly Dictionary<string, float> RotationOffsets = new Dictionary<string, float>
        {
            ["lying_idle"] = 77f,
        };

        /// <param name="travel">
        /// Un clip qui se déplace (une marche capturée, s'asseoir qui recule de 35 cm) : le déplacement horizontal
        /// part dans le mouvement de racine (centre de masse), que le corps applique ou ignore ; la pose, elle,
        /// reste centrée sur la racine. Les clips Mixamo du client web sont déjà sur place.
        /// </param>
        static void ConfigureClip(string path, bool loop, bool travel, float yawOffset)
        {
            if (!(AssetImporter.GetAtPath(path) is ModelImporter mi)) return;
            var dirty = false;
            if (mi.animationType != ModelImporterAnimationType.Human)
            {
                mi.animationType = ModelImporterAnimationType.Human;
                mi.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
                dirty = true;
            }
            if (mi.materialImportMode != ModelImporterMaterialImportMode.None)
            {
                mi.materialImportMode = ModelImporterMaterialImportMode.None;
                dirty = true;
            }
            var clips = mi.clipAnimations.Length > 0 ? mi.clipAnimations : mi.defaultClipAnimations;
            foreach (var c in clips)
            {
                // Une boucle recolle sa dernière pose sur la première (loopPose) : pas d'à-coup à chaque tour. La
                // hauteur et l'orientation restent dans la pose (s'asseoir descend vraiment, s'allonger couche).
                if (c.loopTime == loop && c.loopPose == loop && c.lockRootRotation && c.lockRootHeightY && c.keepOriginalPositionY &&
                    c.lockRootPositionXZ == !travel && c.keepOriginalPositionXZ == !travel && Mathf.Approximately(c.rotationOffset, yawOffset)) continue;
                c.loopTime = loop;
                c.loopPose = loop;
                c.lockRootRotation = true;
                c.lockRootHeightY = true;
                c.lockRootPositionXZ = !travel;
                c.keepOriginalOrientation = true;
                c.keepOriginalPositionY = true;
                c.keepOriginalPositionXZ = !travel;
                c.rotationOffset = yawOffset;
                dirty = true;
            }
            if (!dirty) return;
            mi.clipAnimations = clips;
            mi.SaveAndReimport();
        }

        // --- clips générés ----------------------------------------------------------------------------------
        /// <summary>La pose de repos de Mika : les muscles du premier instant de son clip d'attente.</summary>
        static bool IsIkGoal(string property) =>
            System.Text.RegularExpressions.Regex.IsMatch(property, @"^(Left|Right)(Foot|Hand)[TQ]\.");

        static Dictionary<string, float> BasePose(AnimationClip idle)
        {
            // Les noms tels que les clips humanoïdes les écrivent (les doigts s'y nomment « LeftHand.Index.1
            // Stretched », pas comme dans HumanTrait) : on part des courbes du clip d'attente lui-même.
            var pose = new Dictionary<string, float>();
            if (idle != null)
                foreach (var b in AnimationUtility.GetCurveBindings(idle))
                {
                    if (b.type != typeof(Animator)) continue;
                    // Pas les cibles IK des mains et des pieds (LeftFootT.x…) : recopiées constantes, elles
                    // clouaient les pieds de la marche générée à leur place dans l'attente (jambes immobiles).
                    if (IsIkGoal(b.propertyName)) continue;
                    var curve = AnimationUtility.GetEditorCurve(idle, b);
                    if (curve != null) pose[b.propertyName] = curve.Evaluate(0f);
                }
            foreach (var n in HumanTrait.MuscleName)
                if (!pose.ContainsKey(n) && !n.Contains("Thumb") && !n.Contains("Index") && !n.Contains("Middle") && !n.Contains("Ring") && !n.Contains("Little"))
                    pose[n] = 0f;
            return pose;
        }

        static Dictionary<string, AnimationClip> GenerateClips(Dictionary<string, float> base_)
        {
            Import.RoomImporter.Ensure(Generated);
            var walk = Walk(base_);
            using (var probe = PoseProbe.Create())
                if (probe != null) probe.Ground(walk, base_);
            return new Dictionary<string, AnimationClip>
            {
                ["walk"] = Save("body_walk", walk, loop: true),
                ["sit"] = Save("body_sit", Sit(base_), loop: true),
                ["lie"] = Save("body_lie", Lie(base_), loop: true),
                ["reach"] = Save("body_reach", Reach(base_), loop: false),
                ["life"] = Save("body_life", Life(base_), loop: true),
                ["lie_left"] = Save("body_lie_left", LieSide(base_, left: true), loop: true),
                ["lie_right"] = Save("body_lie_right", LieSide(base_, left: false), loop: true),
            };
        }

        /// <summary>Une pose humanoïde dans le temps : des courbes de muscles (et du corps) à quelques instants.</summary>
        sealed class Track
        {
            public readonly Dictionary<string, AnimationCurve> Curves = new Dictionary<string, AnimationCurve>();
            public float Length;

            public void Key(string property, float time, float value)
            {
                if (!Curves.TryGetValue(property, out var c)) Curves[property] = c = new AnimationCurve();
                c.AddKey(new Keyframe(time, value));
                Length = Mathf.Max(Length, time);
            }

            /// <summary>Toute la pose de repos aux instants donnés, puis les écarts propres au clip.</summary>
            public void Base(Dictionary<string, float> base_, params float[] times)
            {
                foreach (var t in times)
                    foreach (var kv in base_)
                        if (!kv.Key.StartsWith("Root"))
                            Key(kv.Key, t, kv.Value);
            }

            /// <summary>Une valeur absolue du muscle (pour une posture loin du repos : l'assise, le coucher).</summary>
            public void Set(string muscle, float time, float value)
            {
                if (!Curves.TryGetValue(muscle, out var c)) return;
                var keys = c.keys;
                for (var i = 0; i < keys.Length; i++)
                    if (Mathf.Approximately(keys[i].time, time))
                    {
                        keys[i].value = Mathf.Clamp(value, -1f, 1f);
                        c.keys = keys;
                        return;
                    }
            }

            public void Offset(Dictionary<string, float> base_, string muscle, float time, float delta)
            {
                if (!Curves.TryGetValue(muscle, out var c)) return;
                var keys = c.keys;
                for (var i = 0; i < keys.Length; i++)
                    if (Mathf.Approximately(keys[i].time, time))
                    {
                        keys[i].value = Mathf.Clamp(keys[i].value + delta, -1f, 1f);
                        c.keys = keys;
                        return;
                    }
                c.AddKey(time, Mathf.Clamp(base_[muscle] + delta, -1f, 1f));
            }
        }

        /// <summary>
        /// L'avatar posé hors scène, pour mesurer une pose : où sont ses pieds quand ses muscles valent ceci.
        /// Sert à caler au sol un clip généré — sans quoi une marche aux genoux pliés, à hauteur de hanches
        /// d'une attente aux jambes droites, flotte et sautille.
        /// </summary>
        sealed class PoseProbe : IDisposable
        {
            const string AvatarPrefab = "Assets/Mika/Art/Avatars/Mika.prefab";
            static readonly HumanBodyBones[] Feet = { HumanBodyBones.LeftFoot, HumanBodyBones.RightFoot, HumanBodyBones.LeftToes, HumanBodyBones.RightToes };
            GameObject _go;
            Animator _animator;
            HumanPoseHandler _handler;

            public static PoseProbe Create()
            {
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(AvatarPrefab);
                if (prefab == null) return null;
                var go = UnityEngine.Object.Instantiate(prefab);
                go.hideFlags = HideFlags.HideAndDontSave;
                var animator = go.GetComponentInChildren<Animator>();
                if (animator == null || animator.avatar == null || !animator.avatar.isHuman)
                {
                    UnityEngine.Object.DestroyImmediate(go);
                    return null;
                }
                return new PoseProbe { _go = go, _animator = animator, _handler = new HumanPoseHandler(animator.avatar, animator.transform) };
            }

            /// <summary>Le point le plus bas des pieds (au-dessus de la racine) pour ces muscles et cette hauteur du corps.</summary>
            float Lowest(Func<string, float> muscle, float bodyY)
            {
                var pose = new HumanPose
                {
                    bodyPosition = new Vector3(0f, bodyY, 0f),
                    bodyRotation = Quaternion.identity,
                    muscles = new float[HumanTrait.MuscleCount],
                };
                for (var i = 0; i < HumanTrait.MuscleCount; i++) pose.muscles[i] = muscle(HumanTrait.MuscleName[i]);
                _handler.SetHumanPose(ref pose);
                var low = float.MaxValue;
                foreach (var b in Feet)
                {
                    var t = _animator.GetBoneTransform(b);
                    if (t != null) low = Mathf.Min(low, t.position.y - _animator.transform.position.y);
                }
                return low;
            }

            /// <summary>
            /// Ajuste la hauteur du corps (RootT.y) de chaque image pour que le pied d'appui touche le sol au
            /// même niveau que dans la pose de repos.
            /// </summary>
            public void Ground(Track track, Dictionary<string, float> base_)
            {
                if (!track.Curves.TryGetValue("RootT.y", out var rootY)) return;
                var baseY = base_.TryGetValue("RootT.y", out var y) ? y : 1f;
                float Base(string n) => base_.TryGetValue(n, out var v) ? v : 0f;
                var reference = Lowest(Base, baseY);
                // Combien les pieds montent quand le corps monte d'une unité (l'échelle de l'avatar).
                var gain = (Lowest(Base, baseY + 0.1f) - reference) / 0.1f;
                if (gain < 0.05f) return;
                var keys = rootY.keys;
                for (var i = 0; i < keys.Length; i++)
                {
                    var time = keys[i].time;
                    float At(string n) => track.Curves.TryGetValue(n, out var c) ? c.Evaluate(time) : Base(n);
                    keys[i].value -= (Lowest(At, keys[i].value) - reference) / gain;
                }
                rootY.keys = keys;
            }

            public void Dispose()
            {
                _handler?.Dispose();
                if (_go != null) UnityEngine.Object.DestroyImmediate(_go);
            }
        }

        static AnimationClip Save(string name, Track track, bool loop)
        {
            var path = $"{Generated}/{name}.anim";
            var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(path);
            if (clip == null)
            {
                clip = new AnimationClip { name = name };
                AssetDatabase.CreateAsset(clip, path);
            }
            clip.ClearCurves();
            foreach (var kv in track.Curves)
            {
                for (var i = 0; i < kv.Value.length; i++)
                {
                    AnimationUtility.SetKeyLeftTangentMode(kv.Value, i, AnimationUtility.TangentMode.ClampedAuto);
                    AnimationUtility.SetKeyRightTangentMode(kv.Value, i, AnimationUtility.TangentMode.ClampedAuto);
                }
                AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve("", typeof(Animator), kv.Key), kv.Value);
            }
            var settings = AnimationUtility.GetAnimationClipSettings(clip);
            settings.loopTime = loop;
            settings.loopBlend = loop;
            settings.loopBlendOrientation = true;
            settings.loopBlendPositionY = true;
            settings.loopBlendPositionXZ = true;
            settings.keepOriginalOrientation = true;
            settings.keepOriginalPositionY = true;
            settings.keepOriginalPositionXZ = true;
            AnimationUtility.SetAnimationClipSettings(clip, settings);
            EditorUtility.SetDirty(clip);
            return clip;
        }

        static readonly string[] Sides = { "Left", "Right" };

        /// <summary>
        /// Marcher (repli sans motion capture) : 1,1 s par cycle, jambes en opposition, genou fléchi au passage
        /// et légèrement à l'attaque, pied qui déroule, bassin et épaules qui tournent en sens contraire, bras
        /// ballants en contre-temps, tête stable.
        /// </summary>
        static Track Walk(Dictionary<string, float> b)
        {
            var t = new Track();
            const float cycle = 1.1f;
            var times = Enumerable.Range(0, 13).Select(i => cycle * i / 12f).ToArray();
            t.Base(b, times);
            foreach (var time in times)
            {
                var phase = time / cycle * Mathf.PI * 2f;
                for (var s = 0; s < 2; s++)
                {
                    var side = Sides[s];
                    var p = phase + (s == 0 ? 0 : Mathf.PI);
                    t.Offset(b, $"{side} Upper Leg Front-Back", time, LegSign * 0.5f * Mathf.Sin(p));
                    // Le genou plie fort au passage (jambe libre), un peu à l'attaque (amorti).
                    var swing = Mathf.Max(0f, Mathf.Sin(p + 1.2f));
                    var load = Mathf.Max(0f, Mathf.Sin(p - 0.4f)) * 0.25f;
                    t.Offset(b, $"{side} Lower Leg Stretch", time, -0.85f * swing - load);
                    t.Offset(b, $"{side} Foot Up-Down", time, 0.25f * Mathf.Sin(p + 0.6f));
                    t.Offset(b, $"{side} Arm Front-Back", time, -0.3f * Mathf.Sin(p));
                    t.Offset(b, $"{side} Forearm Stretch", time, -0.12f - 0.08f * Mathf.Max(0, Mathf.Sin(p)));
                    t.Offset(b, $"{side} Shoulder Front-Back", time, -0.06f * Mathf.Sin(p));
                }
                t.Key("RootT.y", time, b.TryGetValue("RootT.y", out var y) ? y + 0.015f * Mathf.Abs(Mathf.Cos(phase)) : 1f);
                t.Offset(b, "Spine Twist Left-Right", time, 0.08f * Mathf.Sin(phase));
                t.Offset(b, "Chest Twist Left-Right", time, -0.06f * Mathf.Sin(phase));
                t.Offset(b, "Spine Left-Right", time, 0.04f * Mathf.Sin(phase));
                t.Offset(b, "Head Turn Left-Right", time, -0.03f * Mathf.Sin(phase));
            }
            return t;
        }

        /// <summary>
        /// La vie (calque additif, 12 s bouclées) : souffle, buste qui se balance à peine, nuque et tête qui
        /// bougent sans jamais se répéter à l'identique dans le cycle — périodes 12, 6, 4, 3 et 2,4 s, toutes
        /// diviseurs de 12, pour que la boucle se referme sans à-coup. Première image = repos (le calque
        /// additif retranche sa première image).
        /// </summary>
        static Track Life(Dictionary<string, float> b)
        {
            var t = new Track();
            const float length = 12f;
            var times = Enumerable.Range(0, 49).Select(i => length * i / 48f).ToArray();
            t.Base(b, times);
            float W(float time, float period, float phase) => Mathf.Sin(time / period * Mathf.PI * 2f + phase) - Mathf.Sin(phase);
            foreach (var time in times)
            {
                var breath = W(time, 4f, 0f);
                t.Offset(b, "Chest Front-Back", time, 0.035f * breath);
                t.Offset(b, "Spine Front-Back", time, 0.015f * breath + 0.02f * W(time, 12f, 0.7f));
                t.Offset(b, "Left Shoulder Down-Up", time, 0.03f * breath);
                t.Offset(b, "Right Shoulder Down-Up", time, 0.03f * breath);
                t.Offset(b, "Spine Left-Right", time, 0.025f * W(time, 6f, 1.1f));
                t.Offset(b, "Chest Left-Right", time, 0.02f * W(time, 12f, 2.3f));
                t.Offset(b, "Neck Nod Down-Up", time, 0.03f * W(time, 3f, 0.4f) - 0.015f * breath);
                t.Offset(b, "Neck Turn Left-Right", time, 0.04f * W(time, 6f, 2.0f));
                t.Offset(b, "Head Nod Down-Up", time, 0.025f * W(time, 2.4f, 1.3f));
                t.Offset(b, "Head Tilt Left-Right", time, 0.035f * W(time, 12f, 0.2f));
            }
            return t;
        }

        /// <summary>Assise : cuisses à l'horizontale, genoux pliés, buste droit, souffle lent.</summary>
        static Track Sit(Dictionary<string, float> b)
        {
            var t = new Track();
            var times = new[] { 0f, 1.5f, 3f };
            t.Base(b, times);
            foreach (var time in times)
            {
                var breath = Mathf.Sin(time / 3f * Mathf.PI * 2f);
                foreach (var side in Sides)
                {
                    t.Set($"{side} Upper Leg Front-Back", time, SitThigh);
                    t.Set($"{side} Lower Leg Stretch", time, SitKnee);
                    t.Set($"{side} Upper Leg In-Out", time, 0.05f);
                    t.Offset(b, $"{side} Arm Front-Back", time, 0.2f);
                    t.Offset(b, $"{side} Forearm Stretch", time, -0.25f);
                }
                t.Offset(b, "Chest Front-Back", time, 0.03f * breath);
                t.Key("RootT.y", time, (b.TryGetValue("RootT.y", out var y) ? y : 1f) * 0.62f);
            }
            return t;
        }

        /// <summary>Allongée sur le dos : jambes tendues, bras le long du corps, tête posée, souffle lent.</summary>
        static Track Lie(Dictionary<string, float> b)
        {
            var t = new Track();
            var times = new[] { 0f, 2f, 4f };
            t.Base(b, times);
            // Sur le dos, la tête vers l'avant de la racine (le sens du lit), le visage vers le plafond.
            var q = Quaternion.Euler(0f, 180f, 0f) * Quaternion.Euler(-90f, 0f, 0f);
            foreach (var time in times)
            {
                var breath = Mathf.Sin(time / 4f * Mathf.PI * 2f);
                foreach (var side in Sides)
                {
                    // Par rapport à la pose debout (une jambe tendue y vaut déjà ≈ 0,6 en avant-arrière) : jambes
                    // presque tendues, genoux à peine fléchis, pieds qui retombent en dehors.
                    t.Offset(b, $"{side} Upper Leg Front-Back", time, -0.06f);
                    t.Offset(b, $"{side} Lower Leg Stretch", time, -0.12f);
                    t.Offset(b, $"{side} Upper Leg Twist In-Out", time, -0.2f);
                    // Les mains posées sur le ventre : avant-bras repliés vers le milieu du corps.
                    t.Offset(b, $"{side} Arm Front-Back", time, -0.04f);
                    t.Offset(b, $"{side} Forearm Stretch", time, -0.3f);
                    t.Offset(b, $"{side} Forearm Twist In-Out", time, 0.2f);
                }
                t.Offset(b, "Chest Front-Back", time, 0.04f * breath);
                t.Offset(b, "Head Nod Down-Up", time, -0.2f);
                t.Key("RootT.x", time, 0f);
                t.Key("RootT.y", time, 0.12f);
                t.Key("RootT.z", time, 0f);
                t.Key("RootQ.x", time, q.x);
                t.Key("RootQ.y", time, q.y);
                t.Key("RootQ.z", time, q.z);
                t.Key("RootQ.w", time, q.w);
            }
            return t;
        }

        /// <summary>
        /// Couchée sur le côté (gauche ou droit) : le corps roulé d'un quart de tour autour de l'axe tête-pieds,
        /// genoux pliés (la jambe du dessus un peu plus en avant), bras devant la poitrine, tête posée, souffle lent.
        /// Repère du clip allongé : la tête vers l'avant de la racine, sur le dos la droite du corps vers −X ;
        /// rouler sur le côté droit, c'est tourner de +90° autour de l'axe de la tête (le visage passe vers −X).
        /// </summary>
        static Track LieSide(Dictionary<string, float> b, bool left)
        {
            var t = new Track();
            var times = new[] { 0f, 2.5f, 5f };
            t.Base(b, times);
            var back = Quaternion.Euler(0f, 180f, 0f) * Quaternion.Euler(-90f, 0f, 0f);
            var q = Quaternion.AngleAxis(left ? -90f : 90f, Vector3.forward) * back;
            var under = left ? "Left" : "Right";
            var over = left ? "Right" : "Left";
            foreach (var time in times)
            {
                var breath = Mathf.Sin(time / 5f * Mathf.PI * 2f);
                // Cuisse : négatif = vers l'avant (mesuré sur l'avatar) ; genou : négatif = plié.
                t.Set($"{under} Upper Leg Front-Back", time, -0.35f);
                t.Set($"{under} Lower Leg Stretch", time, -0.45f);
                t.Set($"{over} Upper Leg Front-Back", time, -0.6f);
                t.Set($"{over} Lower Leg Stretch", time, -0.6f);
                t.Set($"{over} Upper Leg In-Out", time, -0.1f);
                // Bras ramenés devant (Front-Back négatif = vers l'avant), coudes pliés.
                t.Set($"{under} Arm Front-Back", time, -0.55f);
                t.Set($"{under} Arm Down-Up", time, 0.1f);
                t.Set($"{under} Forearm Stretch", time, -0.45f);
                t.Set($"{over} Arm Front-Back", time, -0.45f);
                t.Set($"{over} Arm Down-Up", time, -0.35f);
                t.Set($"{over} Forearm Stretch", time, -0.35f);
                t.Offset(b, "Spine Front-Back", time, 0.12f);
                t.Offset(b, "Chest Front-Back", time, 0.05f + 0.03f * breath);
                t.Offset(b, "Head Nod Down-Up", time, -0.15f);
                t.Key("RootT.x", time, 0f);
                t.Key("RootT.y", time, 0.2f);
                t.Key("RootT.z", time, 0f);
                t.Key("RootQ.x", time, q.x);
                t.Key("RootQ.y", time, q.y);
                t.Key("RootQ.z", time, q.z);
                t.Key("RootQ.w", time, q.w);
            }
            return t;
        }

        /// <summary>Tendre le bras droit vers le bas et l'avant (prendre, poser) ; l'IK amène la main au point exact.</summary>
        static Track Reach(Dictionary<string, float> b)
        {
            var t = new Track();
            var times = new[] { 0f, 0.45f, 0.8f, 1.2f };
            var amount = new[] { 0f, 1f, 1f, 0f };
            t.Base(b, times);
            for (var i = 0; i < times.Length; i++)
            {
                var k = amount[i];
                t.Offset(b, "Right Arm Front-Back", times[i], 0.7f * k);
                t.Offset(b, "Right Arm Down-Up", times[i], 0.25f * k);
                t.Offset(b, "Right Forearm Stretch", times[i], 0.3f * k);
                t.Offset(b, "Spine Front-Back", times[i], 0.35f * k);
                t.Offset(b, "Chest Front-Back", times[i], 0.2f * k);
            }
            return t;
        }

        /// <summary>
        /// Le sens du muscle « Upper Leg Front-Back » : +1 si une valeur positive avance la jambe. Vérifié sur
        /// l'avatar (capture d'une assise) ; à inverser ici seulement si une nouvelle version de Unity le change.
        /// </summary>
        const float LegSign = -1f;

        /// <summary>
        /// Assise : cuisse à l'horizontale, genou à angle droit. Mesuré sur l'avatar en balayant les deux muscles
        /// (genou et pied relevés par rapport à la hanche) : −0,62 met le genou à hauteur de hanche, 0 met le pied
        /// sous le genou.
        /// </summary>
        public const float SitThigh = -0.62f;
        public const float SitKnee = 0f;

        // --- ce que le contrôleur sait jouer --------------------------------------------------------------------
        /// <summary>Les variantes d'attente et de parole, avec l'humeur que leur prête le manifeste du client web.</summary>
        static BodyClipSet ClipSet(Dictionary<string, AnimationClip> clips)
        {
            var set = AssetDatabase.LoadAssetAtPath<BodyClipSet>(ClipSetPath);
            if (set == null)
            {
                set = ScriptableObject.CreateInstance<BodyClipSet>();
                AssetDatabase.CreateAsset(set, ClipSetPath);
            }
            set.idles.Clear();
            set.talks.Clear();
            var manifestPath = Path.Combine(WebSource, "manifest.json");
            var manifest = File.Exists(manifestPath) ? (JObject)JToken.Parse(File.ReadAllText(manifestPath))["clips"] : new JObject();
            BodyVariant Variant(string name, JToken m, int index, float weight, Vector2 hold) => new BodyVariant
            {
                clip = name,
                index = index,
                weight = m?["weight"]?.Value<float>() ?? weight,
                hold = m?["hold"] is JArray h && h.Count == 2 ? new Vector2(h[0].Value<float>(), h[1].Value<float>()) : hold,
                valence = m?["valence"]?.Value<float>() ?? 0f,
                arousal = m?["arousal"]?.Value<float>() ?? 0f,
            };
            // La plus courante d'abord : l'index 0 est l'attente par défaut du contrôleur (avant tout tirage, après s'être levée).
            float Weight(string n) => manifest[n]?["weight"]?.Value<float>() ?? 1f;
            foreach (var name in clips.Keys.Where(n => n.StartsWith("idle_")).OrderByDescending(Weight).ThenBy(n => n))
                set.idles.Add(Variant(name, manifest[name], set.idles.Count, 1f, new Vector2(8, 14)));
            if (clips.ContainsKey("waiting"))
                set.idles.Add(Variant("waiting", null, set.idles.Count, 2f, new Vector2(8, 14)));
            foreach (var name in clips.Keys.Where(n => n.StartsWith("talk_")).OrderByDescending(Weight).ThenBy(n => n))
                set.talks.Add(Variant(name, manifest[name], set.talks.Count, 1f, new Vector2(4, 9)));
            set.gestures = GestureClips.Where(kv => clips.ContainsKey(kv.Value)).Select(kv => kv.Key).ToList();
            // La vitesse au sol du clip de marche : celle qu'il a dans sa prise (racine), sinon une marche ordinaire.
            var walk = Preferred["walk"].Select(n => clips.TryGetValue(n, out var c) ? c : null).FirstOrDefault(c => c != null);
            var speed = walk != null ? new Vector2(walk.averageSpeed.x, walk.averageSpeed.z).magnitude : 0f;
            set.walkClipSpeed = speed > 0.4f && speed < 2.5f ? speed : (walk != null ? 1.2f : 1.0f);
            Measures(set, clips);
            EditorUtility.SetDirty(set);
            return set;
        }

        /// <summary>
        /// Les grandeurs des clips capturés (vitesses, reculs, hauteurs), lues dans <c>clips.json</c> et ramenées à
        /// la taille du squelette de la prise (ses hanches au repos) : en « tailles », valables pour tout avatar.
        /// </summary>
        static void Measures(BodyClipSet set, Dictionary<string, AnimationClip> clips)
        {
            set.walkSlowNorm = set.walkNorm = set.sitTravelNorm = set.sitHipsNorm = set.standTravelNorm = 0f;
            set.walkSlowSeconds = set.walkSeconds = 0f;
            set.sitDownSeconds = set.standUpSeconds = 0f;
            var path = Path.Combine(MocapSource, "clips.json");
            if (!File.Exists(path)) return;
            var list = (JArray)(JToken.Parse(File.ReadAllText(path))["clips"] ?? new JArray());
            JToken Clip(string n) => clips.ContainsKey(n) ? list.FirstOrDefault(c => c["name"]?.Value<string>() == n) : null;
            // L'unité « humaine » est celle qu'Unity donne au squelette de la prise (son humanScale), pas la hauteur
            // de hanches notée par l'export : on la retrouve par la marche (m/s réels ÷ vitesse normalisée du clip).
            var scale = 0.95f;
            var rootWalk = _rawWalk != null ? _rawWalk : clips.TryGetValue("walking", out var w0) ? w0 : null;
            if (Clip("walking") is { } wk && rootWalk != null && rootWalk.averageSpeed.magnitude > 0.1f)
                scale = wk["speed_m_s"].Value<float>() / rootWalk.averageSpeed.magnitude;
            float Rest(JToken c) => scale;
            float Hips(JToken c, string key, int i) => c?[key] is JArray a && a.Count == 3 ? a[i].Value<float>() : 0f;
            if (Clip("walking") is { } w) set.walkNorm = w["speed_m_s"].Value<float>() / Rest(w);
            if (Clip("walking_slow") is { } ws) set.walkSlowNorm = ws["speed_m_s"].Value<float>() / Rest(ws);
            // La vitesse de la prise ramenée à sa taille surestime la sienne : ses jambes sont plus courtes que celles
            // de l'acteur par rapport à ses hanches, sa foulée l'est aussi (le pied d'appui avançait de 0,25 m/s à
            // 0,85 m/s). On mesure donc, sur son squelette, la vitesse à laquelle son pied d'appui recule sous elle.
            if (clips.TryGetValue("walking", out var wc) && StanceSweep(wc) is var n1 && n1 > 0f) set.walkNorm = n1;
            if (clips.TryGetValue("walking_slow", out var sc) && StanceSweep(sc) is var n0 && n0 > 0f) set.walkSlowNorm = n0;
            set.walkSeconds = clips.TryGetValue("walking", out var wl) ? wl.length : 0f;
            set.walkSlowSeconds = clips.TryGetValue("walking_slow", out var sl) ? sl.length : 0f;
            if (Clip("sit_down") is { } sd)
            {
                var dz = Hips(sd, "hips_end_unity_m", 2) - Hips(sd, "hips_start_unity_m", 2);
                set.sitTravelNorm = Mathf.Abs(dz) / Rest(sd);
                set.sitHipsNorm = Hips(sd, "hips_end_unity_m", 1) / Rest(sd);
                set.sitDownSeconds = clips["sit_down"].length;
            }
            if (Clip("stand_up") is { } su)
            {
                var dz = Hips(su, "hips_end_unity_m", 2) - Hips(su, "hips_start_unity_m", 2);
                set.standTravelNorm = Mathf.Abs(dz) / Rest(su);
                set.standUpSeconds = clips["stand_up"].length;
            }
            // Les clips de l'atelier sont adaptés à son squelette et à la hauteur de ses sièges : leurs grandeurs se
            // lisent sur eux, la fiche de la prise CMU ne leur correspond plus (hanches assises à 0,46 m d'après elle,
            // à 0,57 m dans le clip — le jeu soulevait la racine de 13 cm de trop).
            if (_atelier.TryGetValue("sit_down", out var asd) && HipsPath(asd) is { } down)
            {
                set.sitTravelNorm = Mathf.Abs(down.travel);
                set.sitHipsNorm = down.endHeight;
                set.sitDownSeconds = asd.length;
            }
            if (_atelier.TryGetValue("stand_up", out var asu) && HipsPath(asu) is { } up)
            {
                set.standTravelNorm = Mathf.Abs(up.travel);
                set.standUpSeconds = asu.length;
            }
        }

        /// <summary>
        /// Le chemin des hanches d'un clip joué sur elle : leur déplacement vers l'avant entre le début et la fin, et
        /// leur hauteur à la fin, en tailles (÷ humanScale). L'échantillon garde le déplacement de la prise.
        /// </summary>
        static (float travel, float endHeight)? HipsPath(AnimationClip clip)
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Mika/Art/Avatars/Mika.prefab");
            if (prefab == null || clip == null || clip.length <= 0f) return null;
            var go = UnityEngine.Object.Instantiate(prefab);
            go.hideFlags = HideFlags.HideAndDontSave;
            go.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
            try
            {
                var a = go.GetComponentInChildren<Animator>();
                if (a == null || !a.isHuman || a.humanScale <= 0f) return null;
                var hips = a.GetBoneTransform(HumanBodyBones.Hips);
                clip.SampleAnimation(a.gameObject, 0f);
                var start = a.transform.InverseTransformPoint(hips.position);
                clip.SampleAnimation(a.gameObject, clip.length);
                var end = a.transform.InverseTransformPoint(hips.position);
                var travel = (end.z - start.z) / a.humanScale;
                var height = end.y / a.humanScale;
                Debug.Log($"[Mika] « {clip.name} » : les hanches avancent de {end.z - start.z:+0.00;-0.00} m et finissent à {end.y:0.00} m du sol.");
                return (travel, height);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        // --- contrôleur -----------------------------------------------------------------------------------------
        static AnimatorController BuildController(Dictionary<string, AnimationClip> clips, Dictionary<string, AnimationClip> body, BodyClipSet set)
        {
            // Le même asset d'une reconstruction à l'autre (même GUID) : ce qui le référence ne le perd pas.
            var ac = AssetDatabase.LoadAssetAtPath<AnimatorController>(ControllerPath);
            if (ac == null)
            {
                ac = AnimatorController.CreateAnimatorControllerAtPath(ControllerPath);
            }
            else
            {
                foreach (var sub in AssetDatabase.LoadAllAssetsAtPath(ControllerPath))
                    if (sub != null && sub != ac)
                        UnityEngine.Object.DestroyImmediate(sub, true);
                ac.parameters = new AnimatorControllerParameter[0];
                ac.layers = new AnimatorControllerLayer[0];
                ac.AddLayer("Base Layer");
            }
            foreach (var (name, type) in new[]
                     {
                         ("Speed", AnimatorControllerParameterType.Float), ("Posture", AnimatorControllerParameterType.Int),
                         ("Gesture", AnimatorControllerParameterType.Trigger), ("GestureId", AnimatorControllerParameterType.Int),
                         ("Holding", AnimatorControllerParameterType.Bool), ("Talking", AnimatorControllerParameterType.Bool),
                         ("Reach", AnimatorControllerParameterType.Trigger), ("Activity", AnimatorControllerParameterType.Int),
                         ("Asleep", AnimatorControllerParameterType.Bool), ("IdleVariant", AnimatorControllerParameterType.Int),
                         ("TalkVariant", AnimatorControllerParameterType.Int), ("Tempo", AnimatorControllerParameterType.Float),
                         ("WalkPlayback", AnimatorControllerParameterType.Float), ("WalkBlend", AnimatorControllerParameterType.Float),
                         ("Pose", AnimatorControllerParameterType.Int), ("LieSide", AnimatorControllerParameterType.Int),
                         ("Covered", AnimatorControllerParameterType.Bool), ("Symetrie", AnimatorControllerParameterType.Float),
                     })
                ac.AddParameter(name, type);
            // Les courbes des gestes de l'atelier (AtelierImporter : « Geste… ») : un paramètre du même nom que la courbe la
            // reçoit à chaque image du clip qui la porte (la chaise que le geste déplace, l'objet dans la main).
            foreach (var name in BodyAnim.GestureCurves)
                ac.AddParameter(name, AnimatorControllerParameterType.Float);
            var ps = ac.parameters;
            foreach (var p in ps)
                if (p.name == "Tempo" || p.name == "WalkPlayback") p.defaultFloat = 1f;
                else if (p.name == "Symetrie") p.defaultFloat = 0.5f;
            ac.parameters = ps;

            var layers = ac.layers;
            layers[0].iKPass = true;
            ac.layers = layers;
            var sm = ac.layers[0].stateMachine;

            // Debout : une attente par variante, une parole par variante, la marche.
            var fallbackIdle = clips.TryGetValue("idle_breathing", out var ib) ? ib : body["sit"];
            var idles = set.idles.Count > 0
                ? set.idles.Select((v, i) => State(sm, $"Attente · {v.clip}", clips[v.clip], new Vector3(250, 60 * i), "Tempo")).ToList()
                : new List<AnimatorState> { State(sm, "Attente", fallbackIdle, new Vector3(250, 0), "Tempo") };
            var talks = set.talks.Count > 0
                ? set.talks.Select((v, i) => State(sm, $"Parle · {v.clip}", clips[v.clip], new Vector3(550, 60 * i), "Tempo")).ToList()
                : new List<AnimatorState> { idles[0] };
            // La marche : lente et normale mélangées selon la vitesse (WalkBlend), à la cadence qui colle les pieds au sol.
            Motion walkMotion = body["walk"];
            if (clips.TryGetValue("walking_slow", out var slowWalk) && clips.TryGetValue("walking", out var normalWalk))
            {
                var tree = new BlendTree { name = "Marche", blendParameter = "WalkBlend", useAutomaticThresholds = false, hideFlags = HideFlags.HideInHierarchy };
                AssetDatabase.AddObjectToAsset(tree, ac);
                // Les deux prises ne commencent pas sur le même pied : mélangées telles quelles, les jambes se
                // contrarient (les pieds bougent ensemble, ne se posent jamais, elle semble léviter). On décale la
                // marche lente pour que ses foulées tombent sur celles de la marche normale.
                var offset = CycleOffset(normalWalk, slowWalk);
                // Une marche de l'atelier est déjà symétrique : elle entre telle quelle.
                if (_atelier.ContainsKey("walking_slow")) tree.AddChild(slowWalk, 0f);
                else tree.AddChild(Symmetric(ac, slowWalk, "Marche lente", 0f), 0f);
                if (_atelier.ContainsKey("walking")) tree.AddChild(normalWalk, 1f);
                else tree.AddChild(Symmetric(ac, normalWalk, "Marche normale", 0f), 1f);
                var children = tree.children;
                if (children[0].motion is AnimationClip) children[0].cycleOffset = offset;
                else ShiftTree((BlendTree)children[0].motion, offset);
                tree.children = children;
                walkMotion = tree;
            }
            var walk = State(sm, "Marche", walkMotion, new Vector3(400, -150), "WalkPlayback");
            sm.defaultState = idles[0];

            for (var i = 0; i < idles.Count; i++)
            {
                for (var j = 0; j < idles.Count; j++)
                    if (i != j) Link(idles[j], idles[i], 0.9f, ("IdleVariant", AnimatorConditionMode.Equals, i), ("Talking", AnimatorConditionMode.IfNot, 0));
                foreach (var talk in talks.Where(t => !idles.Contains(t)))
                    Link(talk, idles[i], 0.5f, ("Talking", AnimatorConditionMode.IfNot, 0), ("IdleVariant", AnimatorConditionMode.Equals, i));
                Link(walk, idles[i], 0.3f, ("Speed", AnimatorConditionMode.Less, 0.08f), ("IdleVariant", AnimatorConditionMode.Equals, i));
            }
            for (var i = 0; i < talks.Count && !idles.Contains(talks[i]); i++)
            {
                foreach (var idle in idles)
                    Link(idle, talks[i], 0.3f, ("Talking", AnimatorConditionMode.If, 0), ("TalkVariant", AnimatorConditionMode.Equals, i));
                for (var j = 0; j < talks.Count; j++)
                    if (i != j) Link(talks[j], talks[i], 0.6f, ("TalkVariant", AnimatorConditionMode.Equals, i), ("Talking", AnimatorConditionMode.If, 0));
            }
            var standing = idles.Concat(talks).Distinct().ToList();
            foreach (var st in standing)
                Link(st, walk, 0.25f, ("Speed", AnimatorConditionMode.Greater, 0.12f), ("Posture", AnimatorConditionMode.Equals, 0));

            // Assise et allongée : des boucles, et entre elles les transitions réelles quand la motion capture les a.
            var sit = State(sm, "Assise", body["sit"], new Vector3(850, 0), null, tag: "seated");
            var lie = State(sm, "Allongée", body["lie"], new Vector3(850, 200), null, tag: "lying");
            // Sur le côté : elle se retourne (le fondu fait rouler le corps autour de l'axe tête-pieds).
            var lieLeft = State(sm, "Allongée · gauche", body["lie_left"], new Vector3(1100, 140), null, tag: "lying");
            var lieRight = State(sm, "Allongée · droite", body["lie_right"], new Vector3(1100, 260), null, tag: "lying");
            Link(lie, lieLeft, 1.6f, ("LieSide", AnimatorConditionMode.Equals, 1), ("Posture", AnimatorConditionMode.Equals, 2));
            Link(lie, lieRight, 1.6f, ("LieSide", AnimatorConditionMode.Equals, 2), ("Posture", AnimatorConditionMode.Equals, 2));
            Link(lieLeft, lie, 1.6f, ("LieSide", AnimatorConditionMode.Equals, 0), ("Posture", AnimatorConditionMode.Equals, 2));
            Link(lieRight, lie, 1.6f, ("LieSide", AnimatorConditionMode.Equals, 0), ("Posture", AnimatorConditionMode.Equals, 2));
            Link(lieLeft, lieRight, 2.4f, ("LieSide", AnimatorConditionMode.Equals, 2), ("Posture", AnimatorConditionMode.Equals, 2));
            Link(lieRight, lieLeft, 2.4f, ("LieSide", AnimatorConditionMode.Equals, 1), ("Posture", AnimatorConditionMode.Equals, 2));
            foreach (var side in new[] { lieLeft, lieRight })
            {
                Link(side, sit, 1.6f, ("Posture", AnimatorConditionMode.Equals, 1));
                Link(side, idles[0], 1.4f, ("Posture", AnimatorConditionMode.Equals, 0));
            }
            var sitDown = clips.TryGetValue("sit_down", out var sd) ? State(sm, "S'asseoir", sd, new Vector3(700, -60), null) : null;
            var standUp = clips.TryGetValue("stand_up", out var su) ? State(sm, "Se lever", su, new Vector3(700, 60), null) : null;
            foreach (var st in standing.Append(walk))
            {
                Link(st, sitDown ?? sit, sitDown != null ? 0.25f : 0.95f, ("Posture", AnimatorConditionMode.Equals, 1));
                Link(st, lie, 1.4f, ("Posture", AnimatorConditionMode.Equals, 2));
            }
            if (sitDown != null) After(sitDown, sit, 0.35f, 0.9f);
            Link(sit, standUp ?? idles[0], standUp != null ? 0.2f : 0.85f, ("Posture", AnimatorConditionMode.Equals, 0));
            if (standUp != null) After(standUp, idles[0], 0.35f, 0.88f);
            Link(sit, lie, 1.5f, ("Posture", AnimatorConditionMode.Equals, 2));
            Link(lie, sit, 1.4f, ("Posture", AnimatorConditionMode.Equals, 1));
            Link(lie, idles[0], 1.2f, ("Posture", AnimatorConditionMode.Equals, 0));

            // Au bureau : les clips de l'atelier (taper, écrire, lire, boire, pivoter la chaise…), le corps entier,
            // seulement assise. Une pose sans clip (ou debout) laisse passer le calque de base (état vide).
            // Passe IK : le regard vers quelqu'un et les pieds assis s'appliquent par-dessus le clip.
            var osm = AddLayer(ac, BodyAnim.PoseLayer, null, AnimatorLayerBlendingMode.Override, ikPass: true);
            var free = osm.AddState("Rien", new Vector3(300, 0));
            osm.defaultState = free;
            var row = 0;
            var desked = new HashSet<int>();
            // Assise : les clips du bureau ; debout : ceux de la fenêtre et de la bibliothèque. Chaque état quitte la
            // couche quand la posture change (elle se lève, s'assoit, s'allonge).
            foreach (var (clipsOf, posture) in new[] { (BodyAnim.DeskClips, 1), (BodyAnim.StandClips, 0) })
                foreach (var (pose, clipName) in clipsOf)
                {
                    if (!clips.TryGetValue(clipName, out var poseClip)) continue;
                    var id = BodyAnim.PoseId(pose);
                    desked.Add(id);
                    var st = osm.AddState(pose, new Vector3(650, 50 * row++));
                    st.motion = poseClip;
                    var enter = osm.AddAnyStateTransition(st);
                    enter.hasExitTime = false;
                    // Un geste qui déplace quelque chose (pivoter, rouler la chaise, prendre le stylo) part tout de suite : sa
                    // courbe commence au repos ; le reste se fond en douceur.
                    enter.duration = pose.StartsWith("turn_") || pose == "pull_in" || pose == "push_out" ? 0.25f
                        : pose.StartsWith("write_") ? 0.3f : 0.45f;
                    enter.canTransitionToSelf = false;
                    enter.AddCondition(AnimatorConditionMode.Equals, id, "Pose");
                    enter.AddCondition(AnimatorConditionMode.Equals, posture, "Posture");
                    var leave = st.AddTransition(free);
                    leave.hasExitTime = false;
                    leave.duration = 0.45f;
                    leave.AddCondition(AnimatorConditionMode.NotEqual, posture, "Posture");
                }
            for (var id = 0; id < BodyAnim.Poses.Length; id++)
            {
                if (desked.Contains(id)) continue;
                var back = osm.AddAnyStateTransition(free);
                back.hasExitTime = false;
                back.duration = 0.45f;
                back.canTransitionToSelf = false;
                back.AddCondition(AnimatorConditionMode.Equals, id, "Pose");
            }

            // Gestes : le haut du corps, par-dessus.
            var upper = Mask(UpperMaskPath, AvatarMaskBodyPart.Body, AvatarMaskBodyPart.Head, AvatarMaskBodyPart.LeftArm, AvatarMaskBodyPart.RightArm,
                AvatarMaskBodyPart.LeftFingers, AvatarMaskBodyPart.RightFingers, AvatarMaskBodyPart.LeftHandIK, AvatarMaskBodyPart.RightHandIK);
            var gsm = AddLayer(ac, "Gestes", upper, AnimatorLayerBlendingMode.Override, ikPass: true);
            var none = gsm.AddState("Rien", new Vector3(300, 0));
            gsm.defaultState = none;
            for (var id = 1; id < BodyAnim.Gestures.Length; id++)
            {
                var name = BodyAnim.Gestures[id];
                if (!GestureClips.TryGetValue(name, out var clipName) || !clips.TryGetValue(clipName, out var clip)) continue;
                var st = gsm.AddState(name, new Vector3(600, 40 * id));
                st.motion = clip;
                st.speedParameterActive = true;
                st.speedParameter = "Tempo";
                var enter = gsm.AddAnyStateTransition(st);
                enter.hasExitTime = false;
                enter.duration = 0.25f;
                enter.canTransitionToSelf = false;
                enter.AddCondition(AnimatorConditionMode.If, 0, "Gesture");
                enter.AddCondition(AnimatorConditionMode.Equals, id, "GestureId");
                After(st, none, 0.35f, 0.88f);
            }

            // Tendre la main : le bras droit, déclenché par Reach (l'IK fait le reste).
            var arm = Mask(ArmMaskPath, AvatarMaskBodyPart.RightArm, AvatarMaskBodyPart.RightFingers, AvatarMaskBodyPart.Body);
            var rsm = AddLayer(ac, "Main", arm, AnimatorLayerBlendingMode.Override, ikPass: false);
            var rest = rsm.AddState("Repos", new Vector3(300, 0));
            rsm.defaultState = rest;
            var reaching = rsm.AddState("Tendre", new Vector3(600, 0));
            reaching.motion = body["reach"];
            var go = rest.AddTransition(reaching);
            go.hasExitTime = false;
            go.duration = 0.15f;
            go.AddCondition(AnimatorConditionMode.If, 0, "Reach");
            After(reaching, rest, 0.2f, 0.95f);

            // La vie : additive, par-dessus tout (le directeur l'atténue pendant le sommeil).
            var lsm = AddLayer(ac, BodyAnim.LifeLayer, null, AnimatorLayerBlendingMode.Additive, ikPass: false);
            var life = lsm.AddState("Vie", new Vector3(300, 0));
            life.motion = body["life"];
            lsm.defaultState = life;

            EditorUtility.SetDirty(ac);
            return ac;
        }

        /// <remarks>
        /// Jamais d'IK des pieds sur les états : un clip généré n'a pas de cibles IK, et pendant un fondu avec un
        /// clip qui en a, Unity mélange une cible réelle avec une cible nulle — les pieds remontaient jusqu'au
        /// bassin au début de chaque transition. Les clips générés sont calés au sol à la construction.
        /// </remarks>
        /// <summary>
        /// Une marche rendue symétrique : la prise et son miroir décalé d'un demi-cycle, à parts égales (paramètre
        /// constant « Symetrie » à 0,5). Retargetées sur elle, les marches capturées boitaient — un pas de 86 cm, le
        /// suivant de 35 — ; dans le miroir décalé, la jambe droite fait ce que la gauche faisait et inversement, et la
        /// moyenne des deux égalise les pas sans changer l'allure.
        /// </summary>
        static BlendTree Symmetric(AnimatorController ac, AnimationClip clip, string name, float offset)
        {
            var tree = new BlendTree { name = name, blendParameter = "Symetrie", useAutomaticThresholds = false, hideFlags = HideFlags.HideInHierarchy };
            AssetDatabase.AddObjectToAsset(tree, ac);
            tree.AddChild(clip, 0f);
            tree.AddChild(clip, 1f);
            var children = tree.children;
            children[0].cycleOffset = offset;
            children[1].mirror = true;
            // Un demi-cycle pour une marche régulière ; la leur ne l'est pas (un pied se pose 0,43 s après l'autre,
            // l'autre 0,70 s après) : on cale le miroir sur les foulées de la prise.
            children[1].cycleOffset = Mathf.Repeat(offset + CycleOffset(clip, clip, otherMirrored: true), 1f);
            tree.children = children;
            return tree;
        }

        /// <summary>
        /// Le décalage de cycle (0 → 1) qui aligne les foulées de <paramref name="other"/> sur celles de
        /// <paramref name="reference"/> : la phase de la foulée (pied gauche moins pied droit, le long de la marche,
        /// relatif aux hanches) échantillonnée sur l'avatar, puis la corrélation la plus forte.
        /// </summary>
        static float CycleOffset(AnimationClip reference, AnimationClip other, bool otherMirrored = false)
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Mika/Art/Avatars/Mika.prefab");
            if (prefab == null) return 0f;
            var go = UnityEngine.Object.Instantiate(prefab);
            go.hideFlags = HideFlags.HideAndDontSave;
            try
            {
                var a = go.GetComponentInChildren<Animator>();
                if (a == null || !a.isHuman) return 0f;
                const int n = 48;
                float[] Stride(AnimationClip clip)
                {
                    var f = new float[n];
                    var mean = 0f;
                    for (var i = 0; i < n; i++)
                    {
                        clip.SampleAnimation(a.gameObject, clip.length * i / n);
                        var hips = a.GetBoneTransform(HumanBodyBones.Hips).position;
                        var fwd = a.transform.forward;
                        f[i] = Vector3.Dot(a.GetBoneTransform(HumanBodyBones.LeftFoot).position - hips, fwd)
                               - Vector3.Dot(a.GetBoneTransform(HumanBodyBones.RightFoot).position - hips, fwd);
                        mean += f[i] / n;
                    }
                    for (var i = 0; i < n; i++) f[i] -= mean;
                    return f;
                }
                var r = Stride(reference);
                var o = Stride(other);
                // En miroir, la gauche devient la droite : la foulée (gauche moins droite) change de signe.
                if (otherMirrored)
                    for (var i = 0; i < n; i++) o[i] = -o[i];
                var best = 0;
                var bestScore = float.MinValue;
                for (var k = 0; k < n; k++)
                {
                    var score = 0f;
                    for (var i = 0; i < n; i++) score += r[i] * o[(i + k) % n];
                    if (score > bestScore)
                    {
                        bestScore = score;
                        best = k;
                    }
                }
                Debug.Log($"[Mika] marche : « {other.name} »{(otherMirrored ? " en miroir" : "")} décalée de {best / (float)n:0.00} cycle pour suivre « {reference.name} ».");
                return best / (float)n;
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        static AnimationClip _rawWalk;
        static Dictionary<string, AnimationClip> _atelier = new Dictionary<string, AnimationClip>();

        /// <summary>Décale tous les enfants d'un mélange d'une même fraction de cycle.</summary>
        static void ShiftTree(BlendTree tree, float offset)
        {
            var children = tree.children;
            for (var i = 0; i < children.Length; i++) children[i].cycleOffset = Mathf.Repeat(children[i].cycleOffset + offset, 1f);
            tree.children = children;
        }

        /// <summary>
        /// Les pieds à plat à l'appui. Retargetées sur elle, les marches capturées posaient un pied pointe en l'air
        /// et l'autre sur la pointe pendant tout l'appui (de 15 à 25°, l'inverse dans la marche lente) : elle
        /// marchait sur un talon et sur une pointe. On mesure sur son squelette l'inclinaison moyenne de chaque pied
        /// quand il est au sol, et on décale d'autant sa courbe « Foot Up-Down » (méthode de Newton, la pente du
        /// muscle mesurée elle aussi). La copie corrigée, dans Generated, remplace la prise.
        /// </summary>
        static AnimationClip FlatFeet(AnimationClip source, string name)
        {
            var path = $"{Generated}/{name}.anim";
            var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(path);
            if (clip == null)
            {
                clip = new AnimationClip { name = name };
                AssetDatabase.CreateAsset(clip, path);
            }
            clip.ClearCurves();
            clip.frameRate = source.frameRate;
            foreach (var b in AnimationUtility.GetCurveBindings(source))
                AnimationUtility.SetEditorCurve(clip, b, AnimationUtility.GetEditorCurve(source, b));
            AnimationUtility.SetAnimationClipSettings(clip, AnimationUtility.GetAnimationClipSettings(source));

            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Mika/Art/Avatars/Mika.prefab");
            if (prefab == null) return clip;
            var go = UnityEngine.Object.Instantiate(prefab);
            go.hideFlags = HideFlags.HideAndDontSave;
            go.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
            try
            {
                var a = go.GetComponentInChildren<Animator>();
                if (a == null || !a.isHuman) return clip;
                // L'inclinaison talon-orteils d'un pied posé à plat : celle du squelette au repos.
                var rest = new float[2];
                for (var s = 0; s < 2; s++) rest[s] = FootSlope(a, s);
                var before = StanceSlope(clip, a, rest);
                var now = before;
                for (var iter = 0; iter < 3; iter++)
                {
                    if (Mathf.Abs(now[0]) < 1f && Mathf.Abs(now[1]) < 1f) break;
                    const float probe = 0.05f;
                    for (var s = 0; s < 2; s++) OffsetMuscle(clip, $"{Sides[s]} Foot Up-Down", probe);
                    var probed = StanceSlope(clip, a, rest);
                    for (var s = 0; s < 2; s++)
                    {
                        var gain = (probed[s] - now[s]) / probe;
                        var step = Mathf.Abs(gain) > 1f ? Mathf.Clamp(-now[s] / gain, -0.6f, 0.6f) : 0f;
                        OffsetMuscle(clip, $"{Sides[s]} Foot Up-Down", step - probe);
                    }
                    now = StanceSlope(clip, a, rest);
                }
                Debug.Log($"[Mika] marche « {source.name} » → {name} : pieds à l'appui {before[0]:+0;-0}°/{before[1]:+0;-0}° → {now[0]:+0;-0}°/{now[1]:+0;-0}° (gauche/droit, + pointe en bas).");
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
            EditorUtility.SetDirty(clip);
            return clip;
        }

        /// <summary>La pente cheville → orteils d'un pied (degrés, + pointe en bas) dans la pose actuelle.</summary>
        static float FootSlope(Animator a, int side)
        {
            var foot = a.GetBoneTransform(side == 0 ? HumanBodyBones.LeftFoot : HumanBodyBones.RightFoot).position;
            var toes = a.GetBoneTransform(side == 0 ? HumanBodyBones.LeftToes : HumanBodyBones.RightToes).position;
            var d = toes - foot;
            return Mathf.Atan2(-d.y, new Vector2(d.x, d.z).magnitude) * Mathf.Rad2Deg;
        }

        /// <summary>
        /// L'inclinaison moyenne de chaque pied (degrés par rapport au pied posé à plat, + pointe en bas) pendant
        /// qu'il est d'appui : bas, et presque immobile au sol (la pose de <c>SampleAnimation</c> garde le
        /// déplacement de la prise).
        /// </summary>
        static float[] StanceSlope(AnimationClip clip, Animator a, float[] rest)
        {
            const int n = 60;
            var dt = clip.length / n;
            var height = new float[2, n + 1];
            var along = new float[2, n + 1];
            var slope = new float[2, n + 1];
            var hips = new float[n + 1];
            for (var i = 0; i <= n; i++)
            {
                clip.SampleAnimation(a.gameObject, i * dt);
                var fwd = a.transform.forward;
                hips[i] = Vector3.Dot(a.GetBoneTransform(HumanBodyBones.Hips).position, fwd);
                for (var s = 0; s < 2; s++)
                {
                    var p = a.GetBoneTransform(s == 0 ? HumanBodyBones.LeftFoot : HumanBodyBones.RightFoot).position;
                    height[s, i] = p.y;
                    along[s, i] = Vector3.Dot(p, fwd);
                    slope[s, i] = FootSlope(a, s) - rest[s];
                }
            }
            var stride = Mathf.Abs(hips[n] - hips[0]) / clip.length;
            var result = new float[2];
            for (var s = 0; s < 2; s++)
            {
                var low = float.MaxValue;
                for (var i = 0; i <= n; i++) low = Mathf.Min(low, height[s, i]);
                var sum = 0f;
                var count = 0;
                for (var i = 1; i < n; i++)
                {
                    var v = (along[s, i + 1] - along[s, i - 1]) / (2f * dt);
                    if (height[s, i] > low + 0.03f || Mathf.Abs(v) > 0.4f * stride) continue;
                    sum += slope[s, i];
                    count++;
                }
                result[s] = count > 0 ? sum / count : 0f;
            }
            return result;
        }

        /// <summary>Décale toute la courbe d'un muscle (les tangentes suivent).</summary>
        static void OffsetMuscle(AnimationClip clip, string muscle, float delta)
        {
            var binding = EditorCurveBinding.FloatCurve("", typeof(Animator), muscle);
            var curve = AnimationUtility.GetEditorCurve(clip, binding);
            if (curve == null) return;
            var keys = curve.keys;
            for (var i = 0; i < keys.Length; i++) keys[i].value += delta;
            curve.keys = keys;
            AnimationUtility.SetEditorCurve(clip, binding, curve);
        }

        /// <summary>
        /// La vitesse (en tailles/s, lecture normale) à laquelle son pied d'appui recule sous ses hanches dans ce
        /// clip, échantillonné sur son squelette : la vitesse au sol pour laquelle ses pieds ne glissent pas. Un pied
        /// est d'appui quand il est à moins d'un centimètre et demi de son point le plus bas. 0 : mesure impossible.
        /// </summary>
        /// <remarks>
        /// <c>SampleAnimation</c> laisse le déplacement de la prise dans la pose (les hanches avancent d'une foulée
        /// sur le clip) : on n'échantillonne donc pas en boucle, la dernière image n'est pas voisine de la première.
        /// Même ainsi, sur ses proportions le pied d'appui de la prise avance encore de ~0,2 m/s : c'est ce que la
        /// vitesse de la racine, seule, ne dit pas.
        /// </remarks>
        static float StanceSweep(AnimationClip clip)
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Mika/Art/Avatars/Mika.prefab");
            if (prefab == null || clip == null || clip.length <= 0f) return 0f;
            var go = UnityEngine.Object.Instantiate(prefab);
            go.hideFlags = HideFlags.HideAndDontSave;
            go.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
            try
            {
                var a = go.GetComponentInChildren<Animator>();
                if (a == null || !a.isHuman || a.humanScale <= 0f) return 0f;
                const int n = 120;
                var dt = clip.length / n;
                var bones = new[] { HumanBodyBones.LeftFoot, HumanBodyBones.RightFoot };
                var foot = new float[2, n + 1];   // le long de la marche, au sol (la pose garde le déplacement)
                var height = new float[2, n + 1];
                var hips = new float[n + 1];
                for (var i = 0; i <= n; i++)
                {
                    clip.SampleAnimation(a.gameObject, i * dt);
                    var fwd = a.transform.forward;
                    hips[i] = Vector3.Dot(a.GetBoneTransform(HumanBodyBones.Hips).position, fwd);
                    for (var s = 0; s < 2; s++)
                    {
                        var p = a.GetBoneTransform(bones[s]).position;
                        foot[s, i] = Vector3.Dot(p, fwd);
                        height[s, i] = p.y;
                    }
                }
                var stride = (hips[n] - hips[0]) / clip.length;
                var sum = 0f;
                var count = 0;
                for (var s = 0; s < 2; s++)
                {
                    var low = float.MaxValue;
                    for (var i = 0; i <= n; i++) low = Mathf.Min(low, height[s, i]);
                    for (var i = 1; i < n; i++)
                    {
                        // D'appui : bas, et presque immobile au sol. La hauteur seule ne suffit pas : en fin de
                        // balancement, la cheville passe au ras du sol alors que le pied file encore vers l'avant.
                        var vFoot = (foot[s, i + 1] - foot[s, i - 1]) / (2f * dt);
                        if (height[s, i] > low + 0.03f || Mathf.Abs(vFoot) > 0.4f * stride) continue;
                        var vHips = (hips[i + 1] - hips[i - 1]) / (2f * dt);
                        sum += vHips - vFoot;
                        count++;
                    }
                }
                if (count < 6) return 0f;
                var sweep = sum / count;
                Debug.Log($"[Mika] marche : « {clip.name} » ({clip.length:0.00} s), son pied d'appui recule de {sweep:0.00} m/s, soit {sweep / a.humanScale:0.000} taille/s.");
                return sweep > 0.05f ? sweep / a.humanScale : 0f;
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        static AnimatorState State(AnimatorStateMachine sm, string name, Motion motion, Vector3 position, string speedParameter, string tag = null)
        {
            var st = sm.AddState(name, position);
            st.motion = motion;
            st.iKOnFeet = false;
            st.writeDefaultValues = true;
            if (tag != null) st.tag = tag;
            if (speedParameter != null)
            {
                st.speedParameterActive = true;
                st.speedParameter = speedParameter;
            }
            return st;
        }

        static AnimatorStateMachine AddLayer(AnimatorController ac, string name, AvatarMask mask, AnimatorLayerBlendingMode mode, bool ikPass)
        {
            var layer = new AnimatorControllerLayer
            {
                name = name, defaultWeight = 1f, avatarMask = mask, blendingMode = mode, iKPass = ikPass,
                stateMachine = new AnimatorStateMachine { name = name },
            };
            AssetDatabase.AddObjectToAsset(layer.stateMachine, ac);
            ac.AddLayer(layer);
            return layer.stateMachine;
        }

        /// <summary>Une transition jouée quand le clip se termine (une transition de posture, un geste).</summary>
        static void After(AnimatorState from, AnimatorState to, float duration, float exitTime = 0.92f)
        {
            var t = from.AddTransition(to);
            t.hasExitTime = true;
            t.exitTime = exitTime;
            t.duration = duration;
        }

        static void Link(AnimatorState from, AnimatorState to, float duration, params (string param, AnimatorConditionMode mode, float value)[] conditions)
        {
            var t = from.AddTransition(to);
            t.hasExitTime = false;
            t.duration = duration;
            foreach (var c in conditions) t.AddCondition(c.mode, c.value, c.param);
        }

        static AvatarMask Mask(string path, params AvatarMaskBodyPart[] parts)
        {
            var mask = AssetDatabase.LoadAssetAtPath<AvatarMask>(path);
            if (mask == null)
            {
                mask = new AvatarMask();
                AssetDatabase.CreateAsset(mask, path);
            }
            for (var p = AvatarMaskBodyPart.Root; p < AvatarMaskBodyPart.LastBodyPart; p++)
                mask.SetHumanoidBodyPartActive(p, parts.Contains(p));
            EditorUtility.SetDirty(mask);
            return mask;
        }

        // --- le catalogue et l'avatar ------------------------------------------------------------------------
        /// <summary>Le catalogue du monde porte le contrôleur commun : la scène le pose sur chaque corps humanoïde.</summary>
        static void AssignToCatalog(AnimatorController controller, BodyClipSet set)
        {
            var catalog = AssetDatabase.LoadAssetAtPath<AssetCatalog>("Assets/Mika/Content/AssetCatalog.asset");
            if (catalog == null) return;
            catalog.humanoidController = controller;
            catalog.bodyClips = set;
            EditorUtility.SetDirty(catalog);
        }
    }
}
