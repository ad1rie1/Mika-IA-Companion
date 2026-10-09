import com.android.build.api.variant.ResValue
import groovy.json.JsonSlurper

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ksp)
    alias(libs.plugins.room)
}

android {
    namespace = "fr.qwartz.mika"
    compileSdk = 37

    defaultConfig {
        applicationId = "fr.qwartz.mika"
        minSdk = 29
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        // Filament (le rendu natif de Mika) embarque ses bibliothèques par architecture : les téléphones
        // (arm64) et l'émulateur (x86_64) suffisent, les deux autres doubleraient la taille pour rien.
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            resValue("string", "app_name", "Mika (dev)")
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            resValue("string", "app_name", "Mika")
            // Signée avec la clé de débogage : installable directement, rien n'est publié.
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
        resValues = true
    }

    testOptions {
        unitTests {
            // Le cœur est du Kotlin pur ; ce filet évite qu'un Log oublié fasse échouer un test JVM.
            isReturnDefaultValues = true
            all {
                it.maxParallelForks = 1
                it.maxHeapSize = "768m"
            }
        }
    }
}

room {
    schemaDirectory("$projectDir/schemas")
}

// Les mouvements de l'atelier (os seuls, versionnés : la source commune avec Unity) et le manifeste des animations
// du client web, copiés dans les assets de l'app à chaque construction — jamais une seconde copie à tenir à jour.
val avatarMotions = layout.buildDirectory.dir("generated/avatarMotions")
val copyAvatarMotions by tasks.registering(Copy::class) {
    into(avatarMotions.map { it.dir("avatar3d") })
    from(rootProject.file("../Unity/ArtSource/atelier/motions")) {
        include("*.json.gz")
        into("motions")
    }
    // Le manifeste des animations du client web : poids, durées, humeur des clips — une seule source.
    from(rootProject.file("../Web/public/animations/manifest.json"))
}
android.sourceSets.getByName("main").assets.srcDir(avatarMotions.get().asFile)
tasks.named("preBuild") { dependsOn(copyAvatarMotions) }

// Les notifications app fermée passent par Firebase (ADR 0077). Le fichier google-services.json du projet Firebase
// (non versionné, à poser dans app/) donne à chaque variante ses identifiants, en ressources que FirebaseInitProvider
// lit au démarrage — ce que fait le greffon com.google.gms.google-services, sans lui. Sans le fichier, ou sans
// l'identifiant de la variante (fr.qwartz.mika, fr.qwartz.mika.debug), l'app se construit et marche : elle ne reçoit
// simplement que ce qu'elle trouve en s'ouvrant, et le dit dans ses paramètres.
val googleServices: File = file("google-services.json")

@Suppress("UNCHECKED_CAST")
fun firebaseValues(json: File, applicationId: String): Map<String, String>? {
    if (!json.isFile) return null
    val root = JsonSlurper().parse(json) as Map<String, Any?>
    val project = root["project_info"] as? Map<String, Any?> ?: return null
    val client = (root["client"] as? List<Map<String, Any?>>).orEmpty().firstOrNull { c ->
        val info = c["client_info"] as? Map<String, Any?>
        (info?.get("android_client_info") as? Map<String, Any?>)?.get("package_name") == applicationId
    } ?: return null
    val appId = (client["client_info"] as Map<String, Any?>)["mobilesdk_app_id"] as? String ?: return null
    val apiKey = (client["api_key"] as? List<Map<String, Any?>>)?.firstOrNull()?.get("current_key") as? String
        ?: return null
    return listOfNotNull(
        "google_app_id" to appId,
        "google_api_key" to apiKey,
        "gcm_defaultSenderId" to (project["project_number"] as? String ?: return null),
        "project_id" to (project["project_id"] as? String ?: return null),
        (project["storage_bucket"] as? String)?.let { "google_storage_bucket" to it },
    ).toMap()
}

androidComponents {
    onVariants { variant ->
        val values = firebaseValues(googleServices, variant.applicationId.get())
        if (values == null) {
            logger.lifecycle("Firebase : pas d'identifiants pour ${variant.applicationId.get()} (app/google-services.json) " +
                "— construite sans notifications app fermée.")
        }
        values?.forEach { (name, value) ->
            variant.resValues.put(variant.makeResValueKey("string", name), ResValue(value, "Firebase (ADR 0077)"))
        }
    }
}

dependencies {
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.foundation)
    implementation(libs.compose.material3)
    implementation(libs.compose.ui.tooling.preview)
    debugImplementation(libs.compose.ui.tooling)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.process)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.okhttp)
    implementation(libs.filament.android)
    implementation(libs.filament.gltfio)
    implementation(libs.filament.utils)
    implementation(libs.room.runtime)
    implementation(libs.room.ktx)
    ksp(libs.room.compiler)
    implementation(libs.datastore.preferences)
    // Les vignettes et la visionneuse des images de Mika, avec le client HTTP authentifié de l'app.
    implementation(libs.coil.compose)
    implementation(libs.coil.network.okhttp)
    // Les notifications app fermée (ADR 0077) : des messages de données Firebase, chiffrés par le serveur.
    implementation(platform(libs.firebase.bom))
    implementation(libs.firebase.messaging)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.okhttp.mockwebserver3)

    // Instrumentés (émulateur) : Room en mémoire et écrans Compose.
    androidTestImplementation(platform(libs.compose.bom))
    androidTestImplementation(libs.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.kotlinx.coroutines.test)
    debugImplementation(libs.compose.ui.test.manifest)
}
