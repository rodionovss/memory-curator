package com.example.profile

data class ProfileState(
    val isLoading: Boolean = false,
    val error: ApiError? = null,
)
