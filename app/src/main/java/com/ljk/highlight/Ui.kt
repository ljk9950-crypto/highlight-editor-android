package com.ljk.highlight

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// ───────── 테마 A(스카이 팝) ─────────
data class Pal(
    val bgFrom: Color, val bgTo: Color, val card: Color, val line: Color, val ink: Color, val sub: Color,
    val pri: Color, val prib: Color, val start: Color, val end: Color, val acc: Color, val go: Color,
    val video: Color, val field: Color, val fline: Color, val danger: Color, val seg: Color,
    val onPri: Color, val dis: Color, val disInk: Color, val rowSel: Color, val rowAct: Color, val rowDel: Color,
    val dstart: Color, val dend: Color, val note: Color, val noteInk: Color, val dark: Boolean,
)

val LightPal = Pal(
    Color(0xFFE8F4FF), Color(0xFFFFF4CC), Color(0xFFFFFFFF), Color(0xFFCFE6FA), Color(0xFF14263D), Color(0xFF5B6F86),
    Color(0xFF2F80ED), Color(0xFFDCEBFF), Color(0xFF18B26B), Color(0xFFFF7A45), Color(0xFFFFC93C), Color(0xFF7C5CFF),
    Color(0xFF0E2238), Color(0xFFF3F9FF), Color(0xFFB7D6F4), Color(0xFFE5484D), Color(0xFFFF9F43),
    Color.White, Color(0xFFE4EDF6), Color(0xFF8CA0B8), Color(0xFFFFF6D6), Color(0xFFFFE9DA), Color(0xFFFFE4E4),
    Color(0xFFE5484D), Color(0xFF9B2C34), Color(0xFFFFF8E1), Color(0xFF7A5200), false,
)

val DarkPal = Pal(
    Color(0xFF0E1A2B), Color(0xFF16233A), Color(0xFF18283F), Color(0xFF294262), Color(0xFFEAF3FF), Color(0xFF9DB2CC),
    Color(0xFF5BA8FF), Color(0xFF22406A), Color(0xFF2BD283), Color(0xFFFF8A57), Color(0xFFFFD35C), Color(0xFF8E78FF),
    Color(0xFF050C16), Color(0xFF102036), Color(0xFF355278), Color(0xFFFF6B70), Color(0xFFFFA84F),
    Color(0xFF0E1A2B), Color(0xFF223149), Color(0xFF60758F), Color(0xFF3A3320), Color(0xFF4A2E22), Color(0xFF4A2328),
    Color(0xFFFF6B70), Color(0xFFC2454D), Color(0xFF3A3320), Color(0xFFFFD98A), true,
)

val LocalPal = staticCompositionLocalOf { LightPal }

enum class Kind { Normal, Primary, Soft, Start, End, Danger, Go, DStart, DEnd, Sel }

@Composable
fun PBtn(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    kind: Kind = Kind.Normal,
    enabled: Boolean = true,
    big: Boolean = false,
    small: Boolean = false,
) {
    val p = LocalPal.current
    val (bg, fg, bd) = when (kind) {
        Kind.Normal -> Triple(p.card, p.ink, p.fline)
        Kind.Primary, Kind.Sel -> Triple(p.pri, p.onPri, p.pri)
        Kind.Soft -> Triple(p.prib, p.pri, p.prib)
        Kind.Start -> Triple(p.start, Color.White, p.start)
        Kind.End -> Triple(p.end, Color.White, p.end)
        Kind.Danger -> Triple(p.card, p.danger, p.danger)
        Kind.Go -> Triple(p.go, Color.White, p.go)
        Kind.DStart -> Triple(p.dstart, Color.White, p.dstart)
        Kind.DEnd -> Triple(p.dend, Color.White, p.dend)
    }
    val shape = RoundedCornerShape(if (big) 14.dp else 12.dp)
    Box(
        modifier
            .heightIn(min = if (big) 52.dp else if (small) 32.dp else 40.dp)
            .clip(shape)
            .background(if (enabled) bg else p.dis)
            .border(2.dp, if (enabled) bd else p.dis, shape)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = if (small) 8.dp else 12.dp, vertical = 4.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text, color = if (enabled) fg else p.disInk, fontWeight = FontWeight.Bold,
            fontSize = if (big) 17.sp else if (small) 13.sp else 14.sp, maxLines = 1, textAlign = TextAlign.Center,
        )
    }
}

@Composable
fun SCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val p = LocalPal.current
    val shape = RoundedCornerShape(16.dp)
    Column(
        modifier
            .fillMaxWidth()
            .shadow(3.dp, shape, ambientColor = p.pri.copy(alpha = 0.2f), spotColor = p.pri.copy(alpha = 0.2f))
            .clip(shape)
            .background(p.card)
            .border(1.dp, p.line, shape)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        content = content,
    )
}

@Composable
fun H(text: String) = Text(text, color = LocalPal.current.ink, fontWeight = FontWeight.Bold, fontSize = 16.sp)

@Composable
fun Sub(text: String, modifier: Modifier = Modifier, color: Color? = null, size: TextUnit = 13.sp) =
    Text(text, modifier = modifier, color = color ?: LocalPal.current.sub, fontSize = size)

@Composable
fun BRow(modifier: Modifier = Modifier, gap: Dp = 6.dp, content: @Composable RowScope.() -> Unit) =
    Row(modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(gap),
        verticalAlignment = Alignment.CenterVertically, content = content)

@Composable
fun Field(
    value: String,
    onChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = "",
    enabled: Boolean = true,
    number: Boolean = false,
    center: Boolean = false,
) {
    val p = LocalPal.current
    val shape = RoundedCornerShape(10.dp)
    BasicTextField(
        value = value,
        onValueChange = onChange,
        enabled = enabled,
        singleLine = true,
        textStyle = TextStyle(color = if (enabled) p.ink else p.disInk, fontSize = 15.sp,
            textAlign = if (center) TextAlign.Center else TextAlign.Start),
        cursorBrush = SolidColor(p.pri),
        keyboardOptions = if (number) KeyboardOptions(keyboardType = KeyboardType.Decimal) else KeyboardOptions.Default,
        modifier = modifier
            .heightIn(min = 40.dp)
            .clip(shape)
            .background(if (enabled) p.field else p.dis)
            .border(2.dp, p.fline, shape),
        decorationBox = { inner ->
            Box(Modifier.padding(horizontal = 10.dp, vertical = 9.dp), contentAlignment = if (center) Alignment.Center else Alignment.CenterStart) {
                if (value.isEmpty()) Text(placeholder, color = p.disInk, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                inner()
            }
        },
    )
}

@Composable
fun Check(label: String, checked: Boolean, onChange: (Boolean) -> Unit, enabled: Boolean = true) {
    val p = LocalPal.current
    Row(
        Modifier
            .clip(RoundedCornerShape(8.dp))
            .clickable(enabled = enabled) { onChange(!checked) }
            .padding(4.dp)
            .alpha(if (enabled) 1f else 0.5f),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(
            Modifier
                .size(22.dp)
                .clip(RoundedCornerShape(5.dp))
                .background(if (checked) p.pri else p.field)
                .border(2.dp, if (checked) p.pri else p.fline, RoundedCornerShape(5.dp)),
            contentAlignment = Alignment.Center,
        ) { if (checked) Text("✓", color = p.onPri, fontWeight = FontWeight.Bold, fontSize = 14.sp) }
        Text(label, color = p.ink, fontWeight = FontWeight.Bold, fontSize = 15.sp)
    }
}

@Composable
fun Picker(
    value: String,
    options: List<String>,
    onPick: (String) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    var open by remember { mutableStateOf(false) }
    val p = LocalPal.current
    Box(modifier) {
        PBtn("$value ▾", { open = true }, Modifier.fillMaxWidth(), Kind.Normal, enabled, small = true)
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            options.forEach { o ->
                DropdownMenuItem(text = { Text(o, color = p.ink) }, onClick = { open = false; onPick(o) })
            }
        }
    }
}

/** 세그먼트 버튼(여러 개 중 하나 선택) */
@Composable
fun Seg(options: List<String>, selected: String?, onPick: (String) -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        options.forEach { o ->
            PBtn(o, { onPick(o) }, Modifier.weight(1f), if (o == selected) Kind.Sel else Kind.Soft, enabled, small = true)
        }
    }
}

@Composable
fun Pill(text: String, on: Boolean) {
    val p = LocalPal.current
    Box(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(if (on) p.end else p.dis)
            .padding(horizontal = 14.dp, vertical = 6.dp)
    ) {
        Text(text, color = if (on) Color.White else p.sub, fontSize = 13.sp,
            fontWeight = if (on) FontWeight.Bold else FontWeight.Normal, maxLines = 2)
    }
}

@Composable
fun Note(text: String) {
    val p = LocalPal.current
    Text(
        text,
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(p.note)
            .padding(horizontal = 10.dp, vertical = 6.dp),
        color = p.noteInk, fontSize = 12.sp,
    )
}

@Composable
fun Ghost(text: String) {
    val p = LocalPal.current
    Box(
        Modifier
            .fillMaxWidth()
            .border(BorderStroke(2.dp, p.fline), RoundedCornerShape(12.dp))
            .padding(12.dp),
        contentAlignment = Alignment.Center,
    ) { Text(text, color = p.sub, fontSize = 13.sp, textAlign = TextAlign.Center) }
}

@Composable
fun Progress(fraction: Float) {
    val p = LocalPal.current
    Box(
        Modifier
            .fillMaxWidth()
            .height(14.dp)
            .clip(RoundedCornerShape(7.dp))
            .background(p.field)
            .border(1.dp, p.fline, RoundedCornerShape(7.dp))
    ) {
        Box(
            Modifier
                .fillMaxWidth(fraction.coerceIn(0f, 1f))
                .height(14.dp)
                .background(p.go)
        )
    }
}

/** 재생 위치 막대: 지정한 구간(색 막대)과 지정 중 구간(줄무늬) 표시, 눌러서/끌어서 이동 */
@Composable
fun SeekBar(
    duration: Double,
    position: Double,
    segments: List<Pair<Double, Double>>,
    active: Pair<Double, Double>?,
    onSeek: (Double) -> Unit,
    segColor: Color? = null,
) {
    val p = LocalPal.current
    val seek by rememberUpdatedState(onSeek)
    val dur by rememberUpdatedState(duration)
    val c = segColor ?: p.seg
    Canvas(
        Modifier
            .fillMaxWidth()
            .height(30.dp)
            .pointerInput(Unit) {
                detectTapGestures { o -> if (dur > 0) seek((o.x / size.width).coerceIn(0f, 1f) * dur) }
            }
            .pointerInput(Unit) {
                detectHorizontalDragGestures { ch, _ ->
                    if (dur > 0) seek((ch.position.x / size.width).coerceIn(0f, 1f) * dur)
                }
            }
    ) {
        val top = size.height / 2 - 9.dp.toPx()
        val h = 18.dp.toPx()
        drawRoundRect(p.field, Offset(0f, top), Size(size.width, h), CornerRadius(h / 2))
        drawRoundRect(p.fline, Offset(0f, top), Size(size.width, h), CornerRadius(h / 2),
            style = androidx.compose.ui.graphics.drawscope.Stroke(1.dp.toPx()))
        if (duration > 0) {
            fun x(t: Double) = (t / duration * size.width).toFloat()
            for ((s, e) in segments) {
                drawRoundRect(c, Offset(x(s), top + 3), Size(max(3f, x(e) - x(s)), h - 6), CornerRadius(6f))
            }
            active?.let { (s, e) ->
                drawRoundRect(
                    Brush.linearGradient(listOf(c, Color.White.copy(alpha = 0.6f), c)),
                    Offset(x(s), top + 3), Size(max(3f, x(e) - x(s)), h - 6), CornerRadius(6f)
                )
            }
            val hx = x(position)
            drawRoundRect(p.ink, Offset(hx - 2.dp.toPx(), top - 4.dp.toPx()), Size(4.dp.toPx(), h + 8.dp.toPx()), CornerRadius(4f))
        }
    }
}

private fun max(a: Float, b: Float) = if (a > b) a else b

val NoPad = PaddingValues(0.dp)
