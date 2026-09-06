package com.example.profile

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

class ProfileViewModel @Inject constructor(
    private val interactor: ProfileInteractor,
) : ViewModel() {

    val state = MutableStateFlow(ProfileState())

    fun load() {
        state.value = state.value.copy(isLoading = true, error = null)
        viewModelScope.launch {
            try {
                interactor.refresh()
                state.value = state.value.copy(isLoading = false)
            } catch (e: ApiError) {
                state.value = state.value.copy(isLoading = false, error = e)
            }
        }
    }
}

interface ProfileInteractor {
    suspend fun refresh()
}
