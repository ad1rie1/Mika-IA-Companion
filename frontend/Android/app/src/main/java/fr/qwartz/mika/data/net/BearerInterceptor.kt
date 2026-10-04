package fr.qwartz.mika.data.net

import okhttp3.Interceptor
import okhttp3.Response

/**
 * Pose le jeton sur les requêtes vers SON serveur seulement (même schéma, hôte et port) — jamais
 * vers une adresse tierce qu'une redirection ou un lien glisserait. Pour les fichiers de Mika et les
 * vignettes (le client HTTP partagé avec Coil).
 */
class BearerInterceptor(private val credentials: () -> Pair<ServerBase, String>?) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val (base, token) = credentials() ?: return chain.proceed(request)
        if (!base.sameOrigin(request.url) || request.header(MikaProtocol.HEADER_AUTHORIZATION) != null) {
            return chain.proceed(request)
        }
        return chain.proceed(request.newBuilder().header(MikaProtocol.HEADER_AUTHORIZATION, "Bearer $token").build())
    }
}
