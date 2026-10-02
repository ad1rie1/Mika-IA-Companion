using System;
using System.Collections.Generic;
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
    }

    /// <summary>
    /// La conversation avec elle (<c>/ws</c>) vue d'un client natif : envoyer un message, recevoir ses paroles,
    /// la dérive de son visage, son état intérieur, et rattraper ce qui a été manqué (curseur sur l'identifiant
    /// du dernier message montré). Comme <see cref="WorldSession"/> : sans Unity, vidée par <see cref="Tick"/>.
    /// </summary>
    public sealed class ChatSession : IDisposable
    {
        readonly WsChannel _channel = new WsChannel();
        readonly string _prefix = Guid.NewGuid().ToString("N").Substring(0, 6);
        long _counter;
        double _now, _lastReceived, _lastPing, _retryAt, _backoff = 1;

        public ChatSession(ChatSessionOptions options) => Options = options;

        public ChatSessionOptions Options { get; }
        public LinkState State { get; private set; } = LinkState.Offline;
        /// <summary>Le plus grand identifiant de message montré : ce que l'on redemande après une coupure.</summary>
        public long Cursor { get; private set; }

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

        /// <summary>Envoie un message ; rend son identifiant client (pour relier l'accusé et la réponse).</summary>
        public string Send(string text)
        {
            var id = $"u-{_prefix}-{++_counter}";
            if (State == LinkState.Online)
                _ = _channel.SendAsync(ChatJson.Chat(text, id));
            return id;
        }

        public void Tick(double nowSeconds)
        {
            _now = nowSeconds;
            while (_channel.TryDequeue(out var e))
            {
                switch (e.Kind)
                {
                    case WsEventKind.Opened:
                        Set(LinkState.Online);
                        _backoff = 1;
                        _lastPing = _now;
                        _lastReceived = _now;
                        // Rattraper ce qui a été dit pendant la coupure (ou le début du fil, au premier passage).
                        _ = _channel.SendAsync(ChatJson.Sync(Cursor));
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
                    Ack?.Invoke(a);
                    break;
                case HistoryFrame h:
                    if (h.LastId > Cursor) Cursor = h.LastId;
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

        void Set(LinkState s)
        {
            if (State == s) return;
            State = s;
            StateChanged?.Invoke(s);
        }

        public void Dispose() => _channel.Dispose();
    }
}
