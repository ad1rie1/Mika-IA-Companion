using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using UniVRM10;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace Mika.Avatar.Editor
{
    /// <summary>
    /// Vérifie <see cref="MikaFace"/> sur le vrai modèle, sans mode jeu et sans toucher aux scènes ouvertes : le
    /// prefab est posé dans une scène de prévisualisation, le visage est avancé à pas fixe, et ce qui arrive
    /// jusqu'aux maillages est relevé (une émotion, le nettoyage des symboles, la parole et ses repères, la
    /// physiologie, le regard, l'énergie, le sommeil). Rapport dans <c>Temp/mika-avatar-check.txt</c>.
    /// </summary>
    public static class AvatarFaceCheck
    {
        public static string ReportPath => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "Temp", "mika-avatar-check.txt"));

        [MenuItem("Mika/Avatar/Vérifier le visage sur le modèle", priority = 11)]
        public static void RunFromMenu()
        {
            try
            {
                Debug.Log("[Mika] vérification du visage :\n" + Run());
            }
            catch (Exception e)
            {
                Debug.LogException(e);
            }
        }

        public static string Run()
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(AvatarImporter.PrefabPath);
            if (prefab == null)
                throw new InvalidOperationException($"[Mika] pas de prefab {AvatarImporter.PrefabPath} : importer l'avatar d'abord.");
            var sb = new StringBuilder();
            var scene = EditorSceneManager.NewPreviewScene();
            GameObject go = null;
            MikaFace face = null;
            Vrm10Instance vrm = null;
            const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
            try
            {
                go = (GameObject)PrefabUtility.InstantiatePrefab(prefab, scene);
                face = go.GetComponent<MikaFace>();
                vrm = go.GetComponent<Vrm10Instance>();
                typeof(MikaFace).GetMethod("Awake", flags).Invoke(face, null);
                typeof(MikaFace).GetMethod("Start", flags).Invoke(face, null);
                var step = typeof(MikaFace).GetMethod("Step", flags);
                var rt = vrm.Runtime;
                var ex = rt.Expression;
                float W(string n) => ex.GetWeight(ExpressionKey.CreateCustom(n));
                var peaks = new Dictionary<string, float>();
                void Run(float seconds)
                {
                    for (float s = 0f; s < seconds; s += 1f / 60f)
                    {
                        step.Invoke(face, new object[] { 1f / 60f });
                        foreach (var n in new[] { "raw:vrc.v_pp", "raw:vrc.v_aa", "raw:vrc.v_oh", "raw:vrc.v_ff" })
                            peaks[n] = Math.Max(peaks.TryGetValue(n, out var m) ? m : 0f, W(n));
                    }
                }

                sb.AppendLine($"prêt={face.IsReady} bouche={face.LipSyncMode} émotions riches={face.RichEmotionCount}/29 clés runtime={ex.ExpressionKeys.Count}");

                // Une émotion, jusqu'au maillage — et les symboles du groupe d'auteur n'y arrivent pas.
                face.ShowEmotion("surprised", 1f, null, false);
                Run(0.5f);
                sb.AppendLine($"surprised : clean:Shocked={W("clean:Shocked"):0.00} Shocked(groupe d'origine)={W("Shocked"):0.00}");
                rt.Process();
                var renderers = go.GetComponentsInChildren<SkinnedMeshRenderer>(true);
                float Morph(string name)
                {
                    float best = 0f;
                    foreach (var r in renderers)
                    {
                        int i = r.sharedMesh != null ? r.sharedMesh.GetBlendShapeIndex(name) : -1;
                        if (i >= 0)
                            best = Math.Max(best, r.GetBlendShapeWeight(i));
                    }
                    return best;
                }
                var clean = vrm.Vrm.Expression.CustomClips.First(c => c != null && c.name == "clean:Shocked");
                var kept = clean.MorphTargetBindings.Select(b =>
                {
                    var r = go.transform.Find(b.RelativePath).GetComponent<SkinnedMeshRenderer>();
                    return r.sharedMesh.GetBlendShapeName(b.Index);
                }).ToList();
                sb.AppendLine($"maillage, visage surpris : {string.Join(", ", kept.Select(k => $"{k}={Morph(k):0}"))} ; Eye@@={Morph("Eye@@"):0} FaceSweat={Morph("FaceSweat"):0} FaceShadow2={Morph("FaceShadow2"):0}");
                ex.SetWeight(ExpressionKey.CreateCustom("Shocked"), 1f);
                rt.Process();
                sb.AppendLine($"témoin, groupe d'origine « Shocked » à 1 : Eye@@={Morph("Eye@@"):0} FaceSweat={Morph("FaceSweat"):0} FaceShadow2={Morph("FaceShadow2"):0}");
                ex.SetWeight(ExpressionKey.CreateCustom("Shocked"), 0f);

                // La parole, ses repères, sa fin.
                int ended = 0;
                var cues = new List<string>();
                var beats = new List<string>();
                face.SpeechEnded += () => ended++;
                face.ProsodicCue += c => cues.Add(c);
                face.BeatReached += b => beats.Add(b.Kind.ToString());
                face.ShowEmotion("happy", 0.7f, null, false);
                float d = face.Speak("papa [SIGH] maman, vraiment ?", 1f);
                peaks.Clear();
                Run(d + 0.3f);
                sb.AppendLine($"parole : durée estimée={d:0.00} s, pics pp={peaks["raw:vrc.v_pp"]:0.00} aa={peaks["raw:vrc.v_aa"]:0.00} oh={peaks["raw:vrc.v_oh"]:0.00} ff={peaks["raw:vrc.v_ff"]:0.00}, " +
                              $"SpeechEnded×{ended}, repères=[{string.Join(",", cues)}], temps=[{string.Join(",", beats)}], parle encore={face.IsSpeaking}");
                float d2 = face.Speak("une longue phrase qu'on coupe", 1f);
                Run(0.2f);
                face.StopSpeaking();
                Run(0.3f);
                sb.AppendLine($"coupure : durée={d2:0.00} s, SpeechEnded×{ended}, bouche après 0,3 s : aa={W("raw:vrc.v_aa"):0.000}");

                // La dérive d'humeur attend la fin de la phrase.
                face.Speak("je parle encore un peu", 1f);
                Run(0.1f);
                face.ShowEmotion("sad", 0.8f, null, true);
                Run(0.1f);
                string during = face.CurrentEmotion;
                face.StopSpeaking();
                sb.AppendLine($"dérive pendant la parole : émotion pendant={during}, après la fin={face.CurrentEmotion}");

                // Physiologie.
                face.ShowEmotion("embarrassed", 0.9f, null, false);
                Run(5f);
                sb.AppendLine($"embarrassed 0,9 / 5 s : raw:FaceRed={W("raw:FaceRed"):0.00} clean:Shy={W("clean:Shy"):0.00}");
                face.ShowEmotion("sad", 0.95f, null, false);
                Run(10f);
                sb.AppendLine($"sad 0,95 / 10 s : raw:EyeWatery={W("raw:EyeWatery"):0.00} raw:Tear={W("raw:Tear"):0.00}");
                face.ShowEmotion("sad", 0.5f, null, false);
                Run(1f);

                // Le regard : une cible à SA droite (+X d'un VRM 1.0 qui regarde +Z).
                face.ShowEmotion("neutral", 0.5f, null, false);
                var head = vrm.Humanoid.Head;
                face.LookAt((Vector3?)(head.position + go.transform.forward + go.transform.right * 0.2f));
                Run(0.4f);
                var yp = rt.LookAt.LookAtInput.YawPitch;
                rt.Process();
                var leftEye = vrm.Humanoid.GetBoneTransform(HumanBodyBones.LeftEye);
                sb.AppendLine($"regard vers sa droite : entrée UniVRM yaw={(yp.HasValue ? yp.Value.Yaw : float.NaN):0.0}° pitch={(yp.HasValue ? yp.Value.Pitch : float.NaN):0.0}°, " +
                              $"sémantique yaw={face.EyeAngles.Yaw:0.000} rad (attendu < 0), état={face.Attention}, " +
                              $"œil gauche (avant de l'œil · droite du modèle)={(leftEye != null ? Vector3.Dot(leftEye.forward, go.transform.right) : float.NaN):0.000}");

                // Énergie, sommeil.
                face.SetEnergy(0.1f);
                Run(4f);
                sb.AppendLine($"énergie 0,1 : clean:Sleepy={W("clean:Sleepy"):0.00}");
                face.SetSleepPhase("deep_sleep");
                Run(3f);
                sb.AppendLine($"deep_sleep : blink={ex.GetWeight(ExpressionKey.Blink):0.00} attention={face.Attention}");
                face.SetSleepPhase("awake");
                Run(1.5f);
                sb.AppendLine($"réveil 1,5 s : blink={ex.GetWeight(ExpressionKey.Blink):0.00} ; micro BrowInnerUp={W("BrowInnerUp"):0.000}");
            }
            finally
            {
                if (vrm != null)
                    vrm.DisposeRuntime();
                if (face != null && typeof(MikaFace).GetField("_rig", flags)?.GetValue(face) is FaceRig rig)
                {
                    foreach (var o in (List<UnityEngine.Object>)typeof(FaceRig).GetField("_created", flags).GetValue(rig))
                        if (o != null)
                            UnityEngine.Object.DestroyImmediate(o);
                }
                if (go != null)
                    UnityEngine.Object.DestroyImmediate(go);
                EditorSceneManager.ClosePreviewScene(scene);
            }
            var report = sb.ToString();
            File.WriteAllText(ReportPath, report);
            return report;
        }
    }
}
