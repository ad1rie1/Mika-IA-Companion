using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>Une clé d'asset du monde (« props/mug », « avatars/mika ») et ce qui la montre.</summary>
    [Serializable]
    public sealed class AssetEntry
    {
        public string key;
        public GameObject prefab;
    }

    /// <summary>
    /// Ce que le moteur sait montrer : chaque clé d'asset que la définition du monde peut nommer, et son prefab.
    /// Les archétypes y sont listés avec leur prefab ; les autres clés (avatars, personnages) en entrées libres.
    /// </summary>
    /// <remarks>
    /// Une clé inconnue n'est pas une erreur : le moteur montre un substitut et le dit au noyau (<c>loaded</c>,
    /// <c>missing_assets</c>), qui l'affiche dans la console. Un monde peut donc avancer plus vite que ses modèles.
    /// </remarks>
    [CreateAssetMenu(menuName = "Mika/Monde/Catalogue d'assets", fileName = "AssetCatalog")]
    public sealed class AssetCatalog : ScriptableObject
    {
        public List<ArchetypeAsset> archetypes = new List<ArchetypeAsset>();
        public List<AssetEntry> entries = new List<AssetEntry>();

        [NonSerialized] Dictionary<string, GameObject> _byKey;
        [NonSerialized] Dictionary<string, ArchetypeAsset> _byArchetype;

        void OnValidate()
        {
            _byKey = null;
            _byArchetype = null;
        }

        void Build()
        {
            _byKey = new Dictionary<string, GameObject>(StringComparer.Ordinal);
            _byArchetype = new Dictionary<string, ArchetypeAsset>(StringComparer.Ordinal);
            foreach (var a in archetypes.Where(a => a != null))
            {
                if (!string.IsNullOrEmpty(a.id))
                    _byArchetype[a.id] = a;
                if (!string.IsNullOrEmpty(a.assetKey) && a.prefab != null)
                    _byKey[a.assetKey] = a.prefab;
            }
            foreach (var e in entries.Where(e => e != null && !string.IsNullOrEmpty(e.key) && e.prefab != null))
                _byKey[e.key] = e.prefab;
        }

        public GameObject Prefab(string key)
        {
            if (string.IsNullOrEmpty(key)) return null;
            if (_byKey == null) Build();
            return _byKey.TryGetValue(key, out var p) ? p : null;
        }

        public bool Has(string key) => Prefab(key) != null;

        public ArchetypeAsset Archetype(string id)
        {
            if (string.IsNullOrEmpty(id)) return null;
            if (_byArchetype == null) Build();
            return _byArchetype.TryGetValue(id, out var a) ? a : null;
        }

        public void Invalidate() => OnValidate();
    }
}
