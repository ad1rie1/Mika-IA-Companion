using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>Relaie la passe IK de l'Animator (qui n'appelle que les composants de son propre objet) vers le corps.</summary>
    public sealed class IkRelay : MonoBehaviour
    {
        public ActorBody Body;

        void OnAnimatorIK(int layerIndex)
        {
            if (Body != null) Body.OnIK();
        }
    }
}
