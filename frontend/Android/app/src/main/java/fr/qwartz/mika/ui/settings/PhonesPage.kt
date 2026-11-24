package fr.qwartz.mika.ui.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.ago
import fr.qwartz.mika.data.moi.phone.PhoneDevices
import fr.qwartz.mika.data.moi.phone.shortPhone
import fr.qwartz.mika.data.moi.settings.doneText
import fr.qwartz.mika.data.moi.settings.phoneRows
import fr.qwartz.mika.data.moi.settings.pushWords
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.FollowLive
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.rememberSessionKey
import kotlinx.coroutines.launch

/**
 * Paramètres › Téléphones (ADR 0190) : tes téléphones (les jetons `mobile` de ton compte, révoqués compris) — celui-ci
 * reconnu par l'identifiant de son jeton, gardé avec la session (R3-03) ; une session d'avant le reconnaît à son nom, et
 * ne propose pas « Révoquer » sur un autre du même nom, qui pourrait être lui —, s'ils reçoivent les notifications
 * application fermée, quand ils ont servi. En révoquer un autre (perdu, prêté) : son jeton ne vaut plus rien, ses
 * messages restent. Révoquer celui-ci, c'est se déconnecter : la déconnexion habituelle rend son jeton et efface ce qu'il
 * garde.
 */
class PhonesListViewModel(graph: AppGraph) : SettingsModel(graph) {
    var load by mutableStateOf<Load<PhoneDevices>>(Load.Loading)
        private set

    fun resume() {
        viewModelScope.launch { read() }
    }

    /** Relu sans bruit : un retour sur la page, ou le direct (ADR 0308) qui dit que ce qu'elle montre a changé. */
    suspend fun read() {
        when (val got = api.phones()) {
            is MoiApi.Result.Ok -> load = Load.Ready(got.value)
            is MoiApi.Result.Failed -> if (load !is Load.Ready) load = Load.Failed(got.error) else say(got.error)
        }
    }

    fun retry() {
        load = Load.Loading
        resume()
    }

    fun revoke(id: Long) {
        viewModelScope.launch {
            when (val got = api.revokePhone(id)) {
                is MoiApi.Result.Ok -> say(doneText(got.value.message, text(R.string.settings_phones_revoked)))
                is MoiApi.Result.Failed -> say(got.error)
            }
            resume()
        }
    }
}

@Composable
internal fun PhonesPage(graph: AppGraph) {
    val session = rememberSessionKey(graph)
    val vm: PhonesListViewModel = viewModel(key = "settings.phones|$session") { PhonesListViewModel(graph) }
    FollowLive(graph.live, SettingsLive.PHONES, vm, onShown = { vm.resume() }) { vm.read() }
    SettingsEffects(vm)
    // le téléphone à révoquer (son id ; celui-ci : THIS)
    var revoking by rememberSaveable { mutableStateOf<Long?>(null) }
    // « vu il y a 4 min » avance tout seul
    val now = rememberNow(wallMs = graph.clock::wallMs)
    SectionScaffold(topBar = { MikaTopBar(stringResource(R.string.settings_phones), BarNav.BACK) }) { modifier ->
        LoadBox(vm.load, onRetry = vm::retry, modifier = modifier) { got ->
            val rows = phoneRows(got.items, graph.deviceLabel, graph.auth.tokenId())
            Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
                SetHead(stringResource(R.string.settings_phones_connected))
                SetGroup {
                    if (rows.isEmpty()) SetRow(stringResource(R.string.settings_phones_none), stringResource(R.string.settings_phones_none_help))
                    rows.forEachIndexed { i, row ->
                        if (i > 0) SetDivider()
                        val p = row.phone
                        val title = if (row.mine) stringResource(R.string.settings_phones_this) else shortPhone(p.label)
                        val sub = listOf(
                            if (row.mine) shortPhone(p.label) else "",
                            pushWords(p.push),
                            if (p.createdAt > 0) stringResource(R.string.settings_phones_created, MoiDates.short(p.createdAt, now)) else "",
                            if (!row.mine && p.lastUsed > 0) stringResource(R.string.settings_phones_seen, ago(p.lastUsed, now)) else "",
                            // une session d'avant ne sait pas lequel des deux est celui-ci : pas de « Révoquer », dit en mots
                            if (row.unsure) stringResource(R.string.settings_phones_unsure) else "",
                        ).filter { it.isNotBlank() }.joinToString(" · ")
                        SetItem(R.drawable.ic_m_phone, title, sub) {
                            when {
                                p.revoked -> Tag(stringResource(R.string.settings_phones_revoked_tag), Tone.NEUTRAL)
                                row.mine -> Column {
                                    Tag(stringResource(R.string.settings_phones_this_tag), Tone.OK)
                                    TextButton(onClick = { revoking = THIS }) { Text(stringResource(R.string.settings_phones_revoke), color = MaterialTheme.colorScheme.error) }
                                }
                                row.revocable -> TextButton(onClick = { revoking = p.id }) { Text(stringResource(R.string.settings_phones_revoke), color = MaterialTheme.colorScheme.error) }
                                else -> Tag(stringResource(R.string.settings_phones_unsure_tag), Tone.WARN)
                            }
                        }
                    }
                }
                SetNote(stringResource(R.string.settings_phones_note))
            }
        }
    }
    when (val id = revoking) {
        null -> Unit
        THIS -> ConfirmDialog(
            title = stringResource(R.string.settings_phones_revoke_this_title),
            text = stringResource(R.string.settings_phones_revoke_this_text),
            confirm = stringResource(R.string.menu_logout),
            danger = true,
            onConfirm = {
                revoking = null
                // révoquer celui-ci, c'est la déconnexion habituelle : son jeton rendu au serveur, ce qu'il garde effacé
                graph.scope.launch { graph.auth.logout() }
            },
            onDismiss = { revoking = null },
        )
        else -> {
            val name = (vm.load as? Load.Ready)?.value?.items?.firstOrNull { it.id == id }?.let { shortPhone(it.label) }.orEmpty()
            ConfirmDialog(
                title = stringResource(R.string.settings_phones_revoke_title),
                text = stringResource(R.string.settings_phones_revoke_text, name.ifBlank { stringResource(R.string.settings_phones_that) }),
                confirm = stringResource(R.string.settings_phones_revoke),
                danger = true,
                onConfirm = {
                    revoking = null
                    vm.revoke(id)
                },
                onDismiss = { revoking = null },
            )
        }
    }
}

/** « Révoquer » sur ce téléphone même. */
private const val THIS = -1L
