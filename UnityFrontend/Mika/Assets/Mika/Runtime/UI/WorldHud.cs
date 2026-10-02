using System;
using System.Collections.Generic;
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
    /// et ses sous-titres, et les réglages de connexion. Elle ne parle jamais au noyau elle-même : elle passe par
    /// l'interacteur (actions) et par les sessions (conversation, réponses aux demandes).
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
        VisualElement _focus, _menu, _toasts, _request, _chatLog, _subtitleBox, _settings;
        TextField _chatInput, _urlField, _tokenField;
        Toggle _hostToggle;
        Request _pendingRequest;
        float _subtitleUntil;
        bool _chatOpen;
        bool _interactorBound;

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

            var chat = Add(hud, "chat");
            _chatLog = Add(chat, "chat-log");
            _chatInput = new TextField { maxLength = 2000 };
            _chatInput.AddToClassList("chat-input");
            _chatInput.AddToClassList("hidden");
            _chatInput.RegisterCallback<KeyDownEvent>(OnChatKey, TrickleDown.TrickleDown);
            chat.Add(_chatInput);

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
        void OpenChat()
        {
            _chatOpen = true;
            _chatInput.RemoveFromClassList("hidden");
            controller.Inputs.EnableGameplay(false);
            controller.SetCursorFree(true);
            _chatInput.schedule.Execute(() => _chatInput.Focus());
        }

        void CloseChat()
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
                    _chat.Send(text);
                    AddLine(text, mika: false);
                }
                CloseChat();
                e.StopPropagation();
            }
        }

        void OnSpeech(SpeechFrame s)
        {
            if (string.IsNullOrEmpty(s.Text)) return;
            var text = StripCues(s.Text);
            AddLine(s.Inner ? $"({text})" : text, mika: true);
            _subtitle.text = s.Inner ? $"« {text} »" : text;
            _subtitleBox.RemoveFromClassList("hidden");
            _subtitleUntil = Time.unscaledTime + Mathf.Clamp(text.Length * 0.065f, 3f, 14f);
        }

        void OnHistory(HistoryFrame h)
        {
            foreach (var m in h.Messages.Skip(Math.Max(0, h.Messages.Count - 8)))
                AddLine(StripCues(m.Text), mika: m.Role == "assistant");
        }

        void AddLine(string text, bool mika)
        {
            if (_chatLog == null || string.IsNullOrEmpty(text)) return;
            var line = new Label(mika ? $"Mika : {text}" : text);
            line.AddToClassList("chat-line");
            line.AddToClassList(mika ? "mika" : "me");
            _chatLog.Add(line);
            while (_chatLog.childCount > 8) _chatLog.RemoveAt(0);
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
