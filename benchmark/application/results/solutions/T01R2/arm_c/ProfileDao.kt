package com.example.profile

import androidx.room.Dao
import androidx.room.Query

@Dao
interface ProfileDao {

    @Query("SELECT name FROM profiles WHERE id = :id")
    suspend fun getUserName(id: Long): String

    @Query("UPDATE profiles SET avatarUrl = :url WHERE id = :id")
    suspend fun updateAvatar(id: Long, url: String)

    @Query("SELECT * FROM profiles WHERE id = :id")
    suspend fun getProfileById(id: Long): Profile
}
