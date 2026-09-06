package com.example.api

import retrofit2.http.GET

interface UserApi {

    @GET("v1/user/profile")
    suspend fun getProfile(): ProfileDto
}
