using System.Collections.Generic;
using System.Linq;
using Mika.World.Engine;
using Mika.World.Engine.Authoring;
using Mika.World.Protocol;
using UnityEditor;
using UnityEngine;

namespace Mika.Editor.Creator
{
    /// <summary>
    /// Le chemin inverse de l'export : une définition du monde (un fichier, ou celle que tient le noyau) posée dans
    /// la scène ouverte. Ce qui existe déjà (même identifiant) est mis à jour, ce qui manque est créé — un objet
    /// depuis le prefab de son archétype, à son emplacement de départ. Rien n'est supprimé : un import n'efface
    /// pas le travail du créateur (le retrait se fait à la main, puis s'exporte).
    /// </summary>
    public static class WorldSceneImporter
    {
        const string ArchetypesDir = "Assets/Mika/Content/Archetypes";

        public static (int created, int updated) Import(WorldDef def, WorldAuthoring root)
        {
            var created = 0;
            var updated = 0;
            Undo.RegisterFullObjectHierarchyUndo(root.gameObject, "Importer un monde");
            root.worldId = def.Id;
            root.label = def.Label;
            root.baseRev = def.Rev;

            var rooms = root.GetComponentsInChildren<RoomAuthoring>(true).ToDictionary(r => r.id);
            foreach (var r in def.Rooms)
            {
                if (!rooms.TryGetValue(r.Id, out var ra))
                {
                    var go = new GameObject(r.Id);
                    Undo.RegisterCreatedObjectUndo(go, "Pièce");
                    go.transform.SetParent(root.transform, false);
                    go.transform.localPosition = new Vector3(12f * rooms.Count, 0, 0);
                    ra = go.AddComponent<RoomAuthoring>();
                    ra.id = r.Id;
                    rooms[r.Id] = ra;
                    created++;
                }
                else updated++;
                ra.label = r.Label;
                ra.tags = r.Tags?.ToList() ?? new List<string>();
            }

            var places = root.GetComponentsInChildren<PlaceAuthoring>(true).ToDictionary(p => p.id);
            foreach (var p in def.Places)
            {
                if (!rooms.TryGetValue(p.Room, out var room)) continue;
                if (!places.TryGetValue(p.Id, out var pa))
                {
                    var go = new GameObject($"Lieu · {p.Id}");
                    Undo.RegisterCreatedObjectUndo(go, "Lieu");
                    var parent = room.transform.Find("Lieux") ?? room.transform;
                    go.transform.SetParent(parent, false);
                    pa = go.AddComponent<PlaceAuthoring>();
                    pa.id = p.Id;
                    places[p.Id] = pa;
                    created++;
                }
                else updated++;
                pa.label = p.Label;
                pa.kind = p.PlaceKind;
                pa.capacity = p.Capacity;
                pa.tags = p.Tags?.ToList() ?? new List<string>();
                pa.transform.position = room.transform.TransformPoint(RoomSpace.ToUnity(p.Pos));
                pa.transform.rotation = room.transform.rotation * RoomSpace.Facing(p.Facing ?? 0);
            }
            foreach (var r in def.Rooms)
            {
                var ra = rooms[r.Id];
                ra.exits = (r.Exits ?? new List<Exit>()).Select(e => new ExitSpec
                {
                    via = places.TryGetValue(e.Via, out var v) ? v : null,
                    to = rooms.TryGetValue(e.To, out var t) ? t : null,
                    arrives = places.TryGetValue(e.Arrives, out var a) ? a : null,
                }).ToList();
            }

            var archetypes = def.Archetypes.ToDictionary(a => a.Id, Archetype);
            if (root.catalog != null)
            {
                foreach (var a in archetypes.Values.Where(a => !root.catalog.archetypes.Contains(a)))
                    root.catalog.archetypes.Add(a);
                root.catalog.Invalidate();
                EditorUtility.SetDirty(root.catalog);
            }

            var objects = root.GetComponentsInChildren<ObjectAuthoring>(true).ToDictionary(o => o.id);
            foreach (var o in def.Objects)
            {
                archetypes.TryGetValue(o.Archetype, out var archetype);
                if (!objects.TryGetValue(o.Id, out var oa))
                {
                    var prefab = archetype != null ? archetype.prefab : null;
                    var go = prefab != null ? (GameObject)PrefabUtility.InstantiatePrefab(prefab) : GameObject.CreatePrimitive(PrimitiveType.Cube);
                    Undo.RegisterCreatedObjectUndo(go, "Objet");
                    go.name = o.Id;
                    oa = go.AddComponent<ObjectAuthoring>();
                    oa.id = o.Id;
                    Place(go.transform, o.Home, rooms, places, objects);
                    objects[o.Id] = oa;
                    created++;
                }
                else updated++;
                oa.archetype = archetype;
                oa.label = o.Label;
                oa.state = o.State;
                oa.owner = o.Owner;
                oa.givenBy = o.GivenBy;
                oa.access = o.Access;
                oa.overrideSalience = o.Salience.HasValue;
                if (o.Salience.HasValue) oa.salience = (float)o.Salience.Value;
                oa.tags = o.Tags?.ToList() ?? new List<string>();
                switch (o.Home)
                {
                    case On on when objects.TryGetValue(on.Object, out var support):
                        oa.home = HomeKind.On;
                        oa.support = support;
                        oa.slot = on.Slot;
                        break;
                    case In inside when objects.TryGetValue(inside.Object, out var container):
                        oa.home = HomeKind.In;
                        oa.support = container;
                        break;
                    case InRoom ir:
                        oa.home = HomeKind.Room;
                        oa.near = ir.Near != null && places.TryGetValue(ir.Near, out var near) ? near : null;
                        break;
                }
                EditorUtility.SetDirty(oa);
            }

            var actors = root.GetComponentsInChildren<ActorAuthoring>(true).ToDictionary(a => a.id);
            foreach (var a in def.Actors)
            {
                if (!actors.TryGetValue(a.Id, out var aa))
                {
                    var go = new GameObject($"Personnage · {a.Id}");
                    Undo.RegisterCreatedObjectUndo(go, "Personnage");
                    go.transform.SetParent(root.transform, false);
                    aa = go.AddComponent<ActorAuthoring>();
                    aa.id = a.Id;
                    created++;
                }
                else updated++;
                aa.label = a.Label;
                aa.assetKey = a.Asset;
                aa.controller = a.Controller;
                aa.tags = a.Tags?.ToList() ?? new List<string>();
                aa.home = places.TryGetValue(a.Home, out var home) ? home : null;
                if (aa.home != null) aa.transform.position = aa.home.transform.position;
            }
            return (created, updated);
        }

        /// <summary>L'asset d'un archétype reçu : mis à jour s'il existe (son prefab reste), créé sinon.</summary>
        static ArchetypeAsset Archetype(ArchetypeDef def)
        {
            var path = $"{ArchetypesDir}/{def.Id}.asset";
            var asset = AssetDatabase.LoadAssetAtPath<ArchetypeAsset>(path);
            if (asset == null)
            {
                asset = ScriptableObject.CreateInstance<ArchetypeAsset>();
                AssetDatabase.CreateAsset(asset, path);
            }
            asset.CopyFrom(def);
            EditorUtility.SetDirty(asset);
            return asset;
        }

        static void Place(Transform t, Location home, Dictionary<string, RoomAuthoring> rooms, Dictionary<string, PlaceAuthoring> places, Dictionary<string, ObjectAuthoring> objects)
        {
            switch (home)
            {
                case InRoom ir when rooms.TryGetValue(ir.Room, out var room):
                    t.SetParent(room.transform, true);
                    t.position = ir.Near != null && places.TryGetValue(ir.Near, out var near)
                        ? near.transform.position + near.transform.rotation * new Vector3(0.3f, 0, 0.5f)
                        : room.transform.position;
                    break;
                case On on when objects.TryGetValue(on.Object, out var support):
                    var slot = support.GetComponentsInChildren<SurfaceSlot>(true).FirstOrDefault(s => s.index == on.Slot);
                    t.SetParent(support.transform.parent, true);
                    t.position = slot != null ? slot.transform.position : support.transform.position + Vector3.up;
                    break;
                case In inside when objects.TryGetValue(inside.Object, out var container):
                    t.SetParent(container.transform, true);
                    t.localPosition = Vector3.zero;
                    break;
            }
        }
    }
}
