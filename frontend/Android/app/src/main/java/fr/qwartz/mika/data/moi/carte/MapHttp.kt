package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.data.net.BearerInterceptor
import fr.qwartz.mika.data.net.ServerBase
import okhttp3.Dispatcher
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody

/**
 * Le client HTTP de MapLibre (ADR 0193) : ses tuiles, ses polices et ses icônes, demandées à ce serveur seul, avec le
 * jeton du téléphone ([BearerInterceptor] : même origine seulement). Toute autre adresse — un style qui en nommerait
 * une, une planche par défaut — est refusée ici même, sans qu'aucun octet ne sorte : [SameServerOnly]. Une redirection
 * ne se suit pas : OkHttp la suivrait après ce filtre, qui ne voit que la première adresse, et la tuile partirait
 * ailleurs (un mandataire qui passe en HTTPS, une interception en clair) ; sa réponse 30x est une tuile en échec.
 */
object MapHttp {
    /** Comme MapLibre le règle pour lui (`HttpRequestImpl`) : assez de tuiles à la fois vers le même serveur. */
    private const val PER_HOST = 20

    /**
     * Le client de la carte, tiré de celui de l'app ([base], ses délais et son pool) ; [credentials] : le serveur de la
     * session et son jeton, relus à chaque requête (une autre session, un autre serveur).
     */
    fun client(base: OkHttpClient, credentials: () -> Pair<ServerBase, String>?): OkHttpClient =
        base.newBuilder()
            .dispatcher(Dispatcher().apply { maxRequestsPerHost = PER_HOST })
            .followRedirects(false)
            .followSslRedirects(false)
            .addInterceptor(SameServerOnly { credentials()?.first })
            .addInterceptor(BearerInterceptor(credentials))
            .build()
}

/**
 * Ne laisse partir que les requêtes vers le serveur de la session (même schéma, hôte et port) ; hors session, aucune.
 * Une autre reçoit un refus fabriqué ici (403), sans réseau : MapLibre la compte comme une ressource absente.
 */
class SameServerOnly(private val server: () -> ServerBase?) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val base = server()
        if (base != null && base.sameOrigin(request.url)) return chain.proceed(request)
        return Response.Builder()
            .request(request)
            .protocol(Protocol.HTTP_1_1)
            .code(403)
            .message("Forbidden")
            .body(REFUSED.toResponseBody(TEXT))
            .build()
    }

    companion object {
        const val REFUSED = "La carte ne parle qu'au serveur de Mika."
        private val TEXT = "text/plain; charset=utf-8".toMediaType()
    }
}
