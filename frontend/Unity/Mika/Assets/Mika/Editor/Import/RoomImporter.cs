using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Mika.World.Engine;
using Mika.World.Protocol;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace Mika.Editor.Import
{
    /// <summary>
    /// Fait de l'export Blender de la chambre des assets Unity prêts à l'emploi : des matériaux URP fidèles à
    /// Blender, des modèles importés proprement (UV de lightmap, matériaux remappés), et un prefab par objet avec
    /// ce qu'il faut pour vivre dans le monde — <see cref="WorldObject"/>, collisions, places de surface,
    /// charnières (porte, fenêtre, armoire), lumières des lampes.
    /// </summary>
    /// <remarks>
    /// Idempotent : relancer après un nouvel export met tout à jour sans dupliquer (les GUID sont gardés). Rien
    /// n'est deviné : ce que l'export ne dit pas (une émission, une charnière) n'est pas inventé ici.
    /// </remarks>
    public static class RoomImporter
    {
        public const string ArtRoot = "Assets/Mika/Art/Room";
        public const string MaterialsDir = ArtRoot + "/Materials";
        public const string PrefabsDir = ArtRoot + "/Prefabs";

        /// <summary>Combien de places porte la surface d'un meuble, quand le monde ne le dit pas.</summary>
        static readonly Dictionary<string, int> SlotsById = new Dictionary<string, int>
        {
            ["writing_desk"] = 8, ["nightstand"] = 4, ["shelves"] = 12, ["dresser"] = 4, ["trinket_shelf"] = 5,
        };

        /// <summary>Les lampes : couleur et intensité de leur lumière (la lumière du jour, elle, vient d'ailleurs).</summary>
        static readonly Dictionary<string, (Color color, float intensity, float range, LightShadows shadows)> Lamps =
            new Dictionary<string, (Color, float, float, LightShadows)>
            {
                ["desk_lamp"] = (new Color(1f, 0.78f, 0.55f), 1.6f, 3.5f, LightShadows.Soft),
                ["bedside_lamp"] = (new Color(1f, 0.76f, 0.5f), 1.2f, 3f, LightShadows.None),
                ["ceiling_lamp"] = (new Color(1f, 0.9f, 0.78f), 5.5f, 11f, LightShadows.Soft),
                ["monitor"] = (new Color(0.75f, 0.85f, 1f), 0.35f, 2f, LightShadows.None),
                ["moon_lamp"] = (new Color(1f, 0.88f, 0.7f), 0.3f, 1.5f, LightShadows.None),
                ["star_lamp"] = (new Color(1f, 0.84f, 0.48f), 0.25f, 1.2f, LightShadows.None),
                ["candle"] = (new Color(1f, 0.69f, 0.31f), 0.35f, 1.5f, LightShadows.None),
            };

        [MenuItem("Mika/Art/1 · Importer la chambre (matériaux, modèles, prefabs)", priority = 1)]
        public static void ImportAll()
        {
            var layout = RoomLayout.Read(Path.Combine(ArtRoot, "room_layout.json"));
            var specs = RoomMaterials.Read(Path.Combine(ArtRoot, "materials.json"));
            try
            {
                AssetDatabase.StartAssetEditing();
                Ensure(MaterialsDir);
                Ensure(PrefabsDir);
            }
            finally
            {
                AssetDatabase.StopAssetEditing();
            }
            var materials = BuildMaterials(specs);
            ConfigureModels(layout, materials);
            var built = BuildPrefabs(layout, specs);
            AssetDatabase.SaveAssets();
            Debug.Log($"[Mika] chambre importée : {materials.Count} matériaux, {built} prefabs ({PrefabsDir}).");
        }

        // --- matériaux -------------------------------------------------------------------------------------------
        static Dictionary<string, Material> BuildMaterials(RoomMaterials specs)
        {
            var lit = Shader.Find("Universal Render Pipeline/Lit");
            var result = new Dictionary<string, Material>();
            foreach (var kv in specs.Materials)
            {
                var path = $"{MaterialsDir}/{kv.Key}.mat";
                var mat = AssetDatabase.LoadAssetAtPath<Material>(path);
                if (mat == null)
                {
                    mat = new Material(lit) { name = kv.Key };
                    AssetDatabase.CreateAsset(mat, path);
                }
                else if (mat.shader != lit)
                {
                    mat.shader = lit;
                }
                Configure(mat, kv.Value);
                EditorUtility.SetDirty(mat);
                result[kv.Key] = mat;
            }
            return result;
        }

        static void Configure(Material mat, MaterialSpec spec)
        {
            var color = Parse(spec.BaseColor?.SrgbHex, Color.white);
            color.a = spec.Alpha;
            mat.SetColor("_BaseColor", color);
            var tex = spec.Textures?.Base != null ? AssetDatabase.LoadAssetAtPath<Texture2D>($"{ArtRoot}/{spec.Textures.Base}") : null;
            mat.SetTexture("_BaseMap", tex);
            mat.SetFloat("_Smoothness", Mathf.Clamp01(1f - spec.Roughness));
            mat.SetFloat("_Metallic", Mathf.Clamp01(spec.Metallic));

            var strength = spec.Emission?.Strength ?? 0f;
            if (strength > 0f)
            {
                // Blender compte l'émission en W/m² ; ici une intensité HDR telle que le bloom (seuil 1) prenne
                // les ampoules et les néons, pas les abat-jour à peine éclairés.
                var e = Parse(spec.Emission.Color?.SrgbHex, Color.white).linear * Mathf.Clamp(strength * 0.9f, 0.4f, 6f);
                mat.EnableKeyword("_EMISSION");
                mat.SetColor("_EmissionColor", e);
                mat.globalIlluminationFlags = MaterialGlobalIlluminationFlags.BakedEmissive;
            }
            else
            {
                mat.DisableKeyword("_EMISSION");
                mat.SetColor("_EmissionColor", Color.black);
                mat.globalIlluminationFlags = MaterialGlobalIlluminationFlags.EmissiveIsBlack;
            }

            var transparent = spec.Alpha < 0.999f || (spec.Blend != null && spec.Blend != "opaque");
            mat.SetFloat("_Surface", transparent ? 1f : 0f);
            mat.SetOverrideTag("RenderType", transparent ? "Transparent" : "Opaque");
            mat.SetFloat("_SrcBlend", transparent ? (float)BlendMode.SrcAlpha : (float)BlendMode.One);
            mat.SetFloat("_DstBlend", transparent ? (float)BlendMode.OneMinusSrcAlpha : (float)BlendMode.Zero);
            mat.SetFloat("_ZWrite", transparent ? 0f : 1f);
            mat.renderQueue = transparent ? (int)RenderQueue.Transparent : -1;
            if (transparent) mat.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            else mat.DisableKeyword("_SURFACE_TYPE_TRANSPARENT");
            mat.SetFloat("_Cull", spec.DoubleSided ? (float)CullMode.Off : (float)CullMode.Back);
            mat.doubleSidedGI = spec.DoubleSided;
        }

        static Color Parse(string hex, Color fallback) =>
            hex != null && ColorUtility.TryParseHtmlString(hex, out var c) ? c : fallback;

        // --- modèles ----------------------------------------------------------------------------------------------
        static void ConfigureModels(RoomLayout layout, Dictionary<string, Material> materials)
        {
            foreach (var obj in layout.Objects)
            {
                var path = $"{ArtRoot}/{obj.Fbx}";
                if (!(AssetImporter.GetAtPath(path) is ModelImporter importer))
                {
                    Debug.LogWarning($"[Mika] modèle introuvable : {path}");
                    continue;
                }
                var dirty = false;
                void Set<T>(T current, T wanted, Action<T> assign)
                {
                    if (EqualityComparer<T>.Default.Equals(current, wanted)) return;
                    assign(wanted);
                    dirty = true;
                }
                Set(importer.materialImportMode, ModelImporterMaterialImportMode.ImportViaMaterialDescription, v => importer.materialImportMode = v);
                Set(importer.importCameras, false, v => importer.importCameras = v);
                Set(importer.importLights, false, v => importer.importLights = v);
                Set(importer.importAnimation, false, v => importer.importAnimation = v);
                Set(importer.animationType, ModelImporterAnimationType.None, v => importer.animationType = v);
                Set(importer.generateSecondaryUV, obj.Category != "prop", v => importer.generateSecondaryUV = v);
                Set(importer.isReadable, true, v => importer.isReadable = v); // collisions de maillage
                var existing = importer.GetExternalObjectMap();
                foreach (var name in obj.Materials)
                {
                    if (!materials.TryGetValue(name, out var mat)) continue;
                    var id = new AssetImporter.SourceAssetIdentifier(typeof(Material), name);
                    if (existing.TryGetValue(id, out var current) && current == mat) continue;
                    importer.AddRemap(id, mat);
                    dirty = true;
                }
                if (dirty) importer.SaveAndReimport();
            }
        }

        // --- prefabs ------------------------------------------------------------------------------------------------
        static int BuildPrefabs(RoomLayout layout, RoomMaterials specs)
        {
            var emissiveMats = new HashSet<string>(specs.Materials.Where(kv => (kv.Value.Emission?.Strength ?? 0) > 0).Select(kv => kv.Key));
            var count = 0;
            foreach (var obj in layout.Objects)
            {
                var model = AssetDatabase.LoadAssetAtPath<GameObject>($"{ArtRoot}/{obj.Fbx}");
                if (model == null) continue;
                var dir = $"{PrefabsDir}/{obj.Category}";
                Ensure(dir);
                var root = new GameObject(obj.Id);
                try
                {
                    var instance = (GameObject)PrefabUtility.InstantiatePrefab(model, root.transform);
                    instance.name = "Modèle";
                    Dress(root, instance, obj, layout, emissiveMats);
                    PrefabUtility.SaveAsPrefabAsset(root, $"{dir}/{obj.Id}.prefab");
                    count++;
                }
                finally
                {
                    UnityEngine.Object.DestroyImmediate(root);
                }
            }
            return count;
        }

        /// <summary>Tout ce qui fait d'un modèle un objet du monde.</summary>
        static void Dress(GameObject root, GameObject model, LayoutObject obj, RoomLayout layout, HashSet<string> emissiveMats)
        {
            var wo = root.AddComponent<WorldObject>();
            wo.id = obj.Id;

            var isStatic = obj.Category != "prop";
            foreach (var mf in model.GetComponentsInChildren<MeshFilter>(true))
            {
                if (obj.Id == "window_sky") break;
                if (isStatic)
                {
                    var mc = mf.gameObject.AddComponent<MeshCollider>();
                    mc.sharedMesh = mf.sharedMesh;
                }
            }
            if (!isStatic)
            {
                var b = Bounds(root);
                var box = root.AddComponent<BoxCollider>();
                box.center = root.transform.InverseTransformPoint(b.center);
                box.size = b.size;
                wo.grip = MakeChild(root.transform, "Prise", root.transform.InverseTransformPoint(b.center)).transform;
            }
            if (obj.Category == "architecture" || (obj.Category == "furniture" && obj.Children.Count == 0) || obj.Category == "decor")
            {
                foreach (var t in root.GetComponentsInChildren<Transform>(true))
                    GameObjectUtility.SetStaticEditorFlags(t.gameObject, StaticEditorFlags.ContributeGI | StaticEditorFlags.ReflectionProbeStatic);
            }

            Surfaces(root, obj);
            Hinges(root, model, obj);
            Lights(root, model, obj, layout, emissiveMats);
            if (obj.Materials.Contains("M_Duvet") && Bedding.Available)
                Bedding.Dress(root, model, obj);
            if (obj.Id == "wall_clock")
            {
                var clock = root.AddComponent<WallClock>();
                clock.hourHand = Find(model.transform, "Clock_HourHand");
                clock.minuteHand = Find(model.transform, "Clock_MinuteHand");
            }
        }

        static void Surfaces(GameObject root, LayoutObject obj)
        {
            if (obj.Surfaces.Count == 0) return;
            var want = SlotsById.TryGetValue(obj.Id, out var n) ? n : Mathf.Clamp(obj.Surfaces.Count, 1, 4);
            // Une place par surface d'abord (de la plus haute à la plus basse : le dessus est ce qu'on voit), puis on
            // en ajoute le long des plus grandes.
            var surfaces = obj.Surfaces.OrderByDescending(s => s.Height).ToList();
            var perSurface = surfaces.Select(_ => 0).ToArray();
            for (var i = 0; i < want; i++)
            {
                var best = 0;
                var bestScore = float.MinValue;
                for (var s = 0; s < surfaces.Count; s++)
                {
                    var area = (surfaces[s].Max.X - surfaces[s].Min.X) * (surfaces[s].Max.Z - surfaces[s].Min.Z);
                    var score = area / (perSurface[s] + 1) + (perSurface[s] == 0 ? 10f : 0f);
                    if (score > bestScore)
                    {
                        bestScore = score;
                        best = s;
                    }
                }
                perSurface[best]++;
            }
            var index = 0;
            for (var s = 0; s < surfaces.Count; s++)
            {
                var surf = surfaces[s];
                var k = perSurface[s];
                if (k == 0) continue;
                var sx = surf.Max.X - surf.Min.X;
                var sz = surf.Max.Z - surf.Min.Z;
                for (var j = 0; j < k; j++)
                {
                    // Le long du plus grand côté, à intervalles réguliers.
                    var f = (j + 0.5f) / k;
                    var x = sx >= sz ? surf.Min.X + sx * f : (surf.Min.X + surf.Max.X) / 2f;
                    var z = sx >= sz ? (surf.Min.Z + surf.Max.Z) / 2f : surf.Min.Z + sz * f;
                    var slot = MakeChild(root.transform, $"Place {index}", RoomSpace.ToUnity(x, surf.Height, z));
                    slot.AddComponent<SurfaceSlot>().index = index;
                    index++;
                }
            }
        }

        static void Hinges(GameObject root, GameObject model, LayoutObject obj)
        {
            foreach (var child in obj.Children.Where(c => c.Motion?.Type == "hinge"))
            {
                var leaf = Find(model.transform, child.Name);
                if (leaf == null) continue;
                var hinge = root.AddComponent<StateHinge>();
                hinge.leaf = leaf;
                // Le sens d'ouverture : le bord libre du battant va vers « opens_toward ».
                var free = Bounds(leaf.gameObject).center - leaf.position;
                free.y = 0;
                var toward = child.Motion.OpensToward != null ? RoomSpace.ToUnity(child.Motion.OpensToward.X, 0, child.Motion.OpensToward.Z) : Vector3.zero;
                var sign = Vector3.Cross(free, toward).y >= 0 ? 1f : -1f;
                var angle = obj.Id == "window_pane" ? 70f : obj.Id == "wardrobe" ? 100f : 95f;
                hinge.poses = new List<StateHinge.Pose>
                {
                    new StateHinge.Pose { state = "closed" },
                    new StateHinge.Pose { state = "open", localEuler = new Vector3(0, sign * angle, 0) },
                };
                hinge.duration = obj.Id == "window_pane" ? 1.6f : 1.2f;
            }
        }

        static void Lights(GameObject root, GameObject model, LayoutObject obj, RoomLayout layout, HashSet<string> emissiveMats)
        {
            if (!Lamps.TryGetValue(obj.Id, out var lamp)) return;
            var anchors = layout.LightAnchors.Where(a => a.Object == obj.Id).ToList();
            var lights = new List<Light>();
            if (anchors.Count == 0)
                anchors.Add(new LightAnchor { Name = "Lumière", Local = new V3 { Y = obj.Size?.Y * 0.8f ?? 0.3f } });
            foreach (var a in anchors)
            {
                var go = MakeChild(root.transform, a.Name ?? "Lumière", RoomSpace.ToUnity(a.Local.X, a.Local.Y, a.Local.Z));
                var light = go.AddComponent<Light>();
                light.type = LightType.Point;
                light.color = lamp.color;
                light.intensity = lamp.intensity;
                light.range = lamp.range;
                light.shadows = lamp.shadows;
                light.shadowStrength = 0.8f;
                lights.Add(light);
            }
            var state = root.AddComponent<StateLight>();
            state.lights = lights;
            state.emissive = model.GetComponentsInChildren<Renderer>(true)
                .Where(r => r.sharedMaterials.Any(m => m != null && emissiveMats.Contains(m.name)))
                .ToList();
        }

        // --- utilitaires -----------------------------------------------------------------------------------------------
        static GameObject MakeChild(Transform parent, string name, Vector3 localPosition)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            go.transform.localPosition = localPosition;
            return go;
        }

        static Transform Find(Transform root, string name)
        {
            if (root.name == name) return root;
            foreach (Transform c in root)
            {
                var f = Find(c, name);
                if (f != null) return f;
            }
            return null;
        }

        static Bounds Bounds(GameObject go)
        {
            var rs = go.GetComponentsInChildren<Renderer>(true);
            if (rs.Length == 0) return new Bounds(go.transform.position, Vector3.zero);
            var b = rs[0].bounds;
            foreach (var r in rs.Skip(1)) b.Encapsulate(r.bounds);
            return b;
        }

        internal static void Ensure(string dir)
        {
            if (AssetDatabase.IsValidFolder(dir)) return;
            var parent = Path.GetDirectoryName(dir)?.Replace('\\', '/');
            if (!string.IsNullOrEmpty(parent)) Ensure(parent);
            AssetDatabase.CreateFolder(parent, Path.GetFileName(dir));
        }
    }
}
