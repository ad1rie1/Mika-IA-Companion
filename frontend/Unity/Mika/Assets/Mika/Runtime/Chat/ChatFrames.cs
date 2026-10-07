using System.Collections.Generic;
using System.Text.RegularExpressions;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Mika.Chat
{
    /// <summary>
    /// Les trames de la conversation (<c>/ws</c>), celles que lit le client web
    /// (<c>frontend/Web/src/types/messages.ts</c>, écrites par <c>backendv2/src/mika/adapters/web/protocol.py</c>).
    /// Écrites à la main : le protocole de conversation n'a pas de schéma publié, et seul ce que le moteur
    /// montre est lu ici — le reste reste dans <see cref="Raw"/>.
    /// </summary>
    public abstract class ChatFrame
    {
        [JsonIgnore] public JObject Raw;
    }

    public sealed class BlendPart
    {
        [JsonProperty("emotion")] public string Emotion;
        [JsonProperty("weight")] public float Weight;
    }

    public sealed class VoiceProfile
    {
        [JsonProperty("pitch")] public float Pitch = 1f;
        [JsonProperty("rate")] public float Rate = 1f;
        [JsonProperty("gain")] public float Gain = 1f;
    }

    /// <summary>
    /// Un fichier qu'elle envoie avec une parole (<c>protocol.shared_item</c>, <c>backendv2/docs/protocole-chat.md</c> §6) :
    /// un texte qu'elle a écrit, un fichier d'un projet, un dessin. Il se télécharge avec le jeton du compte
    /// (<see cref="ChatSession.DownloadAsync"/>). Une ligne de la personne n'en porte que le nom et la sorte.
    /// </summary>
    public sealed class SharedFile
    {
        static readonly Regex FileId = new Regex(@"\A[0-9a-f]{32}\z");
        // Ce qui sortirait du dossier, ou que Windows refuse dans un nom ; « # » et « % » casseraient l'adresse
        // file:// qui l'ouvre.
        const string ForbiddenInName = "<>:\"/\\|?*#%";

        [JsonProperty("id")] public string Id;
        [JsonProperty("name")] public string Name;
        /// <summary><c>image</c> (montrée en vignette) ou <c>file</c>.</summary>
        [JsonProperty("kind")] public string Kind = "file";
        [JsonProperty("mime")] public string Mime;
        /// <summary>En octets.</summary>
        [JsonProperty("size")] public long? Size;
        [JsonProperty("url")] public string Url;
        /// <summary>Faux une fois retiré par la rétention : on le dit, au lieu d'un téléchargement voué au 410.</summary>
        [JsonProperty("available")] public bool Available = true;

        public bool IsImage => Kind == "image";

        /// <summary>
        /// Sa route, relative au serveur (<c>/files/&lt;id&gt;</c>), ou <c>null</c> si l'entrée n'en désigne pas une
        /// qu'on accepte de suivre. Jamais une adresse absolue : le jeton ne part que vers son serveur, et une ligne
        /// du fil ne choisit pas où.
        /// </summary>
        public string Route
        {
            get
            {
                var id = Id?.ToLowerInvariant();
                if (id == null || !FileId.IsMatch(id)) return null;
                var expected = "/files/" + id;
                return string.IsNullOrEmpty(Url) || Url.Trim().ToLowerInvariant() == expected ? expected : null;
            }
        }

        /// <summary>
        /// Le nom sous lequel le ranger sur ce poste : le sien, sans rien qui sorte du dossier (le serveur n'en retire
        /// que les caractères de contrôle) ; à défaut, « fichier ».
        /// </summary>
        public string LocalName
        {
            get
            {
                var chars = (Name ?? "").ToCharArray();
                for (var i = 0; i < chars.Length; i++)
                    if (char.IsControl(chars[i]) || ForbiddenInName.IndexOf(chars[i]) >= 0) chars[i] = '_';
                // Windows retire lui-même points et espaces finaux : l'extension lue ici doit être celle du disque.
                var cleaned = new string(chars).Trim().TrimEnd('.', ' ');
                return cleaned.Length > 0 ? cleaned : "fichier";
            }
        }
    }

    /// <summary>Une parole (ou une pensée à voix haute) : le texte, l'émotion du moment, faut-il la dire.</summary>
    public sealed class SpeechFrame : ChatFrame
    {
        [JsonProperty("text")] public string Text;
        [JsonProperty("emotion")] public string Emotion = "neutral";
        [JsonProperty("emotion_intensity")] public float EmotionIntensity;
        [JsonProperty("emotion_blend")] public List<BlendPart> EmotionBlend = new List<BlendPart>();
        [JsonProperty("source")] public string Source;
        [JsonProperty("person_id")] public string PersonId;
        [JsonProperty("speak")] public bool Speak = true;
        [JsonProperty("voice_reason")] public string VoiceReason;
        /// <summary><c>speaking</c> (à quelqu'un) ou <c>inner</c> (elle pense tout haut).</summary>
        [JsonProperty("voice_persona")] public string VoicePersona = "speaking";
        [JsonProperty("voice_profile")] public VoiceProfile VoiceProfile = new VoiceProfile();
        [JsonProperty("message_id")] public long? MessageId;
        [JsonProperty("user_message_id")] public long? UserMessageId;
        [JsonProperty("client_msg_id")] public string ClientMsgId;
        /// <summary>Les fichiers qu'elle envoie avec (souvent aucun ; jamais avec une pensée).</summary>
        [JsonProperty("attachments")] public List<SharedFile> Attachments = new List<SharedFile>();

        public bool Inner => VoicePersona == "inner";
    }

    /// <summary>Le visage entre deux répliques (la dérive d'humeur).</summary>
    public sealed class EmotionUpdateFrame : ChatFrame
    {
        [JsonProperty("person_id")] public string PersonId;
        [JsonProperty("emotion")] public string Emotion = "neutral";
        [JsonProperty("emotion_intensity")] public float EmotionIntensity;
        [JsonProperty("emotion_blend")] public List<BlendPart> EmotionBlend = new List<BlendPart>();
    }

    /// <summary>L'accusé d'un message envoyé : accepté, ou refusé et pourquoi.</summary>
    public sealed class AckFrame : ChatFrame
    {
        [JsonProperty("client_msg_id")] public string ClientMsgId;
        [JsonProperty("status")] public string Status;
        /// <summary>
        /// Pour <c>no_reply</c>, pourquoi la réponse ne viendra pas : <c>no_model</c>, <c>unreachable</c>,
        /// <c>timeout</c>, <c>too_late</c> ou <c>error</c> (<c>backendv2/docs/protocole-chat.md</c> §4).
        /// </summary>
        [JsonProperty("reason")] public string Reason;
    }

    public sealed class HistoryItem
    {
        [JsonProperty("id")] public long Id;
        [JsonProperty("role")] public string Role;
        [JsonProperty("text")] public string Text;
        [JsonProperty("ts")] public long Ts;
        [JsonProperty("source")] public string Source;
        [JsonProperty("emotion")] public string Emotion;
        [JsonProperty("emotion_intensity")] public float EmotionIntensity;
        /// <summary>D'un message de Mika : ses fichiers, comme dans <see cref="SpeechFrame"/> ; de la personne : un nom et une sorte.</summary>
        [JsonProperty("attachments")] public List<SharedFile> Attachments = new List<SharedFile>();
    }

    public sealed class HistoryFrame : ChatFrame
    {
        [JsonProperty("mode")] public string Mode;
        [JsonProperty("messages")] public List<HistoryItem> Messages = new List<HistoryItem>();
        [JsonProperty("last_id")] public long LastId;
        [JsonProperty("truncated")] public bool Truncated;
    }

    /// <summary>L'état intérieur (sommeil, énergie, lieu…) : seules les clés que le moteur montre sont lues.</summary>
    public sealed class InnerStateFrame : ChatFrame
    {
        public string SleepPhase => Raw?["inner_state"]?["sleep_phase"]?.Value<string>() ?? Raw?["sleep_phase"]?.Value<string>();
        public float? Energy => Raw?["inner_state"]?["energy"]?.Value<float?>();
        public string Place => Raw?["inner_state"]?["place"]?.Value<string>();
    }

    public sealed class ProjectReportFrame : ChatFrame
    {
        [JsonProperty("project_title")] public string ProjectTitle;
        [JsonProperty("text")] public string Text;
    }

    public sealed class UnknownChatFrame : ChatFrame
    {
        public string Type => Raw?["type"]?.Value<string>();
    }

    public static class ChatJson
    {
        public static ChatFrame Read(string json)
        {
            var obj = JObject.Parse(json);
            ChatFrame frame = (obj["type"]?.Value<string>()) switch
            {
                "speech" => obj.ToObject<SpeechFrame>(),
                "emotion_update" => obj.ToObject<EmotionUpdateFrame>(),
                "ack" => obj.ToObject<AckFrame>(),
                "history" => obj.ToObject<HistoryFrame>(),
                "inner_state_update" => new InnerStateFrame(),
                "project_report" => obj.ToObject<ProjectReportFrame>(),
                _ => new UnknownChatFrame(),
            };
            frame.Raw = obj;
            return frame;
        }

        public static string Chat(string text, string clientMsgId) =>
            new JObject { ["type"] = "chat", ["message"] = text, ["client_msg_id"] = clientMsgId }.ToString(Formatting.None);

        public static string Sync(long afterId) =>
            new JObject { ["type"] = "sync", ["after_id"] = afterId }.ToString(Formatting.None);

        public static string Ping(long t) =>
            new JObject { ["type"] = "ping", ["t"] = t }.ToString(Formatting.None);
    }
}
