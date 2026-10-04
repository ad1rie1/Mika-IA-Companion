using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// Relaie au corps ce que l'Animator n'envoie qu'aux composants de son propre objet : la passe IK, et le
    /// mouvement de racine des clips capturés (le recul de « s'asseoir »). Implémenter <c>OnAnimatorMove</c>
    /// retire ce mouvement à l'Animator : c'est le corps qui décide de l'appliquer ou non.
    /// </summary>
    public sealed class IkRelay : MonoBehaviour
    {
        public ActorBody Body;
        Animator _animator;

        void OnAnimatorIK(int layerIndex)
        {
            if (Body != null) Body.OnIK(layerIndex);
        }

        void OnAnimatorMove()
        {
            if (_animator == null) _animator = GetComponent<Animator>();
            if (Body != null && _animator != null) Body.OnRootMotion(_animator.deltaPosition);
        }
    }
}
