package com.example.app.ui.profile

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.sp

@Composable
fun ProfileScreen(modifier: Modifier = Modifier) {
    Column(modifier = modifier) {
        Text(
            text = "Профиль",
            fontSize = 32.sp,
            modifier = Modifier.fillMaxWidth(),
        )
        LazyColumn(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f),
        ) {
        }
    }
}
