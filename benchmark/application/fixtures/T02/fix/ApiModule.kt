package com.example.api

import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory

object ApiModule {

    const val BASE_URL = "https://api.example.com/mobile/api/"

    fun retrofit(): Retrofit = Retrofit.Builder()
        .baseUrl(BASE_URL)
        .addConverterFactory(MoshiConverterFactory.create())
        .build()
}
