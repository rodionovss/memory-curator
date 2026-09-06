package com.example.profile

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage

@Composable
fun ProfileItem(
    name: String,
    email: String,
    avatar: Any?,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(8.dp),
    ) {
        AsyncImage(
            model = avatar,
            contentDescription = null,
            modifier = Modifier.size(48.dp),
        )
        Column(
            modifier = Modifier
                .weight(1f)
                .padding(start = 12.dp),
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
