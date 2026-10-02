using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using UniVRM10;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace Mika.Avatar.Editor
{
    /// <summary>
    /// Fait de l'avatar du client web (<c>frontend/public/models/default.vrm</c>, un VRM 0.x) un prefab Unity
    /// prêt à poser : le modèle importé par UniVRM (migré en VRM 1.0), avec son <see cref="Animator"/> humanoïde
    /// sans contrôleur et son <see cref="Vrm10Instance"/>, plus <see cref="MikaFace"/>.
    /// </summary>
    /// <remarks>
    /// <para>
    /// L'import est celui d'UniVRM (<c>VrmScriptedImporter</c>, extension <c>.vrm</c>) avec ses réglages par
    /// défaut : <c>MigrateToVrm1 = true</c> (un VRM 0.x est migré en 1.0 — rotation de 180°, presets renommés
    /// joy→happy, sorrow→sad, fun→relaxed, groupes personnalisés gardés sous leur nom) et un pipeline
    /// « Auto », qui choisit les matériaux URP du projet. Le fichier n'est recopié (et donc réimporté) que s'il a
    /// changé : l'import d'un modèle de 100 Mo coûte de la mémoire, on ne le fait qu'une fois.
    /// </para>
    /// <para>
    /// Le prefab est une VARIANTE du modèle importé : un nouvel export se propage sans rien reconstruire. S'il
    /// existe déjà, il n'est pas recréé — seul ce qui lui manque est ajouté (le visage), pour ne pas écraser ce
    /// qu'un autre outil y a mis (le contrôleur d'animation, notamment). Aucune scène ouverte n'est touchée : la
    /// création passe par une scène de prévisualisation.
    /// </para>
    /// </remarks>
    public static class AvatarImporter
    {
        public const string AvatarsDir = "Assets/Mika/Art/Avatars";
        public const string VrmPath = AvatarsDir + "/default.vrm";
        public const string PrefabPath = AvatarsDir + "/Mika.prefab";

        /// <summary>Rapport du dernier import (expressions trouvées, manques), pour un outil sans fenêtre.</summary>
        public static string ReportPath => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "Temp", "mika-avatar-import.txt"));

        /// <summary>Le modèle du client web, à la racine du dépôt (<c>Assets/</c> est dans <c>UnityFrontend/Mika/</c>).</summary>
        public static string SourcePath =>
            Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "..", "frontend", "public", "models", "default.vrm"));

        [MenuItem("Mika/Avatar/Importer l'avatar du frontend", priority = 10)]
        public static void ImportFromFrontend()
        {
            try
            {
                Import();
            }
            catch (Exception e)
            {
                Debug.LogException(e);
            }
        }

        /// <summary>Copie (si besoin), importe, construit ou complète le prefab. Rend le rapport.</summary>
        public static string Import()
        {
            var source = SourcePath;
            if (!File.Exists(source))
                throw new FileNotFoundException($"[Mika] modèle introuvable : {source} (non versionné : il faut le déposer là).");

            EnsureFolder(AvatarsDir);
            var dest = Path.GetFullPath(Path.Combine(Application.dataPath, "..", VrmPath));
            bool changed = !File.Exists(dest) || !SameContent(source, dest);
            if (changed)
            {
                File.Copy(source, dest, overwrite: true);
                Debug.Log($"[Mika] avatar copié ({new FileInfo(dest).Length / (1024 * 1024)} Mo) → {VrmPath} ; import par UniVRM…");
                AssetDatabase.ImportAsset(VrmPath, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
            }
            else if (AssetDatabase.LoadMainAssetAtPath(VrmPath) == null)
            {
                AssetDatabase.ImportAsset(VrmPath, ImportAssetOptions.ForceSynchronousImport);
            }

            var model = AssetDatabase.LoadAssetAtPath<GameObject>(VrmPath);
            if (model == null)
                throw new InvalidOperationException($"[Mika] UniVRM n'a produit aucun modèle pour {VrmPath} (voir la console : migration VRM 0.x refusée ?).");
            var instance = model.GetComponent<Vrm10Instance>();
            var animator = model.GetComponent<Animator>();
            if (instance == null || instance.Vrm == null)
                throw new InvalidOperationException("[Mika] le modèle importé n'a pas de Vrm10Instance/VRM10Object.");
            if (animator == null || animator.avatar == null || !animator.avatar.isHuman || !animator.avatar.isValid)
                throw new InvalidOperationException("[Mika] le modèle importé n'a pas d'Avatar humanoïde valide.");

            BuildOrUpdatePrefab(model);
            var report = Report(model);
            File.WriteAllText(ReportPath, report);
            Debug.Log($"[Mika] avatar prêt : {PrefabPath} (rapport : {ReportPath})\n{report}");
            return report;
        }

        static void BuildOrUpdatePrefab(GameObject model)
        {
            if (AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath) != null)
            {
                var root = PrefabUtility.LoadPrefabContents(PrefabPath);
                try
                {
                    Configure(root);
                    PrefabUtility.SaveAsPrefabAsset(root, PrefabPath);
                }
                finally
                {
                    PrefabUtility.UnloadPrefabContents(root);
                }
                return;
            }

            // Une scène de prévisualisation : rien n'apparaît dans les scènes ouvertes, rien ne les salit.
            var scene = EditorSceneManager.NewPreviewScene();
            try
            {
                var go = (GameObject)PrefabUtility.InstantiatePrefab(model, scene);
                go.name = "Mika";
                Configure(go);
                PrefabUtility.SaveAsPrefabAsset(go, PrefabPath, out bool ok);
                if (!ok)
                    throw new InvalidOperationException($"[Mika] échec de l'écriture de {PrefabPath}.");
            }
            finally
            {
                EditorSceneManager.ClosePreviewScene(scene);
            }
        }

        /// <summary>Ce que le prefab doit porter. N'enlève rien de ce qu'un autre outil y a mis.</summary>
        static void Configure(GameObject root)
        {
            var face = root.GetComponent<MikaFace>();
            if (face == null)
                face = root.AddComponent<MikaFace>();
            var vrm = root.GetComponent<Vrm10Instance>();
            if (vrm != null)
            {
                // Le lien est explicite dans l'inspecteur (le composant le retrouverait seul, mais un prefab se lit).
                var so = new SerializedObject(face);
                var field = so.FindProperty("vrm");
                if (field != null && field.objectReferenceValue == null)
                {
                    field.objectReferenceValue = vrm;
                    so.ApplyModifiedPropertiesWithoutUndo();
                }
                // Les yeux sont pilotés par le visage (lacet/tangage), jamais par un Transform suivi.
                vrm.LookAtTargetType = VRM10ObjectLookAt.LookAtTargetTypes.YawPitchValue;
                vrm.LookAtTarget = null;
            }
        }

        // ── Rapport ─────────────────────────────────────────────────────────

        static string Report(GameObject model)
        {
            var vrm = model.GetComponent<Vrm10Instance>().Vrm;
            var animator = model.GetComponent<Animator>();
            var renderers = model.GetComponentsInChildren<SkinnedMeshRenderer>(true);
            var morphs = new HashSet<string>(StringComparer.Ordinal);
            foreach (var r in renderers)
                if (r.sharedMesh != null)
                    for (int i = 0; i < r.sharedMesh.blendShapeCount; i++)
                        morphs.Add(r.sharedMesh.GetBlendShapeName(i));

            var presets = new List<string>();
            var customs = new List<string>();
            var clips = new Dictionary<string, VRM10Expression>(StringComparer.Ordinal);
            foreach (var (preset, clip) in vrm.Expression.Clips)
            {
                string name = preset == ExpressionPreset.custom ? clip.name : preset.ToString();
                (preset == ExpressionPreset.custom ? customs : presets).Add(name);
                clips[name] = clip;
            }

            var sb = new StringBuilder();
            sb.AppendLine($"modèle : {VrmPath} → prefab {PrefabPath}");
            sb.AppendLine($"Animator : humanoïde={animator.avatar.isHuman}, valide={animator.avatar.isValid}, contrôleur={(animator.runtimeAnimatorController != null ? animator.runtimeAnimatorController.name : "aucun")}");
            sb.AppendLine($"maillages à morphs : {renderers.Length}, morphs distincts : {morphs.Count}");
            sb.AppendLine($"regard : {vrm.LookAt.LookAtType}, horizontal ext. {vrm.LookAt.HorizontalOuter.CurveXRangeDegree}°→{vrm.LookAt.HorizontalOuter.CurveYRangeDegree}, " +
                          $"bas {vrm.LookAt.VerticalDown.CurveXRangeDegree}°→{vrm.LookAt.VerticalDown.CurveYRangeDegree}, haut {vrm.LookAt.VerticalUp.CurveXRangeDegree}°→{vrm.LookAt.VerticalUp.CurveYRangeDegree}");
            sb.AppendLine($"presets ({presets.Count}) : {string.Join(", ", presets)}");
            sb.AppendLine($"groupes ({customs.Count}) : {string.Join(", ", customs)}");

            var rich = EmotionFace.RichMap.Values.SelectMany(r => r.Keys).Append(EmotionFace.TiredGroup).Distinct().ToList();
            var richMissing = rich.Where(g => !clips.ContainsKey(g)).ToList();
            int richEmotions = Emotions.All.Count(e => EmotionFace.RichMap[e].Count > 0 && EmotionFace.RichMap[e].Keys.All(clips.ContainsKey));
            sb.AppendLine($"émotions sur les groupes riches : {richEmotions}/{Emotions.All.Count}" +
                          (richMissing.Count > 0 ? $" — groupes absents : {string.Join(", ", richMissing)}" : ""));

            var stripped = new List<string>();
            foreach (var group in rich.Where(clips.ContainsKey))
            {
                var removed = clips[group].MorphTargetBindings
                    .Select(b => MorphName(model.transform, b))
                    .Where(m => m != null && FaceNames.IsStripped(m))
                    .Distinct()
                    .ToList();
                if (removed.Count > 0)
                    stripped.Add($"{group} [{string.Join(", ", removed)}]");
            }
            sb.AppendLine($"symboles/regard retirés au nettoyage : {(stripped.Count > 0 ? string.Join(" ; ", stripped) : "aucun")}");

            var vrc = VisemeRouting.VrcMorphs().ToList();
            sb.AppendLine($"visèmes VRChat : {vrc.Count(morphs.Contains)}/{vrc.Count}" +
                          (vrc.Any(m => !morphs.Contains(m)) ? $" (absents : {string.Join(", ", vrc.Where(m => !morphs.Contains(m)))})" : ""));
            sb.AppendLine($"presets de bouche : {string.Join(", ", VisemeRouting.MouthPresets.Where(clips.ContainsKey))}");
            sb.AppendLine($"physiologie : {string.Join(", ", FacePhysiology.Morphs.Select(m => morphs.Contains(m) ? m : m + "(absent)"))}");
            var idle = FaceIdleModel.CandidateShapes().ToList();
            sb.AppendLine($"micro-expressions perfect sync : {idle.Count(clips.ContainsKey)}/{idle.Count}" +
                          (idle.Any(n => !clips.ContainsKey(n)) ? $" (absentes : {string.Join(", ", idle.Where(n => !clips.ContainsKey(n)))})" : ""));
            sb.AppendLine($"clignement : {(clips.ContainsKey("blink") ? "preset blink" : "ABSENT")}");
            return sb.ToString();
        }

        static string MorphName(Transform root, MorphTargetBinding b)
        {
            var t = root.Find(b.RelativePath);
            var r = t != null ? t.GetComponent<SkinnedMeshRenderer>() : null;
            if (r == null || r.sharedMesh == null || b.Index < 0 || b.Index >= r.sharedMesh.blendShapeCount)
                return null;
            return r.sharedMesh.GetBlendShapeName(b.Index);
        }

        // ── Fichiers ────────────────────────────────────────────────────────

        static void EnsureFolder(string assetPath)
        {
            if (AssetDatabase.IsValidFolder(assetPath))
                return;
            var parent = Path.GetDirectoryName(assetPath)?.Replace('\\', '/');
            if (!string.IsNullOrEmpty(parent))
                EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, Path.GetFileName(assetPath));
        }

        /// <summary>Même taille et même empreinte, lus en flux (100 Mo ne passent pas en mémoire d'un bloc).</summary>
        static bool SameContent(string a, string b)
        {
            if (new FileInfo(a).Length != new FileInfo(b).Length)
                return false;
            using (var sha = SHA256.Create())
            {
                byte[] ha, hb;
                using (var fa = File.OpenRead(a))
                    ha = sha.ComputeHash(fa);
                using (var fb = File.OpenRead(b))
                    hb = sha.ComputeHash(fb);
                return ha.SequenceEqual(hb);
            }
        }
    }
}
