using UnityEngine.InputSystem;

namespace Mika.Player
{
    /// <summary>
    /// Les commandes de la joueuse, déclarées ici plutôt que dans un fichier d'actions : une seule source, lisible
    /// et testable. Clavier/souris et manette.
    /// </summary>
    public sealed class PlayerInputs : System.IDisposable
    {
        public readonly InputAction Move = new InputAction("Move", InputActionType.Value);
        public readonly InputAction Look = new InputAction("Look", InputActionType.Value);
        public readonly InputAction Run = new InputAction("Run", InputActionType.Button);
        public readonly InputAction Interact = new InputAction("Interact", InputActionType.Button);
        public readonly InputAction Menu = new InputAction("Menu", InputActionType.Button);
        public readonly InputAction Drop = new InputAction("Drop", InputActionType.Button);
        public readonly InputAction Chat = new InputAction("Chat", InputActionType.Button);
        public readonly InputAction Cursor = new InputAction("Cursor", InputActionType.Button);
        public readonly InputAction View = new InputAction("View", InputActionType.Button);
        public readonly InputAction Scroll = new InputAction("Scroll", InputActionType.Value);

        public PlayerInputs()
        {
            // Les touches sont des positions physiques (disposition US) : « w a s d » est aussi « z q s d » sur
            // un clavier AZERTY, sans rien de plus à déclarer.
            Move.AddCompositeBinding("2DVector")
                .With("Up", "<Keyboard>/w")
                .With("Down", "<Keyboard>/s")
                .With("Left", "<Keyboard>/a")
                .With("Right", "<Keyboard>/d");
            Move.AddBinding("<Gamepad>/leftStick");
            Look.AddBinding("<Mouse>/delta");
            Look.AddBinding("<Gamepad>/rightStick").WithProcessor("scaleVector2(x=12,y=12)");
            Run.AddBinding("<Keyboard>/leftShift");
            Run.AddBinding("<Gamepad>/leftStickPress");
            Interact.AddBinding("<Keyboard>/e");
            Interact.AddBinding("<Mouse>/leftButton");
            Interact.AddBinding("<Gamepad>/buttonSouth");
            Menu.AddBinding("<Keyboard>/f");
            Menu.AddBinding("<Mouse>/rightButton");
            Menu.AddBinding("<Gamepad>/buttonWest");
            Drop.AddBinding("<Keyboard>/g");
            Drop.AddBinding("<Gamepad>/buttonEast");
            Chat.AddBinding("<Keyboard>/t");
            Chat.AddBinding("<Keyboard>/enter");
            Cursor.AddBinding("<Keyboard>/tab");
            Cursor.AddBinding("<Keyboard>/escape");
            View.AddBinding("<Keyboard>/v");
            Scroll.AddBinding("<Mouse>/scroll/y");
        }

        public void Enable(bool on)
        {
            foreach (var a in All)
                if (on) a.Enable(); else a.Disable();
        }

        /// <summary>Le jeu sans le clavier (pendant qu'on écrit dans la conversation).</summary>
        public void EnableGameplay(bool on)
        {
            foreach (var a in new[] { Move, Look, Run, Interact, Menu, Drop, View, Scroll })
                if (on) a.Enable(); else a.Disable();
        }

        InputAction[] All => new[] { Move, Look, Run, Interact, Menu, Drop, Chat, Cursor, View, Scroll };

        public void Dispose()
        {
            foreach (var a in All) a.Dispose();
        }
    }
}
