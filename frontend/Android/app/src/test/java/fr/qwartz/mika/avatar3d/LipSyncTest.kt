package fr.qwartz.mika.avatar3d

import fr.qwartz.mika.avatar3d.FrenchVisemes.Viseme
import fr.qwartz.mika.avatar3d.LipSync.PlanSegment
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs
import kotlin.math.floor

/**
 * La bouche qui parle : les intentions de `LipSyncController.test.ts` (et de la cadence, de `lipSyncPlan`, de
 * `articulationFor`), puis ce que l'app ajoute — un curseur d'affichage suivi à chaque image.
 *
 * Le modèle de Mika porte 13 visèmes : ni `vrc.v_sil` (l'absence des autres) ni `vrc.v_pp` (vide sur le modèle
 * d'origine). La fermeture des lèvres s'y lit donc comme sur le web : les autres visèmes qui s'effacent vite.
 */
class LipSyncTest {

    private val mika: Set<String> = LipSync.VRC_VISEME_MORPHS.filter { it != "vrc.v_pp" }.toSet()

    private fun speech(text: String, start: Int = 0) = listOf(PlanSegment.Speech(text, start))

    private fun LipSync.outputs(load: Float = 0f): Map<String, Float> {
        val m = HashMap<String, Float>()
        forEachOutput(load) { name, w -> m[name] = w }
        return m
    }

    private class Sample(val offset: Int, val viseme: Viseme, val values: Map<String, Float>, val pp: Float)

    /** Joue `text` au pas de 1/120 s ; une image par pas, sorties et niveau de la fermeture. */
    private fun play(lip: LipSync, text: String, msPerChar: Double = 60.0, load: Float = 0f): List<Sample> {
        lip.startFromPlan(speech(text), msPerChar)
        val samples = ArrayList<Sample>()
        var k = 0
        while (k < 400 && lip.isSpeaking) {
            lip.update(STEP)
            samples += Sample(lip.currentCharOffset, lip.currentViseme, lip.outputs(load), lip.levelOf(Viseme.PP))
            k++
        }
        return samples
    }

    private fun List<Sample>.peak(name: String) = maxOf { it.values[name] ?: 0f }
    private fun Map<String, Float>.sum() = values.sum()

    // --- Cadence et articulation ---

    @Test fun `la cadence suit le débit, bornée comme lui`() {
        assertEquals(60.0, LipSync.msPerCharForRate(1.0), 0.0)
        assertEquals(30.0, LipSync.msPerCharForRate(2.0), 0.0)
        assertEquals(120.0, LipSync.msPerCharForRate(0.5), 0.0)
        assertEquals(30.0, LipSync.msPerCharForRate(10.0), 0.0)
        assertEquals(60.0, LipSync.msPerCharForRate(Double.NaN), 0.0)
        assertEquals(60.0, LipSync.msPerCharForRate(0.0), 0.0)
    }

    @Test fun `une voix excitée articule grand, une voix lasse entrouvre à peine les lèvres`() {
        assertEquals(1f, LipSync.articulationFor("neutral", 1f), 1e-6f)
        assertTrue(LipSync.articulationFor("excited", 1f) > 1.1f)
        assertTrue(LipSync.articulationFor("bored", 1f) < 0.85f)
        assertTrue(LipSync.articulationFor("happy", 0.8f, fatigue = 1f) < LipSync.articulationFor("happy", 0.8f))
        for (e in FaceDriver.EMOTION_NAMES) for (f in listOf(0f, 1f)) {
            val a = LipSync.articulationFor(e, 1f, f)
            assertTrue("$e/$f = $a", a in 0.6f..1.15f)
        }
        assertEquals(1f, LipSync.articulationFor("bogus", Float.NaN, Float.NaN), 1e-6f)
    }

    // --- Prosodie ---

    @Test fun `les jetons de prosodie deviennent des silences, le texte garde sa position`() {
        val text = "Hmm... [SIGH] bon écoute, [PAUSE:400] je crois que oui."
        val plan = LipSync.speechPlan(text)
        assertEquals(5, plan.size)
        assertEquals(PlanSegment.Speech("Hmm...", 0), plan[0])
        assertEquals(PlanSegment.Silence(LipSync.SIGH_MS), plan[1])
        assertEquals(PlanSegment.Speech("bon écoute,", text.indexOf("bon")), plan[2])
        assertEquals(PlanSegment.Silence(400.0), plan[3])
        assertEquals(PlanSegment.Speech("je crois que oui.", text.indexOf("je")), plan[4])

        assertEquals(listOf(PlanSegment.Silence(500.0)), LipSync.speechPlan("[PAUSE]"))
        assertEquals(listOf(PlanSegment.Silence(50.0)), LipSync.speechPlan("[pause:10]"))
        assertEquals(listOf(PlanSegment.Silence(3000.0)), LipSync.speechPlan("[PAUSE:99999999999999999999]"))
        assertEquals(
            listOf(PlanSegment.Silence(LipSync.LAUGH_MS), PlanSegment.Silence(LipSync.BREATH_MS)),
            LipSync.speechPlan("[Laugh] [BREATH]"),
        )
        // Un crochet qui n'est pas un jeton se dit comme du texte (rien de magique).
        assertEquals(listOf(PlanSegment.Speech("[NOTE] oui", 0)), LipSync.speechPlan("[NOTE] oui"))
    }

    @Test fun `un silence de prosodie ferme la bouche pour sa durée exacte`() {
        val lip = LipSync(mika)
        lip.startFromPlan(LipSync.speechPlan("ah [PAUSE:400] ah"), 60.0)
        var open = 0f
        repeat(12) { // 100 ms : le premier « ah »
            lip.update(STEP * 1)
            open = maxOf(open, lip.outputs().sum())
        }
        assertTrue(open > 0.5f)
        var t = 0.1
        var during = 1f
        while (t < 0.1 + 0.4) {
            lip.update(STEP)
            t += STEP
            if (t > 0.3) during = minOf(during, lip.outputs().sum()) // relâchée
            if (t > 0.3 && t < 0.45) assertEquals(-1, lip.currentCharOffset)
        }
        assertTrue("fermée pendant la pause : $during", during < 0.05f)
        var reopened = 0f
        repeat(30) {
            lip.update(STEP)
            reopened = maxOf(reopened, lip.outputs().sum())
        }
        assertTrue(reopened > 0.5f)
    }

    // --- Les trames gardent leur index ---

    @Test fun `l'estimation avance dans le texte, et une frontière de mot la recale`() {
        val lip = LipSync(mika)
        lip.startFromPlan(speech("bonjour tout le monde"), 60.0)
        assertEquals(0, lip.currentCharOffset)
        // À 130 ms : passé la fermeture du « b », dans le « on » nasal — une trame pour le digramme, ancrée sur sa
        // première lettre.
        lip.update(0.13f)
        assertEquals(1, lip.currentCharOffset)
        assertEquals(Viseme.OH, lip.currentViseme)

        assertTrue(lip.seekToChar(8)) // « tout »
        assertEquals(8, lip.currentCharOffset)
        assertTrue(lip.isSpeaking)
    }

    @Test fun `le recalage marche aussi en arrière`() {
        val lip = LipSync(mika)
        lip.startFromPlan(speech("bonjour tout le monde"), 60.0)
        lip.update(1f)
        assertTrue(lip.currentCharOffset > 10)
        lip.seekToChar(3)
        assertEquals(3, lip.currentCharOffset)
    }

    @Test fun `les silences n'ont pas d'index, et un recalage les enjambe`() {
        val lip = LipSync(mika)
        lip.startFromPlan(listOf(PlanSegment.Speech("ok", 0), PlanSegment.Silence(600.0), PlanSegment.Speech("oui", 9)), 60.0)
        assertTrue(lip.seekToChar(9))
        assertEquals(9, lip.currentCharOffset)
    }

    @Test fun `des blancs repliés gardent les index d'ORIGINE`() {
        val lip = LipSync(mika)
        lip.startFromPlan(speech("a  b"), 60.0)
        lip.seekToChar(3)
        assertEquals(3, lip.currentCharOffset)
        // Le double blanc est une trame courte, pas deux.
        lip.seekToChar(1)
        assertEquals(1, lip.currentCharOffset)
        lip.update(0.035f)
        assertEquals(3, lip.currentCharOffset)
    }

    @Test fun `une frontière au-delà du dernier caractère voisé se pose sur la dernière trame voisée`() {
        val lip = LipSync(mika)
        lip.startFromPlan(speech("ok.", 4), 60.0)
        assertTrue(lip.seekToChar(500))
        assertEquals(6, lip.currentCharOffset)
    }

    @Test fun `un plan fini trop tôt est ranimé par le recalage suivant`() {
        val lip = LipSync(mika)
        lip.startFromPlan(speech("salut"), 60.0)
        lip.update(5f)
        assertFalse(lip.isSpeaking)
        assertTrue(lip.seekToChar(3))
        assertTrue(lip.isSpeaking)
        assertEquals(3, lip.currentCharOffset)
    }

    @Test fun `un plan sans positions joue encore, et refuse poliment un recalage`() {
        val lip = LipSync(mika)
        lip.startTextDriven("bonjour", 420.0)
        assertTrue(lip.isSpeaking)
        assertEquals(-1, lip.currentCharOffset)
        assertFalse(lip.seekToChar(2))
        assertFalse(lip.trackChar(2))
        lip.stop()
        assertFalse(lip.seekToChar(0))
        assertFalse(lip.trackChar(0))
        // Un texte vide ne parle pas (et ne reste pas « en parole » pour toujours).
        lip.startFromPlan(LipSync.speechPlan(""), 60.0)
        assertFalse(lip.isSpeaking)
    }

    @Test fun `l'estimation dure le budget de caractères du texte`() {
        val lip = LipSync(mika)
        lip.startFromPlan(speech("bonjour tout le monde"), 60.0)
        lip.update(21 * 0.06f - 0.01f)
        assertTrue(lip.isSpeaking)
        lip.update(0.02f)
        assertFalse(lip.isSpeaking)
    }

    // --- Le rendu sur les visèmes ---

    @Test fun `elle écrit les morphoses vrc_v du modèle, et rien d'autre`() {
        val lip = LipSync(mika)
        assertEquals("visemes", lip.outputMode)
        assertEquals(mika, lip.outputNames.toSet())
        val samples = play(lip, "papa")
        assertTrue(samples.peak("vrc.v_aa") > 0.6f)
        // Sans liste de morphoses, les 14 visèmes sont supposés là.
        assertEquals(LipSync.VRC_VISEME_MORPHS.toSet(), LipSync().outputNames.toSet())
    }

    @Test fun `une bilabiale ferme vraiment la bouche entre deux voyelles`() {
        val samples = play(LipSync(mika), "papa")
        // Une fois la bouche ouverte par le premier « a », le second « p » doit se lire : fermeture tenue, la forme
        // ouverte effacée — sur ce modèle, toute la bouche revient au repos.
        val opened = samples.indexOfFirst { (it.values["vrc.v_aa"] ?: 0f) > 0.5f }
        assertTrue(opened > -1)
        assertTrue(samples.drop(opened).any { it.pp > 0.6f && it.values.sum() < 0.35f })
    }

    @Test fun `et la voyelle d'après s'ouvre franchement - la fermeture passe le relais, elle ne traîne pas`() {
        val firstA = play(LipSync(mika), "papa").filter { it.offset == 1 }
        assertTrue(firstA.any { (it.values["vrc.v_aa"] ?: 0f) > 0.72f && it.pp < 0.2f })
    }

    @Test fun `elle anticipe - les lèvres commencent à se fermer pour le « p » avant la fin du « a »`() {
        val firstA = play(LipSync(mika), "papa").filter { it.offset == 1 }
        assertTrue(firstA.size > 3)
        val lowest = firstA.minOf { it.pp }
        assertTrue(firstA.last().pp > lowest + 0.1f)
    }

    @Test fun `les visèmes ne dépassent jamais une bouche`() {
        for (s in play(LipSync(mika), "oiseau, champagne, beaucoup !")) assertTrue(s.values.sum() <= 1f + 1e-6f)
    }

    @Test fun `ce qu'une expression fait à la bouche - une ouverture compte plein, une forme à 40 %`() {
        fun inv(vararg binds: Pair<String, Float>) = LipSync.mouthInvolvement(binds.map { VrmDocument.Bind(it.first, it.second) })
        assertEquals(1f, inv("MouthOpen4" to 1f), 1e-6f)
        assertEquals(0.5f, inv("jawOpen" to 0.5f), 1e-6f)
        assertEquals(0.4f, inv("MouthSmile2" to 1f), 1e-6f)
        assertEquals(0.829f, inv("あ" to 0.829f), 1e-6f)
        assertEquals(1f, inv("MouthSmile2" to 1f, "MouthBigOpen" to 1f), 1e-6f) // le plus fort lien compte
        assertEquals(0f, inv("Blink" to 1f, "EyeWideLeft" to 1f, "FaceRed" to 1f), 0f)
    }

    @Test fun `elle laisse la place à une émotion qui ouvre déjà la bouche`() {
        val free = play(LipSync(mika), "papa").maxOf { it.values.sum() }
        val shocked = play(LipSync(mika), "papa", load = 1f).maxOf { it.values.sum() }
        assertTrue(free > 0.8f)
        // Une bouche grande ouverte laisse à la parole son plancher, pas plus.
        assertTrue(shocked <= LipSync.MIN_VISEME_ALLOWANCE + 1e-6f)
        assertTrue(shocked > 0.3f)
        // Un sourire n'est pas une ouverture : il coûte bien moins à la parole.
        assertTrue(play(LipSync(mika), "papa", load = 0.4f).maxOf { it.values.sum() } > 0.8f)
    }

    @Test fun `une articulation plus basse ouvre moins mais garde les fermetures`() {
        val full = play(LipSync(mika), "papa")
        val tiredLip = LipSync(mika)
        tiredLip.setArticulation(0.6f)
        val tired = play(tiredLip, "papa")
        assertTrue(tired.peak("vrc.v_aa") < full.peak("vrc.v_aa") * 0.7f)
        assertTrue(tired.maxOf { it.pp } > full.maxOf { it.pp } * 0.85f)
        // N'importe quoi → articulation normale (deux décimales : la reprise part de la traîne du relâchement).
        tiredLip.setArticulation(Float.NaN)
        assertEquals(full.peak("vrc.v_aa"), play(tiredLip, "papa").peak("vrc.v_aa"), 0.01f)
    }

    @Test fun `sans visèmes, elle se replie sur les cinq préréglages VRM`() {
        val lip = LipSync(setOf("Blink", "MouthSmile2"))
        assertEquals("presets", lip.outputMode)
        assertEquals(LipSync.MOUTH_PRESETS.toSet(), lip.outputNames.toSet())
        val samples = play(lip, "bonjour Mika")
        assertTrue(samples.peak("oh") > 0.3f) // « on »
        assertTrue(samples.peak("ou") > 0.3f) // « ou »
        assertTrue(samples.peak("ih") > 0.3f) // « i »
        assertTrue(samples.peak("aa") > 0.3f) // « a »
        // Puis la bouche revient au repos.
        lip.stop()
        repeat(120) { lip.update(STEP) }
        for ((name, w) in lip.outputs()) assertTrue("$name = $w", w < 0.01f)
    }

    @Test fun `un jeu de visèmes incomplet est complété par les préréglages, visème par visème`() {
        val lip = LipSync(setOf("vrc.v_aa", "vrc.v_oh"))
        assertEquals("mixed", lip.outputMode)
        val samples = play(lip, "papa oui")
        assertTrue(samples.peak("vrc.v_aa") > 0.6f)
        assertTrue(samples.peak("aa") < 0.35f) // le « a » va au visème, seules les consonnes débordent ici
        assertTrue(samples.peak("ou") > 0.3f) // « ou » n'a pas de visème sur ce modèle
    }

    // --- Le suivi d'un affichage, image par image (propre à l'app) ---

    private class Reading(val outputs: List<Map<String, Float>>, val ends: Double, val resyncs: Int)

    /** Lit `text` à `fps` images par seconde ; `cursor(lip, elapsedMs)` rend le curseur de l'image, ou null. */
    private fun read(
        text: String,
        msPerChar: Double,
        fps: Int = 60,
        extraMs: Double = 1500.0,
        cursor: ((LipSync, Double) -> Int?)? = null,
    ): Reading {
        val lip = LipSync(mika)
        lip.startFromPlan(LipSync.speechPlan(text), msPerChar)
        val dt = 1f / fps
        val outputs = ArrayList<Map<String, Float>>()
        var elapsed = 0.0
        var ends = -1.0
        val frames = ((text.length * msPerChar + extraMs) / (1000.0 / fps)).toInt()
        repeat(frames) {
            cursor?.invoke(lip, elapsed)?.let { lip.trackChar(it) }
            lip.update(dt)
            elapsed += 1000.0 / fps
            outputs += lip.outputs()
            if (ends < 0 && !lip.isSpeaking) ends = elapsed
        }
        return Reading(outputs, ends, lip.resyncs)
    }

    /** Articulations visibles : combien de fois la forme dominante d'une bouche ouverte change. Un plan remis à zéro
     * à chaque image en ferait davantage (la même syllabe reprise), un plan qui saute moins (des syllabes avalées). */
    private fun articulations(outputs: List<Map<String, Float>>): Int {
        var count = 0
        var last: String? = null
        for (o in outputs) {
            if (o.values.sum() < 0.15f) continue
            val dominant = o.maxBy { it.value }.key
            if (dominant != last) count++
            last = dominant
        }
        return count
    }

    @Test fun `recaler chaque image là où le plan serait de toute façon donne exactement la même lecture`() {
        for (text in TEXTS) {
            val free = LipSync(mika)
            val tracked = LipSync(mika)
            free.startFromPlan(LipSync.speechPlan(text), 40.0)
            tracked.startFromPlan(LipSync.speechPlan(text), 40.0)
            var k = 0
            while (free.isSpeaking) {
                // Le curseur de cette image : le caractère que le plan libre articule (hors silences de prosodie).
                val c = free.currentCharOffset
                if (c >= 0) assertTrue(tracked.trackChar(c))
                free.update(STEP_60)
                tracked.update(STEP_60)
                val a = free.outputs()
                val b = tracked.outputs()
                for (name in a.keys) assertEquals("$text, image $k, $name", a.getValue(name), b.getValue(name), 0f)
                assertEquals(free.levelOf(Viseme.PP), tracked.levelOf(Viseme.PP), 0f)
                assertEquals(free.currentCharOffset, tracked.currentCharOffset)
                k++
            }
            assertFalse(tracked.isSpeaking)
            assertEquals(0, tracked.resyncs)
        }
    }

    @Test fun `un curseur d'affichage régulier (temps × cadence), de 0 à 2 caractères par image, se lit sans heurt`() {
        for (text in TEXTS) for ((cps, fps) in listOf(15.0 to 60, 25.0 to 60, 40.0 to 60, 40.0 to 30, 40.0 to 20)) {
            val ms = 1000.0 / cps
            val free = read(text, ms, fps)
            val tracked = read(text, ms, fps) { _, elapsed -> floor(elapsed / ms).toInt() }
            val label = "$cps car/s à $fps i/s : $text"
            // Ni saut, ni attente, ni silence forcé : la lecture suit le texte d'elle-même.
            assertEquals(label, 0, tracked.resyncs)
            // Ni hoquet ni syllabe avalée : autant d'articulations que la lecture libre. Un nombre fait exception dans
            // un sens : l'affichage montre « 2026 » en quatre caractères quand la bouche doit dire « deux mille
            // vingt-six » — elle se presse pour ne pas perdre le texte, et quelques formes brèves y passent.
            val shapesFree = articulations(free.outputs)
            val shapesTracked = articulations(tracked.outputs)
            val margin = 2 + shapesFree / 10
            assertTrue("$label : $shapesTracked formes pour $shapesFree", shapesTracked <= shapesFree + margin)
            if (text.none { it.isDigit() }) {
                assertTrue("$label : $shapesTracked formes pour $shapesFree", shapesTracked >= shapesFree - margin)
            }
            // La même bouche, au glissement près : le plan libre s'écarte du texte de quelques caractères (un « x » se
            // dit en deux phonèmes, un « eau » en un), le suivi l'y ramène — c'est ce décalage, et lui seul, qui les
            // distingue.
            var diff = 0.0
            var n = 0
            for (k in free.outputs.indices) for ((name, v) in free.outputs[k]) {
                diff += abs(v - (tracked.outputs[k][name] ?: 0f))
                n++
            }
            assertTrue("$label : écart moyen ${diff / n}", diff / n < 0.08)
            // Et elle finit avec le texte (à quelques caractères près), même quand le plan libre s'en écartait.
            val textEnd = text.length * ms
            assertTrue("$label : fin ${tracked.ends} pour $textEnd", abs(tracked.ends - textEnd) <= 6 * ms + 1000.0 / fps)
        }
    }

    @Test fun `un curseur qui va deux fois plus vite que le plan est rattrapé sans saut`() {
        val text = TEXTS[0]
        val ms = 60.0
        // Le plan croit à 60 ms par caractère, le texte s'affiche à 30.
        val r = read(text, ms) { _, elapsed -> floor(elapsed / (ms / 2)).toInt() }
        assertEquals(0, r.resyncs)
        val textEnd = text.length * ms / 2
        assertTrue("fin ${r.ends} pour $textEnd", r.ends < textEnd + 12 * ms)
        val shapesFree = articulations(read(text, ms).outputs)
        val shapes = articulations(r.outputs)
        assertTrue("$shapes formes pour $shapesFree", abs(shapes - shapesFree) <= 2 + shapesFree / 10)
    }

    @Test fun `tout afficher d'un coup referme la bouche proprement`() {
        val text = TEXTS[0]
        val ms = 40.0
        val lip = LipSync(mika)
        lip.startFromPlan(LipSync.speechPlan(text), ms)
        var elapsed = 0.0
        // Un peu plus d'une seconde de lecture suivie, puis la bulle est touchée : le curseur passe à la fin.
        var opened = 0f
        while (elapsed < 1100.0 || lip.outputs().sum() < 0.3f) {
            lip.trackChar(floor(elapsed / ms).toInt())
            lip.update(STEP_60)
            elapsed += 1000.0 / 60
            opened = lip.outputs().sum()
        }
        assertTrue(opened >= 0.3f)
        var previous = lip.outputs()
        var t = 0.0
        while (t < 0.6) {
            lip.trackChar(text.length)
            lip.update(STEP_60)
            t += 1.0 / 60
            assertFalse(lip.isSpeaking)
            val now = lip.outputs()
            // Aucune forme nouvelle, aucune qui remonte : la bouche ne fait que se détendre.
            for ((name, v) in now) assertTrue("$name remonte : $v", v <= (previous[name] ?: 0f) + 1e-6f)
            previous = now
        }
        assertTrue(previous.sum() < 0.01f)
        assertEquals(1, lip.resyncs)
    }

    @Test fun `un saut en avant au milieu du texte y emmène la bouche`() {
        val text = TEXTS[0]
        val lip = LipSync(mika)
        lip.startFromPlan(LipSync.speechPlan(text), 40.0)
        repeat(10) {
            lip.trackChar(it / 2)
            lip.update(STEP_60)
        }
        val target = text.indexOf("beaucoup")
        lip.trackChar(target)
        assertEquals(target, lip.currentCharOffset)
        assertEquals(1, lip.resyncs)
        assertTrue(lip.isSpeaking)
    }

    @Test fun `un curseur qui revient en arrière ranime un plan fini`() {
        val text = TEXTS[0]
        val lip = LipSync(mika)
        lip.startFromPlan(LipSync.speechPlan(text), 40.0)
        lip.update(30f)
        assertFalse(lip.isSpeaking)
        lip.trackChar(text.length) // tout est affiché : rien à faire
        assertFalse(lip.isSpeaking)
        lip.trackChar(2)
        assertTrue(lip.isSpeaking)
        assertEquals(1, lip.currentCharOffset) // « Bonjour » : le « n » muet appartient au « on », ancré sur le « o »
    }

    @Test fun `un texte qui cale - la bouche l'attend fermée, puis reprend où elle en était`() {
        val text = TEXTS[0]
        val ms = 40.0
        val lip = LipSync(mika)
        lip.startFromPlan(LipSync.speechPlan(text), ms)
        // Le texte s'affiche normalement 0,5 s, puis cale 1,5 s sur le même caractère.
        var elapsed = 0.0
        while (elapsed < 500.0) {
            lip.trackChar(floor(elapsed / ms).toInt())
            lip.update(STEP_60)
            elapsed += 1000.0 / 60
        }
        val stalledAt = floor(elapsed / ms).toInt()
        var t = 0.0
        var lastOffset = -1
        while (t < 1500.0) {
            lip.trackChar(stalledAt)
            lip.update(STEP_60)
            t += 1000.0 / 60
            lastOffset = maxOf(lastOffset, lip.currentCharOffset)
        }
        // Elle n'a pas filé seule jusqu'à la fin de la phrase, ni bégayé en arrière : elle attend, bouche détendue.
        assertTrue("devance de ${lastOffset - stalledAt}", lastOffset - stalledAt <= LipSync.HOLD_CHARS + 6)
        assertTrue(lip.outputs().sum() < 0.02f)
        assertTrue(lip.isSpeaking)
        assertEquals(1, lip.resyncs)
        val waitingAt = lip.currentCharOffset
        // Le texte repart : elle reprend, sans revenir en arrière.
        var reopened = 0f
        while (elapsed < 2500.0) {
            lip.trackChar(stalledAt + floor((elapsed - 500.0) / ms).toInt())
            lip.update(STEP_60)
            elapsed += 1000.0 / 60
            assertTrue(lip.currentCharOffset < 0 || lip.currentCharOffset >= waitingAt)
            reopened = maxOf(reopened, lip.outputs().sum())
        }
        assertTrue(reopened > 0.5f)
        assertEquals(1, lip.resyncs)
    }

    @Test fun `stop - la bouche se referme en douceur, pas d'un coup`() {
        val lip = LipSync(mika)
        lip.startFromPlan(speech("aaaa"), 60.0)
        repeat(12) { lip.update(STEP) }
        val open = lip.outputs().getValue("vrc.v_aa")
        assertTrue(open > 0.5f)
        lip.stop()
        lip.update(1f / 60)
        val after = lip.outputs().getValue("vrc.v_aa")
        assertTrue("$open → $after", after > open * 0.6f && after < open)
        repeat(60) { lip.update(1f / 60) }
        assertTrue(lip.outputs().getValue("vrc.v_aa") < 0.01f)
    }

    companion object {
        const val STEP = 1f / 120
        const val STEP_60 = 1f / 60
        val TEXTS = listOf(
            "Bonjour ! Je suis contente de te voir, tu sais. Aujourd'hui j'ai beaucoup réfléchi à ce que tu m'as dit hier soir.",
            "Les oiseaux chantaient dans le jardin, et moi je regardais les nuages passer au-dessus des toits.",
            "Ils mangent des pommes et des poires depuis 2026, c'est fou non ? Eau, beaux, chevaux, travaux.",
            "Hmm... [SIGH] je ne sais pas trop. *Peut-être* qu'on pourrait essayer autre chose demain, qu'en penses-tu ?",
            "Taxi, examen, exprès, extraordinaire, explosion : beaucoup de x et de k à prononcer vite.",
        )
    }
}
