using System.Collections.Generic;
using System.IO;
using Mika.World.Model;
using Mika.World.Protocol;
using NUnit.Framework;

namespace Mika.Tests
{
    public class WorldMirrorTests
    {
        static WorldMirror Ready()
        {
            var mirror = new WorldMirror();
            mirror.Apply(new Definition { World = WireJson.ReadWorld(File.ReadAllText(RepoPaths.Backend("examples", "monde", "chambre.json"))) });
            mirror.Apply(WireJson.ReadServer(@"{""type"": ""snapshot"", ""state"": {""rev"": 0, ""seq"": 100,
                ""actors"": [{""id"": ""mika"", ""room"": ""bedroom"", ""place"": ""center""}],
                ""objects"": [{""id"": ""mug"", ""location"": {""kind"": ""room"", ""room"": ""bedroom"", ""near"": ""desk""}}]}}"));
            return mirror;
        }

        [Test]
        public void RienNEstAppliqueAvantLInstantane()
        {
            var mirror = new WorldMirror();
            var effect = mirror.Apply(new Delta { Seq = 3, Changes = new List<Change>() });
            Assert.That(effect, Is.EqualTo(FrameEffect.NotReady));
        }

        [Test]
        public void UneActionTermineeDeplaceLActeurEtCeQuIlPrend()
        {
            var mirror = Ready();
            var started = new List<string>();
            mirror.IntentStarted += i => started.Add(i.Id);
            mirror.Apply(new IntentStart
            {
                Seq = 101,
                Intent = new Intent
                {
                    Id = "i-101", Actor = "mika", Started = 0, Eta = 10, Deadline = 20,
                    Cause = new Cause { Source = Source.Mika },
                    Steps = new List<Step> { new Step { Kind = StepKind.Walk, ToRoom = "bedroom", ToPlace = "desk", DurationUs = 5_000_000 } },
                },
            });
            Assert.That(started, Is.EqualTo(new[] { "i-101" }));
            Assert.That(mirror.IntentOf("mika"), Is.Not.Null);

            mirror.Apply(new IntentEnd
            {
                Seq = 104, Intent = "i-101", Actor = "mika", Outcome = Outcome.Done,
                Changes = new List<Change>
                {
                    new ActorMoved { Actor = "mika", Room = "bedroom", Place = "desk", Posture = Posture.Sit },
                    new ObjectMoved { Object = "mug", To = new Held { Actor = "mika", Hand = Hand.Right } },
                },
            });
            Assert.That(mirror.IntentOf("mika"), Is.Null);
            Assert.That(mirror.Actor("mika").Place, Is.EqualTo("desk"));
            Assert.That(mirror.Actor("mika").Posture, Is.EqualTo(Posture.Sit));
            Assert.That(mirror.Actor("mika").Holding, Is.EqualTo(new[] { "mug" }));
            Assert.That(mirror.HolderOf("mug"), Is.EqualTo("mika"));
            Assert.That(mirror.RoomOfObject("mug"), Is.EqualTo("bedroom"));
            Assert.That(mirror.Seq, Is.EqualTo(104));
        }

        [Test]
        public void UneTrameDejaVueEstIgnoree()
        {
            var mirror = Ready();
            var frame = new Delta { Seq = 100, Changes = new List<Change> { new ObjectSet { Object = "mug", State = "empty" } } };
            Assert.That(mirror.Apply(frame), Is.EqualTo(FrameEffect.Duplicate));
            Assert.That(mirror.Object("mug").State, Is.Null);
        }

        [Test]
        public void PoserUnObjetLeRetireDeLaMain()
        {
            var mirror = Ready();
            mirror.Apply(new Delta { Seq = 101, Changes = new List<Change> { new ObjectMoved { Object = "mug", To = new Held { Actor = "mika" } } } });
            mirror.Apply(new Delta { Seq = 102, Changes = new List<Change> { new ObjectMoved { Object = "mug", To = new On { Object = "writing_desk", Slot = 0 } } } });
            Assert.That(mirror.Actor("mika").Holding, Is.Empty);
            Assert.That(mirror.RoomOfObject("mug"), Is.EqualTo("bedroom"));
        }

        [Test]
        public void UnePersonneEntreEtSort()
        {
            var mirror = Ready();
            mirror.Apply(new Presence { Seq = 101, Actor = "player:user_1", Joined = true, Room = "bedroom", Place = "door", Label = "Adrien" });
            Assert.That(mirror.Visitors["player:user_1"].Label, Is.EqualTo("Adrien"));
            Assert.That(mirror.Actor("player:user_1").Place, Is.EqualTo("door"));
            mirror.Apply(new Presence { Seq = 102, Actor = "player:user_1", Joined = false });
            Assert.That(mirror.Actor("player:user_1"), Is.Null);
        }

        [Test]
        public void UneEditionRemplaceOuRetire()
        {
            var mirror = Ready();
            var rev = mirror.World.Rev;
            mirror.Apply(new DefinitionDelta
            {
                Seq = 101, Base = rev, Rev = rev + 1,
                Changes = new List<DefChange>
                {
                    new DefRemove { Of = DefKind.Object, Id = "mug" },
                    new DefPut { Item = new RoomDef { Id = "attic", Label = "le grenier" } },
                },
            });
            Assert.That(mirror.World.Rev, Is.EqualTo(rev + 1));
            Assert.That(mirror.World.Object("mug"), Is.Null);
            Assert.That(mirror.World.Room("attic").Label, Is.EqualTo("le grenier"));
        }

        [Test]
        public void LeCalendrierDUneActionPlaceLActeurSurSonTrajet()
        {
            var intent = new Intent
            {
                Started = 1_000_000,
                Steps = new List<Step>
                {
                    new Step { Kind = StepKind.Posture, Posture = Posture.Stand, DurationUs = 1_000_000 },
                    new Step { Kind = StepKind.Walk, DurationUs = 4_000_000 },
                },
            };
            var p = IntentTimeline.At(intent, 3_000_000);
            Assert.That(p.Step, Is.EqualTo(1));
            Assert.That(p.Fraction, Is.EqualTo(0.25).Within(1e-9));
            Assert.That(IntentTimeline.At(intent, 9_000_000).Done(intent), Is.True);
        }
    }
}
