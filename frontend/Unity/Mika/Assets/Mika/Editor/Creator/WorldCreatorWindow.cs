using System.Collections.Generic;
using System.IO;
using System.Linq;
using Mika.Net;
using Mika.World.Engine;
using Mika.World.Engine.Authoring;
using Mika.World.Model;
using Mika.World.Protocol;
using UnityEditor;
using UnityEngine;

namespace Mika.Editor.Creator
{
    /// <summary>
    /// Le créateur de monde : on écrit le monde dans la scène (pièces, lieux, objets, personnages posés là où ils
    /// sont), cette fenêtre le vérifie, en tire la définition du noyau, l'exporte, l'importe, la compare à celle
    /// que tient le noyau, et lui envoie les changements (rôle <c>creator</c>, par lots qui passent en entier ou
    /// pas du tout). Les objets eux-mêmes se fabriquent ici : un modèle de la scène devient un objet du monde, ou
    /// une nouvelle sorte d'objet (archétype) avec son prefab.
    /// </summary>
    public sealed class WorldCreatorWindow : EditorWindow
    {
        static readonly string[] Tabs = { "Monde", "Lieux", "Objets", "Archétypes", "Noyau" };
        int _tab;
        Vector2 _scroll;
        List<string> _problems = new List<string>();
        WorldDef _lastExport;
        string _status;
        ArchetypeAsset _archetypeForSelection;
        string _newArchetypeId = "";
        string _newArchetypeLabel = "";
        Size _newArchetypeSize = Size.Hand;

        // Le lien avec le noyau (créateur).
        WorldSession _link;
        List<DefChange> _pending;
        string _linkStatus;

        [MenuItem("Mika/Créateur de monde", priority = 0)]
        public static void Open() => GetWindow<WorldCreatorWindow>("Créateur de monde").Show();

        WorldAuthoring Root => FindAnyObjectByType<WorldAuthoring>();

        void OnEnable() => EditorApplication.update += TickLink;

        void OnDisable()
        {
            EditorApplication.update -= TickLink;
            _link?.Dispose();
            _link = null;
        }

        void OnGUI()
        {
            var root = Root;
            if (root == null)
            {
                EditorGUILayout.HelpBox("La scène ouverte n'a pas de racine de monde. Ouvrez la chambre (Assets/Mika/Scenes/Chambre.unity) ou créez-en une.", MessageType.Info);
                if (GUILayout.Button("Créer une racine de monde ici"))
                {
                    var go = new GameObject("Monde");
                    Undo.RegisterCreatedObjectUndo(go, "Monde");
                    go.AddComponent<WorldAuthoring>();
                }
                return;
            }
            _tab = GUILayout.Toolbar(_tab, Tabs);
            _scroll = EditorGUILayout.BeginScrollView(_scroll);
            switch (_tab)
            {
                case 0: WorldTab(root); break;
                case 1: PlacesTab(root); break;
                case 2: ObjectsTab(root); break;
                case 3: ArchetypesTab(root); break;
                case 4: KernelTab(root); break;
            }
            EditorGUILayout.EndScrollView();
            if (!string.IsNullOrEmpty(_status))
                EditorGUILayout.HelpBox(_status, MessageType.None);
        }

        // --- Monde ---------------------------------------------------------------------------------------------
        void WorldTab(WorldAuthoring root)
        {
            var so = new SerializedObject(root);
            EditorGUILayout.PropertyField(so.FindProperty("worldId"), new GUIContent("Identifiant"));
            EditorGUILayout.PropertyField(so.FindProperty("label"), new GUIContent("Nom (ce qu'elle lit)"));
            EditorGUILayout.PropertyField(so.FindProperty("baseRev"), new GUIContent("Révision de base"));
            EditorGUILayout.PropertyField(so.FindProperty("catalog"), new GUIContent("Catalogue"));
            so.ApplyModifiedProperties();

            EditorGUILayout.Space();
            EditorGUILayout.LabelField("Contenu", EditorStyles.boldLabel);
            EditorGUILayout.LabelField($"{root.GetComponentsInChildren<RoomAuthoring>(true).Length} pièce(s), {root.GetComponentsInChildren<PlaceAuthoring>(true).Length} lieu(x), " +
                                       $"{root.GetComponentsInChildren<ObjectAuthoring>(true).Length} objet(s), {root.GetComponentsInChildren<ActorAuthoring>(true).Length} personnage(s)");

            EditorGUILayout.Space();
            using (new EditorGUILayout.HorizontalScope())
            {
                if (GUILayout.Button("Vérifier")) Validate(root);
                if (GUILayout.Button("Exporter en JSON…")) ExportDialog(root);
                if (GUILayout.Button("Importer un JSON…")) ImportDialog(root);
            }
            if (_problems.Count > 0)
            {
                EditorGUILayout.HelpBox($"{_problems.Count} problème(s) : le noyau refuserait ce monde.", MessageType.Warning);
                foreach (var p in _problems) EditorGUILayout.LabelField("• " + p, EditorStyles.wordWrappedLabel);
            }
            else if (_lastExport != null)
            {
                EditorGUILayout.HelpBox("Aucun problème trouvé ici (le noyau vérifiera la cohérence complète).", MessageType.Info);
            }
        }

        public WorldDef Validate(WorldAuthoring root)
        {
            _problems = new List<string>();
            _lastExport = WorldDefExporter.Export(root, _problems);
            Repaint();
            return _lastExport;
        }

        void ExportDialog(WorldAuthoring root)
        {
            var path = EditorUtility.SaveFilePanel("Exporter le monde", Path.Combine(Application.dataPath, "Mika/Content/Worlds"), root.worldId + ".json", "json");
            if (!string.IsNullOrEmpty(path)) ExportTo(root, path);
        }

        /// <summary>Écrit la définition de la scène dans un fichier (même format que les mondes du noyau).</summary>
        public string ExportTo(WorldAuthoring root, string path)
        {
            var def = Validate(root);
            var json = Newtonsoft.Json.Linq.JToken.Parse(WireJson.Write(def)).ToString(Newtonsoft.Json.Formatting.Indented);
            File.WriteAllText(path, json + "\n");
            _status = $"Exporté : {path} ({def.Objects.Count} objets, {def.Places.Count} lieux){(_problems.Count > 0 ? $" — {_problems.Count} problème(s)" : "")}.";
            AssetDatabase.Refresh();
            return path;
        }

        void ImportDialog(WorldAuthoring root)
        {
            var path = EditorUtility.OpenFilePanel("Importer un monde", Path.Combine(Application.dataPath, "Mika/Content/Worlds"), "json");
            if (!string.IsNullOrEmpty(path)) ImportFrom(root, path);
        }

        public void ImportFrom(WorldAuthoring root, string path)
        {
            var def = WireJson.ReadWorld(File.ReadAllText(path));
            var (created, updated) = WorldSceneImporter.Import(def, root);
            _status = $"Importé : {created} créé(s), {updated} mis à jour. Rien n'a été retiré de la scène.";
        }

        // --- Lieux ----------------------------------------------------------------------------------------------
        void PlacesTab(WorldAuthoring root)
        {
            foreach (var room in root.GetComponentsInChildren<RoomAuthoring>(true))
            {
                EditorGUILayout.LabelField($"{room.label} ({room.id})", EditorStyles.boldLabel);
                foreach (var p in room.GetComponentsInChildren<PlaceAuthoring>(true))
                {
                    using (new EditorGUILayout.HorizontalScope())
                    {
                        EditorGUILayout.LabelField($"{p.id}", GUILayout.Width(110));
                        EditorGUILayout.LabelField($"{p.label}  ·  {KindLabel(p.kind)}{(p.tags.Count > 0 ? "  ·  " + string.Join(", ", p.tags) : "")}");
                        if (GUILayout.Button("Voir", GUILayout.Width(50))) Focus(p.gameObject);
                    }
                }
                if (GUILayout.Button($"+ Un lieu dans {room.id}, là où regarde la vue"))
                    AddPlace(room);
            }
            EditorGUILayout.Space();
            if (GUILayout.Button("+ Une pièce"))
            {
                var go = new GameObject("nouvelle_piece");
                Undo.RegisterCreatedObjectUndo(go, "Pièce");
                go.transform.SetParent(root.transform, false);
                var r = go.AddComponent<RoomAuthoring>();
                r.id = "nouvelle_piece";
                r.label = "une nouvelle pièce";
                Selection.activeGameObject = go;
            }
            EditorGUILayout.HelpBox("Un lieu : sa position est le point d'arrivée à pied, sa flèche le sens dans lequel on s'y tient. Une assise ou un lit porte en plus « Assise » (les hanches) et « Allongée ».", MessageType.None);
        }

        static string KindLabel(PlaceKind k) => k switch { PlaceKind.Seat => "assise", PlaceKind.Bed => "lit", _ => "debout" };

        void AddPlace(RoomAuthoring room)
        {
            var view = SceneView.lastActiveSceneView;
            var pos = room.transform.position;
            if (view != null && Physics.Raycast(view.camera.transform.position, view.camera.transform.forward, out var hit, 30f))
                pos = hit.point;
            else if (view != null)
                pos = view.pivot;
            pos.y = room.transform.position.y;
            var go = new GameObject("Lieu · nouveau");
            Undo.RegisterCreatedObjectUndo(go, "Lieu");
            go.transform.SetParent(room.transform.Find("Lieux") ?? room.transform, true);
            go.transform.position = pos;
            var p = go.AddComponent<PlaceAuthoring>();
            p.id = "nouveau_lieu";
            p.label = "un nouvel endroit";
            Selection.activeGameObject = go;
        }

        // --- Objets ----------------------------------------------------------------------------------------------
        void ObjectsTab(WorldAuthoring root)
        {
            EditorGUILayout.LabelField("Faire de la sélection un objet du monde", EditorStyles.boldLabel);
            _archetypeForSelection = (ArchetypeAsset)EditorGUILayout.ObjectField("Archétype", _archetypeForSelection, typeof(ArchetypeAsset), false);
            using (new EditorGUI.DisabledScope(Selection.gameObjects.Length == 0 || _archetypeForSelection == null))
                if (GUILayout.Button($"Faire de {Selection.gameObjects.Length} objet(s) sélectionné(s) des objets du monde"))
                    foreach (var go in Selection.gameObjects) MakeWorldObject(go, _archetypeForSelection);

            EditorGUILayout.Space();
            var objects = root.GetComponentsInChildren<ObjectAuthoring>(true).OrderBy(o => o.archetype != null ? o.archetype.id : "").ThenBy(o => o.id);
            string group = null;
            foreach (var o in objects)
            {
                var g = o.archetype != null ? $"{o.archetype.label} ({o.archetype.id})" : "sans archétype";
                if (g != group)
                {
                    group = g;
                    EditorGUILayout.LabelField(g, EditorStyles.boldLabel);
                }
                using (new EditorGUILayout.HorizontalScope())
                {
                    EditorGUILayout.LabelField(o.id, GUILayout.Width(170));
                    EditorGUILayout.LabelField(string.IsNullOrEmpty(o.label) ? "—" : o.label);
                    if (GUILayout.Button("Voir", GUILayout.Width(50))) Focus(o.gameObject);
                }
            }
        }

        /// <summary>Un objet de la scène devient un objet du monde (avec son rendu prêt à vivre).</summary>
        public static ObjectAuthoring MakeWorldObject(GameObject go, ArchetypeAsset archetype)
        {
            var oa = go.TryGetComponent<ObjectAuthoring>(out var existing) ? existing : Undo.AddComponent<ObjectAuthoring>(go);
            if (string.IsNullOrEmpty(oa.id)) oa.id = Slug(go.name);
            oa.archetype = archetype;
            if (go.GetComponent<WorldObject>() == null) Undo.AddComponent<WorldObject>(go).id = oa.id;
            if (go.GetComponentInChildren<Collider>() == null)
            {
                var box = Undo.AddComponent<BoxCollider>(go);
                var rs = go.GetComponentsInChildren<Renderer>();
                if (rs.Length > 0)
                {
                    var b = rs[0].bounds;
                    foreach (var r in rs.Skip(1)) b.Encapsulate(r.bounds);
                    box.center = go.transform.InverseTransformPoint(b.center);
                    box.size = b.size;
                }
            }
            EditorUtility.SetDirty(oa);
            return oa;
        }

        // --- Archétypes ----------------------------------------------------------------------------------------------
        void ArchetypesTab(WorldAuthoring root)
        {
            EditorGUILayout.LabelField("Nouvelle sorte d'objet à partir de la sélection", EditorStyles.boldLabel);
            _newArchetypeId = EditorGUILayout.TextField("Identifiant", _newArchetypeId);
            _newArchetypeLabel = EditorGUILayout.TextField("Nom (ce qu'elle lit)", _newArchetypeLabel);
            _newArchetypeSize = (Size)EditorGUILayout.EnumPopup("Taille", _newArchetypeSize);
            using (new EditorGUI.DisabledScope(Selection.activeGameObject == null || string.IsNullOrEmpty(_newArchetypeId)))
                if (GUILayout.Button("Créer l'archétype (prefab + asset) et l'ajouter au catalogue"))
                {
                    var a = CreateArchetype(Selection.activeGameObject, _newArchetypeId.Trim(), _newArchetypeLabel.Trim(), _newArchetypeSize, root.catalog);
                    Selection.activeObject = a;
                }
            EditorGUILayout.HelpBox("Les états, les actions (allumer, lire…) et les places de surface se règlent ensuite dans l'inspecteur de l'archétype. Le prefab reçoit un « Objet du monde (rendu) » : ajoutez-y ses places (SurfaceSlot) et ses visuels d'état (charnière, lumière, afficher/masquer).", MessageType.None);

            EditorGUILayout.Space();
            if (root.catalog == null) return;
            foreach (var a in root.catalog.archetypes.Where(a => a != null).OrderBy(a => a.id))
            {
                using (new EditorGUILayout.HorizontalScope())
                {
                    EditorGUILayout.LabelField(a.id, GUILayout.Width(130));
                    var extra = new List<string> { a.size.ToString().ToLowerInvariant() };
                    if (a.states.Count > 0) extra.Add("états : " + string.Join("/", a.states));
                    if (a.affordances.Count > 0) extra.Add("actions : " + string.Join(", ", a.affordances.Select(f => f.label)));
                    if (a.prefab == null) extra.Add("SANS PREFAB");
                    EditorGUILayout.LabelField($"{a.label} — {string.Join(" · ", extra)}", EditorStyles.wordWrappedMiniLabel);
                    if (GUILayout.Button("Ouvrir", GUILayout.Width(55))) Selection.activeObject = a;
                }
            }
        }

        public static ArchetypeAsset CreateArchetype(GameObject source, string id, string label, Size size, AssetCatalog catalog)
        {
            const string dir = "Assets/Mika/Content/Archetypes";
            const string prefabDir = "Assets/Mika/Content/Prefabs";
            Import.RoomImporter.Ensure(dir);
            Import.RoomImporter.Ensure(prefabDir);
            var copy = Instantiate(source);
            copy.name = id;
            copy.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
            foreach (var oa in copy.GetComponentsInChildren<ObjectAuthoring>(true)) DestroyImmediate(oa);
            var wo = copy.GetOrAdd<WorldObject>();
            wo.id = "";
            var prefab = PrefabUtility.SaveAsPrefabAsset(copy, $"{prefabDir}/{id}.prefab");
            DestroyImmediate(copy);
            var asset = CreateInstance<ArchetypeAsset>();
            asset.id = id;
            asset.label = string.IsNullOrEmpty(label) ? id : label;
            asset.size = size;
            asset.assetKey = (size == Size.Fixed ? "furniture/" : "props/") + id;
            asset.prefab = prefab;
            AssetDatabase.CreateAsset(asset, $"{dir}/{id}.asset");
            if (catalog != null)
            {
                catalog.archetypes.Add(asset);
                catalog.Invalidate();
                EditorUtility.SetDirty(catalog);
            }
            AssetDatabase.SaveAssets();
            return asset;
        }

        // --- Noyau ----------------------------------------------------------------------------------------------------
        void KernelTab(WorldAuthoring root)
        {
            EditorGUILayout.HelpBox("Comparer la scène au monde que tient le noyau, puis lui envoyer les changements en un seul lot (rôle créateur : un compte opérateur, jeton « mw_… »). Le noyau valide tout ; un lot qui rendrait le monde incohérent est refusé en entier.", MessageType.None);
            var url = EditorPrefs.GetString("mika.creator.url", "http://127.0.0.1:8001");
            var token = EditorPrefs.GetString("mika.creator.token", "");
            url = EditorGUILayout.TextField("Adresse du noyau", url);
            token = EditorGUILayout.PasswordField("Jeton", token);
            EditorPrefs.SetString("mika.creator.url", url);
            EditorPrefs.SetString("mika.creator.token", token);
            using (new EditorGUILayout.HorizontalScope())
            {
                if (GUILayout.Button(_link == null ? "Se connecter" : "Reconnecter")) Connect(url, token);
                using (new EditorGUI.DisabledScope(_link == null || _link.Mirror.World == null))
                {
                    if (GUILayout.Button("Comparer")) Compare(root);
                    if (GUILayout.Button("Importer le monde du noyau")) ImportKernel(root);
                }
            }
            if (!string.IsNullOrEmpty(_linkStatus)) EditorGUILayout.HelpBox(_linkStatus, MessageType.Info);
            if (_pending != null)
            {
                EditorGUILayout.LabelField($"{_pending.Count} changement(s)", EditorStyles.boldLabel);
                foreach (var c in _pending.Take(200)) EditorGUILayout.LabelField(WorldDiff.Describe(c));
                using (new EditorGUI.DisabledScope(_pending.Count == 0))
                    if (GUILayout.Button("Envoyer au noyau")) Push();
            }
        }

        void Connect(string url, string token)
        {
            _link?.Dispose();
            _link = new WorldSession(new WorldSessionOptions { BaseUrl = url, Token = token, Roles = new List<Role> { Role.Viewer, Role.Creator }, ClientName = "Mika Unity (créateur)" })
            {
                Log = m => _linkStatus = m,
            };
            _link.Welcomed += w => _linkStatus = $"Connecté au monde « {w.World} » (révision {w.Rev}) ; rôles : {string.Join(", ", w.Granted.Select(r => WireJson.Name(r)))}.";
            _link.Connect();
            _linkStatus = "Connexion…";
        }

        void TickLink()
        {
            if (_link == null) return;
            _link.Tick(EditorApplication.timeSinceStartup);
            if (_link.State == LinkState.Refused) _linkStatus = "Connexion refusée : vérifiez le jeton (un compte opérateur).";
        }

        void Compare(WorldAuthoring root)
        {
            var problems = new List<string>();
            var scene = WorldDefExporter.Export(root, problems);
            _pending = WorldDiff.Between(_link.Mirror.World.Def, scene);
            _linkStatus = problems.Count > 0 ? $"Attention : {problems.Count} problème(s) dans la scène (onglet Monde)." : $"Le noyau est à la révision {_link.Mirror.World.Rev}.";
        }

        void ImportKernel(WorldAuthoring root)
        {
            var (created, updated) = WorldSceneImporter.Import(WorldIndex.Clone(_link.Mirror.World.Def), root);
            _status = $"Monde du noyau importé : {created} créé(s), {updated} mis à jour.";
        }

        async void Push()
        {
            if (_link == null || _pending == null || _link.Mirror.World == null) return;
            var result = await _link.Command(new Edit { Base = _link.Mirror.World.Rev, Changes = _pending });
            _linkStatus = result.Status == Status.Accepted
                ? $"Accepté (seq {result.Seq}) : le monde est à jour."
                : $"Refusé ({(result.Code.HasValue ? WireJson.Name(result.Code.Value) : "?")}) : {result.Message}";
            if (result.Status == Status.Accepted)
            {
                _pending = null;
                var root = Root;
                if (root != null)
                {
                    root.baseRev = _link.Mirror.World.Rev;
                    EditorUtility.SetDirty(root);
                }
            }
            Repaint();
        }

        // --- utilitaires -------------------------------------------------------------------------------------------------
        static void Focus(GameObject go)
        {
            Selection.activeGameObject = go;
            SceneView.lastActiveSceneView?.FrameSelected();
        }

        static string Slug(string name)
        {
            var s = new string(name.ToLowerInvariant().Select(c => char.IsLetterOrDigit(c) && c < 128 ? c : '_').ToArray()).Trim('_');
            while (s.Contains("__")) s = s.Replace("__", "_");
            if (s.Length == 0 || !char.IsLetter(s[0])) s = "objet_" + s;
            return s.Length > 48 ? s.Substring(0, 48) : s;
        }
    }
}
