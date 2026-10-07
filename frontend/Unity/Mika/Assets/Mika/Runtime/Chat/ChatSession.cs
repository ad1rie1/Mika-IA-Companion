using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Threading.Tasks;
using Mika.Net;
using Mika.World.Model;

namespace Mika.Chat
{
    public sealed class ChatSessionOptions
    {
        public string BaseUrl = "http://127.0.0.1:8001";
        /// <summary>Jeton du compte (<c>mw_…</c>) : un client natif n'a ni cookie ni <c>Origin</c>.</summary>
        public string Token;
        public double PingIntervalS = 20;
        public double SilenceTimeoutS = 50;

        public Uri ChatUri()
        {
            var b = new UriBuilder(BaseUrl.TrimEnd('/'));
            b.Scheme = b.Scheme == "https" ? "wss" : "ws";
            b.Path = b.Path.TrimEnd('/') + "/ws";
            return b.Uri;
        }

        /// <summary>L'adresse HTTP d'une route sous ce serveur (<c>/files/&lt;id&gt;</c>).</summary>
        public Uri HttpUri(string route)
        {
            var b = new UriBuilder(BaseUrl.TrimEnd('/'));
            b.Path = b.Path.TrimEnd('/') + route;
            return b.Uri;
        }
    }

    /// <summary>Le sort d'un téléchargement : le fichier sur ce poste, ou pourquoi il n'y est pas (en mots).</summary>
    public sealed class SharedFileDownload
    {
        public string LocalPath;
        public string Error;

        public bool Ok => LocalPath != null;
    }

    /// <summary>
    /// La conversation avec elle (<c>/ws</c>) vue d'un client natif : envoyer un message, recevoir ses paroles,
    /// la dérive de son visage, son état intérieur, et rattraper ce qui a été manqué (curseur sur l'identifiant
    /// du dernier message montré) ; télécharger les fichiers qu'elle envoie. Comme <see cref="WorldSession"/> : sans
    /// Unity, vidée par <see cref="Tick"/>.
    /// </summary>
    public sealed class ChatSession : IDisposable
    {
        /// <summary>Au-delà, le plus ancien message en attente est abandonné (et dit refusé, jamais perdu en silence).</summary>
        const int OutboxMax = 50;

        readonly WsChannel _channel = new WsChannel();
        readonly string _prefix = Guid.NewGuid().ToString("N").Substring(0, 6);
        // Les messages pas encore accusés, dans l'ordre d'écriture : renvoyés à chaque ouverture (le serveur
        // dédoublonne par l'identifiant client), oubliés à leur accusé. Sans elle, un message tapé pendant une
        // coupure s'affichait envoyé sans avoir jamais quitté le poste.
        readonly List<KeyValuePair<string, string>> _outbox = new List<KeyValuePair<string, string>>();
        // Les refus décidés ici (connexion refusée, file pleine) : rendus par Tick comme un accusé du serveur,
        // jamais pendant Send — l'appelant n'a pas encore l'identifiant qu'il devra reconnaître.
        readonly Queue<AckFrame> _localAcks = new Queue<AckFrame>();
        // Les fichiers qu'elle envoie (10 Mio au plus) : sans redirection suivie, le jeton ne part que vers son serveur.
        readonly HttpClient _http = new HttpClient(new HttpClientHandler { AllowAutoRedirect = false })
        {
            Timeout = TimeSpan.FromSeconds(60),
        };
        // Un téléchargement par fichier à la fois (la vignette et « Ouvrir » partagent le même) ; lu et écrit depuis
        // le fil principal seulement.
        readonly Dictionary<string, Task<SharedFileDownload>> _downloads = new Dictionary<string, Task<SharedFileDownload>>();
        long _counter;
        double _now, _lastReceived, _lastPing, _retryAt, _backoff = 1;

        public ChatSession(ChatSessionOptions options) => Options = options;

        public ChatSessionOptions Options { get; }
        public LinkState State { get; private set; } = LinkState.Offline;
        /// <summary>Le plus grand identifiant de message montré : ce que l'on redemande après une coupure.</summary>
        public long Cursor { get; private set; }
        /// <summary>L'empreinte de la vie d'où vient le curseur (vide tant qu'aucun fil n'est arrivé).</summary>
        public string Life { get; private set; } = "";

        public event Action<LinkState> StateChanged;
        public event Action<SpeechFrame> Speech;
        public event Action<EmotionUpdateFrame> EmotionUpdate;
        public event Action<AckFrame> Ack;
        public event Action<HistoryFrame> History;
        public event Action<InnerStateFrame> InnerState;
        public event Action<ProjectReportFrame> ProjectReport;
        public Action<string> Log = _ => { };

        public void Connect()
        {
            if (State != LinkState.Offline && State != LinkState.Refused) return;
            Open();
        }

        public void Disconnect()
        {
            _channel.Close();
            Set(LinkState.Offline);
            _retryAt = 0;
        }

        void Open()
        {
            Set(LinkState.Connecting);
            var headers = new Dictionary<string, string>();
            if (!string.IsNullOrEmpty(Options.Token))
                headers["Authorization"] = "Bearer " + Options.Token;
            _lastReceived = _now;
            _ = _channel.OpenAsync(Options.ChatUri(), headers);
        }

        /// <summary>
        /// Envoie un message ; rend son identifiant client (pour relier l'accusé et la réponse). Hors ligne, il
        /// attend la prochaine ouverture ; chaque message reçoit un accusé (<see cref="Ack"/>), du serveur ou d'ici.
        /// </summary>
        public string Send(string text)
        {
            var id = $"u-{_prefix}-{++_counter}";
            if (State == LinkState.Refused)
            {
                _localAcks.Enqueue(new AckFrame { ClientMsgId = id, Status = "unauthorized" });
                return id;
            }
            if (_outbox.Count >= OutboxMax)
            {
                _localAcks.Enqueue(new AckFrame { ClientMsgId = _outbox[0].Key, Status = "overloaded" });
                _outbox.RemoveAt(0);
            }
            _outbox.Add(new KeyValuePair<string, string>(id, text));
            if (State == LinkState.Online)
                _ = _channel.SendAsync(ChatJson.Chat(text, id));
            return id;
        }

        public void Tick(double nowSeconds)
        {
            _now = nowSeconds;
            while (_localAcks.Count > 0)
                Ack?.Invoke(_localAcks.Dequeue());
            while (_channel.TryDequeue(out var e))
            {
                switch (e.Kind)
                {
                    case WsEventKind.Opened:
                        Set(LinkState.Online);
                        _backoff = 1;
                        _lastPing = _now;
                        _lastReceived = _now;
                        // Le serveur envoie de lui-même le début du fil à la connexion ; après une coupure, on
                        // redemande seulement ce qui a suivi le dernier message montré.
                        if (Cursor > 0) _ = _channel.SendAsync(ChatJson.Sync(Cursor));
                        foreach (var m in _outbox)
                            _ = _channel.SendAsync(ChatJson.Chat(m.Value, m.Key));
                        break;
                    case WsEventKind.Message:
                        _lastReceived = _now;
                        Dispatch(e.Text);
                        break;
                    case WsEventKind.Closed:
                        if (e.CloseCode == 4401 || e.CloseCode == 1008)
                        {
                            Log($"conversation : connexion refusée ({e.CloseCode}) — vérifie le jeton");
                            Set(LinkState.Refused);
                            // Plus rien ne partira sur cette session : ce qui attendait est refusé, et le dit.
                            foreach (var m in _outbox)
                                _localAcks.Enqueue(new AckFrame { ClientMsgId = m.Key, Status = "unauthorized" });
                            _outbox.Clear();
                        }
                        else
                        {
                            Set(LinkState.Offline);
                            _retryAt = _now + _backoff;
                            _backoff = Math.Min(_backoff * 1.5, 30);
                        }
                        break;
                }
            }
            if (State == LinkState.Offline && _retryAt > 0 && _now >= _retryAt)
            {
                _retryAt = 0;
                Open();
            }
            if (State == LinkState.Online)
            {
                if (_now - _lastPing >= Options.PingIntervalS)
                {
                    _lastPing = _now;
                    _ = _channel.SendAsync(ChatJson.Ping(KernelClock.LocalNowUs() / 1000));
                }
                if (_now - _lastReceived > Options.SilenceTimeoutS)
                {
                    Log("conversation : plus de nouvelles, reconnexion");
                    _channel.Close();
                    Set(LinkState.Offline);
                    _retryAt = _now;
                }
            }
        }

        void Dispatch(string text)
        {
            ChatFrame frame;
            try
            {
                frame = ChatJson.Read(text);
            }
            catch (Exception ex)
            {
                Log($"conversation : trame illisible ({ex.Message})");
                return;
            }
            switch (frame)
            {
                case SpeechFrame s:
                    if (s.MessageId is long id && id > Cursor) Cursor = id;
                    if (s.UserMessageId is long uid && uid > Cursor) Cursor = uid;
                    Speech?.Invoke(s);
                    break;
                case EmotionUpdateFrame u:
                    EmotionUpdate?.Invoke(u);
                    break;
                case AckFrame a:
                    _outbox.RemoveAll(m => m.Key == a.ClientMsgId);
                    Ack?.Invoke(a);
                    break;
                case HistoryFrame h:
                    // Un fil d'une autre vie (une sauvegarde restaurée, un autre dossier de données) : ses identifiants
                    // ne valent rien ici, le curseur repart du sien. Plus grand que sa tête, il ne redescendait jamais,
                    // et chaque reconnexion recevait de nouveau un `reset`.
                    if (h.FromAnotherLife(Life)) Cursor = h.LastId;
                    else if (h.LastId > Cursor) Cursor = h.LastId;
                    if (!string.IsNullOrEmpty(h.Life)) Life = h.Life;
                    History?.Invoke(h);
                    break;
                case InnerStateFrame i:
                    InnerState?.Invoke(i);
                    break;
                case ProjectReportFrame p:
                    ProjectReport?.Invoke(p);
                    break;
            }
        }

        /// <summary>
        /// Télécharge un fichier qu'elle a envoyé (<c>GET /files/&lt;id&gt;</c>, avec le jeton du compte) dans
        /// <paramref name="folder"/>, sous <c>&lt;id&gt;-&lt;nom&gt;</c> ; une copie déjà faite est reprise telle quelle. À
        /// appeler du fil principal. Un refus du serveur (404, 410, 429…) ou une coupure se dit en mots
        /// (<see cref="SharedFileDownload.Error"/>), jamais par une exception.
        /// </summary>
        public Task<SharedFileDownload> DownloadAsync(SharedFile file, string folder)
        {
            var route = file?.Route;
            if (route == null)
                return Task.FromResult(new SharedFileDownload { Error = "ce fichier ne vient pas de Mika" });
            if (!file.Available)
                return Task.FromResult(new SharedFileDownload { Error = "plus disponible" });
            var id = file.Id.ToLowerInvariant();
            if (_downloads.TryGetValue(id, out var running) && !running.IsCompleted)
                return running;
            var task = Fetch(route, Path.Combine(folder, id + "-" + file.LocalName));
            _downloads[id] = task;
            return task;
        }

        async Task<SharedFileDownload> Fetch(string route, string target)
        {
            if (File.Exists(target) && new FileInfo(target).Length > 0)
                return new SharedFileDownload { LocalPath = target };
            // Un nom à part pendant l'écriture : un fichier tronqué ne passe jamais pour complet.
            var part = target + ".part";
            try
            {
                using (var request = new HttpRequestMessage(HttpMethod.Get, Options.HttpUri(route)))
                {
                    if (!string.IsNullOrEmpty(Options.Token))
                        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", Options.Token);
                    using (var response = await _http.SendAsync(request).ConfigureAwait(false))
                    {
                        if (!response.IsSuccessStatusCode)
                            return new SharedFileDownload { Error = HttpError((int)response.StatusCode) };
                        var bytes = await response.Content.ReadAsByteArrayAsync().ConfigureAwait(false);
                        Directory.CreateDirectory(Path.GetDirectoryName(target));
                        File.WriteAllBytes(part, bytes);
                    }
                }
                if (File.Exists(target)) File.Delete(target);
                File.Move(part, target);
                return new SharedFileDownload { LocalPath = target };
            }
            catch (HttpRequestException)
            {
                return new SharedFileDownload { Error = "serveur injoignable" };
            }
            catch (UnauthorizedAccessException)
            {
                return new SharedFileDownload { Error = "impossible de l'écrire sur ce poste" };
            }
            catch (Exception e) when (e is IOException || e is OperationCanceledException || e is ObjectDisposedException)
            {
                // Une coupure, le délai dépassé, ou la session refermée (reconnexion) pendant le téléchargement.
                return new SharedFileDownload { Error = "téléchargement interrompu" };
            }
            finally
            {
                if (File.Exists(part)) File.Delete(part);
            }
        }

        /// <summary>404 : inconnu ou pas à toi (le serveur ne distingue pas) ; 410 : retiré par la rétention.</summary>
        static string HttpError(int code) => code switch
        {
            401 => "connexion refusée (jeton ?)",
            404 => "fichier introuvable",
            410 => "plus disponible",
            429 => "trop de téléchargements — réessaie dans une minute",
            _ when code >= 500 => $"erreur du serveur ({code})",
            _ => $"téléchargement refusé ({code})",
        };

        void Set(LinkState s)
        {
            if (State == s) return;
            State = s;
            StateChanged?.Invoke(s);
        }

        public void Dispose()
        {
            _channel.Dispose();
            _http.Dispose();
        }
    }
}
