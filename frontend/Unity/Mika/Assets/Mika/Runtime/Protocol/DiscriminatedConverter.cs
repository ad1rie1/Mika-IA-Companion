using System;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Mika.World.Protocol
{
    /// <summary>
    /// Lit une union discriminée (« type », « kind » ou « op ») : choisit la classe concrète d'après le
    /// discriminant, puis la remplit. L'écriture reste celle de Newtonsoft (chaque classe porte son
    /// discriminant en propriété calculée).
    /// </summary>
    /// <remarks>
    /// Une valeur inconnue du discriminant donne <see cref="UnknownTagException"/> : un client du monde ignore
    /// ce qu'il ne sait pas montrer, et c'est à l'appelant (la session) de décider s'il s'en passe ou s'il
    /// redemande l'état — jamais à la lecture de deviner.
    /// </remarks>
    public abstract class DiscriminatedConverter<TBase> : JsonConverter where TBase : class
    {
        readonly string _property;
        readonly Func<string, Type> _resolve;

        protected DiscriminatedConverter(string property, Func<string, Type> resolve)
        {
            _property = property;
            _resolve = resolve;
        }

        public override bool CanConvert(Type objectType) => typeof(TBase).IsAssignableFrom(objectType);

        public override bool CanWrite => false;

        public override void WriteJson(JsonWriter writer, object value, JsonSerializer serializer) =>
            throw new NotSupportedException("écriture déléguée au sérialiseur par défaut");

        public override object ReadJson(JsonReader reader, Type objectType, object existingValue, JsonSerializer serializer)
        {
            if (reader.TokenType == JsonToken.Null)
                return null;
            var obj = JObject.Load(reader);
            Type target;
            if (!objectType.IsAbstract)
            {
                // Une propriété typée par un membre précis (Finished.at : ActorMoved) : pas de choix à faire.
                target = objectType;
            }
            else
            {
                var tag = obj[_property]?.Value<string>();
                target = tag == null ? null : _resolve(tag);
                if (target == null)
                    throw new UnknownTagException(typeof(TBase).Name, _property, tag);
            }
            var instance = Activator.CreateInstance(target);
            using (var sub = obj.CreateReader())
                serializer.Populate(sub, instance);
            return instance;
        }
    }

    /// <summary>Un discriminant que ce client ne connaît pas (une trame ou un changement plus récents que lui).</summary>
    public sealed class UnknownTagException : JsonSerializationException
    {
        public string Union { get; }
        public string Tag { get; }

        public UnknownTagException(string union, string property, string tag)
            : base($"{union} : « {property} » inconnu ({tag ?? "absent"})")
        {
            Union = union;
            Tag = tag;
        }
    }
}
