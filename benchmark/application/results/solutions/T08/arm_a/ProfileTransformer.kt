package com.example.profile

import javax.inject.Inject

class ProfileTransformer @Inject constructor() {

    fun toRender(state: ProfileState): ProfileRender =
        ProfileRender(
            isLoading = state.isLoading,
            errorState = state.error?.toErrorModel(),
        )

    private fun ApiError.toErrorModel(): ErrorModel =
        when (this) {
            is ApiError.Validation -> ErrorModel(messageRes = VALIDATION_ERROR_RES)
            ApiError.Network -> ErrorModel(messageRes = NETWORK_ERROR_RES)
        }

    private companion object {
        const val VALIDATION_ERROR_RES = 1
        const val NETWORK_ERROR_RES = 2
    }
}
