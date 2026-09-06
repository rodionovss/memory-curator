package com.example.profile

import javax.inject.Inject

class ProfileTransformer @Inject constructor() {

    fun toRender(state: ProfileState): ProfileRender =
        ProfileRender(isLoading = state.isLoading)
}
