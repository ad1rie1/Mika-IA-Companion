package fr.qwartz.mika.ui.mail

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestDispatcher
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.rules.TestWatcher
import org.junit.runner.Description

/**
 * Les modèles d'écran sur la JVM : leur fil principal (`viewModelScope`) sur un répartiteur de test, que `runTest`
 * partage ; et leur magasin, vidé à la fin du test — leurs coroutines s'arrêtent avec lui, aucune ne déborde sur le
 * test suivant.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MainDispatcherRule(private val dispatcher: TestDispatcher = UnconfinedTestDispatcher()) : TestWatcher() {
    private val store = ViewModelStore()

    /** Un modèle tenu par le magasin du test. */
    inline fun <reified T : ViewModel> model(noinline create: () -> T): T = provide(T::class.java, create)

    fun <T : ViewModel> provide(type: Class<T>, create: () -> T): T {
        val factory = object : ViewModelProvider.Factory {
            override fun <V : ViewModel> create(modelClass: Class<V>): V = modelClass.cast(create())!!
        }
        return ViewModelProvider(store, factory)["${type.name}:${System.identityHashCode(create)}", type]
    }

    override fun starting(description: Description) = Dispatchers.setMain(dispatcher)

    override fun finished(description: Description) {
        store.clear()
        Dispatchers.resetMain()
    }
}
