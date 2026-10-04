package fr.qwartz.mika.core

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Le réseau par défaut : disponible ou non, et lequel (un changement de réseau tue les sockets). */
data class NetworkStatus(val available: Boolean, val networkId: Long?)

class NetworkMonitor(context: Context) {
    private val connectivity = context.getSystemService(ConnectivityManager::class.java)
    private val _status = MutableStateFlow(current())
    val status: StateFlow<NetworkStatus> = _status.asStateFlow()

    fun install() {
        connectivity.registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                _status.value = NetworkStatus(true, network.networkHandle)
            }

            override fun onLost(network: Network) {
                if (_status.value.networkId == network.networkHandle) _status.value = NetworkStatus(false, null)
            }

            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                val usable = caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                if (usable && _status.value.networkId != network.networkHandle) {
                    _status.value = NetworkStatus(true, network.networkHandle)
                }
            }
        })
    }

    private fun current(): NetworkStatus {
        val network = connectivity.activeNetwork ?: return NetworkStatus(false, null)
        return NetworkStatus(true, network.networkHandle)
    }
}
