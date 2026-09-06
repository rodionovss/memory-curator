package com.example.profile

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import javax.inject.Inject

class ProfileViewModel @Inject constructor(
    private val interactor: ProfileInteractor,
) : ViewModel() {

    val state = MutableStateFlow(ProfileState())

    fun load() {
        viewModelScope.launch {
            try {
                interactor.refresh()
            } catch (e: ApiError.Network) {
                // заглушка
            }
        }
    }
}

interface ProfileInteractor {
    suspend fun refresh()
}
