package com.example.api

import retrofit2.http.GET

interface UserApi {

    @GET("v1/user/profile")
    suspend fun getProfile(): ProfileDto

    @GET("v1/user/settings")
    suspend fun getSettings(): SettingsDto
}
