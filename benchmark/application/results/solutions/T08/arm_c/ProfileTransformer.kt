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
            is ApiError.Network -> ErrorModel(messageRes = NETWORK_ERROR_MESSAGE_RES)
            is ApiError.Validation -> ErrorModel(messageRes = VALIDATION_ERROR_MESSAGE_RES)
        }

    private companion object {
        const val NETWORK_ERROR_MESSAGE_RES = 1
        const val VALIDATION_ERROR_MESSAGE_RES = 2
    }
}
