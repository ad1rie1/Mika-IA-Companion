using System.Collections.Generic;
using System.IO;
using Mika.Chat;
using Mika.Net;
using Mika.Player;
using Mika.UI;
using Mika.World.Engine;
using Mika.World.Model;
using Mika.World.Protocol;
using UnityEngine;

namespace Mika.App
{
    /// <summary>
    /// Le point de départ du client Unity : il ouvre les deux connexions au noyau — le monde (<c>/ws/world</c>) et
    /// la conversation (<c>/ws</c>) —, les relie à la scène (<see cref="WorldStage"/>), à l'hôte, au corps de la
    /// joueuse et à l'interface, et les fait avancer à chaque image. Sans noyau, il montre un aperçu du monde
    /// tel qu'il est écrit, sans rien faire bouger.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Mika/Application")]
    public sealed class MikaApp : MonoBehaviour
    {
        public WorldStage stage;
        public HostReporter host;
        public PlayerController player;
        public PlayerPresence presence;
        public PlayerInteractor interactor;
        public WorldHud hud;
        [Tooltip("Le monde à montrer hors ligne (le monde par défaut du noyau).")]
        public TextAsset offlineWorld;
        [Tooltip("Chemin du monde par défaut dans le dépôt (lu de préférence dans l'éditeur : il ne vieillit pas).")]
        public string repoWorldPath = "../../backendv2/src/mika/faculties/world/chambre.json";
        [Tooltip("Sans réponse du noyau après ce délai (s), montrer l'aperçu.")]
        public float offlineAfter = 3f;
        [Tooltip("L'acteur de Mika dans le monde.")]
        public string mikaActor = "mika";

        WorldSession _world;
        ChatSession _chat;
        float _startedAt;
        bool _preview;

        public WorldSession World => _world;
        public ChatSession Chat => _chat;

        /// <summary>Une parole de Mika (pour la couche avatar : visage, lèvres).</summary>
        public event System.Action<SpeechFrame> MikaSpoke;
        public event System.Action<EmotionUpdateFrame> MikaMoodDrifted;
        public event System.Action<InnerStateFrame> InnerStateChanged;
        /// <summary>L'accusé d'un message de la joueuse (accepté : une réponse se compose).</summary>
        public event System.Action<AckFrame> MessageAcknowledged;
        /// <summary>Les sessions viennent d'être (re)créées.</summary>
        public event System.Action Connected;

        void Start()
        {
            if (hud != null) hud.SettingsApplied += (url, token, wantHost) => Connect(url, token, wantHost);
            Connect(PlayerPrefs.GetString("mika.baseUrl", "http://127.0.0.1:8001"), PlayerPrefs.GetString("mika.token", ""),
                PlayerPrefs.GetInt("mika.host", 1) == 1);
        }

        /// <summary>(Re)connecte le monde et la conversation avec ces réglages.</summary>
        public void Connect(string baseUrl, string token, bool wantHost)
        {
            _world?.Dispose();
            _chat?.Dispose();
            var roles = new List<Role> { Role.Viewer };
            if (wantHost) roles.Add(Role.Host);
            var mirror = new WorldMirror();
            _world = new WorldSession(new WorldSessionOptions { BaseUrl = baseUrl, Token = token, Roles = roles, Avatar = "avatars/default" }, mirror)
            {
                Log = m => Debug.Log("[Mika] " + m),
            };
            _chat = new ChatSession(new ChatSessionOptions { BaseUrl = baseUrl, Token = token }) { Log = m => Debug.Log("[Mika] " + m) };

            stage.Bind(mirror, _world.Clock, host);
            host?.Bind(_world, stage);
            presence?.Bind(_world, stage);
            interactor?.Bind(_world, stage);
            hud?.Bind(_world, _chat);

            _chat.Speech += s => MikaSpoke?.Invoke(s);
            _chat.EmotionUpdate += u => MikaMoodDrifted?.Invoke(u);
            _chat.InnerState += s => InnerStateChanged?.Invoke(s);
            _chat.Ack += a => MessageAcknowledged?.Invoke(a);
            _world.Welcomed += _ =>
            {
                _preview = false;
                hud?.SetWorldNote(null);
            };

            _preview = false;
            _startedAt = Time.unscaledTime;
            _world.Connect();
            _chat.Connect();
            Connected?.Invoke();
        }

        void Update()
        {
            var now = Time.realtimeSinceStartupAsDouble;
            _world?.Tick(now);
            _chat?.Tick(now);
            if (_world != null && !_preview && !_world.Mirror.Ready && Time.unscaledTime - _startedAt > offlineAfter)
                StartPreview();
        }

        void StartPreview()
        {
            var def = LoadOfflineWorld();
            if (def == null) return;
            _preview = true;
            OfflinePreview.Apply(_world.Mirror, def);
            hud?.SetWorldNote("Monde : aperçu hors ligne (noyau injoignable)");
        }

        WorldDef LoadOfflineWorld()
        {
            try
            {
#if UNITY_EDITOR
                var path = Path.GetFullPath(Path.Combine(Application.dataPath, "..", repoWorldPath));
                if (File.Exists(path)) return WireJson.ReadWorld(File.ReadAllText(path));
#endif
                return offlineWorld != null ? WireJson.ReadWorld(offlineWorld.text) : null;
            }
            catch (System.Exception e)
            {
                Debug.LogWarning("[Mika] aperçu hors ligne impossible : " + e.Message);
                return null;
            }
        }

        void OnDestroy()
        {
            _world?.Dispose();
            _chat?.Dispose();
        }
    }
}
