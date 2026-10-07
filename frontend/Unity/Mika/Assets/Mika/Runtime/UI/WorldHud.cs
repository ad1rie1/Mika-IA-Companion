using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Mika.Chat;
using Mika.Net;
using Mika.Player;
using Mika.World.Model;
using Mika.World.Protocol;
using UnityEngine;
using UnityEngine.UIElements;

namespace Mika.UI
{
    /// <summary>
    /// L'interface par-dessus le monde (UI Toolkit, construite en code) : l'état des connexions, ce que l'on vise
    /// et ce qu'on peut en faire, le menu des actions, les refus du noyau, les demandes de Mika, la conversation
    /// (et les fichiers qu'elle y envoie) et ses sous-titres, et les réglages de connexion. Elle ne parle jamais au
    /// noyau elle-même : elle passe par l'interacteur (actions) et par les sessions (conversation, réponses aux
    /// demandes).
    /// </summary>
    [RequireComponent(typeof(UIDocument))]
    [AddComponentMenu("Mika/Interface/HUD du monde")]
    public sealed class WorldHud : MonoBehaviour
    {
        public PlayerController controller;
        public PlayerInteractor interactor;

        WorldSession _world;
        ChatSession _chat;
        VisualElement _root;
        Label _worldPill, _chatPill, _hostPill, _focusLabel, _focusHint, _subtitle, _requestText;
        VisualElement _focus, _menu, _toasts, _request, _chatLog, _chatBox, _subtitleBox, _settings;
        TextField _chatInput, _urlField, _tokenField;
        Toggle _hostToggle;
        Request _pendingRequest;
        float _subtitleUntil;
        bool _chatOpen;
        // Les messages déjà montrés (par identifiant du journal) : un rattrapage ne les remontre pas.
        readonly System.Collections.Generic.HashSet<long> _shown = new System.Collections.Generic.HashSet<long>();
        // L'empreinte de la vie d'où vient ce que montre le fil (vide tant qu'aucun n'est arrivé) : comme le fil, elle
        // survit à une nouvelle session.
        string _life = "";
        // Les bulles de la joueuse qui attendent leur accusé (par identifiant client) : un refus s'y lit.
        readonly Dictionary<string, Label> _unacked = new Dictionary<string, Label>();
        // Les lignes tapées ici (identifiant client → texte) pas encore rattachées à leur identifiant du journal, dans
        // l'ordre d'écriture : la trame de parole qui y répond (ou se tait) les rattache par son client_msg_id, une ligne
        // « user » du fil par leur texte. Sans quoi un rattrapage (une rafale, une reconnexion) les remontrait.
        readonly List<KeyValuePair<string, string>> _unbound = new List<KeyValuePair<string, string>>();
        bool _interactorBound;
        // Sous le fil, ce qui se passe de son côté (comme le web et Android) : « Mika réfléchit… » entre l'accusé et
        // sa réponse, plafonné ; ou sa note de sommeil, jusqu'à ce qu'elle reparle.
        Label _waiting;
        float _waitingUntil;
        bool _asleep;

        const string ThinkingText = "Mika réfléchit…";
        const string AsleepNote = "Mika dort — elle te répondra à son réveil.";
        /// <summary>La raison d'une trame sans texte quand elle dort (<c>protocol.ASLEEP</c>).</summary>
        const string AsleepReason = "asleep";
        // Le plafond du web (TYPING_TIMEOUT_MS) : l'attente entière, file d'attente et fournisseur lent compris.
        const float ThinkingMaxSeconds = 300f;

        // Ce qu'elle envoie se range sur ce poste et s'ouvre avec le système — d'un clic seulement sous une sorte que le
        // serveur sert comme sûre (app.SAFE_MIMES) : un script (.bat, .js, .py…) s'exécuterait. Le reste montre son dossier.
        static readonly HashSet<string> OpenableExtensions = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            ".txt", ".md", ".csv", ".json", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf",
        };
        /// <summary>Le grand côté d'une vignette (px) : le fil ne fait que 260 px de haut.</summary>
        const float ThumbnailMax = 120f;

        static string SharedFolder => System.IO.Path.Combine(Application.persistentDataPath, "partages");

        /// <summary>Les réglages de connexion ont changé (adresse, jeton, hôte) : l'application se reconnecte.</summary>
        public event Action<string, string, bool> SettingsApplied;

        public void Bind(WorldSession world, ChatSession chat)
        {
            _world = world;
            _chat = chat;
            world.StateChanged += _ => RefreshStatus();
            world.HostChanged += _ => RefreshStatus();
            world.Mirror.RequestOpened += OnRequest;
            world.Mirror.RequestClosed += c =>
            {
                if (_pendingRequest != null && c.Request == _pendingRequest.Id) HideRequest();
            };
            chat.StateChanged += _ => RefreshStatus();
            chat.Speech += OnSpeech;
            chat.History += OnHistory;
            chat.Ack += OnAck;
            // Une nouvelle session ne renverra pas ce que l'ancienne gardait : ces bulles ne partiront plus (aucune ligne
            // du fil ne leur reviendra).
            foreach (var line in _unacked.Values) MarkRefused(line, "connexion changée");
            _unbound.RemoveAll(m => _unacked.ContainsKey(m.Key));
            _unacked.Clear();
            // … ni la réponse que l'ancienne attendait.
            HideWaiting();
            if (interactor != null && !_interactorBound)
            {
                _interactorBound = true;
                interactor.FocusChanged += OnFocus;
                interactor.MenuRequested += OpenMenu;
                interactor.Notice += Toast;
            }
            RefreshStatus();
        }

        void OnEnable()
        {
            _root = GetComponent<UIDocument>().rootVisualElement;
            _root.Clear();
            var hud = Add(_root, "hud");
            hud.pickingMode = PickingMode.Ignore;

            var status = Add(hud, "status");
            _worldPill = Pill(status, "Monde : hors ligne");
            _hostPill = Pill(status, "");
            _chatPill = Pill(status, "Conversation : hors ligne");

            Add(hud, "crosshair");
            _focus = Add(hud, "focus");
            _focusLabel = new Label { name = "focus-label" };
            _focusLabel.AddToClassList("focus-label");
            _focusHint = new Label();
            _focusHint.AddToClassList("focus-hint");
            _focus.Add(_focusLabel);
            _focus.Add(_focusHint);
            _focus.AddToClassList("hidden");

            _menu = Add(hud, "menu");
            _menu.AddToClassList("hidden");

            _toasts = Add(hud, "toasts");

            _request = Add(hud, "request");
            _requestText = new Label();
            _requestText.AddToClassList("request-text");
            _request.Add(_requestText);
            var buttons = Add(_request, "request-buttons");
            buttons.Add(Button("Refuser", () => Answer(false)));
            var yes = Button("Accepter", () => Answer(true));
            yes.AddToClassList("primary");
            buttons.Add(yes);
            _request.AddToClassList("hidden");

            _subtitleBox = Add(hud, "subtitle");
            _subtitle = new Label();
            _subtitle.AddToClassList("subtitle-text");
            _subtitleBox.Add(_subtitle);
            _subtitleBox.AddToClassList("hidden");

            _chatBox = Add(hud, "chat");
            _chatLog = Add(_chatBox, "chat-log");
            // Hors du fil (il ne garde que huit lignes) : toujours en bas, jamais poussée dehors.
            _waiting = new Label();
            _waiting.AddToClassList("chat-line");
            _waiting.AddToClassList("waiting");
            _waiting.AddToClassList("hidden");
            _chatBox.Add(_waiting);
            _chatInput = new TextField { maxLength = 2000 };
            _chatInput.textEdition.placeholder = "Écris à Mika…  (Entrée : envoyer · Échap : fermer)";
            _chatInput.textEdition.hidePlaceholderOnFocus = false;
            _chatInput.AddToClassList("chat-input");
            _chatInput.AddToClassList("hidden");
            _chatInput.RegisterCallback<KeyDownEvent>(OnChatKey, TrickleDown.TrickleDown);
            _chatBox.Add(_chatInput);

            BuildSettings(hud);
        }

        void BuildSettings(VisualElement hud)
        {
            _settings = Add(hud, "settings");
            var title = new Label("Connexion au noyau");
            title.AddToClassList("settings-title");
            _settings.Add(title);
            _urlField = new TextField("Adresse") { value = PlayerPrefs.GetString("mika.baseUrl", "http://127.0.0.1:8001") };
            _tokenField = new TextField("Jeton") { value = PlayerPrefs.GetString("mika.token", ""), isPasswordField = true };
            _hostToggle = new Toggle("Jouer le monde (hôte)") { value = PlayerPrefs.GetInt("mika.host", 1) == 1 };
            _settings.Add(_urlField);
            _settings.Add(_tokenField);
            _settings.Add(_hostToggle);
            var apply = Button("Se connecter", () =>
            {
                PlayerPrefs.SetString("mika.baseUrl", _urlField.value.Trim());
                PlayerPrefs.SetString("mika.token", _tokenField.value.Trim());
                PlayerPrefs.SetInt("mika.host", _hostToggle.value ? 1 : 0);
                PlayerPrefs.Save();
                SettingsApplied?.Invoke(_urlField.value.Trim(), _tokenField.value.Trim(), _hostToggle.value);
            });
            apply.AddToClassList("primary");
            _settings.Add(apply);
            var note = new Label("Le jeton se crée côté noyau pour ton compte (jeton de client natif, « mw_… »). Tab : libérer la souris · E : agir · F / clic droit : toutes les actions · G : lâcher · T : parler · V : vue.");
            note.AddToClassList("settings-note");
            _settings.Add(note);
            _settings.AddToClassList("hidden");
        }

        void Update()
        {
            if (controller == null) return;
            var free = controller.CursorFree;
            _settings?.EnableInClassList("hidden", !free || _chatOpen);
            if (!free && !_chatOpen) CloseMenu();
            if (controller.Inputs.Chat.WasPressedThisFrame() && !_chatOpen)
                OpenChat();
            if (_subtitleUntil > 0 && Time.unscaledTime > _subtitleUntil)
            {
                _subtitleUntil = 0;
                _subtitleBox.AddToClassList("hidden");
            }
            if (_waitingUntil > 0 && Time.unscaledTime > _waitingUntil)
                HideWaiting();
        }

        // --- état ----------------------------------------------------------------------------------------------
        void RefreshStatus()
        {
            if (_worldPill == null || _world == null) return;
            SetPill(_worldPill, "Monde", _world.State);
            _hostPill.text = _world.IsHost ? "hôte : ce poste joue le monde" : _world.Has(Role.Host) || _world.Wants(Role.Host) ? "hôte : un autre poste" : "";
            _hostPill.EnableInClassList("hidden", string.IsNullOrEmpty(_hostPill.text));
            if (_chat != null) SetPill(_chatPill, "Conversation", _chat.State);
        }

        static void SetPill(Label pill, string what, LinkState state)
        {
            pill.text = state switch
            {
                LinkState.Online => $"{what} : en ligne",
                LinkState.Connecting => $"{what} : connexion…",
                LinkState.Greeting => $"{what} : présentation…",
                LinkState.Refused => $"{what} : refusé (jeton ?)",
                _ => $"{what} : hors ligne",
            };
            pill.EnableInClassList("ok", state == LinkState.Online);
            pill.EnableInClassList("warn", state == LinkState.Connecting || state == LinkState.Greeting);
            pill.EnableInClassList("bad", state == LinkState.Refused);
        }

        /// <summary>Un bandeau d'information (aperçu hors ligne…) dans la barre d'état.</summary>
        public void SetWorldNote(string note)
        {
            if (_worldPill == null) return;
            if (!string.IsNullOrEmpty(note)) _worldPill.text = note;
            else RefreshStatus();
        }

        // --- viser ---------------------------------------------------------------------------------------------
        void OnFocus(Focus focus, IReadOnlyList<ActionOption> options)
        {
            if (focus.IsEmpty)
            {
                _focus.AddToClassList("hidden");
                return;
            }
            _focus.RemoveFromClassList("hidden");
            _focusLabel.text = focus.Label;
            var primary = options.FirstOrDefault(o => o.Primary) ?? options.FirstOrDefault();
            _focusHint.text = primary != null ? $"E · {primary.Label}" + (options.Count > 1 ? "   ·   F · plus" : "") : "";
        }

        void OpenMenu(Focus focus, IReadOnlyList<ActionOption> options)
        {
            if (options.Count == 0) return;
            _menu.Clear();
            var title = new Label(focus.IsEmpty ? "Toi" : focus.Label);
            title.AddToClassList("menu-title");
            _menu.Add(title);
            foreach (var o in options)
            {
                var option = o;
                var b = Button(o.Label, () =>
                {
                    interactor.Execute(option);
                    CloseMenu();
                    controller.SetCursorFree(false);
                });
                b.AddToClassList("menu-item");
                _menu.Add(b);
            }
            _menu.RemoveFromClassList("hidden");
            controller.SetCursorFree(true);
        }

        void CloseMenu() => _menu?.AddToClassList("hidden");

        public void Toast(string message)
        {
            if (_toasts == null || string.IsNullOrEmpty(message)) return;
            var t = new Label(message);
            t.AddToClassList("toast");
            _toasts.Add(t);
            t.schedule.Execute(() => t.RemoveFromHierarchy()).StartingIn(4500);
        }

        // --- demandes de Mika ------------------------------------------------------------------------------------
        void OnRequest(Request r)
        {
            if (_world == null || r.ToActor != _world.Actor) return;
            _pendingRequest = r;
            var who = _world.Mirror.World?.Actor(r.FromActor)?.Label ?? r.FromActor;
            var what = r.Object != null ? (_world.Mirror.World?.Object(r.Object)?.Label ?? r.Object) : null;
            _requestText.text = r.Kind switch
            {
                RequestKind.Offer => $"{who} te tend {what}.",
                RequestKind.Ask => $"{who} te demande {what}.",
                RequestKind.Hug => $"{who} voudrait un câlin.",
                RequestKind.HighFive => $"{who} lève la main : tope là ?",
                RequestKind.HoldHand => $"{who} te tend la main.",
                RequestKind.Invite => $"{who} t'invite à la rejoindre ({_world.Mirror.World?.Place(r.Place)?.Label ?? r.Place}).",
                _ => $"{who} te demande quelque chose.",
            };
            _request.RemoveFromClassList("hidden");
            controller?.SetCursorFree(true);
        }

        async void Answer(bool accept)
        {
            var r = _pendingRequest;
            HideRequest();
            if (r == null || _world == null) return;
            var result = await _world.Command(new Reply { Request = r.Id, Accept = accept });
            if (result.Status == Status.Refused) Toast(result.Message);
        }

        void HideRequest()
        {
            _pendingRequest = null;
            _request?.AddToClassList("hidden");
            controller?.SetCursorFree(false);
        }

        // --- conversation ------------------------------------------------------------------------------------------
        /// <summary>Ouvre la saisie (touche T ou Entrée).</summary>
        public void OpenChat()
        {
            _chatOpen = true;
            _chatInput.RemoveFromClassList("hidden");
            controller.Inputs.EnableGameplay(false);
            controller.SetCursorFree(true);
            _chatInput.schedule.Execute(() => _chatInput.Focus());
        }

        public void CloseChat()
        {
            _chatOpen = false;
            _chatInput.value = "";
            _chatInput.AddToClassList("hidden");
            controller.Inputs.EnableGameplay(true);
            controller.SetCursorFree(false);
        }

        void OnChatKey(KeyDownEvent e)
        {
            if (e.keyCode == KeyCode.Escape)
            {
                CloseChat();
                e.StopPropagation();
            }
            else if (e.keyCode == KeyCode.Return || e.keyCode == KeyCode.KeypadEnter)
            {
                var text = _chatInput.value.Trim();
                if (text.Length > 0 && _chat != null)
                {
                    var id = _chat.Send(text);
                    var line = AddLine(text, mika: false);
                    if (line != null)
                    {
                        _unacked[id] = line;
                        _unbound.Add(new KeyValuePair<string, string>(id, text));
                    }
                    if (_chat.State != LinkState.Online && _chat.State != LinkState.Refused)
                        Toast("Conversation hors ligne : le message partira à la reconnexion.");
                }
                CloseChat();
                e.StopPropagation();
            }
        }

        void OnSpeech(SpeechFrame s)
        {
            // Toute trame de parole clôt « Mika réfléchit… », un silence aussi : se taire est une issue valide. La
            // note de sommeil, elle, survit à un murmure à elle-même — ce n'est pas encore sa réponse.
            if (!s.Inner || !_asleep) HideWaiting();
            // La question qu'elle règle (une réponse, un silence, son sommeil) reçoit son identifiant : un rattrapage ne
            // la remontrera pas.
            if (s.ClientMsgId != null && s.UserMessageId is long asked && _unbound.RemoveAll(m => m.Key == s.ClientMsgId) > 0)
                _shown.Add(asked);
            if (string.IsNullOrEmpty(s.Text))
            {
                // Elle dort : la réponse attend son réveil (backendv2/docs/protocole-chat.md).
                if (s.VoiceReason == AsleepReason) ShowWaiting(asleep: true);
                return;
            }
            var text = StripCues(s.Text);
            if (s.MessageId is long id && !_shown.Add(id)) return;
            // Le fil se lit tout de suite ; le sous-titre, lui, attend que sa bouche dise la réplique. Une pensée
            // n'emporte jamais de fichier.
            AddLine(s.Inner ? $"({text})" : text, mika: true, files: s.Inner ? null : s.Attachments);
        }

        /// <summary>
        /// Le sous-titre d'une réplique, à son début réel (appelé par la présentation de Mika) : une réplique qui
        /// attend qu'elle finisse la précédente laisse celle-ci affichée jusque-là.
        /// </summary>
        public void ShowSubtitle(SpeechFrame s)
        {
            if (_subtitle == null || string.IsNullOrEmpty(s.Text)) return;
            var text = StripCues(s.Text);
            _subtitle.text = s.Inner ? $"« {text} »" : text;
            _subtitleBox.RemoveFromClassList("hidden");
            _subtitleUntil = Time.unscaledTime + Mathf.Clamp(text.Length * 0.065f, 3f, 14f);
        }

        void OnHistory(HistoryFrame h)
        {
            // Un fil d'une autre vie : ce qui est montré s'en va avant de fusionner (backendv2/docs/protocole-chat.md §4).
            if (h.FromAnotherLife(_life)) ForgetLife();
            if (!string.IsNullOrEmpty(h.Life)) _life = h.Life;
            foreach (var m in h.Messages.Skip(Math.Max(0, h.Messages.Count - 8)))
                // Une ligne de la joueuse déjà montrée s'adopte au lieu de s'afficher une seconde fois.
                if (_shown.Add(m.Id) && !Adopt(m))
                {
                    // Ses fichiers réapparaissent avec elle (ceux d'un message de la personne n'ont qu'un nom).
                    AddLine(StripCues(m.Text), mika: m.Role == "assistant", files: m.Role == "assistant" ? m.Attachments : null);
                    // Sa parole au réveil, arrivée par un rattrapage, rend la note de sommeil caduque. « Réfléchit… »,
                    // lui, attend sa trame : un rattrapage peut précéder la réponse.
                    if (_asleep && m.Role == "assistant") HideWaiting();
                }
        }

        /// <summary>
        /// Une ligne « user » du fil que la joueuse a tapée ici et qui n'est pas encore rattachée : la plus ancienne au
        /// même texte reçoit son identifiant au lieu d'être montrée deux fois. Par le texte, comme le web et Android :
        /// les premiers messages d'une rafale ne se rattachent que par le rattrapage qui précède la réponse
        /// (<c>backendv2/docs/protocole-chat.md</c> §4).
        /// </summary>
        bool Adopt(HistoryItem m)
        {
            if (m.Role != "user") return false;
            var i = _unbound.FindIndex(u => u.Value == m.Text);
            if (i < 0) return false;
            _unbound.RemoveAt(i);
            return true;
        }

        /// <summary>
        /// Le fil d'une autre vie (une sauvegarde restaurée, un autre dossier de données, un fil oublié) : ses
        /// identifiants ne veulent rien dire ici — gardés, ils faisaient jeter ses nouvelles réponses. Tout ce qui est
        /// montré s'en va, sauf les lignes encore en partance (pas encore accusées) : elles partiront vers la vie qui parle.
        /// </summary>
        void ForgetLife()
        {
            _shown.Clear();
            _unbound.RemoveAll(m => !_unacked.ContainsKey(m.Key));
            if (_chatLog == null) return;
            for (var i = _chatLog.childCount - 1; i >= 0; i--)
                if (!(_chatLog[i] is Label line && _unacked.ContainsValue(line)))
                    Forget(_chatLog[i]);
        }

        /// <summary>
        /// Le sort d'un message de la joueuse (<c>backendv2/docs/protocole-chat.md</c>) : <c>accepted</c> le dit reçu
        /// (« Mika réfléchit… » jusqu'à sa réponse), <c>no_reply</c> dit qu'une question reçue restera sans réponse,
        /// tout autre statut est un refus.
        /// </summary>
        void OnAck(AckFrame a)
        {
            if (a.Status == "no_reply")
            {
                // La réponse ne viendra pas : ni « réfléchit… », ni la promesse d'une réponse au réveil.
                HideWaiting();
                Toast("Mika n'a pas pu répondre — réessaie.");
                return;
            }
            if (a.ClientMsgId == null || !_unacked.TryGetValue(a.ClientMsgId, out var line)) return;
            _unacked.Remove(a.ClientMsgId);
            if (a.Status == "accepted")
            {
                ShowWaiting(asleep: false);
                return;
            }
            // Refusée, elle n'a jamais quitté le poste : aucune ligne du fil ne lui reviendra.
            _unbound.RemoveAll(m => m.Key == a.ClientMsgId);
            var why = a.Status switch
            {
                "rate_limited" => "trop vite",
                "overloaded" => "trop de messages en attente",
                "too_long" => "trop long",
                "empty" => "message vide",
                "attachments_rejected" => "pièces jointes refusées",
                "unauthorized" => "connexion refusée",
                _ => "refusé",
            };
            MarkRefused(line, why);
            Toast($"Message non envoyé : {why}.");
        }

        static void MarkRefused(Label line, string why)
        {
            line.text += $"  — non envoyé ({why})";
            line.AddToClassList("refused");
        }

        /// <summary>Sous le fil : « Mika réfléchit… » (plafonné), ou sa note de sommeil (jusqu'à ce qu'elle reparle).</summary>
        void ShowWaiting(bool asleep)
        {
            if (_waiting == null) return;
            _asleep = asleep;
            _waiting.text = asleep ? AsleepNote : ThinkingText;
            _waitingUntil = asleep ? 0f : Time.unscaledTime + ThinkingMaxSeconds;
            _waiting.RemoveFromClassList("hidden");
        }

        void HideWaiting()
        {
            _asleep = false;
            _waitingUntil = 0f;
            _waiting?.AddToClassList("hidden");
        }

        Label AddLine(string text, bool mika, IReadOnlyList<SharedFile> files = null)
        {
            if (_chatLog == null || string.IsNullOrEmpty(text)) return null;
            var line = new Label(mika ? $"Mika : {text}" : text);
            line.AddToClassList("chat-line");
            line.AddToClassList(mika ? "mika" : "me");
            var sent = files?.Where(f => f?.Route != null).ToList();
            if (sent == null || sent.Count == 0)
                _chatLog.Add(line);
            else
            {
                // Ses fichiers vont sous sa réplique, dans la même entrée du fil : ils en sortent avec elle.
                var entry = Add(_chatLog, "chat-entry");
                entry.Add(line);
                foreach (var f in sent) AddFile(entry, f);
            }
            while (_chatLog.childCount > 8) Forget(_chatLog[0]);
            return line;
        }

        /// <summary>Une entrée sort du fil (il ne garde que huit lignes) : ses vignettes rendent leur texture.</summary>
        void Forget(VisualElement entry)
        {
            entry.Query<Image>().ForEach(i =>
            {
                if (i.image != null) Destroy(i.image);
            });
            entry.RemoveFromHierarchy();
        }

        /// <summary>
        /// Un fichier qu'elle a envoyé, sous sa réplique : « fichier : courses.md (312 o) » et un bouton — Ouvrir, ou
        /// Voir le dossier pour ce qui ne s'ouvre pas d'un clic ; une image en vignette (un clic l'ouvre). Retiré par la
        /// rétention : son nom, et « plus disponible ».
        /// </summary>
        void AddFile(VisualElement entry, SharedFile f)
        {
            var row = Add(entry, "chat-line");
            row.AddToClassList("mika");
            row.style.flexDirection = FlexDirection.Row;
            row.style.flexWrap = Wrap.Wrap;
            row.style.alignItems = Align.Center;
            var what = f.IsImage ? "image" : "fichier";
            if (!f.Available)
            {
                row.AddToClassList("refused");
                row.Add(new Label($"{what} : {FileName(f)} (plus disponible)"));
                return;
            }
            row.Add(new Label($"{what} : {FileName(f)}{SizeText(f.Size)}"));
            Button open = null;
            open = Button(Openable(f.LocalName) ? "Ouvrir" : "Voir le dossier", () => Open(f, open));
            row.Add(open);
            // Après l'avoir accrochée au fil : une copie déjà sur le poste se montre tout de suite.
            if (f.IsImage) ShowThumbnail(f, row, open);
        }

        /// <summary>
        /// Télécharge (une fois) puis ouvre avec le système ; ce qui ne s'ouvre pas d'un clic montre son dossier. Un
        /// refus se dit : introuvable, plus disponible, trop de téléchargements…
        /// </summary>
        async void Open(SharedFile f, Button button)
        {
            if (_chat == null) return;
            button.SetEnabled(false);
            var result = await _chat.DownloadAsync(f, SharedFolder);
            button.SetEnabled(true);
            if (!result.Ok)
            {
                Toast($"{FileName(f)} : {result.Error}.");
                return;
            }
            if (Openable(result.LocalPath))
            {
                Application.OpenURL(new Uri(result.LocalPath).AbsoluteUri);
                return;
            }
            Application.OpenURL(new Uri(System.IO.Path.GetDirectoryName(result.LocalPath)).AbsoluteUri);
            Toast($"{FileName(f)} ne s'ouvre pas d'un clic : le voici dans son dossier.");
        }

        /// <summary>
        /// Une image en vignette bornée sous sa ligne (un clic l'ouvre). Unity ne lit que le PNG et le JPEG : un WebP,
        /// un GIF ou un téléchargement refusé gardent seulement la ligne et son bouton.
        /// </summary>
        async void ShowThumbnail(SharedFile f, VisualElement row, Button open)
        {
            if (_chat == null) return;
            var result = await _chat.DownloadAsync(f, SharedFolder);
            // L'entrée a pu sortir du fil pendant le téléchargement : pas de texture pour un élément détaché.
            if (!result.Ok || row.panel == null) return;
            byte[] bytes;
            try
            {
                bytes = System.IO.File.ReadAllBytes(result.LocalPath);
            }
            catch (Exception e) when (e is System.IO.IOException || e is UnauthorizedAccessException)
            {
                return;
            }
            var texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            if (!texture.LoadImage(bytes, true))
            {
                Destroy(texture);
                return;
            }
            var scale = Mathf.Min(1f, ThumbnailMax / Mathf.Max(texture.width, texture.height));
            var image = new Image { image = texture, scaleMode = ScaleMode.ScaleToFit };
            image.style.width = texture.width * scale;
            image.style.height = texture.height * scale;
            image.style.marginTop = 4f;
            image.RegisterCallback<ClickEvent>(_ => Open(f, open));
            row.Add(image);
        }

        static string FileName(SharedFile f) => string.IsNullOrWhiteSpace(f.Name) ? "fichier" : f.Name;

        static bool Openable(string path) => OpenableExtensions.Contains(System.IO.Path.GetExtension(path) ?? "");

        /// <summary>« (312 o) », « (2 Ko) », « (1,4 Mo) » ; rien sans taille.</summary>
        static string SizeText(long? size)
        {
            if (size == null || size < 0) return "";
            var b = size.Value;
            if (b < 1024) return $" ({b.ToString(CultureInfo.InvariantCulture)} o)";
            if (b < 1024 * 1024) return $" ({Math.Round(b / 1024.0).ToString(CultureInfo.InvariantCulture)} Ko)";
            return $" ({(b / (1024.0 * 1024.0)).ToString("0.#", CultureInfo.InvariantCulture).Replace('.', ',')} Mo)";
        }

        /// <summary>Les repères prosodiques ([SIGH], [PAUSE:300]…) sont pour la voix, pas pour la lecture.</summary>
        public static string StripCues(string text) =>
            System.Text.RegularExpressions.Regex.Replace(text ?? "", @"\[(SIGH|LAUGH|BREATH|PAUSE(:\d+)?)\]\s*", "").Trim();

        // --- utilitaires ---------------------------------------------------------------------------------------------
        static VisualElement Add(VisualElement parent, string cls)
        {
            var v = new VisualElement();
            v.AddToClassList(cls);
            v.pickingMode = PickingMode.Ignore;
            parent.Add(v);
            return v;
        }

        static Label Pill(VisualElement parent, string text)
        {
            var l = new Label(text);
            l.AddToClassList("pill");
            parent.Add(l);
            return l;
        }

        static Button Button(string text, Action click)
        {
            var b = new Button(click) { text = text };
            b.AddToClassList("btn");
            return b;
        }
    }
}
