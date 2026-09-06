package com.example.settings

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

class SettingsReader(private val context: Context) {

    // blocking-чтение файла настроек
    suspend fun readConfig(): String = withContext(Dispatchers.IO) {
        File(context.filesDir, "config.json").readText()
    }

    // blocking-чтение файла темы
    suspend fun readTheme(): String = withContext(Dispatchers.IO) {
        File(context.filesDir, "theme.json").readText()
    }
}
