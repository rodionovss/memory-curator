package com.example.profile

sealed class ApiError {
    data object Network : ApiError()
    data class Validation(val field: String) : ApiError()
}
