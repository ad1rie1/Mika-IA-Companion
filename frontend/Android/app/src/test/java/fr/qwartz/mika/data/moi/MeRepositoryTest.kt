package fr.qwartz.mika.data.moi

import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Qui est connecté (`GET /api/moi`) : une lecture partie sous une session ne se pose pas après sa fermeture. */
class MeRepositoryTest {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val base = (ServerBase.parse("http://127.0.0.1:8001") as ServerBase.Parsed.Ok).base
    private val credentials = Credentials(base, "mw_telephone")

    /** La réponse du serveur, retenue jusqu'à [release] : le temps de fermer la session pendant la lecture. */
    private class Held(private val body: String) : Interceptor {
        val asked = CountDownLatch(1)
        val release = CountDownLatch(1)
        override fun intercept(chain: Interceptor.Chain): Response {
            asked.countDown()
            release.await(5, TimeUnit.SECONDS)
            return Response.Builder()
                .request(chain.request())
                .protocol(Protocol.HTTP_1_1)
                .code(200)
                .message("OK")
                .body(body.toResponseBody("application/json".toMediaType()))
                .build()
        }
    }

    private fun repository(held: Held): MeRepository {
        val client = OkHttpClient.Builder().addInterceptor(held).build()
        return MeRepository(MoiApi(client, { credentials }, {}, Dispatchers.IO), scope)
    }

    @After fun tearDown() = scope.cancel()

    @Test fun `une lecture se pose`() = runBlocking {
        val held = Held("""{"username":"adrien","name":"Adrien","operator":true}""")
        val me = repository(held)
        held.release.countDown()
        assertTrue(me.load() is MoiApi.Result.Ok)
        assertEquals("Adrien", me.me.value?.shown)
    }

    @Test fun `une lecture partie avant la fermeture de la session ne repose rien après`() = runBlocking {
        val held = Held("""{"username":"adrien","name":"Adrien","operator":true,"owner":true,"counts":{"mail":3}}""")
        val me = repository(held)
        val load = scope.async { me.load() }
        assertTrue("la lecture n'est pas partie", held.asked.await(5, TimeUnit.SECONDS))
        me.clear()
        held.release.countDown()
        withTimeout(5_000) { load.await() }
        assertNull("le nom et les rôles de la session d'avant sont revenus", me.me.value)
    }

    @Test fun `après la fermeture, la lecture suivante se pose`() = runBlocking {
        val held = Held("""{"username":"claire","name":"Claire"}""")
        val me = repository(held)
        me.clear()
        held.release.countDown()
        me.load()
        assertEquals("Claire", me.me.value?.shown)
    }
}
