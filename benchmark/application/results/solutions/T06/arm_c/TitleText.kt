package com.example.core.ui

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.sp

@Composable
fun TitleText(
    text: String,
    modifier: Modifier = Modifier,
) {
    Text(
        text = text,
        fontSize = 18.sp,
        modifier = modifier
            .fillMaxWidth()
            .wrapContentHeight(),
    )
}
