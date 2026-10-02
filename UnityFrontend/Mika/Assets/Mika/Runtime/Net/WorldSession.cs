using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Mika.World.Model;
using Mika.World.Protocol;

namespace Mika.Net
{
    /// <summary>Comment se connecter au monde.</summary>
    public sealed class WorldSessionOptions
    {
        /// <summary>L'adresse du noyau (<c>http://127.0.0.1:8001</c>, le port de <c>mika serve</c>) ; la route <c>/ws/world</c> s'y ajoute.</summary>
        public string BaseUrl = "http://127.0.0.1:8001";
        public List<Role> Roles = new List<Role> { Role.Viewer };
        /// <summary>Jeton du compte (client natif) : sans lui, le noyau refuse une connexion sans <c>Origin</c>.</summary>
        public string Token;
        /// <summary>Le modèle du corps de la personne connectée (clé d'asset du moteur).</summary>
        public string Avatar;
        public string ClientName = "Mika Unity";
        public string ClientVersion = "0.1.0";
        public string Engine = "unity";
        public double PingIntervalS = 5;
        /// <summary>Sans aucune trame pendant ce temps, la connexion est tenue pour morte et rouverte.</summary>
        public double SilenceTimeoutS = 20;
        public double CommandTimeoutS = 10;

        public Uri WorldUri()
        {
            var b = new UriBuilder(BaseUrl.TrimEnd('/'));
            b.Scheme = b.Scheme == "https" ? "wss" : "ws";
            b.Path = b.Path.TrimEnd('/') + Wire.Path;
            return b.Uri;
        }
    }

    public enum LinkState
    {
        Offline,
        Connecting,
        /// <summary>Ouverte, <c>hello</c> envoyé, en attente de <c>welcome</c>.</summary>
        Greeting,
        Online,
        /// <summary>Refusée pour de bon (authentification) : on ne réessaie pas tout seul.</summary>
        Refused,
    }

    /// <summary>
    /// Une session du protocole <c>mika.world/1</c> : se présenter, tenir le miroir du monde à jour dans l'ordre
    /// du journal, renouveler le bail d'hôte, envoyer des commandes et recevoir leur accusé, se reconnecter.
    /// </summary>
    /// <remarks>
    /// Sans Unity : le fil principal appelle <see cref="Tick"/> à chaque image ; tout ce que la session signale
    /// (événements, accusés, miroir) arrive donc sur ce fil, jamais sur celui du réseau.
    /// </remarks>
    public sealed class WorldSession : IDisposable
    {
        readonly WsChannel _channel = new WsChannel();
        readonly Dictionary<string, Pending> _pending = new Dictionary<string, Pending>();
        readonly Dictionary<string, Bucket> _buckets = new Dictionary<string, Bucket>();
        readonly string _prefix = Guid.NewGuid().ToString("N").Substring(0, 6);
        long _counter;
        double _now;
        double _lastReceived;
        double _lastPing;
        double _retryAt;
        double _backoff = 1;
        int _failures;
        long _pingSentLocalUs;

        sealed class Pending
        {
            public TaskCompletionSource<Result> Done;
            public double Deadline;
        }

        sealed class Bucket
        {
            public double Tokens;
            public double Last;
        }

        public WorldSession(WorldSessionOptions options, WorldMirror mirror = null)
        {
            Options = options ?? throw new ArgumentNullException(nameof(options));
            Mirror = mirror ?? new WorldMirror();
        }

        public WorldSessionOptions Options { get; }
        public WorldMirror Mirror { get; }
        public KernelClock Clock { get; } = new KernelClock();
        public LinkState State { get; private set; } = LinkState.Offline;
        public Welcome Welcome { get; private set; }
        public IReadOnlyList<Role> Granted => Welcome?.Granted ?? (IReadOnlyList<Role>)Array.Empty<Role>();
        /// <summary>L'acteur de la personne connectée (<c>player:…</c>), <c>null</c> pour un écran sans corps.</summary>
        public string Actor => Welcome?.Actor;
        /// <summary>Vrai tant que ce client tient le bail d'hôte : il joue les actions et constate.</summary>
        public bool IsHost { get; private set; }
        /// <summary>Le dernier aller-retour mesuré par <c>ping</c>/<c>pong</c>, en millisecondes.</summary>
        public double RoundTripMs { get; private set; }
        public bool Wants(Role role) => Options.Roles.Contains(role);
        public bool Has(Role role) => Granted.Contains(role);

        public event Action<LinkState> StateChanged;
        public event Action<Welcome> Welcomed;
        public event Action<bool> HostChanged;
        public event Action<Failure> ServerError;
        public event Action<PoseOut> PoseReceived;
        /// <summary>Chaque trame reçue, après son application au miroir (pour un journal, un outil de diagnostic).</summary>
        public event Action<ServerFrame, FrameEffect> FrameReceived;
        /// <summary>Ce qui mérite d'être écrit dans la console du moteur.</summary>
        public Action<string> Log = _ => { };

        // --- cycle de vie -------------------------------------------------------------------------------------
        public void Connect()
        {
            if (State == LinkState.Connecting || State == LinkState.Greeting || State == LinkState.Online)
                return;
            Open();
        }

        public void Disconnect()
        {
            _channel.Close();
            SetHost(false);
            SetState(LinkState.Offline);
            FailPending("déconnecté");
        }

        void Open()
        {
            SetState(LinkState.Connecting);
            var headers = new Dictionary<string, string>();
            if (!string.IsNullOrEmpty(Options.Token))
                headers["Authorization"] = "Bearer " + Options.Token;
            _lastReceived = _now;
            _ = _channel.OpenAsync(Options.WorldUri(), headers);
        }

        /// <summary>À appeler à chaque image, avec une horloge en secondes (temps réel, pas le temps du jeu).</summary>
        public void Tick(double nowSeconds)
        {
            _now = nowSeconds;
            while (_channel.TryDequeue(out var e))
            {
                switch (e.Kind)
                {
                    case WsEventKind.Opened:
                        OnOpened();
                        break;
                    case WsEventKind.Message:
                        _lastReceived = _now;
                        OnMessage(e.Text);
                        break;
                    case WsEventKind.Closed:
                        OnClosed(e.CloseCode, e.Text);
                        break;
                }
            }

            if (State == LinkState.Offline && _retryAt > 0 && _now >= _retryAt)
            {
                _retryAt = 0;
                Open();
            }

            if (State == LinkState.Greeting || State == LinkState.Online)
            {
                if (_now - _lastPing >= Options.PingIntervalS)
                {
                    _lastPing = _now;
                    _pingSentLocalUs = KernelClock.LocalNowUs();
                    Send(new Ping { T = _pingSentLocalUs }, track: false);
                }
                if (_now - _lastReceived > Options.SilenceTimeoutS)
                {
                    Log("monde : plus de nouvelles du noyau, reconnexion");
                    _channel.Close();
                    OnClosed(0, "silence");
                }
            }

            if (_pending.Count > 0)
            {
                foreach (var cmd in _pending.Where(kv => _now > kv.Value.Deadline).Select(kv => kv.Key).ToList())
                {
                    var p = _pending[cmd];
                    _pending.Remove(cmd);
                    p.Done.TrySetResult(new Result { Cmd = cmd, Status = Status.Refused, Message = "pas de réponse du noyau" });
                }
            }
        }

        void OnOpened()
        {
            SetState(LinkState.Greeting);
            _backoff = 1;
            _failures = 0;
            var hello = new Hello
            {
                Roles = Options.Roles.Distinct().ToList(),
                Client = new ClientInfo { Name = Options.ClientName, Version = Options.ClientVersion, Engine = Options.Engine },
                Rev = Mirror.Provisional ? null : Mirror.World?.Rev,
                After = Mirror.Ready && !Mirror.Provisional ? Mirror.Seq : (long?)null,
                Token = string.IsNullOrEmpty(Options.Token) ? null : Options.Token,
                Avatar = Options.Avatar,
            };
            _lastPing = _now;
            _ = _channel.SendAsync(WireJson.Write(hello));
        }

        void OnClosed(int code, string reason)
        {
            var wasHost = IsHost;
            SetHost(false);
            FailPending("connexion perdue");
            if (code == 4401 || code == 1008)
            {
                Log($"monde : connexion refusée ({code}{(reason != null ? ", " + reason : "")}) — vérifie le jeton");
                SetState(LinkState.Refused);
                return;
            }
            // Une connexion qui tombe se dit ; les essais qui suivent, une fois sur dix seulement.
            if (State == LinkState.Online || State == LinkState.Greeting || _failures % 10 == 0)
                Log($"monde : connexion fermée ({reason ?? code.ToString()}), nouvel essai dans {_backoff:0.#} s" + (wasHost ? " — bail d'hôte perdu" : ""));
            _failures = State == LinkState.Online ? 0 : _failures + 1;
            SetState(LinkState.Offline);
            _retryAt = _now + _backoff;
            _backoff = Math.Min(_backoff * 1.5, 30);
        }

        void OnMessage(string text)
        {
            var frame = WireJson.TryReadServer(text, out var error, out var seq);
            if (frame == null)
            {
                // Une trame plus récente que ce client : on la passe (règle « ignorer sans planter »).
                Log($"monde : trame ignorée ({error})");
                return;
            }
            var effect = FrameEffect.NotState;
            switch (frame)
            {
                case Welcome w:
                    Welcome = w;
                    Clock.Sync(w.Now, KernelClock.LocalNowUs());
                    SetState(LinkState.Online);
                    Welcomed?.Invoke(w);
                    break;
                case Result r:
                    if (r.Cmd != null && _pending.TryGetValue(r.Cmd, out var p))
                    {
                        _pending.Remove(r.Cmd);
                        p.Done.TrySetResult(r);
                    }
                    break;
                case HostLease lease:
                    SetHost(lease.Granted);
                    break;
                case Pong pong:
                    // Le pong renvoie notre instant : il mesure l'aller-retour (affiché), pas l'heure du noyau.
                    if (pong.T == _pingSentLocalUs && _pingSentLocalUs > 0)
                        RoundTripMs = (KernelClock.LocalNowUs() - _pingSentLocalUs) / 1000.0;
                    break;
                case Failure failure:
                    Log($"monde : erreur du noyau {failure.Code} — {failure.Message}");
                    ServerError?.Invoke(failure);
                    if (failure.Fatal)
                        _channel.Close();
                    break;
                case PoseOut pose:
                    PoseReceived?.Invoke(pose);
                    break;
                default:
                    effect = Mirror.Apply(frame);
                    break;
            }
            FrameReceived?.Invoke(frame, effect);
        }

        // --- commandes ----------------------------------------------------------------------------------------
        /// <summary>
        /// Envoie une commande et rend son accusé (<c>result</c>). L'identifiant <c>cmd</c> est fixé ici. Une
        /// commande hors débit est refusée sur place (<c>rate_limited</c>) plutôt que d'aller se faire refuser.
        /// </summary>
        public Task<Result> Command(ClientFrame frame)
        {
            var cmd = NextCmd(frame.Type);
            SetCmd(frame, cmd);
            if (!Allow(frame.Type))
                return Task.FromResult(new Result { Cmd = cmd, Status = Status.Refused, Code = Refusal.RateLimited, Message = "trop de commandes" });
            if (State != LinkState.Online)
                return Task.FromResult(new Result { Cmd = cmd, Status = Status.Refused, Message = "pas connecté au monde" });
            var done = new TaskCompletionSource<Result>();
            _pending[cmd] = new Pending { Done = done, Deadline = _now + Options.CommandTimeoutS };
            Send(frame, track: true);
            return done.Task;
        }

        /// <summary>La pose continue du corps (20 par seconde au plus) : relayée, jamais journalisée, sans accusé.</summary>
        public void SendPose(double x, double y, double z, double yaw, string anim = null)
        {
            if (State != LinkState.Online || !Allow("pose"))
                return;
            Send(new PoseIn { T = Clock.NowUs, Pos = new Vec3 { X = x, Y = y, Z = z }, Yaw = yaw, Anim = anim }, track: false);
        }

        /// <summary>Redemande ce qui a suivi le dernier <c>seq</c> appliqué.</summary>
        public void RequestSync()
        {
            if (State == LinkState.Online && Mirror.Ready && Allow("sync"))
                Send(new Sync { After = Mirror.Seq }, track: false);
        }

        void Send(ClientFrame frame, bool track)
        {
            _ = _channel.SendAsync(WireJson.Write(frame));
        }

        string NextCmd(string type) => $"{(type.Length > 0 ? type[0] : 'c')}-{_prefix}-{++_counter}";

        static void SetCmd(ClientFrame frame, string cmd)
        {
            switch (frame)
            {
                case Act f: f.Cmd = cmd; break;
                case Moved f: f.Cmd = cmd; break;
                case Address f: f.Cmd = cmd; break;
                case Reply f: f.Cmd = cmd; break;
                case Report f: f.Cmd = cmd; break;
                case Edit f: f.Cmd = cmd; break;
                case Describe f: f.Cmd = cmd; break;
            }
        }

        bool Allow(string type)
        {
            if (!Commands.Rates.TryGetValue(type, out var rate))
                return true;
            if (!_buckets.TryGetValue(type, out var b))
                _buckets[type] = b = new Bucket { Tokens = rate, Last = _now };
            b.Tokens = Math.Min(rate, b.Tokens + (_now - b.Last) * rate);
            b.Last = _now;
            if (b.Tokens < 1)
                return false;
            b.Tokens -= 1;
            return true;
        }

        void FailPending(string why)
        {
            foreach (var kv in _pending)
                kv.Value.Done.TrySetResult(new Result { Cmd = kv.Key, Status = Status.Refused, Message = why });
            _pending.Clear();
        }

        void SetState(LinkState s)
        {
            if (State == s) return;
            State = s;
            StateChanged?.Invoke(s);
        }

        void SetHost(bool host)
        {
            if (IsHost == host) return;
            IsHost = host;
            HostChanged?.Invoke(host);
        }

        public void Dispose()
        {
            FailPending("fermé");
            _channel.Dispose();
        }
    }
}
