using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// Une place sur une surface (un plateau, une étagère) : l'objet qui y est posé s'y place, son bas sur ce
    /// point. L'index est celui du protocole (<c>{"kind": "on", "object": "writing_desk", "slot": 2}</c>).
    /// </summary>
    [AddComponentMenu("Mika/Monde/Place de surface")]
    public sealed class SurfaceSlot : MonoBehaviour
    {
        [Min(0)] public int index;

        void OnDrawGizmos()
        {
            Gizmos.color = new Color(0.4f, 1f, 0.5f, 0.9f);
            Gizmos.matrix = transform.localToWorldMatrix;
            Gizmos.DrawWireCube(new Vector3(0, 0.005f, 0), new Vector3(0.14f, 0.01f, 0.14f));
            Gizmos.DrawLine(Vector3.zero, Vector3.forward * 0.08f);
        }
    }
}
