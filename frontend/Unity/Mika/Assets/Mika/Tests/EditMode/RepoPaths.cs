using System.IO;
using UnityEngine;

namespace Mika.Tests
{
    /// <summary>Les fichiers du dépôt que les tests lisent là où ils sont (la spécification, les mondes).</summary>
    static class RepoPaths
    {
        /// <summary>La racine du dépôt (<c>Assets/</c> est dans <c>frontend/Unity/Mika/</c>).</summary>
        public static string Root => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "..", ".."));

        public static string Backend(params string[] parts) => Path.Combine(Root, "backendv2", Path.Combine(parts));
    }
}
