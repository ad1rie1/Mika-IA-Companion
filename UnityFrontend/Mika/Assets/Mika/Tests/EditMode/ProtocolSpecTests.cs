using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Mika.World.Protocol;
using Newtonsoft.Json.Linq;
using NUnit.Framework;

namespace Mika.Tests
{
    /// <summary>
    /// Chaque exemple JSON de la spécification (<c>backendv2/docs/protocole-monde.md</c>) se lit avec les types
    /// générés, dans la bonne classe, et se réécrit sans rien perdre. Le noyau valide les mêmes exemples contre
    /// son propre schéma (<c>tests/protocol/test_world_wire.py</c>) : les deux côtés lisent donc la même chose.
    /// </summary>
    public class ProtocolSpecTests
    {
        static readonly Regex Block = new Regex("```json (client|serveur)\\n(.*?)```", RegexOptions.Singleline);

        static IEnumerable<(string side, string json)> Examples()
        {
            var text = File.ReadAllText(RepoPaths.Backend("docs", "protocole-monde.md"));
            return Block.Matches(text).Cast<Match>().Select(m => (m.Groups[1].Value, m.Groups[2].Value));
        }

        [Test]
        public void LaSpecificationADesExemplesDesDeuxCotes()
        {
            var all = Examples().ToList();
            Assert.That(all.Count(e => e.side == "client"), Is.GreaterThanOrEqualTo(10));
            Assert.That(all.Count(e => e.side == "serveur"), Is.GreaterThanOrEqualTo(10));
        }

        [Test]
        public void ChaqueTrameDuNoyauSeLitDansSaClasse()
        {
            foreach (var (side, json) in Examples().Where(e => e.side == "serveur"))
            {
                var frame = WireJson.ReadServer(json);
                var type = JObject.Parse(json)["type"].Value<string>();
                Assert.That(frame, Is.Not.Null, json);
                Assert.That(frame.Type, Is.EqualTo(type), json);
                Assert.That(frame.GetType(), Is.EqualTo(ServerFrame.TypeOf(type)), json);
                AssertSubset(JObject.Parse(json), JObject.Parse(WireJson.Write(frame)), json);
            }
        }

        [Test]
        public void ChaqueCommandeDuClientSeLitEtSeReecritALIdentique()
        {
            foreach (var (side, json) in Examples().Where(e => e.side == "client"))
            {
                var frame = WireJson.ReadClient(json);
                var type = JObject.Parse(json)["type"].Value<string>();
                Assert.That(frame.Type, Is.EqualTo(type), json);
                AssertSubset(JObject.Parse(json), JObject.Parse(WireJson.Write(frame)), json);
            }
        }

        [Test]
        public void UnDiscriminantInconnuEstSignaleSansPlanter()
        {
            var frame = WireJson.TryReadServer("{\"type\": \"teleport\", \"seq\": 12}", out var error, out var seq);
            Assert.That(frame, Is.Null);
            Assert.That(error, Does.Contain("teleport"));
            Assert.That(seq, Is.EqualTo(12));
        }

        [Test]
        public void UnChampInconnuEstIgnore()
        {
            var frame = WireJson.ReadServer("{\"type\": \"pong\", \"t\": 5, \"plus_tard\": true}");
            Assert.That(((Pong)frame).T, Is.EqualTo(5));
        }

        [Test]
        public void UneDureeNulleSEcritNulle()
        {
            // « null » = une occupation sans fin prévue ; l'omettre ferait prendre au noyau la durée par défaut.
            var a = new Affordance { Id = "lire", Label = "lire", Effect = Effect.Activity, DurationS = null };
            var json = JObject.Parse(WireJson.Write(a));
            Assert.That(json.ContainsKey("duration_s"), Is.True);
            Assert.That(json["duration_s"].Type, Is.EqualTo(JTokenType.Null));
        }

        [Test]
        public void LesMondesDuNoyauSeLisent()
        {
            foreach (var path in new[]
                     {
                         RepoPaths.Backend("examples", "monde", "chambre.json"),
                         RepoPaths.Backend("src", "mika", "faculties", "world", "chambre.json"),
                     })
            {
                if (!File.Exists(path))
                    continue;
                var world = WireJson.ReadWorld(File.ReadAllText(path));
                Assert.That(world.Places.Select(p => p.Id), Is.SupersetOf(new[] { "center", "window", "desk", "bed", "bookshelf", "door" }), path);
                Assert.That(world.Actors.Any(a => a.Id == "mika"), Is.True, path);
            }
        }

        /// <summary>Tout ce que porte l'original se retrouve à l'identique dans la réécriture (qui peut ajouter des défauts).</summary>
        static void AssertSubset(JToken expected, JToken actual, string context)
        {
            switch (expected)
            {
                case JObject eo:
                    Assert.That(actual, Is.InstanceOf<JObject>(), context);
                    var ao = (JObject)actual;
                    foreach (var prop in eo.Properties())
                    {
                        if (prop.Value.Type == JTokenType.Null && !ao.ContainsKey(prop.Name))
                            continue; // null omis = null
                        Assert.That(ao.ContainsKey(prop.Name), Is.True, $"« {prop.Name} » perdu dans {context}");
                        AssertSubset(prop.Value, ao[prop.Name], context);
                    }
                    break;
                case JArray ea:
                    var aa = (JArray)actual;
                    Assert.That(aa.Count, Is.EqualTo(ea.Count), context);
                    for (var i = 0; i < ea.Count; i++)
                        AssertSubset(ea[i], aa[i], context);
                    break;
                default:
                    if (expected.Type == JTokenType.Float || actual.Type == JTokenType.Float)
                        Assert.That(actual.Value<double>(), Is.EqualTo(expected.Value<double>()).Within(1e-9), context);
                    else
                        Assert.That(JToken.DeepEquals(expected, actual), Is.True, $"{expected} ≠ {actual} dans {context}");
                    break;
            }
        }
    }
}
