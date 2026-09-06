package com.example.detail

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import javax.inject.Inject

class DetailViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
) : ViewModel() {

    // id зашит в route pattern навигации: "detail/{id}" — отсутствие это программная ошибка,
    // падаем явно, а не гасим заглушкой
    private val id: String = requireNotNull(savedStateHandle.get<String>("id")) {
        "Missing required 'id' argument (route pattern \"detail/{id}\")"
    }
}
