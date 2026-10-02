using System.Collections.Generic;
using System.IO;
using System.Linq;
using Mika.App;
using Mika.Player;
using Mika.UI;
using Mika.World.Engine;
using Mika.World.Engine.Authoring;
using Mika.World.Protocol;
using Unity.AI.Navigation;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.AI;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.UIElements;

namespace Mika.Editor.Import
{
    /// <summary>
    /// Assemble la scène de la chambre à partir de l'export Blender et du monde par défaut du noyau : la pièce et
    /// ses objets à leur place, les lieux (avec où s'asseoir et où s'allonger), Mika, les archétypes et le
    /// catalogue, la lumière (lampes, jour, ambiance, post-traitement), la navigation, la joueuse et l'interface.
    /// La scène obtenue sert à la fois au créateur (tout y est éditable) et au jeu (<see cref="MikaApp"/>).
    /// </summary>
    public static class ChambreSceneBuilder
    {
        const string ContentDir = "Assets/Mika/Content";
        const string ArchetypesDir = ContentDir + "/Archetypes";
        const string CatalogPath = ContentDir + "/AssetCatalog.asset";
        const string ScenePath = "Assets/Mika/Scenes/Chambre.unity";
        const string WorldsDir = ContentDir + "/Worlds";
        const string AvatarPrefab = "Assets/Mika/Art/Avatars/Mika.prefab";
        const string VisitorPrefab = ContentDir + "/Prefabs/Visitor.prefab";
        const string PanelPath = "Assets/Mika/UI/MikaPanel.asset";
        const string ThemePath = "Assets/Mika/UI/MikaTheme.tss";
        const string VolumeProfilePath = ContentDir + "/ChambreVolume.asset";

        /// <summary>Où s'asseoir et où s'allonger (repris du client web, roomLayout.ts, recalé sur room.glb).</summary>
        static readonly Dictionary<string, (Vector3 seat, double seatFacing, Vector3? lie, double lieYaw)> Seats =
            new Dictionary<string, (Vector3, double, Vector3?, double)>
            {
                ["desk"] = (new Vector3(-1.4f, 0.51f, -3.3f), -System.Math.PI + 0.3, null, 0),
                ["bed"] = (new Vector3(-2.85f, 0.47f, 1.3f), System.Math.PI / 2, new Vector3(-3.32f, 0.56f, 1.62f), 0),
            };

        [MenuItem("Mika/Art/Tout reconstruire (import + scène)", priority = 3)]
        public static void RebuildAll()
        {
            RoomImporter.ImportAll();
            Build();
        }

        [MenuItem("Mika/Art/2 · Construire la scène de la chambre", priority = 2)]
        public static void Build()
        {
            // Les scènes ouvertes modifiées sont enregistrées telles quelles (sans boîte de dialogue : ce menu est
            // aussi appelé par des outils).
            EditorSceneManager.SaveOpenScenes();
            var layout = RoomLayout.Read(Path.Combine(RoomImporter.ArtRoot, "room_layout.json"));
            var kernelWorld = ReadKernelWorld();
            RoomImporter.Ensure(ArchetypesDir);
            RoomImporter.Ensure(WorldsDir);
            RoomImporter.Ensure(ContentDir + "/Prefabs");
            RoomImporter.Ensure("Assets/Mika/Scenes");

            CopyKernelWorld();
            var archetypes = BuildArchetypes(kernelWorld, layout);
            var catalog = BuildCatalog(archetypes.Values);
            var layers = EnsureLayers();

            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var worldRoot = new GameObject("Monde");
            var authoring = worldRoot.AddComponent<WorldAuthoring>();
            authoring.worldId = kernelWorld.Id;
            authoring.label = kernelWorld.Label;
            authoring.baseRev = kernelWorld.Rev;
            authoring.catalog = catalog;

            var roomDef = kernelWorld.Rooms.First();
            var roomGo = new GameObject(roomDef.Id);
            roomGo.transform.SetParent(worldRoot.transform, false);
            var room = roomGo.AddComponent<RoomAuthoring>();
            room.id = roomDef.Id;
            room.label = roomDef.Label;

            // Objets
            var kernelObjects = kernelWorld.Objects.ToDictionary(o => o.Id);
            var authored = new Dictionary<string, ObjectAuthoring>();
            foreach (var obj in layout.Objects)
            {
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>($"{RoomImporter.PrefabsDir}/{obj.Category}/{obj.Id}.prefab");
                if (prefab == null) continue;
                var go = (GameObject)PrefabUtility.InstantiatePrefab(prefab, roomGo.transform);
                go.transform.localPosition = RoomSpace.ToUnity(obj.Pos.X, obj.Pos.Y, obj.Pos.Z);
                go.transform.localRotation = RoomSpace.Facing(obj.Yaw);
                if (obj.Category == "prop")
                    SetLayer(go, layers.props);
                var archetype = ArchetypeFor(obj.Id, archetypes, kernelObjects);
                if (archetype == null) continue;
                var oa = go.AddComponent<ObjectAuthoring>();
                oa.id = obj.Id;
                oa.archetype = archetype;
                if (kernelObjects.TryGetValue(obj.Id, out var k))
                {
                    oa.label = k.Label;
                    oa.owner = k.Owner;
                    oa.access = k.Access;
                    oa.state = k.State;
                    if (k.Home is InRoom ir) { oa.home = HomeKind.Room; }
                }
                else
                {
                    oa.label = ArchetypeLibrary.Objects.TryGetValue(obj.Id, out var lib) ? lib.label : null;
                    oa.owner = "mika";
                }
                authored[obj.Id] = oa;
            }

            // Lieux
            var placesRoot = new GameObject("Lieux");
            placesRoot.transform.SetParent(roomGo.transform, false);
            var placeByid = new Dictionary<string, PlaceAuthoring>();
            foreach (var p in kernelWorld.Places)
            {
                var go = new GameObject($"Lieu · {p.Id}");
                go.transform.SetParent(placesRoot.transform, false);
                go.transform.localPosition = RoomSpace.ToUnity(p.Pos);
                go.transform.localRotation = RoomSpace.Facing(p.Facing ?? 0);
                var pa = go.AddComponent<PlaceAuthoring>();
                pa.id = p.Id;
                pa.label = p.Label;
                pa.kind = p.PlaceKind;
                pa.capacity = p.Capacity;
                pa.tags = p.Tags?.ToList() ?? new List<string>();
                if (p.OfObject != null && authored.TryGetValue(p.OfObject, out var carrier)) pa.ofObject = carrier;
                if (Seats.TryGetValue(p.Id, out var s))
                {
                    // Les hanches se posent un peu au-dessus du dessus du siège (l'os du bassin n'est pas la peau).
                    pa.seat = Child(go.transform, "Assise", room.transform, s.seat + Vector3.up * 0.08f, s.seatFacing);
                    if (s.lie.HasValue) pa.lie = Child(go.transform, "Allongée", room.transform, s.lie.Value, s.lieYaw);
                }
                placeByid[p.Id] = pa;
            }
            foreach (var oa in authored.Values)
                if (oa.home == HomeKind.Room && kernelObjects.TryGetValue(oa.id, out var k) && k.Home is InRoom ir && ir.Near != null && placeByid.TryGetValue(ir.Near, out var near))
                    oa.near = near;

            // Personnages
            foreach (var a in kernelWorld.Actors)
            {
                var go = new GameObject($"Personnage · {a.Id}");
                go.transform.SetParent(worldRoot.transform, false);
                var aa = go.AddComponent<ActorAuthoring>();
                aa.id = a.Id;
                aa.label = a.Label;
                aa.assetKey = a.Asset;
                aa.controller = a.Controller;
                aa.tags = a.Tags?.ToList() ?? new List<string>();
                if (placeByid.TryGetValue(a.Home, out var home))
                {
                    aa.home = home;
                    go.transform.position = home.transform.position;
                }
            }

            BuildLighting(roomGo.transform);
            BuildNavigation(roomGo, layers.props);
            var app = BuildApp(catalog, authoring);
            EditorSceneManager.SaveScene(scene, ScenePath);
            AddToBuild(ScenePath);
            Debug.Log($"[Mika] scène construite : {ScenePath} ({authored.Count} objets du monde, {placeByid.Count} lieux).");
            Selection.activeGameObject = app;
        }

        // --- le monde par défaut du noyau ------------------------------------------------------------------------
        static string KernelWorldPath => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "..", "backendv2", "src", "mika", "faculties", "world", "chambre.json"));

        static WorldDef ReadKernelWorld() => WireJson.ReadWorld(File.ReadAllText(KernelWorldPath));

        /// <summary>Une copie dans le projet : un exécutable n'a pas le dépôt à côté de lui (aperçu hors ligne).</summary>
        static void CopyKernelWorld()
        {
            var dst = Path.Combine(WorldsDir, "chambre.json");
            File.Copy(KernelWorldPath, dst, true);
            AssetDatabase.ImportAsset(dst);
        }

        // --- archétypes et catalogue -----------------------------------------------------------------------------
        static Dictionary<string, ArchetypeAsset> BuildArchetypes(WorldDef kernelWorld, RoomLayout layout)
        {
            var result = new Dictionary<string, ArchetypeAsset>();
            var prefabOf = layout.Objects.ToDictionary(o => o.Id, o => AssetDatabase.LoadAssetAtPath<GameObject>($"{RoomImporter.PrefabsDir}/{o.Category}/{o.Id}.prefab"));

            // Ceux du noyau font foi : recopiés tels quels, le prefab est celui de l'objet qui les porte.
            foreach (var def in kernelWorld.Archetypes)
            {
                var asset = LoadOrCreate(def.Id);
                asset.CopyFrom(def);
                var carrier = kernelWorld.Objects.FirstOrDefault(o => o.Archetype == def.Id);
                if (carrier != null && prefabOf.TryGetValue(carrier.Id, out var p)) asset.prefab = p;
                // Les places que le meuble porte vraiment (l'export en compte selon sa surface) : un archétype qui
                // en annoncerait moins rendrait des objets de la scène impossibles à poser.
                var slots = asset.prefab != null ? asset.prefab.GetComponentsInChildren<SurfaceSlot>(true).Length : 0;
                asset.surfaceSlots = Mathf.Max(asset.surfaceSlots, slots);
                EditorUtility.SetDirty(asset);
                result[def.Id] = asset;
            }
            // La bibliothèque pour le reste de la chambre.
            foreach (var kind in ArchetypeLibrary.Kinds.Values)
            {
                if (result.ContainsKey(kind.Id)) continue;
                var asset = LoadOrCreate(kind.Id);
                asset.id = kind.Id;
                asset.label = kind.Label;
                asset.size = kind.Size;
                asset.states = kind.States.ToList();
                asset.initialState = kind.Initial;
                asset.stateLabels = kind.StateLabels.Select(l => new StateLabel { state = l.state, label = l.label }).ToList();
                asset.affordances = kind.Affordances.ToList();
                asset.surfaceSlots = kind.SurfaceSlots;
                asset.containerSlots = kind.ContainerSlots;
                asset.salience = kind.Salience;
                var first = ArchetypeLibrary.Objects.FirstOrDefault(o => o.Value.kind == kind.Id).Key;
                asset.assetKey = first != null ? layout.Objects.FirstOrDefault(o => o.Id == first)?.Asset ?? $"props/{kind.Id}" : $"props/{kind.Id}";
                if (first != null && prefabOf.TryGetValue(first, out var p)) asset.prefab = p;
                if (asset.surfaceSlots > 0 && asset.prefab != null)
                    asset.surfaceSlots = Mathf.Max(asset.surfaceSlots, asset.prefab.GetComponentsInChildren<SurfaceSlot>(true).Length);
                EditorUtility.SetDirty(asset);
                result[kind.Id] = asset;
            }
            return result;
        }

        static ArchetypeAsset LoadOrCreate(string id)
        {
            var path = $"{ArchetypesDir}/{id}.asset";
            var asset = AssetDatabase.LoadAssetAtPath<ArchetypeAsset>(path);
            if (asset != null) return asset;
            asset = ScriptableObject.CreateInstance<ArchetypeAsset>();
            asset.id = id;
            AssetDatabase.CreateAsset(asset, path);
            return asset;
        }

        static ArchetypeAsset ArchetypeFor(string objectId, Dictionary<string, ArchetypeAsset> archetypes, Dictionary<string, ObjectDef> kernel)
        {
            if (kernel.TryGetValue(objectId, out var k)) return archetypes.TryGetValue(k.Archetype, out var a) ? a : null;
            return ArchetypeLibrary.Objects.TryGetValue(objectId, out var lib) && archetypes.TryGetValue(lib.kind, out var b) ? b : null;
        }

        static AssetCatalog BuildCatalog(IEnumerable<ArchetypeAsset> archetypes)
        {
            var catalog = AssetDatabase.LoadAssetAtPath<AssetCatalog>(CatalogPath);
            if (catalog == null)
            {
                catalog = ScriptableObject.CreateInstance<AssetCatalog>();
                AssetDatabase.CreateAsset(catalog, CatalogPath);
            }
            catalog.archetypes = archetypes.OrderBy(a => a.id).ToList();
            var entries = new List<AssetEntry>();
            var mika = AssetDatabase.LoadAssetAtPath<GameObject>(AvatarPrefab);
            if (mika != null) entries.Add(new AssetEntry { key = "avatars/mika", prefab = mika });
            else Debug.LogWarning($"[Mika] {AvatarPrefab} n'existe pas encore (menu Mika › Avatar) : Mika sera une silhouette.");
            entries.Add(new AssetEntry { key = "avatars/default", prefab = BuildVisitor() });
            // Les objets de la chambre aussi par leur propre clé : un objet du monde peut nommer « props/ficus ».
            foreach (var prefabPath in AssetDatabase.FindAssets("t:Prefab", new[] { RoomImporter.PrefabsDir }).Select(AssetDatabase.GUIDToAssetPath))
            {
                var category = Path.GetFileName(Path.GetDirectoryName(prefabPath));
                var key = (category == "prop" ? "props" : category == "fixture" ? "fixtures" : category) + "/" + Path.GetFileNameWithoutExtension(prefabPath);
                if (entries.All(e => e.key != key))
                    entries.Add(new AssetEntry { key = key, prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath) });
            }
            catalog.entries = entries;
            catalog.Invalidate();
            EditorUtility.SetDirty(catalog);
            return catalog;
        }

        /// <summary>Le corps par défaut d'une personne (en attendant les avatars) : une silhouette simple et douce.</summary>
        static GameObject BuildVisitor()
        {
            var existing = AssetDatabase.LoadAssetAtPath<GameObject>(VisitorPrefab);
            if (existing != null) return existing;
            var root = new GameObject("Visitor");
            var body = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            body.name = "Corps";
            body.transform.SetParent(root.transform, false);
            body.transform.localPosition = new Vector3(0, 0.75f, 0);
            body.transform.localScale = new Vector3(0.42f, 0.75f, 0.32f);
            var head = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            head.name = "Tête";
            head.transform.SetParent(root.transform, false);
            head.transform.localPosition = new Vector3(0, 1.62f, 0);
            head.transform.localScale = Vector3.one * 0.26f;
            var mat = new Material(Shader.Find("Universal Render Pipeline/Lit")) { color = new Color(0.62f, 0.7f, 0.95f) };
            AssetDatabase.CreateAsset(mat, ContentDir + "/Prefabs/Visitor.mat");
            body.GetComponent<Renderer>().sharedMaterial = mat;
            head.GetComponent<Renderer>().sharedMaterial = mat;
            root.AddComponent<ActorBody>();
            var prefab = PrefabUtility.SaveAsPrefabAsset(root, VisitorPrefab);
            Object.DestroyImmediate(root);
            return prefab;
        }

        // --- lumière -----------------------------------------------------------------------------------------------
        static void BuildLighting(Transform room)
        {
            var sun = new GameObject("Lumière du jour");
            sun.transform.SetParent(room, false);
            var light = sun.AddComponent<Light>();
            light.type = LightType.Directional;
            light.shadows = LightShadows.Soft;
            light.shadowStrength = 0.85f;
            var daylight = sun.AddComponent<Daylight>();
            daylight.sun = light;
            // La fenêtre est sur le mur x = −4 de l'espace de la pièce : la lumière entre par là.
            daylight.windowDirection = RoomSpace.ToUnity(1, 0, 0).normalized;

            RenderSettings.ambientMode = AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = new Color(0.42f, 0.44f, 0.55f);
            RenderSettings.ambientEquatorColor = new Color(0.33f, 0.3f, 0.32f);
            RenderSettings.ambientGroundColor = new Color(0.16f, 0.13f, 0.12f);

            var probe = new GameObject("Reflets").AddComponent<ReflectionProbe>();
            probe.transform.SetParent(room, false);
            probe.transform.localPosition = new Vector3(0, 1.4f, -0.5f);
            probe.size = new Vector3(8.2f, 3.3f, 8.2f);
            probe.boxProjection = true;
            probe.mode = ReflectionProbeMode.Realtime;
            probe.refreshMode = ReflectionProbeRefreshMode.OnAwake;

            var volumeGo = new GameObject("Ambiance (post-traitement)");
            volumeGo.transform.SetParent(room, false);
            var volume = volumeGo.AddComponent<Volume>();
            volume.isGlobal = true;
            volume.sharedProfile = BuildVolumeProfile();
        }

        static VolumeProfile BuildVolumeProfile()
        {
            var profile = AssetDatabase.LoadAssetAtPath<VolumeProfile>(VolumeProfilePath);
            if (profile == null)
            {
                profile = ScriptableObject.CreateInstance<VolumeProfile>();
                AssetDatabase.CreateAsset(profile, VolumeProfilePath);
            }
            T Get<T>() where T : VolumeComponent
            {
                if (!profile.TryGet<T>(out var c))
                {
                    c = profile.Add<T>(true);
                    AssetDatabase.AddObjectToAsset(c, profile);
                }
                return c;
            }
            var bloom = Get<Bloom>();
            bloom.threshold.Override(1f);
            bloom.intensity.Override(0.55f);
            bloom.scatter.Override(0.65f);
            var tone = Get<Tonemapping>();
            tone.mode.Override(TonemappingMode.ACES);
            var vignette = Get<Vignette>();
            vignette.intensity.Override(0.18f);
            var color = Get<ColorAdjustments>();
            color.postExposure.Override(0.15f);
            color.saturation.Override(4f);
            EditorUtility.SetDirty(profile);
            return profile;
        }

        // --- navigation --------------------------------------------------------------------------------------------
        static void BuildNavigation(GameObject room, int propsLayer)
        {
            var surface = room.AddComponent<NavMeshSurface>();
            surface.collectObjects = CollectObjects.Children;
            surface.useGeometry = NavMeshCollectGeometry.PhysicsColliders;
            surface.layerMask = ~(1 << propsLayer);
            surface.agentTypeID = AgentType();
            surface.BuildNavMesh();
            var path = "Assets/Mika/Scenes/Chambre.NavMesh.asset";
            AssetDatabase.DeleteAsset(path);
            AssetDatabase.CreateAsset(surface.navMeshData, path);
        }

        /// <summary>
        /// Le gabarit de navigation à la taille de Mika (≈1,5 m, menue) : celui du profil « Humanoid » par défaut
        /// (0,5 m de rayon) ne passe ni entre le lit et la table de chevet, ni derrière la chaise. On règle ce
        /// profil-là (le seul utilisé) plutôt que d'en créer un second que chaque agent devrait nommer.
        /// </summary>
        static int AgentType()
        {
            var all = new SerializedObject(AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/NavMeshAreas.asset")[0]);
            var list = all.FindProperty("m_Settings");
            for (var i = 0; i < list.arraySize; i++)
            {
                var e = list.GetArrayElementAtIndex(i);
                if (e.FindPropertyRelative("agentTypeID").intValue != 0) continue;
                e.FindPropertyRelative("agentRadius").floatValue = 0.2f;
                e.FindPropertyRelative("agentHeight").floatValue = 1.5f;
                e.FindPropertyRelative("agentClimb").floatValue = 0.2f;
                e.FindPropertyRelative("agentSlope").floatValue = 40f;
            }
            all.ApplyModifiedProperties();
            return 0;
        }

        // --- application, joueuse, interface ----------------------------------------------------------------------------
        static GameObject BuildApp(AssetCatalog catalog, WorldAuthoring authoring)
        {
            var appGo = new GameObject("Application");
            var stage = appGo.AddComponent<WorldStage>();
            stage.catalog = catalog;
            stage.authoring = authoring;
            var host = appGo.AddComponent<HostReporter>();
            host.stage = stage;
            var app = appGo.AddComponent<MikaApp>();
            app.stage = stage;
            app.host = host;
            app.offlineWorld = AssetDatabase.LoadAssetAtPath<TextAsset>(WorldsDir + "/chambre.json");

            // La joueuse : un corps, des yeux, une main.
            var player = new GameObject("Joueuse");
            var door = Object.FindObjectsByType<PlaceAuthoring>(FindObjectsInactive.Include).FirstOrDefault(p => p.tags.Contains("spawn"));
            if (door != null) player.transform.SetPositionAndRotation(door.transform.position, door.transform.rotation * Quaternion.Euler(0, 180, 0));
            player.AddComponent<CharacterController>();
            var controller = player.AddComponent<PlayerController>();
            var camGo = new GameObject("Caméra");
            camGo.tag = "MainCamera";
            camGo.transform.SetParent(player.transform, false);
            camGo.transform.localPosition = new Vector3(0, controller.eyeHeight, 0);
            var cam = camGo.AddComponent<Camera>();
            cam.nearClipPlane = 0.05f;
            cam.fieldOfView = 70f;
            var urp = camGo.AddComponent<UniversalAdditionalCameraData>();
            urp.renderPostProcessing = true;
            urp.antialiasing = AntialiasingMode.SubpixelMorphologicalAntiAliasing;
            camGo.AddComponent<AudioListener>();
            controller.view = cam;
            var hand = new GameObject("Main");
            hand.transform.SetParent(camGo.transform, false);
            hand.transform.localPosition = new Vector3(0.22f, -0.22f, 0.45f);
            stage.localHand = hand.transform;
            var presence = player.AddComponent<PlayerPresence>();
            presence.controller = controller;
            var interactor = player.AddComponent<PlayerInteractor>();
            interactor.controller = controller;

            var ui = new GameObject("Interface");
            var doc = ui.AddComponent<UIDocument>();
            doc.panelSettings = PanelSettingsAsset();
            var hud = ui.AddComponent<WorldHud>();
            hud.controller = controller;
            hud.interactor = interactor;

            app.player = controller;
            app.presence = presence;
            app.interactor = interactor;
            app.hud = hud;
            var presenter = appGo.AddComponent<MikaPresenter>();
            presenter.app = app;
            presenter.stage = stage;
            presenter.player = controller;
            return appGo;
        }

        static PanelSettings PanelSettingsAsset()
        {
            var panel = AssetDatabase.LoadAssetAtPath<PanelSettings>(PanelPath);
            if (panel != null) return panel;
            panel = ScriptableObject.CreateInstance<PanelSettings>();
            panel.themeStyleSheet = AssetDatabase.LoadAssetAtPath<ThemeStyleSheet>(ThemePath);
            panel.scaleMode = PanelScaleMode.ScaleWithScreenSize;
            panel.referenceResolution = new Vector2Int(1600, 900);
            AssetDatabase.CreateAsset(panel, PanelPath);
            return panel;
        }

        // --- utilitaires ----------------------------------------------------------------------------------------------------
        static Transform Child(Transform parent, string name, Transform room, Vector3 roomPos, double facing)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            go.transform.position = room.TransformPoint(RoomSpace.ToUnity(roomPos.x, roomPos.y, roomPos.z));
            go.transform.rotation = room.rotation * RoomSpace.Facing(facing);
            return go.transform;
        }

        static (int props, int actors) EnsureLayers()
        {
            var tags = new SerializedObject(AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/TagManager.asset")[0]);
            var layers = tags.FindProperty("layers");
            int Ensure(string name)
            {
                for (var i = 8; i < layers.arraySize; i++)
                    if (layers.GetArrayElementAtIndex(i).stringValue == name) return i;
                for (var i = 8; i < layers.arraySize; i++)
                {
                    if (!string.IsNullOrEmpty(layers.GetArrayElementAtIndex(i).stringValue)) continue;
                    layers.GetArrayElementAtIndex(i).stringValue = name;
                    tags.ApplyModifiedProperties();
                    return i;
                }
                return 0;
            }
            return (Ensure("MikaProps"), Ensure("MikaActors"));
        }

        static void SetLayer(GameObject go, int layer)
        {
            foreach (var t in go.GetComponentsInChildren<Transform>(true)) t.gameObject.layer = layer;
        }

        static void AddToBuild(string path)
        {
            var scenes = EditorBuildSettings.scenes.ToList();
            if (scenes.Any(s => s.path == path)) return;
            scenes.Insert(0, new EditorBuildSettingsScene(path, true));
            EditorBuildSettings.scenes = scenes.ToArray();
        }
    }
}
