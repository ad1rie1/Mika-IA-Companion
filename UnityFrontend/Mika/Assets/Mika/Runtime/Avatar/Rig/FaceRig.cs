using System;
using System.Collections.Generic;
using System.Linq;
using UniVRM10;
using UnityEngine;

namespace Mika.Avatar
{
    /// <summary>
    /// Ce que le visage enregistre sur le modèle chargé, à travers l'API d'expressions d'UniVRM 1.0 — l'équivalent
    /// de <c>frontend/src/vtuber/faceRig.ts</c>.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Le <see cref="VRM10Object"/> de l'instance est d'abord COPIÉ (<see cref="UnityEngine.Object.Instantiate"/>) :
    /// les expressions ajoutées vivent sur la copie, jamais sur l'asset importé, que l'éditeur partage avec tout
    /// le reste du projet. Les clips d'origine restent partagés (la copie ne duplique que les références).
    /// </para>
    /// <para>
    /// Deux familles ajoutées, comme sur le web : <c>clean:&lt;Groupe&gt;</c> — la copie d'un groupe de l'auteur
    /// sans les liaisons vers un symbole manga (<see cref="FaceNames.SymbolMorphs"/>) ni vers une direction de
    /// regard (<c>eyeLook*</c>) ; seules les liaisons de morphs sont reprises, comme le fait <c>faceRig.ts</c> (les
    /// liaisons de couleur de matériau d'un groupe ne passent pas dans sa copie) — et <c>raw:&lt;morph&gt;</c>, un
    /// morph seul exposé comme expression, une liaison par maillage qui le porte.
    /// </para>
    /// <para>
    /// UniVRM recompose chaque morph comme la SOMME des liaisons pondérées de toutes les expressions : deux
    /// expressions qui touchent le même morph s'additionnent, exactement comme les liaisons VRM de three-vrm.
    /// </para>
    /// </remarks>
    public sealed class FaceRig
    {
        /// <summary>Les presets d'émotion que le repli standard utilise : joués eux aussi à travers une copie
        /// nettoyée, pour qu'un modèle sans groupes riches ne dessine pas non plus de symboles.</summary>
        static readonly string[] EmotionPresets = { "happy", "angry", "sad", "relaxed", "surprised", "neutral" };

        readonly Transform _root;
        readonly VRM10Object _vrm;
        readonly Dictionary<string, ExpressionKey> _keys = new Dictionary<string, ExpressionKey>(StringComparer.Ordinal);
        readonly Dictionary<string, VRM10Expression> _clips = new Dictionary<string, VRM10Expression>(StringComparer.Ordinal);
        readonly HashSet<string> _cleanGroups = new HashSet<string>(StringComparer.Ordinal);
        readonly HashSet<string> _rawMorphs = new HashSet<string>(StringComparer.Ordinal);
        readonly Dictionary<string, string> _alias = new Dictionary<string, string>(StringComparer.Ordinal);
        readonly Dictionary<string, float> _mouthInvolvement = new Dictionary<string, float>(StringComparer.Ordinal);
        readonly List<string> _strippedReport = new List<string>();
        readonly List<UnityEngine.Object> _created = new List<UnityEngine.Object>();

        /// <summary>La copie du <see cref="VRM10Object"/> qui porte les expressions ajoutées.</summary>
        public VRM10Object Vrm => _vrm;

        /// <summary>Les groupes nettoyés et ce que le nettoyage leur a retiré (« Shocked: Eye@@, FaceSweat ») —
        /// pour le journal et le rapport d'import.</summary>
        public IReadOnlyList<string> StrippedReport => _strippedReport;

        /// <summary>Tous les noms d'expression connus (presets, groupes, copies, morphs bruts).</summary>
        public IEnumerable<string> Names => _keys.Keys;

        /// <summary>
        /// Prépare le visage d'une instance VRM 1.0. À appeler AVANT que l'instance ne crée son
        /// <c>Vrm10Runtime</c> ; sinon l'appelant recharge les expressions (<see cref="Apply"/> le fait).
        /// </summary>
        public FaceRig(Vrm10Instance instance, IEnumerable<string> groupsToClean, IEnumerable<string> rawMorphs)
        {
            if (instance == null)
                throw new ArgumentNullException(nameof(instance));
            if (instance.Vrm == null)
                throw new InvalidOperationException("Vrm10Instance sans VRM10Object");
            _root = instance.transform;
            _vrm = UnityEngine.Object.Instantiate(instance.Vrm);
            _vrm.name = instance.Vrm.name + " (Mika)";
            _created.Add(_vrm);

            var sources = new Dictionary<string, VRM10Expression>(StringComparer.Ordinal);
            foreach (var (preset, clip) in _vrm.Expression.Clips.ToList())
            {
                string name = preset == ExpressionPreset.custom ? clip.name : preset.ToString();
                if (!sources.ContainsKey(name))
                    sources[name] = clip;
            }

            foreach (var group in groupsToClean.Concat(EmotionPresets).Distinct())
            {
                if (!sources.TryGetValue(group, out var source) || source == null)
                    continue;
                var clean = CleanCopy(source, FaceNames.Clean(group));
                _created.Add(clean);
                _vrm.Expression.AddClip(ExpressionPreset.custom, clean);
                _cleanGroups.Add(group);
            }

            var renderers = _root.GetComponentsInChildren<SkinnedMeshRenderer>(true);
            foreach (var morph in rawMorphs.Distinct())
            {
                var binds = new List<MorphTargetBinding>();
                foreach (var r in renderers)
                {
                    var mesh = r.sharedMesh;
                    if (mesh == null)
                        continue;
                    int index = mesh.GetBlendShapeIndex(morph);
                    if (index >= 0)
                        binds.Add(new MorphTargetBinding(RelativePath(_root, r.transform), index, 1f));
                }
                if (binds.Count == 0)
                    continue;
                var clip = ScriptableObject.CreateInstance<VRM10Expression>();
                clip.name = FaceNames.Raw(morph);
                clip.MorphTargetBindings = binds.ToArray();
                _created.Add(clip);
                _vrm.Expression.AddClip(ExpressionPreset.custom, clip);
                _rawMorphs.Add(morph);
            }

            // Noms → clés : les presets sous leur nom VRM 1.0 (happy, blink, aa…), puis les groupes et copies sous
            // le leur. Un groupe d'auteur qui porterait le nom d'un preset ne l'écrase pas.
            foreach (var (preset, clip) in _vrm.Expression.Clips)
            {
                var key = _vrm.Expression.CreateKey(clip);
                string name = preset == ExpressionPreset.custom ? key.Name : preset.ToString();
                if (_keys.ContainsKey(name))
                    continue;
                _keys[name] = key;
                _clips[name] = clip;
            }
            foreach (var preset in EmotionPresets)
                if (_cleanGroups.Contains(preset))
                    _alias[preset] = FaceNames.Clean(preset);

            instance.Vrm = _vrm;
        }

        /// <summary>
        /// Branche la copie sur le runtime : si l'instance a déjà construit son <c>Vrm10Runtime</c> avec l'ancien
        /// objet, ses expressions sont rechargées (<c>Vrm10RuntimeExpression.Reload</c>, prévu pour ça).
        /// </summary>
        public void Apply(Vrm10Instance instance)
        {
            var runtime = instance.Runtime;
            bool known = false;
            foreach (var key in runtime.Expression.ExpressionKeys)
            {
                if (key.Preset == ExpressionPreset.custom && key.Name.StartsWith(FaceNames.CleanPrefix, StringComparison.Ordinal))
                {
                    known = true;
                    break;
                }
            }
            if (!known && (_cleanGroups.Count > 0 || _rawMorphs.Count > 0))
                runtime.Expression.Reload(instance);
        }

        /// <summary>Détruit la copie du VRM10Object et les expressions créées — seulement quand plus aucune
        /// instance ne s'en sert.</summary>
        public void DestroyCreated()
        {
            foreach (var o in _created)
                if (o != null)
                    UnityEngine.Object.Destroy(o);
            _created.Clear();
        }

        public bool HasGroup(string group) => _cleanGroups.Contains(group);
        public bool HasRawMorph(string morph) => _rawMorphs.Contains(morph);
        public bool HasExpression(string name) => name != null && _keys.ContainsKey(name);

        /// <summary>Le preset existe sur le modèle (<c>happy</c>, <c>blink</c>, <c>aa</c>…).</summary>
        public bool HasPreset(string preset) =>
            Enum.TryParse<ExpressionPreset>(preset, false, out var p) && p != ExpressionPreset.custom && _keys.ContainsKey(preset);

        /// <summary>Clé UniVRM d'un nom d'expression du visage (avec l'alias vers la copie nettoyée des presets
        /// d'émotion).</summary>
        public bool TryResolve(string name, out ExpressionKey key)
        {
            if (name != null && _alias.TryGetValue(name, out var alias))
                name = alias;
            return _keys.TryGetValue(name ?? "", out key);
        }

        /// <summary>Implication buccale d'une expression (0 = ne touche pas la bouche), calculée une fois.</summary>
        public float MouthInvolvement(string name)
        {
            if (_mouthInvolvement.TryGetValue(name, out var cached))
                return cached;
            float value = 0f;
            string resolved = name != null && _alias.TryGetValue(name, out var alias) ? alias : name;
            if (resolved != null && _clips.TryGetValue(resolved, out var clip) && clip != null)
                value = MouthLoad.Involvement(clip.MorphTargetBindings.Select(b => (MorphName(b), b.Weight)));
            _mouthInvolvement[name] = value;
            return value;
        }

        /// <summary>Les morphs qu'une expression lie (nom du morph, poids 0…1) — diagnostic et import.</summary>
        public IEnumerable<(string morph, float weight)> BindsOf(string name)
        {
            if (name != null && _clips.TryGetValue(name, out var clip) && clip != null)
                foreach (var b in clip.MorphTargetBindings)
                    yield return (MorphName(b), b.Weight);
        }

        VRM10Expression CleanCopy(VRM10Expression source, string name)
        {
            var kept = new List<MorphTargetBinding>();
            var removed = new List<string>();
            foreach (var b in source.MorphTargetBindings ?? Array.Empty<MorphTargetBinding>())
            {
                string morph = MorphName(b);
                if (morph != null && FaceNames.IsStripped(morph))
                {
                    removed.Add(morph);
                    continue;
                }
                kept.Add(b);
            }
            var clip = ScriptableObject.CreateInstance<VRM10Expression>();
            clip.name = name;
            clip.IsBinary = source.IsBinary;
            clip.MorphTargetBindings = kept.ToArray();
            if (removed.Count > 0)
                _strippedReport.Add($"{source.name}: {string.Join(", ", removed.Distinct())}");
            return clip;
        }

        string MorphName(MorphTargetBinding b)
        {
            var t = _root.Find(b.RelativePath);
            if (t == null)
                return null;
            var r = t.GetComponent<SkinnedMeshRenderer>();
            if (r == null || r.sharedMesh == null || b.Index < 0 || b.Index >= r.sharedMesh.blendShapeCount)
                return null;
            return r.sharedMesh.GetBlendShapeName(b.Index);
        }

        /// <summary>Chemin de <paramref name="target"/> relatif à <paramref name="root"/>, au format de
        /// <c>Transform.Find</c> (c'est ce qu'attend <see cref="MorphTargetBinding.RelativePath"/>).</summary>
        public static string RelativePath(Transform root, Transform target)
        {
            var parts = new List<string>();
            for (var t = target; t != null && t != root; t = t.parent)
                parts.Add(t.name);
            parts.Reverse();
            return string.Join("/", parts);
        }
    }
}
