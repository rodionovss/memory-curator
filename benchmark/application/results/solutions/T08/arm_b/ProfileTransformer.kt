package com.example.profile

import javax.inject.Inject

class ProfileTransformer @Inject constructor() {

    fun toRender(state: ProfileState): ProfileRender =
        ProfileRender(
            isLoading = state.isLoading,
            errorState = state.error.toErrorModel(),
        )

    private fun ApiError?.toErrorModel(): ErrorModel? =
        when (this) {
            is ApiError.Validation -> ErrorModel(VALIDATION_ERROR_MESSAGE_RES)
            else -> null
        }

    private companion object {
        const val VALIDATION_ERROR_MESSAGE_RES = 0
    }
}
