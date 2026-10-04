using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Mika.Net
{
    public enum WsEventKind
    {
        Opened,
        Message,
        Closed,
    }

    public readonly struct WsEvent
    {
        public readonly WsEventKind Kind;
        public readonly string Text;
        /// <summary>Code de fermeture WebSocket (4401 : non authentifié), 0 si inconnu.</summary>
        public readonly int CloseCode;

        public WsEvent(WsEventKind kind, string text = null, int closeCode = 0)
        {
            Kind = kind;
            Text = text;
            CloseCode = closeCode;
        }
    }

    /// <summary>
    /// Une connexion WebSocket texte, sans Unity : la réception tourne sur un fil à part et dépose ses
    /// événements dans une file que le fil principal vide à son rythme (<see cref="TryDequeue"/>). Les envois
    /// sont sérialisés (un <see cref="ClientWebSocket"/> refuse deux envois simultanés).
    /// </summary>
    public sealed class WsChannel : IDisposable
    {
        readonly ConcurrentQueue<WsEvent> _events = new ConcurrentQueue<WsEvent>();
        readonly SemaphoreSlim _sendLock = new SemaphoreSlim(1, 1);
        ClientWebSocket _socket;
        CancellationTokenSource _cts;
        int _generation;

        public bool IsOpen => _socket != null && _socket.State == WebSocketState.Open;

        public bool TryDequeue(out WsEvent e) => _events.TryDequeue(out e);

        /// <summary>
        /// Ouvre la connexion (ferme la précédente). Les en-têtes servent à l'authentification d'un client natif
        /// (<c>Authorization: Bearer …</c>) ; un échec d'ouverture arrive comme un <see cref="WsEventKind.Closed"/>.
        /// </summary>
        public async Task OpenAsync(Uri uri, IReadOnlyDictionary<string, string> headers = null)
        {
            Close();
            var generation = Interlocked.Increment(ref _generation);
            var socket = new ClientWebSocket();
            socket.Options.KeepAliveInterval = TimeSpan.FromSeconds(15);
            if (headers != null)
                foreach (var kv in headers)
                    socket.Options.SetRequestHeader(kv.Key, kv.Value);
            var cts = new CancellationTokenSource();
            _socket = socket;
            _cts = cts;
            try
            {
                await socket.ConnectAsync(uri, cts.Token).ConfigureAwait(false);
            }
            catch (Exception)
            {
                if (generation == _generation)
                    _events.Enqueue(new WsEvent(WsEventKind.Closed, "connexion impossible"));
                return;
            }
            if (generation != _generation)
                return;
            _events.Enqueue(new WsEvent(WsEventKind.Opened));
            _ = Task.Run(() => ReceiveLoop(socket, cts.Token, generation));
        }

        async Task ReceiveLoop(ClientWebSocket socket, CancellationToken token, int generation)
        {
            var buffer = new byte[16 * 1024];
            var message = new MemoryStream();
            var code = 0;
            string reason = null;
            try
            {
                while (!token.IsCancellationRequested && socket.State == WebSocketState.Open)
                {
                    var result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), token).ConfigureAwait(false);
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        code = (int)(result.CloseStatus ?? 0);
                        reason = result.CloseStatusDescription;
                        break;
                    }
                    message.Write(buffer, 0, result.Count);
                    if (!result.EndOfMessage)
                        continue;
                    if (result.MessageType == WebSocketMessageType.Text)
                        _events.Enqueue(new WsEvent(WsEventKind.Message, Encoding.UTF8.GetString(message.GetBuffer(), 0, (int)message.Length)));
                    message.SetLength(0);
                }
            }
            catch (Exception e) when (!(e is OutOfMemoryException))
            {
                reason = e.Message;
            }
            if (generation == _generation)
                _events.Enqueue(new WsEvent(WsEventKind.Closed, reason, code));
        }

        public async Task<bool> SendAsync(string text)
        {
            var socket = _socket;
            if (socket == null || socket.State != WebSocketState.Open)
                return false;
            var bytes = Encoding.UTF8.GetBytes(text);
            await _sendLock.WaitAsync().ConfigureAwait(false);
            try
            {
                await socket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, _cts.Token).ConfigureAwait(false);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
            finally
            {
                _sendLock.Release();
            }
        }

        /// <summary>Ferme sans attendre ; plus aucun événement de cette connexion n'arrive ensuite.</summary>
        public void Close()
        {
            Interlocked.Increment(ref _generation);
            var socket = _socket;
            var cts = _cts;
            _socket = null;
            _cts = null;
            if (socket == null)
                return;
            try
            {
                if (socket.State == WebSocketState.Open)
                    _ = socket.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "bye", CancellationToken.None);
            }
            catch (Exception)
            {
                // déjà fermée
            }
            cts?.Cancel();
            _ = Task.Delay(2000).ContinueWith(_ =>
            {
                socket.Dispose();
                cts?.Dispose();
            });
        }

        public void Dispose() => Close();
    }
}
