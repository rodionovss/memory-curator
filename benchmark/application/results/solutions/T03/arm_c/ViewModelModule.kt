package com.example.di

import androidx.lifecycle.ViewModel
import com.example.home.HomeViewModel
import com.example.settings.SettingsViewModel
import dagger.Binds
import dagger.Module
import dagger.Multibinds
import dagger.multibindings.IntoMap
import javax.inject.Provider

@Module
abstract class ViewModelModule {

    @Multibinds
    abstract fun viewModels(): Map<Class<out ViewModel>, @JvmSuppressWildcards Provider<ViewModel>>

    @Binds
    @IntoMap
    @ViewModelKey(HomeViewModel::class)
    abstract fun bindHomeViewModel(homeViewModel: HomeViewModel): ViewModel

    @Binds
    @IntoMap
    @ViewModelKey(SettingsViewModel::class)
    abstract fun bindSettingsViewModel(settingsViewModel: SettingsViewModel): ViewModel
}
