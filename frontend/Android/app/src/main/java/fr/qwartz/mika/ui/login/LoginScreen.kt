package fr.qwartz.mika.ui.login

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.autofill.ContentType
import androidx.compose.ui.platform.LocalAutofillManager
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentType
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.BuildConfig
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.auth.AuthRepository
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** L'état de l'écran de connexion, porté au-delà d'une rotation. */
class LoginViewModel(private val graph: AppGraph) : ViewModel() {
    var server by mutableStateOf("")
    var username by mutableStateOf("")
    var password by mutableStateOf("")
    var devToken by mutableStateOf("")
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    /** La dernière tentative a ouvert la session (pour proposer d'enregistrer les identifiants). */
    var succeeded by mutableStateOf(false)
        private set
    /** Secondes avant de pouvoir réessayer (429). */
    var cooldown by mutableLongStateOf(0L)
        private set
    private var countdown: Job? = null

    init {
        // L'adresse et le nom restent d'une session à l'autre.
        viewModelScope.launch {
            val s = graph.settings.current()
            if (server.isEmpty()) server = s.serverUrl
            if (username.isEmpty()) username = s.username
        }
    }

    val canSubmit: Boolean
        get() = !busy && cooldown <= 0 && server.isNotBlank() &&
            (devToken.isNotBlank() || (username.isNotBlank() && password.isNotEmpty()))

    fun submit() {
        if (!canSubmit) return
        busy = true
        error = null
        succeeded = false
        viewModelScope.launch {
            val result = if (BuildConfig.DEBUG && devToken.isNotBlank()) {
                graph.auth.loginWithToken(server, devToken)
            } else {
                graph.auth.login(server, username, password)
            }
            busy = false
            when (result) {
                AuthRepository.LoginResult.Success -> {
                    succeeded = true
                    password = ""
                }
                is AuthRepository.LoginResult.Failure -> {
                    error = result.error.message
                    result.error.retryAfterSeconds?.let(::startCooldown)
                }
            }
        }
    }

    private fun startCooldown(seconds: Long) {
        countdown?.cancel()
        cooldown = seconds
        countdown = viewModelScope.launch {
            while (cooldown > 0) {
                delay(1000)
                cooldown -= 1
            }
        }
    }
}

@Composable
fun LoginScreen(graph: AppGraph, reason: String?) {
    val vm: LoginViewModel = viewModel { LoginViewModel(graph) }
    val autofill = LocalAutofillManager.current
    // La connexion réussie fait quitter cet écran : c'est le moment de proposer d'enregistrer les identifiants.
    DisposableEffect(Unit) { onDispose { if (vm.succeeded) autofill?.commit() } }
    LoginForm(
        server = vm.server,
        onServer = { vm.server = it },
        username = vm.username,
        onUsername = { vm.username = it },
        password = vm.password,
        onPassword = { vm.password = it },
        reason = reason,
        error = vm.error,
        busy = vm.busy,
        cooldown = vm.cooldown,
        canSubmit = vm.canSubmit,
        onSubmit = vm::submit,
        devToken = if (BuildConfig.DEBUG) ({ DevTokenField(vm) }) else null,
    )
}

/**
 * Le formulaire, sans état : de quoi l'éprouver sans graphe. Les champs portent leur sorte pour le
 * remplissage automatique (gestionnaire de mots de passe).
 */
@Composable
fun LoginForm(
    server: String,
    onServer: (String) -> Unit,
    username: String,
    onUsername: (String) -> Unit,
    password: String,
    onPassword: (String) -> Unit,
    reason: String?,
    error: String?,
    busy: Boolean,
    cooldown: Long,
    canSubmit: Boolean,
    onSubmit: () -> Unit,
    devToken: (@Composable () -> Unit)? = null,
) {
    var showPassword by rememberSaveable { mutableStateOf(false) }
    val parsed = ServerBase.parse(server) as? ServerBase.Parsed.Ok

    Column(
        Modifier
            .fillMaxSize()
            .safeDrawingPadding()
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 32.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(
            stringResource(R.string.login_title),
            style = MaterialTheme.typography.headlineMedium,
            modifier = Modifier.semantics { heading() },
        )
        Text(stringResource(R.string.login_subtitle), style = MaterialTheme.typography.bodyMedium)

        if (reason != null) Notice(reason, MaterialTheme.colorScheme.errorContainer)

        OutlinedTextField(
            value = server,
            onValueChange = onServer,
            label = { Text(stringResource(R.string.login_server)) },
            supportingText = { Text(stringResource(R.string.login_server_hint)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Next),
            modifier = Modifier.fillMaxWidth(),
        )
        if (parsed != null && parsed.base.isInsecure && !parsed.base.isTailscale) {
            Notice(stringResource(R.string.login_insecure_warning), MaterialTheme.colorScheme.tertiaryContainer)
        } else if (parsed != null && !parsed.base.isHttps && parsed.base.isTailscale) {
            Notice(stringResource(R.string.login_tailscale_info), MaterialTheme.colorScheme.secondaryContainer)
        }

        OutlinedTextField(
            value = username,
            onValueChange = onUsername,
            label = { Text(stringResource(R.string.login_username)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
            modifier = Modifier.fillMaxWidth().semantics { contentType = ContentType.Username },
        )
        OutlinedTextField(
            value = password,
            onValueChange = onPassword,
            label = { Text(stringResource(R.string.login_password)) },
            singleLine = true,
            visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { if (canSubmit) onSubmit() }),
            trailingIcon = {
                IconButton(onClick = { showPassword = !showPassword }) {
                    Icon(
                        painterResource(if (showPassword) R.drawable.ic_visibility_off else R.drawable.ic_visibility),
                        contentDescription = stringResource(
                            if (showPassword) R.string.login_hide_password else R.string.login_show_password,
                        ),
                    )
                }
            },
            modifier = Modifier.fillMaxWidth().semantics { contentType = ContentType.Password },
        )

        devToken?.invoke()

        error?.let { message ->
            Text(
                message,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
            )
        }

        Button(onClick = onSubmit, enabled = canSubmit, modifier = Modifier.fillMaxWidth()) {
            Text(
                when {
                    busy -> stringResource(R.string.login_submitting)
                    cooldown > 0 -> stringResource(R.string.login_retry_in, cooldown.toInt())
                    else -> stringResource(R.string.login_submit)
                },
            )
        }
    }
}

/** En débogage seulement : un jeton créé en ligne de commande, avant que la route existe. */
@Composable
private fun DevTokenField(vm: LoginViewModel) {
    var open by rememberSaveable { mutableStateOf(vm.devToken.isNotEmpty()) }
    if (!open) {
        TextButton(onClick = { open = true }) { Text(stringResource(R.string.login_dev_token)) }
        return
    }
    OutlinedTextField(
        value = vm.devToken,
        onValueChange = { vm.devToken = it },
        label = { Text(stringResource(R.string.login_dev_token_field)) },
        supportingText = { Text(stringResource(R.string.login_dev_token_hint)) },
        singleLine = true,
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun Notice(text: String, color: androidx.compose.ui.graphics.Color) {
    Card(colors = CardDefaults.cardColors(containerColor = color), modifier = Modifier.fillMaxWidth()) {
        Text(text, modifier = Modifier.padding(12.dp), style = MaterialTheme.typography.bodyMedium)
    }
}
