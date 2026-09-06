package com.example.detail

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import javax.inject.Inject

class DetailViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
) : ViewModel() {

    // id зашит в route pattern навигации: "detail/{id}"
    private val id: String = savedStateHandle.get<String>("id") ?: ""
}
