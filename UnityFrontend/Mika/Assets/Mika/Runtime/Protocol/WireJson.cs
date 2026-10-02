using System;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Mika.World.Protocol
{
    /// <summary>
    /// Lire et écrire les trames du protocole. Les <c>null</c> sont omis à l'écriture (le noyau prend alors la
    /// valeur par défaut), sauf là où le générateur a marqué qu'un <c>null</c> veut dire quelque chose.
    /// Un champ inconnu est ignoré à la lecture : le noyau peut être plus récent que le moteur.
    /// </summary>
    public static class WireJson
    {
        public static readonly JsonSerializerSettings Settings = new JsonSerializerSettings
        {
            NullValueHandling = NullValueHandling.Ignore,
            MissingMemberHandling = MissingMemberHandling.Ignore,
            DateParseHandling = DateParseHandling.None,
            FloatParseHandling = FloatParseHandling.Double,
            Formatting = Formatting.None,
        };

        static readonly JsonSerializer Serializer = JsonSerializer.Create(Settings);

        public static string Write(object frame) => JsonConvert.SerializeObject(frame, Settings);

        public static T Read<T>(string json) => JsonConvert.DeserializeObject<T>(json, Settings);

        public static ServerFrame ReadServer(string json) => Read<ServerFrame>(json);

        public static ClientFrame ReadClient(string json) => Read<ClientFrame>(json);

        public static WorldDef ReadWorld(string json) => Read<WorldDef>(json);

        /// <summary>La valeur d'une énumération telle qu'elle passe sur le fil (<c>ShakeHead</c> → « shake_head »).</summary>
        public static string Name<T>(T value) where T : struct, Enum => JsonConvert.SerializeObject(value, Settings).Trim('"');

        /// <summary>
        /// Lit une trame du noyau sans lever : <c>null</c> et une raison si elle est illisible ou d'un type
        /// inconnu ; <paramref name="seq"/> dit alors quel numéro elle portait (le trou qu'elle laisse).
        /// </summary>
        public static ServerFrame TryReadServer(string json, out string error, out long? seq)
        {
            seq = null;
            try
            {
                var token = JObject.Parse(json);
                seq = token["seq"]?.Type == JTokenType.Integer ? token["seq"].Value<long>() : (long?)null;
                error = null;
                return token.ToObject<ServerFrame>(Serializer);
            }
            catch (Exception e)
            {
                error = e.Message;
                return null;
            }
        }
    }
}
