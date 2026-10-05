package fr.qwartz.mika.avatar3d

import android.content.Context
import android.view.Choreographer
import android.view.Surface
import android.view.TextureView
import com.google.android.filament.Camera
import com.google.android.filament.ColorGrading
import com.google.android.filament.Engine
import com.google.android.filament.EntityManager
import com.google.android.filament.Renderer
import com.google.android.filament.SwapChain
import com.google.android.filament.ToneMapper
import com.google.android.filament.View
import com.google.android.filament.Viewport
import com.google.android.filament.android.DisplayHelper
import com.google.android.filament.android.UiHelper
import com.google.android.filament.gltfio.AssetLoader
import com.google.android.filament.gltfio.FilamentAsset
import com.google.android.filament.gltfio.ResourceLoader
import com.google.android.filament.gltfio.UbershaderProvider
import com.google.android.filament.utils.Utils
import java.nio.ByteBuffer

/**
 * Mika en 3D native : Filament rend le VRM dans une `TextureView` transparente, posée sur la lumière du fond
 * comme les portraits l'étaient. Un seul fil (le principal), une image par battement de l'écran tant que la
 * vue est visible, aucune quand elle ne l'est pas ; [onFrame] pose le squelette et le visage juste avant.
 */
class AvatarSurface(context: Context, textureView: TextureView) : Choreographer.FrameCallback {

    val engine: Engine = Engine.create()
    private val renderer: Renderer = engine.createRenderer()
    private val scene = engine.createScene()
    private val view: View = engine.createView()
    private val cameraEntity = EntityManager.get().create()
    private val camera: Camera = engine.createCamera(cameraEntity)
    private val uiHelper = UiHelper(UiHelper.ContextErrorPolicy.DONT_CHECK)
    private val displayHelper = DisplayHelper(context)
    private var swapChain: SwapChain? = null
    private val materials = UbershaderProvider(engine)
    private val loader = AssetLoader(engine, materials, EntityManager.get())
    private val resources = ResourceLoader(engine)
    private val choreographer = Choreographer.getInstance()
    private var running = false
    private var loading = false
    private var loadStartedAt = 0L

    /** Le temps qu'a pris le chargement (ms), une fois prêt. */
    var loadMillis = 0L
        private set
    private var width = 1
    private var height = 1

    var asset: FilamentAsset? = null
        private set
    var vrm: VrmDocument? = null
        private set

    /**
     * Le plafond d'images par seconde. Un écran à 120 Hz appelle deux fois plus souvent qu'il n'est utile pour un
     * corps qui respire : au-delà de 60, on saute un battement (la batterie d'une app qu'on garde ouverte longtemps).
     */
    var maxFps = 60
    private var lastRenderNanos = 0L

    /** Appelé à chaque image, avant le rendu : l'animation pose les os et les morphoses ici. */
    var onFrame: ((frameTimeNanos: Long) -> Unit)? = null

    /** Le modèle est chargé, textures comprises. */
    var onReady: (() -> Unit)? = null

    init {
        view.scene = scene
        view.camera = camera
        // Transparente : la lumière de l'humeur, dessinée par Compose, passe derrière elle.
        view.blendMode = View.BlendMode.TRANSLUCENT
        renderer.clearOptions = renderer.clearOptions.apply {
            clear = true
            clearColor = doubleArrayOf(0.0, 0.0, 0.0, 0.0)
        }
        // Les matériaux du VRM sont « unlit » (toon) : ni tone mapping filmique ni exposition, les couleurs
        // de la texture telles quelles.
        view.colorGrading = ColorGrading.Builder().toneMapper(ToneMapper.Linear()).build(engine)
        camera.setExposure(1f)
        view.multiSampleAntiAliasingOptions = view.multiSampleAntiAliasingOptions.apply {
            enabled = true
            sampleCount = 4
        }
        textureView.isOpaque = false
        uiHelper.isOpaque = false
        uiHelper.renderCallback = object : UiHelper.RendererCallback {
            override fun onNativeWindowChanged(surface: Surface) {
                swapChain?.let { engine.destroySwapChain(it) }
                swapChain = engine.createSwapChain(surface, uiHelper.swapChainFlags)
                displayHelper.attach(renderer, textureView.display)
            }

            override fun onDetachedFromSurface() {
                displayHelper.detach()
                swapChain?.let {
                    engine.destroySwapChain(it)
                    engine.flushAndWait()
                }
                swapChain = null
            }

            override fun onResized(w: Int, h: Int) {
                width = w.coerceAtLeast(1)
                height = h.coerceAtLeast(1)
                view.viewport = Viewport(0, 0, width, height)
                frame()
            }
        }
        uiHelper.attachTo(textureView)
    }

    /**
     * Le cadrage des portraits : un objectif de 85 mm à 2,2 m, à hauteur des yeux (1,19 m), visant un peu plus bas
     * pour la garder de la tête à mi-cuisse. Le VRM 0.x regarde vers −Z : la caméra est de ce côté.
     */
    fun frame(eyeHeight: Double = 1.19, aim: Double = 0.957, distance: Double = 2.2, fovDegrees: Double = 23.9) {
        camera.setProjection(fovDegrees, width.toDouble() / height, 0.05, 20.0, Camera.Fov.VERTICAL)
        camera.lookAt(0.0, eyeHeight, -distance, 0.0, aim, 0.0, 0.0, 1.0, 0.0)
    }

    /** Charge le GLB (le tampon doit rester valide jusqu'à [onReady]). */
    fun load(glb: ByteBuffer) {
        vrm = VrmDocument.fromGlb(glb)
        loadStartedAt = System.nanoTime()
        val a = loader.createAsset(glb) ?: error("GLB illisible par gltfio")
        resources.asyncBeginLoad(a)
        scene.addEntities(a.entities)
        asset = a
        loading = true
    }

    private val entityCache = HashMap<Int, Int>()
    private val matrix = FloatArray(16)

    /** L'entité Filament d'un nœud du glTF (gltfio les nomme comme les nœuds, uniques dans ce VRM). */
    private fun entityOf(node: Int): Int = entityCache.getOrPut(node) {
        val name = vrm?.nodes?.get(node)?.name ?: return 0
        asset?.getFirstEntityByName(name) ?: 0
    }

    /** Pose les transformations locales calculées par [AvatarRig.solve]. */
    fun applyLocals(locals: Array<AvatarRig.Local>) {
        val tm = engine.transformManager
        for (l in locals) {
            val e = entityOf(l.node)
            if (e == 0) continue
            val inst = tm.getInstance(e)
            if (inst == 0) continue
            tm.setTransform(inst, trs(l.translation, l.rotation, l.scale, matrix))
        }
    }

    /** Pose la transformation locale d'un nœud quelconque (les mèches que [SpringBones] simule). */
    fun applyNode(node: Int, translation: Vec3, rotation: Quat) {
        val e = entityOf(node)
        if (e == 0) return
        val tm = engine.transformManager
        val inst = tm.getInstance(e)
        if (inst == 0) return
        tm.setTransform(inst, trs(translation, rotation, Vec3.ONE, matrix))
    }

    /** Les poids de toutes les morphoses d'un maillage (dans l'ordre de ses `targetNames`). */
    fun setMorphWeights(mesh: Int, weights: FloatArray) {
        val doc = vrm ?: return
        val rm = engine.renderableManager
        for (node in doc.nodesOfMesh(mesh)) {
            val e = entityOf(node.index)
            if (e == 0) continue
            val inst = rm.getInstance(e)
            if (inst == 0) continue
            rm.setMorphWeights(inst, weights, 0)
        }
    }

    /** Par maillage à morphoses : nom → indice, et le tableau de poids qu'on lui passe. */
    private val morphTables: List<Triple<Int, Map<String, Int>, FloatArray>> by lazy {
        val doc = vrm ?: return@lazy emptyList()
        doc.morphNames.filterValues { it.isNotEmpty() }.map { (mesh, names) ->
            Triple(mesh, names.withIndex().associate { (i, n) -> n to i }, FloatArray(names.size))
        }
    }

    /**
     * Les poids des morphoses, par nom (le visage est découpé par matériau : une même morphose vit dans plusieurs
     * maillages) ; une morphose absente de `weights` revient à zéro.
     */
    fun setMorphs(weights: Map<String, Float>) {
        for ((mesh, index, values) in morphTables) {
            values.fill(0f)
            for ((name, w) in weights) index[name]?.let { values[it] = w }
            setMorphWeights(mesh, values)
        }
    }

    /** La position de la caméra (en monde) : là où elle doit regarder pour regarder la personne. */
    fun cameraPosition(): Vec3 {
        val p = FloatArray(3)
        camera.getPosition(p)
        return Vec3(p[0], p[1], p[2])
    }

    fun start() {
        if (running) return
        running = true
        choreographer.postFrameCallback(this)
    }

    fun stop() {
        running = false
        choreographer.removeFrameCallback(this)
    }

    override fun doFrame(frameTimeNanos: Long) {
        if (!running) return
        choreographer.postFrameCallback(this)
        // Une petite marge sous l'intervalle : un battement à 59,9 Hz n'est pas sauté.
        if (lastRenderNanos != 0L && frameTimeNanos - lastRenderNanos < 900_000_000L / maxFps) return
        lastRenderNanos = frameTimeNanos
        val a = asset
        if (loading && a != null) {
            resources.asyncUpdateLoad()
            if (resources.asyncGetLoadProgress() >= 1f) {
                loading = false
                a.releaseSourceData()
                loadMillis = (System.nanoTime() - loadStartedAt) / 1_000_000
                onReady?.invoke()
            }
        }
        if (!loading) onFrame?.invoke(frameTimeNanos)
        a?.instance?.animator?.updateBoneMatrices()
        val sc = swapChain ?: return
        if (uiHelper.isReadyToRender && renderer.beginFrame(sc, frameTimeNanos)) {
            renderer.render(view)
            renderer.endFrame()
        }
    }

    fun destroy() {
        stop()
        uiHelper.detach()
        asset?.let {
            scene.removeEntities(it.entities)
            loader.destroyAsset(it)
        }
        asset = null
        materials.destroyMaterials()
        materials.destroy()
        resources.destroy()
        loader.destroy()
        engine.destroyRenderer(renderer)
        engine.destroyView(view)
        engine.destroyScene(scene)
        engine.destroyCameraComponent(cameraEntity)
        EntityManager.get().destroy(cameraEntity)
        engine.destroy()
    }

    companion object {
        init {
            Utils.init()
        }
    }
}
