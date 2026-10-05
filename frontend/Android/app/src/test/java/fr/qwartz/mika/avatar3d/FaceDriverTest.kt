package fr.qwartz.mika.avatar3d

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.ceil
import kotlin.random.Random

/**
 * Le visage, sur la JVM : les intentions des tests web (`emotionOnset.test.ts`, `faceHuman.test.ts`,
 * `blinkGaze.test.ts`, `faceIdle.test.ts`) vérifiées sur les poids de morphoses que le pilote sort.
 *
 * Le modèle de test donne à chaque groupe d'émotion sa propre morphose `g:<groupe>` au poids 1 (on y lit le poids du
 * groupe), y joint les symboles que le vrai modèle y mêle (`Eye@@`, `Tear`, `FaceRed`, `eyeLookUp*`…), et donne à
 * chaque forme ARKit sa morphose `ark:<forme>`.
 */
class FaceDriverTest {

    private fun expr(name: String, vararg binds: Pair<String, Float>, preset: String = "unknown", binary: Boolean = false) =
        VrmDocument.Expression(name, preset, binds.map { VrmDocument.Bind(it.first, it.second) }, binary)

    private fun model(withIdle: Boolean = true, without: Set<String> = emptySet()): Map<String, VrmDocument.Expression> {
        val list = ArrayList<VrmDocument.Expression>()
        val recipeGroups = FaceDriver.EMOTION_RECIPES.values.flatMap { it.keys }.toSet()
        for (g in recipeGroups) list += expr(g, "g:$g" to 1f)
        // Les symboles que le vrai modèle mêle à ses groupes (cf. faceRig.ts).
        list += expr("Shocked", "g:Shocked" to 1f, "Eye@@" to 1f, "FaceSweat" to 1f, "eyeLookUpLeft" to 0.3f, "EyeHighlightBig" to 0.61f)
        list += expr("Sad1", "g:Sad1" to 1f, "Tear" to 1f)
        list += expr("Shy", "g:Shy" to 1f, "FaceRed" to 1f, "eyeLookUpRight" to 0.3f)
        // Deux groupes qui poussent la même morphose : la somme doit rester bornée.
        list += expr("Joy2", "g:Joy2" to 1f, "Shared" to 1f)
        list += expr("InWonder", "g:InWonder" to 1f, "Shared" to 1f)
        list += expr(FaceDriver.TIRED_GROUP, "g:Sleepy" to 1f)
        list += expr("Blink", "blinkMorph" to 1f, preset = "blink")
        if (withIdle) {
            val idle = LinkedHashSet<String>()
            FaceDriver.MICRO_CHANNELS.forEach { idle += it.name }
            idle += FaceDriver.SPEECH_BROWS.keys
            FaceDriver.EMOTION_ACCENT.values.forEach { idle += it.keys }
            for (n in idle) list += expr(n, "ark:$n" to 1f)
        }
        // associateBy : le dernier l'emporte, comme dans VrmDocument (les surcharges ci-dessus remplacent les simples).
        return list.filter { it.name !in without }.associateBy { it.name }
    }

    /** Un hasard qui rend toujours la même valeur (le `vi.spyOn(Math, "random")` des tests web). */
    private class FixedRandom(private val value: Float) : Random() {
        override fun nextBits(bitCount: Int): Int = (value.toDouble() * (1L shl bitCount)).toLong().toInt()
        override fun nextFloat(): Float = value
        override fun nextDouble(): Double = value.toDouble()
    }

    /** Fait tourner le pilote `seconds` secondes à `fps` ; rend la dernière image. */
    private fun FaceDriver.runFor(seconds: Float, fps: Int = 60, each: (Map<String, Float>) -> Unit = {}): Map<String, Float> {
        val frames = ceil(seconds * fps).toInt()
        var last: Map<String, Float> = emptyMap()
        repeat(frames) {
            last = update(1f / fps)
            each(last)
        }
        return last
    }

    private fun Map<String, Float>.w(morph: String) = this[morph] ?: 0f

    private fun driver(random: Random = Random(1), withIdle: Boolean = false) = FaceDriver(model(withIdle), random)

    // --- Émotion ---

    @Test fun `chaque recette atteint ses morphoses et rien ne dépasse 1`() {
        for ((emotion, recipe) in FaceDriver.EMOTION_RECIPES) {
            if (recipe.isEmpty()) continue
            val d = driver()
            d.setEmotion(emotion, 1f)
            val out = d.runFor(4f)
            for ((group, w) in recipe) {
                val got = out.w("g:$group")
                assertTrue("$emotion.$group = $got pour $w", got >= w * 0.93f && got <= minOf(1f, w * 1.07f))
            }
        }
        // Toutes les couches à fond à la fois : aucune morphose ne sort de 0…1.
        val d = FaceDriver(model(), Random(3))
        d.setSpeaking(true)
        d.setEnergy(0f)
        d.setSpeechBeat(1f, 1f)
        for (emotion in FaceDriver.EMOTION_NAMES) {
            d.setEmotion(emotion, 1f, listOf(emotion to 0.55f, "amused" to 0.45f))
            d.runFor(1.5f) { out ->
                for ((m, v) in out) assertTrue("$emotion: $m = $v", v > 0f && v <= 1f)
            }
        }
    }

    @Test fun `deux groupes qui poussent la même morphose restent bornés à 1`() {
        val d = driver()
        d.setEmotion("excited", 1f) // Joy2 0,9 + InWonder 0,2 sur « Shared »
        val out = d.runFor(3f)
        assertTrue(out.w("Shared") <= 1f)
        assertTrue(out.w("Shared") >= 0.99f)
    }

    @Test fun `les symboles et le regard ne viennent jamais d'une expression`() {
        val d = driver()
        d.setEmotion("surprised", 1f)
        var shocked = 0f
        d.runFor(2f) { out ->
            for (m in listOf("Eye@@", "FaceSweat", "eyeLookUpLeft", "EyeHighlightBig")) assertEquals(m, 0f, out.w(m))
            shocked = out.w("g:Shocked")
        }
        assertTrue(shocked > 0.8f)

        // Une tristesse douce, longtemps : la larme de `Sad1` ne sort pas avec le groupe.
        val sad = driver()
        sad.setEmotion("sad", 0.5f)
        sad.runFor(30f) { out -> assertEquals(0f, out.w("Tear")) }

        // `Shy` porte FaceRed à 100 % : nettoyé, la rougeur n'est que celle, lente, de la physiologie.
        val shy = driver()
        shy.setEmotion("embarrassed", 1f)
        val out = shy.runFor(0.3f)
        assertTrue(out.w("g:Shy") > 0.4f)
        assertTrue(out.w("FaceRed") < 0.25f)
        assertEquals(0f, out.w("eyeLookUpRight"))
    }

    @Test fun `un sursaut arrive plus vite que la tristesse, et chaque émotion repart plus lentement qu'elle n'est venue`() {
        assertTrue(FaceDriver.onsetSpeedFor("surprised") > FaceDriver.onsetSpeedFor("happy"))
        assertTrue(FaceDriver.onsetSpeedFor("happy") > FaceDriver.onsetSpeedFor("sad"))
        for (name in FaceDriver.EMOTION_NAMES) {
            assertTrue(name, FaceDriver.offsetSpeedFor(name) < FaceDriver.onsetSpeedFor(name))
            assertTrue(name, FaceDriver.offsetSpeedFor(name) >= FaceDriver.MIN_OFFSET_SPEED)
        }
    }

    @Test fun `sur le visage, la surprise est presque là en 100 ms, la tristesse non`() {
        val fast = driver()
        fast.setEmotion("surprised", 1f)
        assertTrue(fast.update(0.1f).w("g:Shocked") > 0.75f * 0.9f)

        val slow = driver()
        slow.setEmotion("sad", 1f)
        assertTrue(slow.update(0.1f).w("g:Sad1") < 0.25f * 0.85f)
    }

    @Test fun `une expression s'efface plus lentement qu'elle n'est venue`() {
        val d = driver()
        d.setEmotion("happy", 1f)
        val risen = d.update(0.1f).w("g:Smile1")
        repeat(60) { d.update(0.05f) }
        d.setEmotion("neutral", 1f)
        val remaining = d.update(0.1f).w("g:Smile1")
        // Monté de `risen` en 100 ms ; redescendu de moins que ça dans les mêmes 100 ms.
        assertTrue("monté $risen, reste $remaining", 1f - remaining < risen * 0.75f)
        // Et finit par disparaître tout à fait de la sortie.
        assertEquals(0f, d.runFor(10f).w("g:Smile1"))
    }

    @Test fun `l'émotion secondaire ne se montre que quand elle pèse assez`() {
        val s = FaceDriver.secondaryOf("happy", listOf("happy" to 0.6f, "sad" to 0.4f))
        assertNotNull(s)
        assertEquals("sad", s!!.emotion)
        assertEquals(0.667f, s.ratio, 0.01f)
        assertNull(FaceDriver.secondaryOf("happy", listOf("happy" to 0.9f, "sad" to 0.1f)))
        assertNull(FaceDriver.secondaryOf("happy", listOf("happy" to 1f)))
        assertNull(FaceDriver.secondaryOf("happy", listOf("happy" to 0.6f, "bogus" to 0.5f)))
    }

    @Test fun `l'émotion secondaire se montre sur le visage à une part de son poids`() {
        val d = driver()
        d.setEmotion("happy", 1f, listOf("happy" to 0.6f, "sad" to 0.4f))
        val out = d.runFor(3f)
        val ratio = 0.4f / 0.6f
        val sad = 0.85f * ratio * FaceDriver.SECONDARY_SHARE // ≈ 0,255
        val smile = 1f - 0.25f * ratio // la principale fait de la place
        assertEquals(sad, out.w("g:Sad1"), sad * 0.06f)
        assertEquals(smile, out.w("g:Smile1"), smile * 0.06f)

        val faint = driver()
        faint.setEmotion("happy", 1f, listOf("happy" to 0.9f, "sad" to 0.1f))
        val o2 = faint.runFor(3f)
        assertEquals(0f, o2.w("g:Sad1"))
        assertTrue(o2.w("g:Smile1") > 0.94f)
    }

    @Test fun `une émotion inconnue retombe sur neutre`() {
        val d = driver()
        d.setEmotion("happy", 1f)
        d.runFor(1f)
        d.setEmotion("bogus", 1f)
        assertEquals("neutral", d.currentEmotion)
        val out = d.runFor(8f)
        assertTrue(out.keys.none { it.startsWith("g:") })
    }

    @Test fun `une recette dont le modèle n'a pas tous les groupes ne montre rien`() {
        val d = FaceDriver(model(withIdle = false, without = setOf("Angry1")), Random(1))
        d.setEmotion("angry", 1f) // Angry4 0,7 + Angry1 0,3 : amputée, ce serait une autre expression
        val out = d.runFor(3f)
        assertEquals(0f, out.w("g:Angry4"))
    }

    @Test fun `la fatigue alourdit les paupières`() {
        val d = driver()
        d.setEnergy(0.1f) // fatigue pleine
        val tired = d.runFor(4f).w("g:Sleepy")
        assertEquals(FaceDriver.TIRED_MAX, tired, FaceDriver.TIRED_MAX * 0.07f)

        d.setEnergy(0.35f) // fatigue à moitié
        assertEquals(FaceDriver.TIRED_MAX / 2, d.runFor(5f).w("g:Sleepy"), FaceDriver.TIRED_MAX * 0.05f)

        d.setEnergy(0.9f) // reposée : le visage ensommeillé s'en va
        assertEquals(0f, d.runFor(8f).w("g:Sleepy"))

        val fresh = driver()
        assertEquals(0f, fresh.runFor(4f).w("g:Sleepy"))
    }

    // --- Physiologie ---

    /** `hold` de faceHuman.test.ts : 30 images par seconde. */
    private fun FaceDriver.hold(emotion: String, intensity: Float, seconds: Float): Map<String, Float> {
        setEmotion(emotion, intensity)
        return runFor(seconds, fps = 30)
    }

    @Test fun `les larmes montent - jamais dans la première seconde, seulement si une forte tristesse dure`() {
        assertEquals(0f, driver().hold("sad", 0.95f, 1f).w("Tear"))
        val out = driver().hold("sad", 0.95f, 10f)
        assertTrue(out.w("EyeWatery") > 0.9f * 0.8f)
        assertTrue(out.w("Tear") > 0.4f)
    }

    @Test fun `une tristesse douce, si longue soit-elle, ne pleure pas`() {
        val out = driver().hold("sad", 0.5f, 60f)
        assertEquals(0f, out.w("Tear"))
        assertTrue(out.w("EyeWatery") < 0.5f * 0.8f)
    }

    @Test fun `on ne rit aux larmes qu'en haut de l'échelle`() {
        assertEquals(0f, driver().hold("amused", 0.7f, 20f).w("EyeWatery"))
        assertTrue(driver().hold("amused", 1f, 8f).w("EyeWatery") > 0.3f * 0.8f)
    }

    @Test fun `les larmes sèchent lentement une fois la tristesse passée`() {
        val d = driver()
        val before = d.hold("sad", 0.95f, 10f).w("EyeWatery")
        assertTrue(d.hold("neutral", 0.5f, 3f).w("EyeWatery") > before * 0.5f)
        assertTrue(d.hold("neutral", 0.5f, 40f).w("EyeWatery") < 0.05f)
    }

    @Test fun `une rougeur vient en une seconde ou deux et repart bien plus lentement`() {
        val d = driver()
        assertTrue(d.hold("embarrassed", 0.9f, 0.3f).w("FaceRed") < 0.3f)
        val peak = d.hold("embarrassed", 0.9f, 5f).w("FaceRed")
        assertTrue(peak > 0.7f)
        assertTrue(d.hold("happy", 0.6f, 2f).w("FaceRed") > peak * 0.7f)
    }

    @Test fun `les pupilles se dilatent avec l'amour et la peur, se contractent avec la colère`() {
        assertTrue(driver().hold("love", 0.9f, 3f).w("EyeDilationLeft") > 0.3f * 0.6f)
        assertTrue(driver().hold("scared", 0.9f, 3f).w("EyeDilationRight") > 0.3f * 0.6f)
        val angry = driver().hold("angry", 0.9f, 3f)
        assertTrue(angry.w("EyeConstrictLeft") > 0.2f * 0.6f)
        assertEquals(0f, angry.w("EyeDilationLeft"))
    }

    // --- Clignement ---

    @Test fun `éveillée, elle cligne à une cadence irrégulière, vite ou lentement`() {
        val d = driver(Random(1234))
        val fps = 60
        val onsets = ArrayList<Float>()
        val durations = ArrayList<Float>()
        var t = 0f
        var closedSince = -1f
        d.runFor(180f, fps) { out ->
            t += 1f / fps
            val closed = out.w("blinkMorph") > 0.5f
            if (closed && closedSince < 0f) {
                closedSince = t
                onsets += t
            } else if (!closed && closedSince >= 0f) {
                durations += t - closedSince
                closedSince = -1f
            }
        }
        // ~2,5–5,5 s entre deux clignements, plus quelques doubles.
        assertTrue("${onsets.size} clignements", onsets.size in 25..100)
        val intervals = onsets.zipWithNext { a, b -> b - a }
        assertTrue("intervalles ${intervals.min()}…${intervals.max()}", intervals.max() - intervals.min() > 2f)
        assertTrue("des clignements longs", durations.any { it > 0.18f })
        assertTrue("des clignements rapides", durations.any { it < 0.13f })
        // Jamais les yeux clos plus que le temps d'un clignement lent.
        assertTrue(durations.max() < 0.3f)
    }

    @Test fun `endormie, les yeux restent fermés, en sommeil paradoxal, ils frémissent`() {
        val d = driver(Random(5))
        d.runFor(2f)
        d.setSleepPhase("deep_sleep")
        d.runFor(3f)
        d.runFor(60f) { out -> assertTrue(out.w("blinkMorph") >= 0.99f) }

        d.setSleepPhase("light_sleep")
        assertEquals(0.85f, d.runFor(4f).w("blinkMorph"), 0.002f)

        d.setSleepPhase("rem")
        d.runFor(3f)
        var lo = 1f
        var hi = 0f
        d.runFor(10f) { out ->
            val v = out.w("blinkMorph")
            lo = minOf(lo, v)
            hi = maxOf(hi, v)
        }
        assertTrue(lo >= 0.7f && hi <= 1f)
        assertTrue("frémissement $lo…$hi", hi - lo > 0.04f)

        // Au réveil, les yeux se rouvrent puis le cycle reprend.
        d.setSleepPhase("awake")
        d.runFor(2f)
        var open = 1f
        d.runFor(1f) { out -> open = minOf(open, out.w("blinkMorph")) }
        assertTrue(open <= 0.03f)
        var blinks = 0
        var closed = false
        d.runFor(20f) { out ->
            val c = out.w("blinkMorph") > 0.5f
            if (c && !closed) blinks++
            closed = c
        }
        assertTrue(blinks >= 2)
    }

    @Test fun `une phase inconnue vaut l'éveil`() {
        val d = driver(Random(5))
        d.setSleepPhase("hibernation")
        var open = 1f
        d.runFor(3f) { out -> open = minOf(open, out.w("blinkMorph")) }
        assertEquals(0f, open)
    }

    @Test fun `un grand saut du regard peut faire cligner hors de la cadence`() {
        val d = FaceDriver(model(withIdle = false), FixedRandom(0.1f))
        repeat(60) { assertEquals(0f, d.update(1f / 60).w("blinkMorph")) }
        d.noteGazeShift(FaceDriver.GAZE_BLINK_MIN_SHIFT + 0.05f)
        d.update(1f / 60)
        assertTrue(d.update(0.05f).w("blinkMorph") > 0.3f)
    }

    @Test fun `un petit saut de fixation, jamais`() {
        val d = FaceDriver(model(withIdle = false), FixedRandom(0.1f))
        repeat(60) { d.update(1f / 60) }
        d.noteGazeShift(FaceDriver.GAZE_BLINK_MIN_SHIFT * 0.5f)
        d.update(1f / 60)
        assertEquals(0f, d.update(0.05f).w("blinkMorph"))
    }

    @Test fun `ni un saut juste après un clignement (période réfractaire)`() {
        val d = FaceDriver(model(withIdle = false), FixedRandom(0.1f))
        repeat(60) { d.update(1f / 60) }
        d.noteGazeShift(0.3f)
        d.update(1f / 60)
        var last = 1f
        repeat(15) { last = d.update(1f / 60).w("blinkMorph") }
        assertEquals(0f, last)
        d.noteGazeShift(0.3f)
        d.update(1f / 60)
        assertEquals(0f, d.update(0.05f).w("blinkMorph"))
        assertTrue(FaceDriver.GAZE_BLINK_REFRACTORY_S > 0.25f)
    }

    @Test fun `le clignement joue le préréglage blink, pas le groupe maison du même nom`() {
        // Le modèle a deux groupes « Blink » : le préréglage (`まばたき`) et un groupe maison qui baisse aussi les
        // sourcils. Le web écrit le préréglage.
        val expressions = mapOf(
            "Blink" to expr("Blink", "BrowDown" to 0.6f, "EyeBlink" to 1f),
            "blink" to expr("Blink", "まばたき" to 1f, preset = "blink"),
        )
        val d = FaceDriver(expressions, Random(2))
        d.setSleepPhase("deep_sleep")
        val out = d.runFor(4f)
        assertTrue(out.w("まばたき") >= 0.99f)
        assertFalse(out.containsKey("BrowDown"))
        assertFalse(out.containsKey("EyeBlink"))

        // Sans préréglage, le groupe nommé « Blink » sert de repli.
        val fallback = FaceDriver(mapOf("Blink" to expressions.getValue("Blink")), Random(2))
        fallback.setSleepPhase("deep_sleep")
        assertTrue(fallback.runFor(4f).w("EyeBlink") >= 0.99f)
    }

    @Test fun `un groupe binaire est tout ou rien`() {
        val expressions = mapOf("Blink" to expr("Blink", "まばたき" to 1f, preset = "blink", binary = true))
        val d = FaceDriver(expressions, Random(2))
        d.setSleepPhase("light_sleep")
        assertEquals(1f, d.runFor(4f).w("まばたき"))
    }

    // --- Micro-mouvements ---

    @Test fun `les canaux de dérive restent discrets`() {
        for (c in FaceDriver.MICRO_CHANNELS) {
            val peak = c.bias + c.amp * (c.talkBoost ?: 1f)
            assertTrue("${c.name} culmine à $peak", peak <= 0.2f)
            assertTrue(c.amp > 0f)
            assertTrue(c.rate > 0f)
        }
    }

    @Test fun `les paires gauche-droite ont des vitesses différentes`() {
        val byBase = HashMap<String, MutableList<Float>>()
        for (c in FaceDriver.MICRO_CHANNELS) {
            val base = c.name.replace(Regex("(Left|Right)$"), "")
            if (base == c.name) continue
            byBase.getOrPut(base) { ArrayList() } += c.rate
        }
        assertTrue(byBase.isNotEmpty())
        for ((base, rates) in byBase) assertEquals("$base partage une vitesse", rates.size, rates.toSet().size)
    }

    @Test fun `les accents ne nomment que des émotions connues, restent sous 0,45, et couvrent presque tout`() {
        for ((emotion, shapes) in FaceDriver.EMOTION_ACCENT) {
            assertTrue("émotion inconnue $emotion", emotion in FaceDriver.EMOTION_NAMES)
            for ((shape, w) in shapes) assertTrue("$emotion.$shape", w > 0f && w <= 0.45f)
        }
        assertTrue(FaceDriver.EMOTION_ACCENT.size >= FaceDriver.EMOTION_NAMES.size - 3)

        // Dérive au plus haut + accent au plus haut ne dépassent 1 sur aucune forme.
        val microPeak = FaceDriver.MICRO_CHANNELS.associate { it.name to it.bias + it.amp * (it.talkBoost ?: 1f) }
        for ((emotion, shapes) in FaceDriver.EMOTION_ACCENT) {
            for ((shape, w) in shapes) assertTrue("$emotion.$shape", w + (microPeak[shape] ?: 0f) <= 1f)
        }
    }

    @Test fun `les tables couvrent exactement les 29 émotions`() {
        assertEquals(29, FaceDriver.EMOTION_NAMES.size)
        assertEquals(FaceDriver.EMOTION_NAMES.toSet(), FaceDriver.EMOTION_RECIPES.keys)
        val known = FaceDriver.EMOTION_NAMES.toSet()
        for (table in listOf(FaceDriver.ONSET_SPEED, FaceDriver.BLUSH, FaceDriver.TEARS, FaceDriver.PUPIL)) {
            assertTrue(known.containsAll(table.keys))
        }
        assertTrue(known.containsAll(FaceDriver.RESTLESS) && known.containsAll(FaceDriver.HEAVY))
    }

    @Test fun `le visage dérive sans cesse, discrètement et pas en miroir`() {
        val d = driver(withIdle = true)
        var lo = 1f
        var hi = 0f
        var asymmetric = 0
        d.runFor(30f) { out ->
            val v = out.w("ark:BrowInnerUp")
            lo = minOf(lo, v)
            hi = maxOf(hi, v)
            if (out.w("ark:BrowOuterUpLeft") != out.w("ark:BrowOuterUpRight")) asymmetric++
            for ((m, x) in out) if (m.startsWith("ark:")) assertTrue("$m = $x", x <= 0.12f + 1e-4f)
        }
        assertTrue("dérive $lo…$hi", hi - lo > 0.03f)
        assertTrue("asymétrique $asymmetric images sur 1800", asymmetric > 1400)
    }

    @Test fun `l'accent d'une émotion s'ajoute, puis s'efface en dormant`() {
        val d = driver(withIdle = true)
        d.setEmotion("sad", 1f)
        assertTrue(d.runFor(4f).w("ark:BrowInnerUp") > 0.4f) // 0,45 d'accent + la dérive
        assertTrue(d.runFor(0.1f).w("ark:MouthFrownLeft") > 0.27f)
        d.setSleepPhase("deep_sleep")
        val asleep = d.runFor(8f)
        assertTrue(asleep.w("ark:BrowInnerUp") < 0.03f) // la dérive seule, réduite au sommeil
        assertEquals(0f, asleep.w("ark:MouthFrownLeft"))
    }

    @Test fun `un mot appuyé lève les sourcils`() {
        // Deux pilotes au même instant : seule la ponctuation de la parole les distingue. La surprise met un accent
        // sous ces sourcils, pour que la dérive ne passe jamais sous 0 (où elle serait bornée et fausserait l'écart).
        val a = driver(withIdle = true)
        val b = driver(withIdle = true)
        a.setEmotion("surprised", 0.5f)
        b.setEmotion("surprised", 0.5f)
        a.runFor(2f)
        b.runFor(2f)
        a.setSpeechBeat(1f, 0f)
        val oa = a.update(1f / 60)
        val ob = b.update(1f / 60)
        assertEquals(0.32f, oa.w("ark:BrowOuterUpLeft") - ob.w("ark:BrowOuterUpLeft"), 1e-4f)
        assertEquals(0.28f, oa.w("ark:BrowInnerUp") - ob.w("ark:BrowInnerUp"), 1e-4f)
    }

    @Test fun `un pas invalide ne casse rien`() {
        val d = driver(withIdle = true)
        d.setEmotion("happy", 1f)
        d.update(Float.NaN)
        d.update(-1f)
        d.update(Float.POSITIVE_INFINITY)
        val out = d.runFor(3f)
        for ((m, v) in out) assertTrue("$m = $v", v > 0f && v <= 1f)
        assertTrue(out.w("g:Smile1") > 0.9f)
    }
}
