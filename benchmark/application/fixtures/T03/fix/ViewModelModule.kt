package com.example.di

import androidx.lifecycle.ViewModel
import dagger.Module
import dagger.Multibinds
import dagger.multibindings.IntoMap
import javax.inject.Provider

@Module
abstract class ViewModelModule {

    @Multibinds
    abstract fun viewModels(): Map<Class<out ViewModel>, @JvmSuppressWildcards Provider<ViewModel>>
}
