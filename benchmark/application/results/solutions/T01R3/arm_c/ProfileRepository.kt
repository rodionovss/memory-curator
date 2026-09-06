package com.example.profile

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import javax.inject.Inject

class ProfileRepository @Inject constructor(
    private val dao: ProfileDao,
) {

    suspend fun getUserName(id: Long): String =
        withContext(Dispatchers.IO) {
            dao.getUserName(id)
        }

    suspend fun updateAvatar(id: Long, url: String) =
        withContext(Dispatchers.IO) {
            dao.updateAvatar(id, url)
        }

    suspend fun getProfileById(id: Long): Profile = dao.getProfileById(id)
}
