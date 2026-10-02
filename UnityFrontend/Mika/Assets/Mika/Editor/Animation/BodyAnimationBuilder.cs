using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Mika.World.Engine;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace Mika.Editor.Animation
{
    /// <summary>
    /// Les animations du corps de Mika : les clips Mixamo du client web importés en humanoïde (Mecanim les
    /// retarget sur n'importe quel avatar), les clips qui manquent générés en muscles humanoïdes à partir de sa
    /// vraie pose de repos (marcher, s'asseoir, s'allonger, tendre la main), et le contrôleur qui les joue selon
    /// le contrat <see cref="BodyAnim"/>. Un clip Mixamo téléchargé plus tard (« locomotion/walking.fbx ») prend
    /// la place du clip généré au prochain passage : rien d'autre à changer.
    /// </summary>
    public static class BodyAnimationBuilder
    {
        const string Root = "Assets/Mika/Art/Animations";
        const string Generated = Root + "/Generated";
        const string ControllerPath = Root + "/MikaBody.controller";
        const string UpperMaskPath = Root + "/UpperBody.mask";
        const string ArmMaskPath = Root + "/RightArm.mask";
        static string Source => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "..", "frontend", "public", "animations"));

        /// <summary>Les catégories du client web qui bouclent (une attente, une parole, une marche).</summary>
        static readonly HashSet<string> Looping = new HashSet<string> { "idle", "talk", "locomotion", "sleep" };

        /// <summary>Le clip Mixamo qui remplace un clip généré, s'il est téléchargé (nom de fichier sans extension).</summary>
        static readonly Dictionary<string, string[]> Preferred = new Dictionary<string, string[]>
        {
            ["walk"] = new[] { "walking", "female_walk", "walk" },
            ["sit"] = new[] { "sitting_idle", "sitting" },
            ["lie"] = new[] { "sleeping_idle", "laying_idle", "lying" },
            ["reach"] = new[] { "picking_up_object", "picking_up" },
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
            var clips = ImportMixamo();
            var base_ = BasePose(clips.TryGetValue("idle_breathing", out var idle) ? idle : clips.Values.FirstOrDefault());
            var generated = GenerateClips(base_);
            foreach (var kv in Preferred)
            {
                var found = kv.Value.Select(n => clips.TryGetValue(n, out var c) ? c : null).FirstOrDefault(c => c != null);
                if (found != null) generated[kv.Key] = found;
            }
            var controller = BuildController(clips, generated);
            AssignToCatalog(controller);
            AssetDatabase.SaveAssets();
            Debug.Log($"[Mika] animations : {clips.Count} clips Mixamo, {generated.Count} clips de corps, contrôleur {ControllerPath}.");
        }

        // --- clips Mixamo -----------------------------------------------------------------------------------
        static Dictionary<string, AnimationClip> ImportMixamo()
        {
            var result = new Dictionary<string, AnimationClip>();
            if (!Directory.Exists(Source))
            {
                Debug.LogWarning($"[Mika] pas de dossier d'animations du client web ({Source}).");
                return result;
            }
            foreach (var file in Directory.GetFiles(Source, "*.fbx", SearchOption.AllDirectories))
            {
                var category = Path.GetFileName(Path.GetDirectoryName(file));
                var dir = $"{Root}/{category}";
                Import.RoomImporter.Ensure(dir);
                var dst = $"{dir}/{Path.GetFileName(file)}";
                var full = Path.GetFullPath(Path.Combine(Application.dataPath, "..", dst));
                if (!File.Exists(full) || File.GetLastWriteTimeUtc(full) < File.GetLastWriteTimeUtc(file))
                {
                    File.Copy(file, full, true);
                    AssetDatabase.ImportAsset(dst, ImportAssetOptions.ForceSynchronousImport);
                }
                ConfigureClip(dst, Looping.Contains(category));
                var clip = AssetDatabase.LoadAllAssetsAtPath(dst).OfType<AnimationClip>().FirstOrDefault(c => !c.name.StartsWith("__preview__"));
                if (clip != null) result[Path.GetFileNameWithoutExtension(dst)] = clip;
            }
            return result;
        }

        static void ConfigureClip(string path, bool loop)
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
                // Sur place : le noyau et le navmesh déplacent le corps ; le clip ne fait que l'animer.
                if (c.loopTime == loop && c.lockRootRotation && c.lockRootHeightY && c.lockRootPositionXZ && c.keepOriginalPositionY) continue;
                c.loopTime = loop;
                c.lockRootRotation = true;
                c.lockRootHeightY = true;
                c.lockRootPositionXZ = true;
                c.keepOriginalOrientation = true;
                c.keepOriginalPositionY = true;
                c.keepOriginalPositionXZ = true;
                dirty = true;
            }
            if (!dirty) return;
            mi.clipAnimations = clips;
            mi.SaveAndReimport();
        }

        // --- clips générés ----------------------------------------------------------------------------------
        /// <summary>La pose de repos de Mika : les muscles du premier instant de son clip d'attente.</summary>
        static Dictionary<string, float> BasePose(AnimationClip idle)
        {
            // Les noms tels que les clips humanoïdes les écrivent (les doigts s'y nomment « LeftHand.Index.1
            // Stretched », pas comme dans HumanTrait) : on part des courbes du clip d'attente lui-même.
            var pose = new Dictionary<string, float>();
            if (idle != null)
                foreach (var b in AnimationUtility.GetCurveBindings(idle))
                {
                    if (b.type != typeof(Animator)) continue;
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
            return new Dictionary<string, AnimationClip>
            {
                ["walk"] = Save("body_walk", Walk(base_), loop: true),
                ["sit"] = Save("body_sit", Sit(base_), loop: true),
                ["lie"] = Save("body_lie", Lie(base_), loop: true),
                ["reach"] = Save("body_reach", Reach(base_), loop: false),
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

        /// <summary>Marcher : 1,1 s par cycle, jambes en opposition, genou plié au passage, bras en contre-temps.</summary>
        static Track Walk(Dictionary<string, float> b)
        {
            var t = new Track();
            const float cycle = 1.1f;
            var times = Enumerable.Range(0, 9).Select(i => cycle * i / 8f).ToArray();
            t.Base(b, times);
            foreach (var time in times)
            {
                var phase = time / cycle * Mathf.PI * 2f;
                for (var s = 0; s < 2; s++)
                {
                    var side = Sides[s];
                    var p = phase + (s == 0 ? 0 : Mathf.PI);
                    t.Offset(b, $"{side} Upper Leg Front-Back", time, LegSign * 0.42f * Mathf.Sin(p));
                    // Le genou plie quand la jambe repasse devant (phase de balancement).
                    t.Offset(b, $"{side} Lower Leg Stretch", time, -0.55f * Mathf.Max(0f, Mathf.Sin(p + 1.3f)));
                    t.Offset(b, $"{side} Foot Up-Down", time, 0.15f * Mathf.Sin(p + 0.5f));
                    t.Offset(b, $"{side} Arm Front-Back", time, -0.22f * Mathf.Sin(p));
                }
                t.Key("RootT.y", time, b.TryGetValue("RootT.y", out var y) ? y + 0.012f * Mathf.Abs(Mathf.Cos(phase)) : 1f);
                t.Offset(b, "Spine Twist Left-Right", time, 0.06f * Mathf.Sin(phase));
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
                    t.Offset(b, $"{side} Upper Leg Front-Back", time, 0f);
                    t.Offset(b, $"{side} Arm Down-Up", time, -0.15f);
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

        // --- contrôleur ---------------------------------------------------------------------------------------
        static AnimatorController BuildController(Dictionary<string, AnimationClip> mixamo, Dictionary<string, AnimationClip> body)
        {
            // Le même asset d'une reconstruction à l'autre (même GUID) : l'avatar et les scènes qui le
            // référencent ne le perdent pas. On le vide, puis on le remplit.
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
            ac.AddParameter("Speed", AnimatorControllerParameterType.Float);
            ac.AddParameter("Posture", AnimatorControllerParameterType.Int);
            ac.AddParameter("Gesture", AnimatorControllerParameterType.Trigger);
            ac.AddParameter("GestureId", AnimatorControllerParameterType.Int);
            ac.AddParameter("Holding", AnimatorControllerParameterType.Bool);
            ac.AddParameter("Talking", AnimatorControllerParameterType.Bool);
            ac.AddParameter("Reach", AnimatorControllerParameterType.Trigger);
            ac.AddParameter("Activity", AnimatorControllerParameterType.Int);
            ac.AddParameter("Asleep", AnimatorControllerParameterType.Bool);

            // Base : debout (attente ↔ marche), debout en parlant, assise, allongée.
            var layers = ac.layers;
            layers[0].iKPass = true;
            ac.layers = layers;
            var sm = ac.layers[0].stateMachine;
            var idle = mixamo.TryGetValue("idle_breathing", out var ib) ? ib : body["sit"];
            var talk = mixamo.TryGetValue("talk_main", out var tm) ? tm : idle;

            var stand = sm.AddState("Debout", new Vector3(300, 0));
            stand.motion = Blend(ac, "Debout (vitesse)", idle, body["walk"]);
            var standTalk = sm.AddState("Debout, parle", new Vector3(300, 100));
            standTalk.motion = Blend(ac, "Parle (vitesse)", talk, body["walk"]);
            var sit = sm.AddState("Assise", new Vector3(600, 0));
            sit.motion = body["sit"];
            var lie = sm.AddState("Allongée", new Vector3(600, 150));
            lie.motion = body["lie"];
            sm.defaultState = stand;

            Link(stand, standTalk, 0.3f, ("Talking", AnimatorConditionMode.If, 0));
            Link(standTalk, stand, 0.5f, ("Talking", AnimatorConditionMode.IfNot, 0));
            foreach (var from in new[] { stand, standTalk })
            {
                Link(from, sit, 0.6f, ("Posture", AnimatorConditionMode.Equals, 1));
                Link(from, lie, 0.8f, ("Posture", AnimatorConditionMode.Equals, 2));
            }
            Link(sit, stand, 0.6f, ("Posture", AnimatorConditionMode.Equals, 0));
            Link(sit, lie, 0.8f, ("Posture", AnimatorConditionMode.Equals, 2));
            Link(lie, stand, 0.8f, ("Posture", AnimatorConditionMode.Equals, 0));
            Link(lie, sit, 0.8f, ("Posture", AnimatorConditionMode.Equals, 1));

            // Gestes : le haut du corps, par-dessus.
            var upper = Mask(UpperMaskPath, AvatarMaskBodyPart.Body, AvatarMaskBodyPart.Head, AvatarMaskBodyPart.LeftArm, AvatarMaskBodyPart.RightArm,
                AvatarMaskBodyPart.LeftFingers, AvatarMaskBodyPart.RightFingers, AvatarMaskBodyPart.LeftHandIK, AvatarMaskBodyPart.RightHandIK);
            var gestures = new AnimatorControllerLayer { name = "Gestes", defaultWeight = 1f, avatarMask = upper, stateMachine = new AnimatorStateMachine { name = "Gestes" }, iKPass = true };
            AssetDatabase.AddObjectToAsset(gestures.stateMachine, ac);
            ac.AddLayer(gestures);
            var gsm = gestures.stateMachine;
            var none = gsm.AddState("Rien", new Vector3(300, 0));
            gsm.defaultState = none;
            for (var id = 1; id < BodyAnim.Gestures.Length; id++)
            {
                var name = BodyAnim.Gestures[id];
                if (!GestureClips.TryGetValue(name, out var clipName) || !mixamo.TryGetValue(clipName, out var clip)) continue;
                var st = gsm.AddState(name, new Vector3(600, 40 * id));
                st.motion = clip;
                var enter = gsm.AddAnyStateTransition(st);
                enter.hasExitTime = false;
                enter.duration = 0.25f;
                enter.canTransitionToSelf = false;
                enter.AddCondition(AnimatorConditionMode.If, 0, "Gesture");
                enter.AddCondition(AnimatorConditionMode.Equals, id, "GestureId");
                var back = st.AddTransition(none);
                back.hasExitTime = true;
                back.exitTime = 0.88f;
                back.duration = 0.35f;
            }

            // Tendre la main : le bras droit, déclenché par Reach (l'IK fait le reste).
            var arm = Mask(ArmMaskPath, AvatarMaskBodyPart.RightArm, AvatarMaskBodyPart.RightFingers, AvatarMaskBodyPart.Body);
            var reach = new AnimatorControllerLayer { name = "Main", defaultWeight = 1f, avatarMask = arm, stateMachine = new AnimatorStateMachine { name = "Main" } };
            AssetDatabase.AddObjectToAsset(reach.stateMachine, ac);
            ac.AddLayer(reach);
            var rsm = reach.stateMachine;
            var rest = rsm.AddState("Repos", new Vector3(300, 0));
            rsm.defaultState = rest;
            var reaching = rsm.AddState("Tendre", new Vector3(600, 0));
            reaching.motion = body["reach"];
            var go = rest.AddTransition(reaching);
            go.hasExitTime = false;
            go.duration = 0.15f;
            go.AddCondition(AnimatorConditionMode.If, 0, "Reach");
            var done = reaching.AddTransition(rest);
            done.hasExitTime = true;
            done.exitTime = 0.95f;
            done.duration = 0.2f;

            EditorUtility.SetDirty(ac);
            return ac;
        }

        static BlendTree Blend(AnimatorController ac, string name, Motion still, Motion walk)
        {
            var tree = new BlendTree { name = name, blendType = BlendTreeType.Simple1D, blendParameter = "Speed", useAutomaticThresholds = false };
            AssetDatabase.AddObjectToAsset(tree, ac);
            tree.AddChild(still, 0f);
            tree.AddChild(walk, 0.9f);
            return tree;
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
        static void AssignToCatalog(AnimatorController controller)
        {
            var catalog = AssetDatabase.LoadAssetAtPath<AssetCatalog>("Assets/Mika/Content/AssetCatalog.asset");
            if (catalog == null) return;
            catalog.humanoidController = controller;
            EditorUtility.SetDirty(catalog);
        }
    }
}
