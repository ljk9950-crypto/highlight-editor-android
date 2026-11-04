package com.ljk.highlight

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** 알림/선택 창 */
data class Dlg(val text: String, val actions: List<Pair<String, () -> Unit>> = emptyList())

class AppUi {
    var dlg by mutableStateOf<Dlg?>(null)
    fun alert(text: String) {
        dlg = Dlg(text)
    }

    fun ask(text: String, vararg actions: Pair<String, () -> Unit>) {
        dlg = Dlg(text, actions.toList())
    }
}

fun takeRead(ctx: Context, uri: Uri) {
    try {
        ctx.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
    } catch (_: Exception) {
    }
}

/** 시간 입력칸: 입력을 마치면(완료/다른 곳 누름) 반영합니다. 잘못 입력하면 원래 값으로 돌아갑니다. */
@Composable
fun TimeField(value: Double?, onCommit: (Double?) -> Boolean, modifier: Modifier = Modifier, enabled: Boolean = true) {
    val p = LocalPal.current
    val shown = fmtTime(value)
    var text by remember(shown) { mutableStateOf(shown) }
    var focused by remember { mutableStateOf(false) }
    val fm = LocalFocusManager.current
    fun commit() {
        if (text == shown) return
        val v = if (text.isBlank()) null else parseTime(text)
        if ((text.isNotBlank() && v == null) || !onCommit(v)) text = shown
    }
    val shape = RoundedCornerShape(10.dp)
    BasicTextField(
        value = text,
        onValueChange = { text = it },
        enabled = enabled,
        singleLine = true,
        textStyle = TextStyle(color = p.ink, fontSize = 14.sp, textAlign = TextAlign.Center),
        cursorBrush = SolidColor(p.pri),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text, imeAction = ImeAction.Done),
        keyboardActions = KeyboardActions(onDone = { commit(); fm.clearFocus() }),
        modifier = modifier
            .heightIn(min = 36.dp)
            .clip(shape)
            .background(if (enabled) p.field else p.dis)
            .border(2.dp, if (focused) p.acc else p.fline, shape)
            .onFocusChanged { f ->
                if (focused && !f.isFocused) commit()
                focused = f.isFocused
            },
        decorationBox = { inner ->
            Box(Modifier.padding(horizontal = 4.dp, vertical = 8.dp), contentAlignment = Alignment.Center) {
                if (text.isEmpty()) androidx.compose.material3.Text("00:00.0", color = p.disInk, fontSize = 13.sp)
                inner()
            }
        },
    )
}
