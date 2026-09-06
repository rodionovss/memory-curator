package com.example.detail

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import javax.inject.Inject

class DetailViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
) : ViewModel() {

    // id зашит в route pattern навигации: "detail/{id}" — отсутствие аргумента
    // возможно только при программной ошибке, поэтому падаем явно, а не гасим заглушкой
    private val id: String = checkNotNull(savedStateHandle.get<String>("id")) {
        "Required route argument \"id\" is missing in \"detail/{id}\""
    }
}
