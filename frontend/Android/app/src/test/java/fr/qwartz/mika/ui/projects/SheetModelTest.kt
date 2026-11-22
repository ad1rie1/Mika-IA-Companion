package fr.qwartz.mika.ui.projects

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.projects.ActivityPage
import fr.qwartz.mika.data.moi.projects.ActivityTabs
import fr.qwartz.mika.data.moi.projects.ActivityTotals
import fr.qwartz.mika.data.moi.projects.Archived
import fr.qwartz.mika.data.moi.projects.Archives
import fr.qwartz.mika.data.moi.projects.Coded
import fr.qwartz.mika.data.moi.projects.DocCan
import fr.qwartz.mika.data.moi.projects.DocFound
import fr.qwartz.mika.data.moi.projects.DocImage
import fr.qwartz.mika.data.moi.projects.DocPage
import fr.qwartz.mika.data.moi.projects.DocSave
import fr.qwartz.mika.data.moi.projects.DocSpace
import fr.qwartz.mika.data.moi.projects.DocTabs
import fr.qwartz.mika.data.moi.projects.DocUpload
import fr.qwartz.mika.data.moi.projects.DocVersion
import fr.qwartz.mika.data.moi.projects.Draft
import fr.qwartz.mika.data.moi.projects.Edit
import fr.qwartz.mika.data.moi.projects.Entry
import fr.qwartz.mika.data.moi.projects.EntryDetail
import fr.qwartz.mika.data.moi.projects.EntryMore
import fr.qwartz.mika.data.moi.projects.EntryPage
import fr.qwartz.mika.data.moi.projects.GestureDone
import fr.qwartz.mika.data.moi.projects.Happening
import fr.qwartz.mika.data.moi.projects.MERGE_ROUTE
import fr.qwartz.mika.data.moi.projects.MdEdit
import fr.qwartz.mika.data.moi.projects.NEW_PAGE_WORD
import fr.qwartz.mika.data.moi.projects.NotebookNote
import fr.qwartz.mika.data.moi.projects.NotebookPage
import fr.qwartz.mika.data.moi.projects.PageSaved
import fr.qwartz.mika.data.moi.projects.ProjectSettings
import fr.qwartz.mika.data.moi.projects.Run
import fr.qwartz.mika.data.moi.projects.RunPage
import fr.qwartz.mika.data.moi.projects.SettingField
import fr.qwartz.mika.data.moi.projects.SettingsSection
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import okhttp3.RequestBody.Companion.toRequestBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Les modèles des onglets Documentation, Activité et Listes et de « Modifier le projet », contre une fausse API :
 * **l'éditeur d'une page** — enregistrer nomme la version lue ; un conflit se dit avec les mots du serveur **sans rien
 * perdre de ce qui est écrit** ; on reprend sur la version actuelle, ou on la prend ; un double appui ne part qu'une
 * fois, un réessai après une coupure ne refait rien ; le brouillon survit à la réouverture de l'écran — ; revenir à une
 * version nomme la version lue ; le fil et sa suite ; les gestes d'une liste ; un réglage n'envoie que ce qui change ;
 * et aucun de ces gestes ne part vers la fusion.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class SheetModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val api = FakeProjectsApi()
    private val deps = ProjectsDeps(api, {}, { 1_795_600_000_000L }, Dispatchers.Unconfined)
    private val path = "guide/installation.md"
    private val moved = "Cette page a changé depuis ta lecture : elle en est à la version 6, écrite par elle."

    private fun page(version: Int, text: String) = DocPage(path = path, version = version, text = text, can = DocCan(write = true))

    private fun editor(at: String = path) = main.model { DocEditViewModel(deps, 3, at) }

    private fun text(name: String, i: Int = api.sent.lastIndex) = (api.sent[i].second.body[name] as? JsonPrimitive)?.content

    // ── L'éditeur ──

    @Test fun `enregistrer nomme la version lue, et la version rendue devient la version lue`() = runTest {
        api.docPage = MoiApi.Result.Ok(page(4, "A"))
        val vm = editor()
        vm.open()
        advanceUntilIdle()
        assertTrue(vm.load is Load.Ready)
        assertEquals(Edit("A", 1), vm.edit)
        assertFalse(vm.dirty)
        vm.type(Edit("A plus", 6))
        assertTrue(vm.dirty)
        vm.save("  Note pour Windows ")
        advanceUntilIdle()
        assertEquals(DocSave(path, "A plus", "Note pour Windows", 4), api.saves.single().second)
        assertEquals(3, api.saves.single().first)
        assertEquals(5, vm.draft?.base)
        assertFalse(vm.dirty)
        assertTrue(vm.justSaved)
        assertEquals(1, vm.saved)
        vm.savedSeen()
        assertFalse(vm.justSaved)
        // la suite part de la version qu'on vient d'écrire
        vm.type(Edit("A plus encore", 13))
        vm.save("")
        advanceUntilIdle()
        assertEquals(5, api.saves.last().second.base)
    }

    @Test fun `un conflit se dit avec les mots du serveur sans perdre le texte - puis on reprend sur la version actuelle`() = runTest {
        api.docPage = MoiApi.Result.Ok(page(4, "A"))
        val vm = editor()
        vm.open()
        advanceUntilIdle()
        vm.type(Edit("mon texte", 9))
        // quelqu'un l'a écrite entre-temps : le serveur refuse, et la page relue n'en est plus à la version lue
        api.docPage = MoiApi.Result.Ok(page(6, "le sien"))
        api.saveResult = MoiApi.Result.Failed(MoiError(409, moved))
        vm.save("")
        advanceUntilIdle()
        // refusé : ses mots, tels quels ; le texte, la version lue et la sélection n'ont pas bougé
        assertEquals(moved, vm.draft?.refusal)
        assertTrue(vm.draft?.conflict == true)
        assertEquals(6, vm.current?.version)
        assertEquals(Edit("mon texte", 9), vm.edit)
        assertEquals(4, vm.draft?.base)
        assertTrue(vm.dirty)
        assertFalse(vm.justSaved)
        // on continue d'écrire : le refus reste dit
        vm.type(Edit("mon texte !", 11))
        assertEquals(moved, vm.draft?.refusal)
        // reprendre : la page se relit, sa version devient le départ, le texte tapé reste entier
        api.docPage = MoiApi.Result.Ok(page(6, "le sien"))
        vm.rebase()
        advanceUntilIdle()
        assertEquals(6, vm.draft?.base)
        assertEquals("mon texte !", vm.edit.text)
        assertEquals("", vm.draft?.refusal)
        assertEquals(6, vm.current?.version)
        assertTrue(vm.dirty)
        api.saveResult = null
        vm.save("je garde le mien")
        advanceUntilIdle()
        assertEquals(DocSave(path, "mon texte !", "je garde le mien", 6), api.saves.last().second)
        assertEquals(7, vm.draft?.base)
        assertFalse(vm.dirty)
    }

    @Test fun `après un conflit, prendre la version actuelle remplace ce qui est écrit - seulement si on le demande`() = runTest {
        api.docPage = MoiApi.Result.Ok(page(4, "A"))
        val vm = editor()
        vm.open()
        advanceUntilIdle()
        vm.type(Edit("mon texte", 9))
        api.docPage = MoiApi.Result.Ok(page(6, "le sien"))
        api.saveResult = MoiApi.Result.Failed(MoiError(409, moved))
        vm.save("")
        advanceUntilIdle()
        vm.readCurrent()
        advanceUntilIdle()
        // la relire ne change rien à ce qui est écrit
        assertEquals("le sien", vm.current?.text)
        assertEquals("mon texte", vm.edit.text)
        assertEquals(4, vm.draft?.base)
        vm.takeCurrent()
        assertEquals("le sien", vm.edit.text)
        assertEquals(6, vm.draft?.base)
        assertFalse(vm.dirty)
        assertNull(vm.current)
    }

    @Test fun `un double appui ne part qu'une fois, un réessai après une coupure ne refait rien, un refus du serveur change de clé`() = runTest {
        api.docPage = MoiApi.Result.Ok(page(4, "A"))
        val vm = editor()
        vm.open()
        advanceUntilIdle()
        vm.type(Edit("B", 1))
        api.hold("saveDoc:$path")
        vm.save("")
        vm.save("")
        assertTrue(vm.saving)
        assertEquals(1, api.saves.size)
        // ce qui est tapé pendant l'envoi reste à enregistrer
        vm.type(Edit("B et la suite", 13))
        api.release("saveDoc:$path")
        advanceUntilIdle()
        assertFalse(vm.saving)
        assertEquals(5, vm.draft?.base)
        assertTrue(vm.dirty)
        // une coupure : rien n'est perdu, et le même envoi redit garde sa clé
        api.saveResult = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        vm.save("")
        advanceUntilIdle()
        assertEquals(MoiError.NETWORK, vm.draft?.refusal)
        assertFalse(vm.draft?.conflict == true)
        assertEquals("B et la suite", vm.edit.text)
        api.saveResult = MoiApi.Result.Failed(MoiError(409, moved))
        vm.save("")
        advanceUntilIdle()
        assertEquals(api.saves[1].third, api.saves[2].third)
        // le serveur a répondu (il a refusé) : l'envoi d'après a sa propre clé
        api.saveResult = null
        vm.save("")
        advanceUntilIdle()
        assertNotEquals(api.saves[2].third, api.saves[3].third)
    }

    @Test fun `la redite d'un enregistrement arrivé revient reconnue par le serveur - ni conflit, ni version de plus`() = runTest {
        api.docPage = MoiApi.Result.Ok(page(4, "A"))
        val vm = editor()
        vm.open()
        advanceUntilIdle()
        vm.type(Edit("B", 1))
        // la réponse s'est perdue en route : l'enregistrement, lui, est arrivé (la page en est à la version 5)
        api.saveResult = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        vm.save("mot")
        advanceUntilIdle()
        assertTrue(vm.dirty)
        // le même envoi, redit sous la même clé : le serveur le reconnaît (`deduped`) et rend la version déjà écrite
        api.docPage = MoiApi.Result.Ok(page(5, "B"))
        api.saveResult = MoiApi.Result.Ok(PageSaved(ok = true, message = "Déjà enregistré.", path = path, version = 5, deduped = true))
        vm.save("mot")
        advanceUntilIdle()
        assertEquals(api.saves[0].third, api.saves[1].third)
        assertEquals(4, api.saves[1].second.base)
        assertEquals(5, vm.draft?.base)
        assertFalse(vm.dirty)
        assertEquals("", vm.draft?.refusal)
        assertFalse(vm.draft?.conflict == true)
        assertNull(vm.current)
        assertTrue(vm.justSaved)
    }

    @Test fun `une page nouvelle se crée à la validation - son chemin refusé se dit dans la feuille, avant qu'on ait rien écrit`() = runTest {
        val docs = main.model { DocsViewModel(deps, 3) }
        docs.show(DocTabs.PAGES)
        advanceUntilIdle()
        // le serveur juge le chemin : son refus, avec ses mots et sous son champ, là où l'on a demandé la page
        val bad = "Un chemin de page est relatif à l'espace et finit par « .md »."
        api.saveResult = MoiApi.Result.Failed(MoiError(400, bad, mapOf("path" to "un chemin de page, relatif, en « .md »")))
        assertTrue(docs.create("guide/depannage.md", " Dépannage "))
        advanceUntilIdle()
        assertEquals(DocSave("guide/depannage.md", "# Dépannage\n\n", NEW_PAGE_WORD, 0), api.saves.single().second)
        assertEquals("", docs.created)
        assertTrue(bad in docs.gestures.refusalAt(DocsViewModel.NEW))
        assertEquals("un chemin de page, relatif, en « .md »", docs.gestures.fieldsAt(DocsViewModel.NEW)["path"])
        // acceptée : elle existe, l'espace se relit, et elle s'ouvre en écriture — une fois
        api.saveResult = null
        docs.create("guide/depannage.md", "Dépannage")
        advanceUntilIdle()
        assertEquals("guide/depannage.md", docs.created)
        assertEquals(DocsViewModel.NEW, docs.gestures.finished)
        assertEquals(3, api.calls.count { it == "docs:3" })
        docs.createdSeen()
        assertEquals("", docs.created)
        // l'onglet quitté avant la réponse : la page est créée, mais rien ne s'ouvre à son retour
        api.hold("saveDoc:autre.md")
        docs.create("autre.md", "Autre")
        advanceUntilIdle()
        docs.leave()
        api.release("saveDoc:autre.md")
        advanceUntilIdle()
        assertEquals("", docs.created)
        docs.resume()
        advanceUntilIdle()
        assertEquals("", docs.created)
    }

    @Test fun `le brouillon survit à la réouverture de l'écran, et une page sans rien en attente se relit`() = runTest {
        api.docPage = MoiApi.Result.Ok(page(1, "# Dépannage"))
        val vm = editor()
        vm.open()
        advanceUntilIdle()
        vm.type(Edit("# Dépannage\n\nUn mot.", 20))
        // l'écran renaît (une rotation, un aller-retour) : ce qui est écrit est toujours là, rien n'est relu par-dessus
        vm.open()
        advanceUntilIdle()
        assertEquals("# Dépannage\n\nUn mot.", vm.edit.text)
        vm.save("")
        advanceUntilIdle()
        assertEquals(1, api.saves.single().second.base)
        assertEquals(2, vm.draft?.base)
        // plus rien en attente : rouvrir l'écran relit la page, qui a pu changer
        api.docPage = MoiApi.Result.Ok(page(3, "relu"))
        vm.open()
        advanceUntilIdle()
        assertEquals("relu", vm.edit.text)
        assertEquals(3, vm.draft?.base)
    }

    @Test fun `une page supprimée puis recréée sous le même chemin ne ressort pas l'ancien brouillon`() = runTest {
        api.docPage = MoiApi.Result.Ok(page(1, "ancien").copy(createdAt = 100))
        val vm = editor()
        vm.open()
        advanceUntilIdle()
        vm.type(Edit("ancien, et ce que j'avais commencé", 6))
        assertTrue(vm.dirty)
        // la page est supprimée, puis recréée sous le même chemin : c'est une autre page, à sa version 1 elle aussi
        api.docPage = MoiApi.Result.Ok(page(1, "# Nouvelle").copy(createdAt = 200))
        vm.open()
        advanceUntilIdle()
        assertEquals("# Nouvelle", vm.edit.text)
        assertFalse(vm.dirty)
        assertEquals(1, vm.draft?.base)
        // supprimée sans être recréée, rien d'écrit en attente : son ancien texte ne ressort pas, l'éditeur dit qu'elle n'est plus là
        val gone = "Aucune page « $path » dans la documentation de ce projet."
        api.docPage = MoiApi.Result.Failed(MoiError(404, gone))
        vm.open()
        advanceUntilIdle()
        assertNull(vm.draft)
        assertEquals(gone, (vm.load as Load.Failed).error.message)
        vm.save("")
        assertTrue(api.saves.isEmpty())
        // avec un texte en attente, il reste — et les mots du serveur se disent, sans conflit à reprendre
        api.docPage = MoiApi.Result.Ok(page(2, "B"))
        val other = editor("autre.md")
        other.open()
        advanceUntilIdle()
        other.type(Edit("B, que je garde", 1))
        api.docPage = MoiApi.Result.Failed(MoiError(404, gone))
        other.open()
        advanceUntilIdle()
        assertEquals("B, que je garde", other.edit.text)
        assertEquals(gone, other.draft?.refusal)
        assertFalse(other.draft?.conflict == true)
        // une coupure, elle, ne dit rien et ne touche à rien
        api.docPage = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        other.type(Edit("B, que je garde encore", 1))
        other.open()
        advanceUntilIdle()
        assertEquals("B, que je garde encore", other.edit.text)
    }

    @Test fun `un 409 n'est un conflit que si la page a bougé - le même texte, une page disparue se disent sans rien à reprendre`() = runTest {
        api.docPage = MoiApi.Result.Ok(page(4, "A"))
        val vm = editor()
        vm.open()
        advanceUntilIdle()
        vm.type(Edit("A ", 2))
        // le même texte (le serveur coupe les blancs de fin) : 409, mais la page en est toujours à la version lue
        val same = "Ce texte est déjà celui de la page : rien n'a été enregistré."
        api.saveResult = MoiApi.Result.Failed(MoiError(409, same))
        vm.save("")
        advanceUntilIdle()
        assertEquals(same, vm.draft?.refusal)
        assertFalse(vm.draft?.conflict == true)
        assertNull(vm.current)
        assertFalse(vm.saving)
        assertEquals("A ", vm.edit.text)
        // la page a disparu : 409 à l'enregistrement, introuvable à la relecture — pas un conflit non plus
        val gone = "Aucune page « $path » dans la documentation de ce projet."
        api.docPage = MoiApi.Result.Failed(MoiError(404, gone))
        api.saveResult = MoiApi.Result.Failed(MoiError(409, gone))
        vm.save("")
        advanceUntilIdle()
        assertEquals(gone, vm.draft?.refusal)
        assertFalse(vm.draft?.conflict == true)
        assertNull(vm.current)
        // « voir la version actuelle » d'une page qui n'existe plus : les mots de l'erreur, pas une attente sans fin
        vm.readCurrent()
        advanceUntilIdle()
        assertNull(vm.current)
        assertEquals(gone, vm.currentRefusal)
        // elle a bougé : un conflit, et la version actuelle est déjà là pour la feuille
        api.docPage = MoiApi.Result.Ok(page(6, "le sien"))
        api.saveResult = MoiApi.Result.Failed(MoiError(409, moved))
        vm.save("")
        advanceUntilIdle()
        assertEquals(moved, vm.draft?.refusal)
        assertTrue(vm.draft?.conflict == true)
        assertEquals(6, vm.current?.version)
        assertEquals("", vm.currentRefusal)
        // un conflit dont la page disparaît quand on veut reprendre : il n'y a plus rien à reprendre, le texte reste
        api.docPage = MoiApi.Result.Failed(MoiError(404, gone))
        vm.rebase()
        advanceUntilIdle()
        assertFalse(vm.draft?.conflict == true)
        assertEquals(gone, vm.draft?.refusal)
        assertEquals("A ", vm.edit.text)
        // une page nouvelle qui existe déjà : elle a « bougé » aussi (base 0)
        assertTrue(Draft.fresh(path, "x").movedOn(page(1, "déjà là")))
    }

    @Test fun `un conflit dont la relecture est injoignable garde de quoi reprendre - le réseau revenu, on reprend sur la version actuelle`() = runTest {
        api.docPage = MoiApi.Result.Ok(page(4, "A"))
        val vm = editor()
        vm.open()
        advanceUntilIdle()
        vm.type(Edit("mon texte", 9))
        // le serveur refuse (la page a changé), puis le réseau coupe : la page ne se relit pas pour le confirmer
        api.docPage = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        api.saveResult = MoiApi.Result.Failed(MoiError(409, moved))
        vm.save("")
        advanceUntilIdle()
        // ses mots, et de quoi reprendre : on ne sait pas qu'elle n'a pas bougé — rien n'est perdu, rien n'est écrasé
        assertEquals(moved, vm.draft?.refusal)
        assertTrue(vm.draft?.conflict == true)
        assertNull(vm.current)
        assertEquals("mon texte", vm.edit.text)
        assertEquals(4, vm.draft?.base)
        // « Voir la version actuelle », toujours hors ligne : l'erreur se dit, le conflit reste à reprendre
        vm.readCurrent()
        advanceUntilIdle()
        assertEquals(MoiError.NETWORK, vm.currentRefusal)
        assertTrue(vm.draft?.conflict == true)
        // le réseau revient : « Reprendre dessus » relit la page, sa version devient le départ, le texte tapé reste
        api.docPage = MoiApi.Result.Ok(page(6, "le sien"))
        vm.rebase()
        advanceUntilIdle()
        assertFalse(vm.draft?.conflict == true)
        assertEquals(6, vm.draft?.base)
        assertEquals("mon texte", vm.edit.text)
        api.saveResult = null
        vm.save("")
        advanceUntilIdle()
        assertEquals(DocSave(path, "mon texte", "", 6), api.saves.last().second)
    }

    @Test fun `un enregistrement abouti après qu'on a quitté l'éditeur ne le referme pas à son retour`() = runTest {
        api.docPage = MoiApi.Result.Ok(page(4, "A"))
        val vm = editor()
        vm.open()
        advanceUntilIdle()
        vm.type(Edit("B", 1))
        api.hold("saveDoc:$path")
        vm.save("")
        advanceUntilIdle()
        // on quitte l'écran avant la réponse (pas une rotation)
        vm.leave()
        api.release("saveDoc:$path")
        advanceUntilIdle()
        assertEquals(1, vm.saved)
        assertFalse(vm.justSaved)
        api.docPage = MoiApi.Result.Ok(page(5, "B"))
        vm.open()
        advanceUntilIdle()
        assertFalse(vm.justSaved)
        // devant l'écran, l'enregistrement le referme — une fois
        vm.type(Edit("C", 1))
        vm.save("")
        advanceUntilIdle()
        assertTrue(vm.justSaved)
    }

    @Test fun `une page qui ne se lit pas le dit, et réessayer relit`() = runTest {
        api.docPage = MoiApi.Result.Failed(MoiError(403, "Tu lis la documentation de ce projet sans pouvoir l'écrire."))
        val vm = editor()
        vm.open()
        advanceUntilIdle()
        assertEquals(403, (vm.load as Load.Failed).error.code)
        assertNull(vm.draft)
        vm.save("")
        assertTrue(api.saves.isEmpty())
        api.docPage = MoiApi.Result.Ok(page(4, "A"))
        vm.retry()
        advanceUntilIdle()
        assertEquals("A", vm.edit.text)
    }

    @Test fun `la barre d'outils agit sur la sélection, Entrée poursuit une liste, jeter revient au texte lu`() = runTest {
        api.docPage = MoiApi.Result.Ok(page(4, "un mot"))
        val vm = editor()
        vm.open()
        advanceUntilIdle()
        vm.type(Edit("un mot", 3, 6))
        assertFalse(vm.dirty)
        vm.change(MdEdit::bold)
        assertEquals(Edit("un **mot**", 5, 8), vm.edit)
        assertEquals("un **mot**", vm.draft?.text)
        assertTrue(vm.dirty)
        vm.type(Edit("- a", 3))
        vm.type(Edit("- a\n", 4))
        assertEquals(Edit("- a\n- ", 6), vm.edit)
        vm.discard()
        assertEquals("un mot", vm.edit.text)
        assertFalse(vm.dirty)
    }

    @Test fun `une image choisie part au serveur puis se cite au curseur - refusée, elle le dit et le texte ne bouge pas`() = runTest {
        api.docPage = MoiApi.Result.Ok(page(4, "Avant"))
        val vm = editor()
        vm.open()
        advanceUntilIdle()
        val image = DocUpload("photo.jpg", 4) { "JPEG".toRequestBody() }
        vm.upload(image)
        advanceUntilIdle()
        assertEquals(image, api.uploads.single().first)
        // le nom est celui que le serveur a rendu, pas celui du téléphone
        assertEquals("Avant\n\n![schema](images/schema.png)\n", vm.edit.text)
        assertTrue(vm.dirty)
        assertFalse(vm.uploading)
        api.uploadResult = MoiApi.Result.Failed(MoiError(409, "Cette image dépasse 5 Mio."))
        vm.upload(DocUpload("gros.jpg", 9) { "x".toRequestBody() })
        advanceUntilIdle()
        assertEquals("Cette image dépasse 5 Mio.", vm.gestures.refusalAt(DocEditViewModel.IMAGE))
        assertEquals("Avant\n\n![schema](images/schema.png)\n", vm.edit.text)
    }

    // ── Une page, l'onglet ──

    @Test fun `revenir à une version nomme la version lue - déplacer et supprimer se disent à l'écran, un refus sur place`() = runTest {
        api.docPage = MoiApi.Result.Ok(page(5, "A"))
        val vm = main.model { DocPageViewModel(deps, 3, path) }
        vm.resume()
        advanceUntilIdle()
        vm.showVersion(2)
        advanceUntilIdle()
        assertTrue(vm.version is Load.Ready)
        vm.restore(2)
        advanceUntilIdle()
        assertEquals("documentation/page/revenir", api.sent.single().second.route)
        assertEquals(setOf("path", "version", "base"), api.sent.single().second.body.keys)
        assertEquals(2, (api.sent.single().second.body["version"] as JsonPrimitive).intOrNull)
        assertEquals(5, (api.sent.single().second.body["base"] as JsonPrimitive).intOrNull)
        assertNull(vm.version)
        assertEquals(1, vm.revision)
        // la page a changé depuis : le refus du serveur, sur place
        api.refuse(409, moved)
        vm.restore(3)
        advanceUntilIdle()
        assertEquals(moved, vm.gestures.refusalAt(DocPageViewModel.HERE))
        api.gestureResult = null
        vm.move("guide/installer.md")
        advanceUntilIdle()
        assertEquals("documentation/page/deplacer", api.sent.last().second.route)
        assertEquals("guide/installer.md", text("to"))
        assertEquals("guide/installer.md", vm.moved)
        vm.remove()
        advanceUntilIdle()
        assertEquals("documentation/page/supprimer", api.sent.last().second.route)
        assertTrue(vm.removed)
        vm.gone()
        assertFalse(vm.removed)
        assertEquals("", vm.moved)
    }

    @Test fun `une version gardée qu'on a quittée ne revient pas quand sa lecture arrive - ni une version d'avant sur celle qu'on regarde`() = runTest {
        api.docPage = MoiApi.Result.Ok(page(5, "A"))
        val vm = main.model { DocPageViewModel(deps, 3, path) }
        vm.resume()
        advanceUntilIdle()
        // la version 2 tarde ; « Revenir à la page » avant qu'elle arrive
        api.hold("docVersion:3:$path:2")
        vm.showVersion(2)
        assertEquals(Load.Loading, vm.version)
        vm.showVersion(0)
        assertNull(vm.version)
        api.release("docVersion:3:$path:2")
        advanceUntilIdle()
        assertNull(vm.version)
        // la version 2 tarde, la 3 est choisie entre-temps : c'est elle qu'on regarde, la 2 ne passe pas par-dessus
        api.docVersion = MoiApi.Result.Ok(DocVersion(n = 2, text = "la deuxième"))
        api.hold("docVersion:3:$path:2")
        vm.showVersion(2)
        api.docVersion = MoiApi.Result.Ok(DocVersion(n = 3, text = "la troisième"))
        vm.showVersion(3)
        advanceUntilIdle()
        assertEquals(3, vm.version?.valueOrNull?.n)
        api.release("docVersion:3:$path:2")
        advanceUntilIdle()
        assertEquals(3, vm.version?.valueOrNull?.n)
    }

    @Test fun `revenir à une version - sans numéro rien ne part, un refus relit la page, et quittée elle ne suit plus rien`() = runTest {
        api.docPage = MoiApi.Result.Ok(page(5, "A"))
        val vm = main.model { DocPageViewModel(deps, 3, path) }
        vm.resume()
        vm.openHistory()
        advanceUntilIdle()
        // il n'y a pas de version 0 : la fenêtre refermée avant le geste ne fait rien partir
        vm.restore(0)
        advanceUntilIdle()
        assertTrue(api.sent.isEmpty())
        // refusée (la page a changé depuis) : elle et ses versions se relisent
        val reads = api.calls.count { it == "docPage:3:$path" }
        val histories = api.calls.count { it == "docHistory:3:$path" }
        api.refuse(409, moved)
        vm.restore(3)
        advanceUntilIdle()
        assertEquals(3, (api.sent.single().second.body["version"] as JsonPrimitive).intOrNull)
        assertEquals(reads + 1, api.calls.count { it == "docPage:3:$path" })
        assertEquals(histories + 1, api.calls.count { it == "docHistory:3:$path" })
        // quittée avant la réponse d'un déplacement : au retour, l'écran ne part pas tout seul
        api.gestureResult = null
        api.hold("gesture:documentation/page/deplacer")
        vm.move("guide/installer.md")
        advanceUntilIdle()
        vm.leave()
        api.release("gesture:documentation/page/deplacer")
        advanceUntilIdle()
        assertEquals("", vm.moved)
        vm.resume()
        advanceUntilIdle()
        assertEquals("", vm.moved)
        api.hold("gesture:documentation/page/supprimer")
        vm.remove()
        advanceUntilIdle()
        vm.leave()
        api.release("gesture:documentation/page/supprimer")
        advanceUntilIdle()
        assertFalse(vm.removed)
    }

    @Test fun `l'onglet Documentation - chaque volet lit ce qu'il montre, la recherche attend la fin de la frappe, les images`() = runTest {
        api.docs = MoiApi.Result.Ok(DocSpace(pages = listOf(DocPage(path = path)), images = listOf(DocImage(name = "schema.png"))))
        api.docFound = DocFound(q = "pare", items = listOf(DocPage(path = path, excerpt = "le pare-feu")))
        val vm = main.model { DocsViewModel(deps, 3) }
        vm.show(DocTabs.PAGES)
        advanceUntilIdle()
        assertEquals(listOf("docs:3"), api.calls)
        vm.show(DocTabs.DECISIONS)
        advanceUntilIdle()
        assertEquals(listOf("docs:3", "decisions:3"), api.calls)
        vm.search("pa")
        vm.search("pare")
        advanceUntilIdle()
        assertEquals(1, api.calls.count { it.startsWith("docSearch") })
        assertEquals("le pare-feu", vm.found?.valueOrNull?.items?.single()?.excerpt)
        vm.search("")
        assertNull(vm.found)
        vm.fold("guide")
        assertEquals(setOf("guide"), vm.closed)
        vm.fold("guide")
        assertTrue(vm.closed.isEmpty())
        // une image de plus : l'espace se relit ; la retirer est un geste, refusé il se dit sur place
        var named = ""
        vm.upload(DocUpload("photo.jpg", 4) { "JPEG".toRequestBody() }) { named = it }
        advanceUntilIdle()
        assertEquals("schema.png", named)
        assertEquals(2, api.calls.count { it == "docs:3" })
        vm.removeImage("schema.png")
        advanceUntilIdle()
        assertEquals("documentation/image/retirer", api.sent.single().second.route)
        assertEquals("schema.png", text("name"))
        api.refuse(403, "Tu lis la documentation de ce projet sans pouvoir l'écrire.")
        vm.removeImage("schema.png")
        advanceUntilIdle()
        assertEquals("Tu lis la documentation de ce projet sans pouvoir l'écrire.", vm.gestures.refusalAt(DocsViewModel.IMAGES))
    }

    // ── L'activité ──

    @Test fun `le fil - ses filtres le relisent, sa suite s'ajoute sans redire, les exécutions et le carnet à la demande`() = runTest {
        api.activity = ActivityPage(next = 90, items = listOf(Happening(seq = 100), Happening(seq = 95)))
        api.feeds["|0|90"] = ActivityPage(next = 0, items = listOf(Happening(seq = 95), Happening(seq = 80)))
        api.feeds["run|0|0"] = ActivityPage(next = 0, items = listOf(Happening(seq = 100, kind = "run")))
        api.totals = ActivityTotals(total = 39, runs = 10, notes = 6)
        val vm = main.model { ActivityViewModel(deps, 3) }
        vm.show(ActivityTabs.FEED)
        advanceUntilIdle()
        assertEquals(listOf(100L, 95L), vm.items.map { it.seq })
        assertEquals(90L, vm.cursor)
        assertEquals(10, vm.totals.value?.runs)
        // rien d'autre n'est lu tant que son volet n'est pas ouvert
        assertFalse(api.calls.any { it.startsWith("runs") || it.startsWith("notebook") || it.startsWith("days") })
        vm.more()
        advanceUntilIdle()
        assertEquals(listOf(100L, 95L, 80L), vm.items.map { it.seq })
        assertEquals(0L, vm.cursor)
        vm.more()
        advanceUntilIdle()
        assertEquals(1, api.calls.count { it.endsWith(":90") })
        // une sorte : le fil se relit depuis le début ; un objectif : ses totaux aussi
        vm.pickKind("run")
        advanceUntilIdle()
        assertEquals(listOf("run"), vm.items.map { it.kind })
        vm.pickObjective(2)
        advanceUntilIdle()
        assertTrue("activity:3:run:2:0" in api.calls)
        assertTrue("totals:3:2" in api.calls)
        // les exécutions et leur suite
        api.runPages[0] = RunPage(total = 3, next = 50, items = listOf(Run(id = "ep-3"), Run(id = "ep-2")))
        api.runPages[50] = RunPage(total = 3, next = 0, items = listOf(Run(id = "ep-2"), Run(id = "ep-1")))
        vm.show(ActivityTabs.RUNS)
        advanceUntilIdle()
        assertEquals(50L, vm.runsCursor)
        vm.moreRuns()
        advanceUntilIdle()
        assertEquals(listOf("ep-3", "ep-2", "ep-1"), vm.allRuns.map { it.id })
        // le carnet, par objectif
        api.notebooks["0|0"] = NotebookPage(total = 2, items = listOf(NotebookNote(seq = 9), NotebookNote(seq = 8)))
        api.notebooks["2|0"] = NotebookPage(total = 1, items = listOf(NotebookNote(seq = 8)))
        vm.show(ActivityTabs.NOTEBOOK)
        advanceUntilIdle()
        assertEquals(2, vm.allNotes.size)
        vm.pickNotebook(2)
        advanceUntilIdle()
        assertEquals(listOf(8L), vm.allNotes.map { it.seq })
    }

    @Test fun `le fil relu garde sa suite chargée - une exécution et son commit, deux lignes d'un même événement`() = runTest {
        val run = Happening(seq = 95, kind = "run", what = "report")
        val commit = Happening(seq = 95, kind = "commit", what = "commit")
        api.activity = ActivityPage(next = 90, items = listOf(Happening(seq = 100), run, commit))
        api.feeds["|0|90"] = ActivityPage(next = 70, items = listOf(Happening(seq = 80), Happening(seq = 75)))
        val vm = main.model { ActivityViewModel(deps, 3) }
        vm.show(ActivityTabs.FEED)
        advanceUntilIdle()
        vm.more()
        advanceUntilIdle()
        assertEquals(listOf(100L, 95L, 95L, 80L, 75L), vm.items.map { it.seq })
        // l'écran revient devant : la première page se relit, la suite déjà chargée reste, son curseur aussi
        vm.resume()
        advanceUntilIdle()
        assertEquals(listOf(100L, 95L, 95L, 80L, 75L), vm.items.map { it.seq })
        assertEquals(70L, vm.cursor)
        // un événement de plus en tête : rien ne se perd ni ne se redit
        api.activity = ActivityPage(next = 95, items = listOf(Happening(seq = 110), Happening(seq = 100), run))
        vm.resume()
        advanceUntilIdle()
        assertEquals(listOf(110L, 100L, 95L, 95L, 80L, 75L), vm.items.map { it.seq })
        assertEquals(70L, vm.cursor)
        // la page relue ne rejoint plus ce qu'on avait (il manquerait des lignes) : la suite repart d'elle
        api.activity = ActivityPage(next = 190, items = listOf(Happening(seq = 200), Happening(seq = 195)))
        vm.resume()
        advanceUntilIdle()
        assertEquals(listOf(200L, 195L), vm.items.map { it.seq })
        assertEquals(190L, vm.cursor)
        // une suite demandée sous un filtre, arrivée après qu'on en a changé, ne s'ajoute pas
        api.feeds["|0|190"] = ActivityPage(next = 0, items = listOf(Happening(seq = 150)))
        api.feeds["run|0|0"] = ActivityPage(next = 0, items = listOf(Happening(seq = 200, kind = "run")))
        api.hold("activity:3::0:0:190")
        vm.more()
        advanceUntilIdle()
        vm.pickKind("run")
        advanceUntilIdle()
        api.release("activity:3::0:0:190")
        advanceUntilIdle()
        assertEquals(listOf(200L), vm.items.map { it.seq })
        assertEquals(listOf("run"), vm.items.map { it.kind })
    }

    @Test fun `les exécutions et le carnet - réessayer pose le curseur, un retour garde la suite, une suite tardive ne s'ajoute pas`() = runTest {
        val vm = main.model { ActivityViewModel(deps, 3) }
        // les exécutions : lues une première fois sans rien (une panne vue du test : une page vide), puis réessayées
        vm.show(ActivityTabs.RUNS)
        advanceUntilIdle()
        assertEquals(0L, vm.runsCursor)
        api.runPages[0] = RunPage(total = 4, next = 50, items = listOf(Run(id = "ep-4"), Run(id = "ep-3")))
        api.runPages[50] = RunPage(total = 4, next = 20, items = listOf(Run(id = "ep-2"), Run(id = "ep-1")))
        vm.runs.retry()
        advanceUntilIdle()
        assertEquals(50L, vm.runsCursor)
        vm.moreRuns()
        advanceUntilIdle()
        assertEquals(listOf("ep-4", "ep-3", "ep-2", "ep-1"), vm.allRuns.map { it.id })
        // un retour sur l'écran : la suite reste
        vm.resume()
        advanceUntilIdle()
        assertEquals(listOf("ep-4", "ep-3", "ep-2", "ep-1"), vm.allRuns.map { it.id })
        assertEquals(20L, vm.runsCursor)
        // le carnet : la suite d'un objectif, arrivée après qu'on en a changé, ne s'ajoute pas
        api.notebooks["0|0"] = NotebookPage(total = 3, next = 8, items = listOf(NotebookNote(seq = 9), NotebookNote(seq = 8)))
        api.notebooks["0|8"] = NotebookPage(total = 3, next = 0, items = listOf(NotebookNote(seq = 7)))
        api.notebooks["2|0"] = NotebookPage(total = 1, items = listOf(NotebookNote(seq = 8)))
        vm.show(ActivityTabs.NOTEBOOK)
        advanceUntilIdle()
        api.hold("notebook:3:0:8")
        vm.moreNotes()
        advanceUntilIdle()
        vm.pickNotebook(2)
        advanceUntilIdle()
        api.release("notebook:3:0:8")
        advanceUntilIdle()
        assertEquals(listOf(8L), vm.allNotes.map { it.seq })
        // revenu à tout le carnet, sa suite chargée reste à un retour sur l'écran
        vm.pickNotebook(0)
        advanceUntilIdle()
        vm.moreNotes()
        advanceUntilIdle()
        vm.resume()
        advanceUntilIdle()
        assertEquals(listOf(9L, 8L, 7L), vm.allNotes.map { it.seq })
    }

    // ── Les listes ──

    @Test fun `une liste - ses éléments, changer un statut, à qui il est, en ajouter un - un refus se dit en tête de la liste`() = runTest {
        val e = Entry(list = "entreprises", key = "atelier-brique", handle = "atelier-brique", status = "a_contacter")
        api.listPages["entreprises"] = EntryPage(list = "entreprises", total = 1, items = listOf(e))
        val vm = main.model { ListsViewModel(deps, 3) }
        vm.show("entreprises")
        vm.show("entreprises")
        advanceUntilIdle()
        assertEquals(1, api.calls.count { it == "list:3:entreprises" })
        assertEquals(listOf(e), vm.pages["entreprises"]?.valueOrNull?.items)
        vm.setStatus(e, "contactee")
        advanceUntilIdle()
        assertEquals("element/statut", api.sent.last().second.route)
        assertEquals(listOf("entreprises", "atelier-brique", "contactee"), listOf(text("list"), text("item"), text("status")))
        assertEquals(1, vm.revision)
        assertEquals(2, api.calls.count { it == "list:3:entreprises" })
        vm.assign(e, "self")
        advanceUntilIdle()
        assertEquals("element/confier", api.sent.last().second.route)
        assertEquals("self", text("actor"))
        api.gestureResult = MoiApi.Result.Ok(GestureDone(ok = true, message = "Ajouté.", list = "entreprises", key = "lumen-conseil"))
        vm.add("entreprises", "Lumen Conseil", "", "a_contacter", "owner")
        advanceUntilIdle()
        assertEquals("element/ajouter", api.sent.last().second.route)
        assertEquals("entreprises" to "lumen-conseil", vm.added)
        vm.addedSeen()
        assertNull(vm.added)
        api.refuse(409, "Il a déjà ce statut.")
        vm.setStatus(e, "a_contacter")
        advanceUntilIdle()
        assertEquals("Il a déjà ce statut.", vm.gestures.refusalAt(ListsViewModel.where("entreprises")))
        assertEquals(3, vm.revision)
    }

    @Test fun `une liste et un élément rouverts montrent ce que le serveur dit maintenant - rien ne s'y décide d'ici là, un refus les relit`() = runTest {
        val e = Entry(list = "entreprises", key = "atelier-brique", handle = "atelier-brique", status = "a_contacter")
        api.listPages["entreprises"] = EntryPage(list = "entreprises", total = 1, items = listOf(e))
        val lists = main.model { ListsViewModel(deps, 3) }
        lists.show("entreprises")
        advanceUntilIdle()
        assertFalse("entreprises" in lists.stale)
        // l'écran revient devant : la liste se relit, et d'ici là aucun geste n'y part
        api.hold("list:3:entreprises")
        lists.resume()
        advanceUntilIdle()
        assertTrue("entreprises" in lists.stale)
        lists.setStatus(e, "contactee")
        lists.assign(e, "self")
        advanceUntilIdle()
        assertTrue(api.sent.isEmpty())
        api.release("list:3:entreprises")
        advanceUntilIdle()
        assertFalse("entreprises" in lists.stale)
        // un refus (la situation a changé) relit la liste
        val reads = api.calls.count { it == "list:3:entreprises" }
        api.refuse(409, "Il a déjà ce statut.")
        lists.setStatus(e, "a_contacter")
        advanceUntilIdle()
        assertEquals(reads + 1, api.calls.count { it == "list:3:entreprises" })
        assertEquals("Il a déjà ce statut.", lists.gestures.refusalAt(ListsViewModel.where("entreprises")))
        // un ajout abouti après qu'on a quitté l'onglet n'ouvre rien à son retour
        api.gestureResult = MoiApi.Result.Ok(GestureDone(ok = true, message = "Ajouté.", list = "entreprises", key = "lumen-conseil"))
        api.hold("gesture:element/ajouter")
        lists.add("entreprises", "Lumen Conseil", "", "a_contacter", "")
        advanceUntilIdle()
        lists.leave()
        api.release("gesture:element/ajouter")
        advanceUntilIdle()
        assertNull(lists.added)

        // un élément, en page
        api.gestureResult = null
        api.element = MoiApi.Result.Ok(EntryDetail(e, EntryMore()))
        val item = main.model { ItemViewModel(deps, 3, "entreprises", "atelier-brique") }
        item.resume()
        advanceUntilIdle()
        assertEquals("a_contacter", item.element?.valueOrNull?.line?.status)
        assertFalse(item.stale)
        // rouvert : il se relit ; pendant ce temps, ni statut, ni personne, ni note ne partent
        val sent = api.sent.size
        api.element = MoiApi.Result.Ok(EntryDetail(e.copy(status = "contactee"), EntryMore()))
        api.hold("element:3:entreprises:atelier-brique")
        item.resume()
        advanceUntilIdle()
        assertTrue(item.stale)
        item.note = "un mot"
        item.setStatus("contactee")
        item.assign("self")
        item.sendNote()
        advanceUntilIdle()
        assertEquals(sent, api.sent.size)
        // ce qui est tapé n'est pas perdu
        assertEquals("un mot", item.note)
        api.release("element:3:entreprises:atelier-brique")
        advanceUntilIdle()
        assertFalse(item.stale)
        assertEquals("contactee", item.element?.valueOrNull?.line?.status)
        // un refus relit l'élément ; sa relecture en panne se dit, et rien ne s'y décide avant « Réessayer »
        api.refuse(409, "Il a déjà ce statut.")
        api.element = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        item.setStatus("contactee")
        advanceUntilIdle()
        assertEquals("Il a déjà ce statut.", item.gestures.refusalAt(ItemViewModel.HERE))
        assertTrue(item.stale)
        assertEquals(MoiError.NETWORK, item.staleError?.message)
        assertEquals("contactee", item.element?.valueOrNull?.line?.status)
        api.element = MoiApi.Result.Ok(EntryDetail(e, EntryMore()))
        item.reread()
        advanceUntilIdle()
        assertFalse(item.stale)
        assertNull(item.staleError)
    }

    // ── Modifier le projet ──

    private val general = SettingsSection(
        name = "general", title = "Général",
        fields = listOf(
            SettingField(name = "title", label = "Titre", value = JsonPrimitive("Outils")),
            SettingField(name = "mode", label = "Mode", kind = "select", choices = listOf(Coded("persona", "Elle avance seule")), value = JsonPrimitive("persona")),
            SettingField(name = "approval", label = "Accord", kind = "bool", value = JsonPrimitive(true), can = false, why = "Réservé à qui s'occupe d'elle."),
        ),
    )

    @Test fun `un réglage n'envoie que ce qui change, jamais un champ réservé - rien de changé ne part pas - un refus nomme son champ`() = runTest {
        api.settings = MoiApi.Result.Ok(ProjectSettings(can = true, sections = listOf(general)))
        val vm = main.model { SettingsViewModel(deps, 3) }
        vm.resume()
        advanceUntilIdle()
        assertTrue(vm.changes(general).isEmpty())
        vm.save(general)
        assertTrue(api.sent.isEmpty())
        vm.set("general", "title", JsonPrimitive("Outils"))
        vm.set("general", "approval", JsonPrimitive(false))
        assertTrue(vm.changes(general).isEmpty())
        vm.save(general)
        assertTrue(api.sent.isEmpty())
        vm.set("general", "title", JsonPrimitive("Outils réseau"))
        assertEquals(setOf("title"), vm.changes(general).keys)
        api.refuse(403, "Ce réglage ouvre autre chose que ce projet.", mapOf("title" to "réservé"))
        vm.save(general)
        advanceUntilIdle()
        val where = SettingsViewModel.where("general")
        assertEquals("réservé", vm.gestures.fieldsAt(where)["title"])
        // refusé : ce qui est saisi reste
        assertEquals(setOf("title"), vm.changes(general).keys)
        api.gestureResult = null
        vm.save(general)
        advanceUntilIdle()
        val sent = api.sent.last().second
        assertEquals("reglages/enregistrer", sent.route)
        assertEquals("general", (sent.body["section"] as JsonPrimitive).content)
        assertEquals(setOf("title"), sent.body["values"]!!.jsonObject.keys)
        assertTrue(vm.typedIn("general").isEmpty())
        assertEquals(1, vm.revision)
        assertEquals(2, api.calls.count { it == "settings:3" })
        vm.archive()
        advanceUntilIdle()
        assertEquals("archiver", api.sent.last().second.route)
        assertTrue(vm.archived)
        vm.archivedSeen()
        assertFalse(vm.archived)
    }

    @Test fun `rien ne s'enregistre ni ne s'archive pendant que les réglages se relisent - ni après une relecture en panne`() = runTest {
        api.settings = MoiApi.Result.Ok(ProjectSettings(can = true, sections = listOf(general)))
        val vm = main.model { SettingsViewModel(deps, 3) }
        vm.resume()
        advanceUntilIdle()
        vm.set("general", "title", JsonPrimitive("Outils réseau"))
        // l'écran revient devant (une rotation, l'arrière-plan) : ses réglages se relisent
        api.hold("settings:3")
        vm.resume()
        advanceUntilIdle()
        assertTrue(vm.settings.stale)
        assertFalse(vm.save(general))
        assertFalse(vm.archive())
        advanceUntilIdle()
        assertTrue(api.sent.isEmpty())
        // ce qui était saisi reste, et part une fois relus
        api.release("settings:3")
        advanceUntilIdle()
        assertFalse(vm.settings.stale)
        assertEquals(setOf("title"), vm.changes(general).keys)
        assertTrue(vm.save(general))
        advanceUntilIdle()
        assertEquals("reglages/enregistrer", api.sent.single().second.route)
        // leur relecture en panne : ils restent d'avant, on le dit, rien ne part ; relus, l'archivage part
        api.settings = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        vm.resume()
        advanceUntilIdle()
        assertTrue(vm.settings.stale)
        assertEquals(MoiError.NETWORK, vm.settings.staleError?.message)
        assertFalse(vm.archive())
        assertEquals(1, api.sent.size)
        api.settings = MoiApi.Result.Ok(ProjectSettings(can = true, sections = listOf(general)))
        vm.settings.read(quiet = false)
        advanceUntilIdle()
        assertFalse(vm.settings.stale)
        assertNull(vm.settings.staleError)
        assertTrue(vm.archive())
        advanceUntilIdle()
        assertEquals("archiver", api.sent.last().second.route)
    }

    @Test fun `un réglage quitté ne garde ni sa saisie ni son refus pour la visite suivante - archivé après le départ, l'écran ne bouge pas`() = runTest {
        api.settings = MoiApi.Result.Ok(ProjectSettings(can = true, sections = listOf(general)))
        val vm = main.model { SettingsViewModel(deps, 3) }
        vm.resume()
        advanceUntilIdle()
        vm.set("general", "title", JsonPrimitive("Outils réseau"))
        api.refuse(403, "Ce réglage ouvre autre chose que ce projet.", mapOf("title" to "réservé"))
        vm.save(general)
        advanceUntilIdle()
        val where = SettingsViewModel.where("general")
        assertTrue(vm.gestures.refusalAt(where).isNotEmpty())
        // une rotation ne quitte rien ; quitter la page de la section, si
        vm.leave("general")
        assertTrue(vm.typedIn("general").isEmpty())
        assertTrue(vm.changes(general).isEmpty())
        assertEquals("", vm.gestures.refusalAt(where))
        // archivé après qu'on a quitté l'écran : au retour, rien ne ramène à la rubrique
        api.gestureResult = null
        vm.resume()
        api.hold("gesture:archiver")
        vm.archive()
        advanceUntilIdle()
        vm.leave("")
        api.release("gesture:archiver")
        advanceUntilIdle()
        assertFalse(vm.archived)
        vm.resume()
        advanceUntilIdle()
        assertFalse(vm.archived)
    }

    @Test fun `un projet archivé se désarchive depuis la rubrique, un refus se dit sous sa ligne - et rien de tout cela ne va vers la fusion`() = runTest {
        api.archives = Archives(listOf(Archived(id = 9, title = "Site")))
        val vm = main.model { ProjectsViewModel(deps) }
        vm.resume()
        advanceUntilIdle()
        assertEquals(listOf(9), vm.archives.value?.items?.map { it.id })
        api.refuse(404, "Introuvable : ce n'est plus là.")
        vm.restore(9)
        advanceUntilIdle()
        assertEquals("Introuvable : ce n'est plus là.", vm.gestures.refusalAt(ProjectsViewModel.restoreWhere(9)))
        assertEquals(0, vm.restored)
        api.gestureResult = null
        vm.restore(9)
        advanceUntilIdle()
        assertEquals(9 to "restaurer", api.sent.last().first to api.sent.last().second.route)
        assertEquals(9, vm.restored)
        vm.restoredOpened()
        assertEquals(0, vm.restored)
        assertTrue(api.sent.none { it.second.route == MERGE_ROUTE })
        assertTrue(api.merges.isEmpty())
    }
}
