import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.weight
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

@Composable
fun ProfileScreen(modifier: Modifier = Modifier) {
    Column(modifier = modifier) {
        Text(
            text = "Профиль",
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
