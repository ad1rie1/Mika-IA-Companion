package fr.qwartz.mika.ui.viewer

import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import coil3.compose.AsyncImage
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.chat.MessageAttachment
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberFileActions

/** Une image de Mika en plein écran : pincer pour agrandir, toucher deux fois pour revenir ; l'enregistrer ou l'ouvrir ailleurs. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ImageViewerScreen(graph: AppGraph, route: Route.Viewer, onBack: () -> Unit) {
    val att = remember(route) {
        MessageAttachment(route.name, "image", route.mime, route.size, id = route.fileId, url = route.url, available = true)
    }
    val url = remember(att) { graph.downloads.absoluteUrl(att) }
    val snackbar = remember { SnackbarHostState() }
    val files = rememberFileActions(graph, snackbar)
    var scale by remember { mutableFloatStateOf(1f) }
    var offset by remember { mutableStateOf(Offset.Zero) }
    var loading by remember { mutableStateOf(true) }
    var failed by remember { mutableStateOf(false) }

    Scaffold(
        containerColor = Color.Black,
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text(route.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(painterResource(R.drawable.ic_arrow_back), stringResource(R.string.back))
                    }
                },
                actions = {
                    val busy = files.busy != null
                    TextButton(onClick = { files.save(att) }, enabled = !busy) { Text(stringResource(R.string.file_save)) }
                    TextButton(onClick = { files.open(att) }, enabled = !busy) { Text(stringResource(R.string.file_open_with)) }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color.Black.copy(alpha = 0.6f),
                    titleContentColor = Color.White,
                    navigationIconContentColor = Color.White,
                    actionIconContentColor = Color.White,
                ),
            )
        },
    ) { padding ->
        Box(
            Modifier
                .fillMaxSize()
                .background(Color.Black)
                .padding(padding)
                .pointerInput(Unit) {
                    detectTapGestures(onDoubleTap = {
                        scale = 1f
                        offset = Offset.Zero
                    })
                }
                .pointerInput(Unit) {
                    detectTransformGestures { _, pan, zoom, _ ->
                        scale = (scale * zoom).coerceIn(1f, 5f)
                        offset = if (scale == 1f) Offset.Zero else offset + pan
                    }
                },
            contentAlignment = Alignment.Center,
        ) {
            if (url == null || failed) {
                Text(stringResource(R.string.file_image_unavailable), color = Color.White)
            } else {
                AsyncImage(
                    model = url,
                    contentDescription = stringResource(R.string.file_image_of_mika, route.name),
                    contentScale = ContentScale.Fit,
                    onSuccess = { loading = false },
                    onError = {
                        loading = false
                        failed = true
                    },
                    modifier = Modifier.fillMaxSize().graphicsLayer {
                        scaleX = scale
                        scaleY = scale
                        translationX = offset.x
                        translationY = offset.y
                    },
                )
                if (loading) CircularProgressIndicator(color = MaterialTheme.colorScheme.primary)
            }
        }
    }
}
