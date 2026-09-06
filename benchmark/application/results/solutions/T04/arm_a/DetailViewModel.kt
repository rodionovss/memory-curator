package com.example.detail

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import javax.inject.Inject

class DetailViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
) : ViewModel() {

    // id зашит в route pattern навигации: "detail/{id}"
    private val id: String = checkNotNull(savedStateHandle.get<String>("id")) {
        "Required argument 'id' from route pattern 'detail/{id}' is missing"
    }
}
