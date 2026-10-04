using System.Collections.Generic;
using System.Linq;
using Mika.World.Engine;
using UnityEditor;
using UnityEngine;

namespace Mika.Editor.Import
{
    /// <summary>
    /// La literie du lit : la couette et le plaid simulés en plusieurs formes (frontend/Web/assets-src/blender/duvet_states.py
    /// → duvet.fbx, throw.fbx) remplacent ceux qui étaient fondus dans le maillage du lit, pour qu'elle puisse ouvrir
    /// son lit, tirer la couette sur elle, se retourner dessous et la repousser (<see cref="DuvetRig"/>).
    /// </summary>
    public static class Bedding
    {
        const string DuvetFbx = RoomImporter.ArtRoot + "/Models/furniture/duvet.fbx";
        const string ThrowFbx = RoomImporter.ArtRoot + "/Models/furniture/throw.fbx";
        const string Generated = RoomImporter.ArtRoot + "/Generated";
        static readonly HashSet<string> Removed = new HashSet<string> { "M_Duvet", "M_Throw" };

        public static bool Available => AssetDatabase.LoadAssetAtPath<GameObject>(DuvetFbx) != null;

        [MenuItem("Mika/Art/Couette du lit (formes simulées)", priority = 30)]
        public static void ApplyToPrefab()
        {
            var path = $"{RoomImporter.PrefabsDir}/furniture/bed_frame.prefab";
            var layout = RoomLayout.Read($"{RoomImporter.ArtRoot}/room_layout.json");
            var obj = layout?.Objects.FirstOrDefault(o => o.Id == "bed_frame");
            var root = PrefabUtility.LoadPrefabContents(path);
            try
            {
                var model = root.transform.Find("Modèle");
                if (model == null || obj == null)
                {
                    Debug.LogWarning("[Mika] literie : lit ou mise en page introuvable.");
                    return;
                }
                Dress(root, model.gameObject, obj);
                PrefabUtility.SaveAsPrefabAsset(root, path);
            }
            finally
            {
                PrefabUtility.UnloadPrefabContents(root);
            }
            Debug.Log("[Mika] literie posée sur le lit.");
        }

        /// <summary>Pose la couette et le plaid à formes sur un lit (préfabriqué en construction).</summary>
        public static void Dress(GameObject root, GameObject model, LayoutObject obj)
        {
            if (!Available) return;
            Configure(DuvetFbx);
            Configure(ThrowFbx);
            foreach (var old in new[] { "Couette", "Plaid" })
            {
                var t = root.transform.Find(old);
                if (t != null) Object.DestroyImmediate(t.gameObject);
            }

            // Le lit sans sa couette ni son plaid (les sous-maillages de ces deux matériaux retirés).
            var mf = model.GetComponentInChildren<MeshFilter>();
            var mr = mf != null ? mf.GetComponent<MeshRenderer>() : null;
            if (mf == null || mr == null) return;
            var source = AssetDatabase.LoadAllAssetsAtPath($"{RoomImporter.ArtRoot}/{obj.Fbx}").OfType<Mesh>().FirstOrDefault();
            if (source == null) source = mf.sharedMesh;
            // L'ordre des sous-maillages est celui des matériaux de la mise en page (le lit peut être déjà dépouillé).
            var materials = obj.Materials.Select(n => AssetDatabase.LoadAssetAtPath<Material>($"{RoomImporter.ArtRoot}/Materials/{n}.mat")).ToArray();
            var keep = Enumerable.Range(0, source.subMeshCount).Where(i => i >= materials.Length || materials[i] == null || !Removed.Contains(materials[i].name)).ToList();
            var duvetMat = materials.FirstOrDefault(m => m != null && m.name == "M_Duvet");
            var throwMat = materials.FirstOrDefault(m => m != null && m.name == "M_Throw");
            var stripped = Object.Instantiate(source);
            stripped.name = source.name + "_sans_couette";
            stripped.subMeshCount = keep.Count;
            for (var i = 0; i < keep.Count; i++)
                stripped.SetTriangles(source.GetTriangles(keep[i]), i);
            stripped.RecalculateBounds();
            RoomImporter.Ensure(Generated);
            var meshPath = $"{Generated}/{stripped.name}.asset";
            var existing = AssetDatabase.LoadAssetAtPath<Mesh>(meshPath);
            if (existing != null)
            {
                EditorUtility.CopySerialized(stripped, existing);
                Object.DestroyImmediate(stripped);
                stripped = existing;
            }
            else
            {
                AssetDatabase.CreateAsset(stripped, meshPath);
            }
            mf.sharedMesh = stripped;
            mr.sharedMaterials = keep.Select(i => materials[i]).ToArray();

            // La couette et le plaid : leurs sommets sont en coordonnées de la chambre (origine de la pièce) ; on
            // annule le placement du lit pour qu'ils tombent juste, et ils le suivront s'il bouge.
            var place = Matrix4x4.TRS(RoomSpace.ToUnity(obj.Pos.X, obj.Pos.Y, obj.Pos.Z), RoomSpace.Facing(obj.Yaw), Vector3.one).inverse;
            var duvet = Add(root.transform, DuvetFbx, "Couette", place, duvetMat);
            var blanket = Add(root.transform, ThrowFbx, "Plaid", place, throwMat);
            var rig = root.GetOrAdd<DuvetRig>();
            rig.duvet = duvet;
            rig.throwBlanket = blanket;
        }

        /// <summary>
        /// Un rendu à formes pour le maillage du FBX : Unity importe un maillage à formes sans squelette en simple
        /// MeshRenderer, qui n'affiche pas les formes.
        /// </summary>
        static SkinnedMeshRenderer Add(Transform parent, string fbx, string name, Matrix4x4 place, Material material)
        {
            var mesh = AssetDatabase.LoadAllAssetsAtPath(fbx).OfType<Mesh>().FirstOrDefault();
            if (mesh == null) return null;
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            go.transform.localPosition = place.GetColumn(3);
            go.transform.localRotation = place.rotation;
            var smr = go.AddComponent<SkinnedMeshRenderer>();
            smr.sharedMesh = mesh;
            if (material != null) smr.sharedMaterials = Enumerable.Repeat(material, mesh.subMeshCount).ToArray();
            smr.updateWhenOffscreen = false;
            smr.skinnedMotionVectors = false;
            smr.localBounds = WithShapes(mesh);
            GameObjectUtility.SetStaticEditorFlags(go, 0);
            return smr;
        }

        /// <summary>La boîte du maillage avec toutes ses formes (couverte, la couette monte bien au-dessus du lit fait).</summary>
        static Bounds WithShapes(Mesh mesh)
        {
            var b = mesh.bounds;
            var v = mesh.vertices;
            var dv = new Vector3[v.Length];
            for (var s = 0; s < mesh.blendShapeCount; s++)
            {
                mesh.GetBlendShapeFrameVertices(s, mesh.GetBlendShapeFrameCount(s) - 1, dv, null, null);
                for (var i = 0; i < v.Length; i++) b.Encapsulate(v[i] + dv[i]);
            }
            return b;
        }

        static void Configure(string path)
        {
            if (!(AssetImporter.GetAtPath(path) is ModelImporter mi)) return;
            var dirty = false;
            if (!mi.importBlendShapes) { mi.importBlendShapes = true; dirty = true; }
            if (mi.importBlendShapeNormals != ModelImporterNormals.Calculate) { mi.importBlendShapeNormals = ModelImporterNormals.Calculate; dirty = true; }
            if (mi.materialImportMode != ModelImporterMaterialImportMode.None) { mi.materialImportMode = ModelImporterMaterialImportMode.None; dirty = true; }
            if (mi.animationType != ModelImporterAnimationType.None) { mi.animationType = ModelImporterAnimationType.None; dirty = true; }
            if (dirty) mi.SaveAndReimport();
        }
    }
}
