package com.example.profile

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

@Composable
fun ProfileItem(
    name: String,
    email: String,
    avatar: @Composable () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.padding(8.dp),
    ) {
        avatar()
        Column(
            modifier = Modifier
                .padding(start = 12.dp)
                .weight(1f),
        ) {
            Text(
                text = name,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = email,
            )
        }
    }
}
