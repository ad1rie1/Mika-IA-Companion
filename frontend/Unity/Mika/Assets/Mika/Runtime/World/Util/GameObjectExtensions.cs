using UnityEngine;

namespace Mika.World.Engine
{
    public static class GameObjectExtensions
    {
        /// <summary>
        /// Le composant s'il existe, sinon un nouveau. À préférer à <c>GetComponent&lt;T&gt;() ?? AddComponent&lt;T&gt;()</c> :
        /// Unity rend un faux « null » que l'opérateur <c>??</c> ne voit pas (l'appel suivant lève alors
        /// <c>MissingComponentException</c>).
        /// </summary>
        public static T GetOrAdd<T>(this GameObject go) where T : Component =>
            go.TryGetComponent<T>(out var c) ? c : go.AddComponent<T>();

        public static T GetOrAdd<T>(this Component c) where T : Component => c.gameObject.GetOrAdd<T>();
    }
}
