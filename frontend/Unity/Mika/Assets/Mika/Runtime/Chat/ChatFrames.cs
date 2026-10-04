using System.Collections.Generic;
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
