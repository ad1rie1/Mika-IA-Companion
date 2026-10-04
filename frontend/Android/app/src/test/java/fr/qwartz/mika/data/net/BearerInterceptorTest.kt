package fr.qwartz.mika.data.net

import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import okhttp3.Request
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.concurrent.TimeUnit

class BearerInterceptorTest {
    private val mika = MockWebServer().apply { start() }
    private val other = MockWebServer().apply { start() }
    private val base = (ServerBase.parse(mika.url("/").toString()) as ServerBase.Parsed.Ok).base
    private val client = OkHttpClient.Builder().addInterceptor(BearerInterceptor { base to "mw_abc" }).build()

    @After fun tearDown() {
        mika.close()
        other.close()
        client.dispatcher.executorService.shutdown()
    }

    private fun get(server: MockWebServer) {
        server.enqueue(MockResponse.Builder().code(200).body("ok").build())
        client.newCall(Request.Builder().url(server.url("/files/x")).build()).execute().close()
    }

    @Test fun `le jeton part vers son serveur, jamais ailleurs`() {
        get(mika)
        assertEquals("Bearer mw_abc", mika.takeRequest(5, TimeUnit.SECONDS)!!.headers["Authorization"])
        get(other)
        assertNull(other.takeRequest(5, TimeUnit.SECONDS)!!.headers["Authorization"])
    }
}
