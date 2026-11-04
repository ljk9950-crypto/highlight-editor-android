package com.ljk.highlight

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

class MainActivity : ComponentActivity() {
    private var hl: HlState? = null
    private var cut: CutState? = null
    private var mg: MergeState? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val h = HlState(this).also { hl = it }
        val c = CutState(this).also { cut = it }
        val m = MergeState(this).also { mg = it }
        val prefs = getSharedPreferences("settings", Context.MODE_PRIVATE)
        setContent {
            var mode by remember { mutableStateOf(prefs.getString("theme", "auto") ?: "auto") }
            val dark = when (mode) { "dark" -> true; "light" -> false; else -> isSystemInDarkTheme() }
            val pal = if (dark) DarkPal else LightPal
            val ui = remember { AppUi() }
            CompositionLocalProvider(LocalPal provides pal) {
                MaterialTheme(
                    colorScheme = if (dark) darkColorScheme(primary = pal.pri, surface = pal.card, background = pal.bgFrom,
                        onSurface = pal.ink, surfaceContainer = pal.card)
                    else lightColorScheme(primary = pal.pri, surface = pal.card, background = pal.bgFrom,
                        onSurface = pal.ink, surfaceContainer = pal.card)
                ) {
                    AppScreen(h, c, m, ui, mode) { nm ->
                        mode = nm
                        prefs.edit().putString("theme", nm).apply()
                    }
                }
            }
        }
    }

    override fun onPause() {
        super.onPause()
        hl?.ph?.stop(); cut?.ph?.stop(); mg?.ph?.stop()
    }

    override fun onDestroy() {
        hl?.ph?.release(); cut?.ph?.release(); mg?.ph?.release()
        super.onDestroy()
    }
}

@Composable
fun AppScreen(h: HlState, c: CutState, m: MergeState, ui: AppUi, mode: String, setMode: (String) -> Unit) {
    val p = LocalPal.current
    var tab by remember { mutableIntStateOf(0) }
    Box(
        Modifier
            .fillMaxSize()
            .background(Brush.linearGradient(listOf(p.bgFrom, p.bgTo)))
    ) {
        Column(
            Modifier
                .fillMaxSize()
                .safeDrawingPadding()
                .padding(horizontal = 12.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            // 맨 위: 제목 + 테마
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("🏀 농구 하이라이트", color = p.ink, fontWeight = FontWeight.Bold, fontSize = 17.sp, modifier = Modifier.weight(1f))
                ThemeToggle(mode, setMode)
            }
            // 탭
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                listOf("① 하이라이트", "② 구간 삭제", "③ 합치기").forEachIndexed { i, t ->
                    val on = i == tab
                    Column(
                        Modifier
                            .weight(1f)
                            .clip(RoundedCornerShape(topStart = 14.dp, topEnd = 14.dp))
                            .background(if (on) p.card else Color.Transparent)
                            .clickable {
                                if (tab != i) {
                                    h.ph.stop(); c.ph.stop(); m.ph.stop()
                                    tab = i
                                }
                            },
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Text(t, color = if (on) p.ink else p.sub, fontWeight = FontWeight.Bold, fontSize = 14.sp,
                            modifier = Modifier.padding(vertical = 9.dp))
                        Box(Modifier.fillMaxWidth().height(4.dp).background(if (on) p.acc else Color.Transparent))
                    }
                }
            }
            Box(Modifier.weight(1f)) {
                when (tab) {
                    0 -> HighlightTab(h, ui)
                    1 -> CutTab(c, ui)
                    else -> MergeTab(m, ui)
                }
            }
        }
        ui.dlg?.let { d ->
            val acts = d.actions.ifEmpty { listOf("확인" to {}) }
            AlertDialog(
                onDismissRequest = { ui.dlg = null },
                containerColor = p.card,
                text = { Text(d.text, color = p.ink, fontSize = 15.sp) },
                confirmButton = {
                    Column(horizontalAlignment = Alignment.End) {
                        acts.forEach { (label, fn) ->
                            TextButton(onClick = { ui.dlg = null; fn() }) {
                                Text(label, color = if (label == "취소") p.sub else p.pri, fontWeight = FontWeight.Bold)
                            }
                        }
                    }
                },
            )
        }
    }
}

@Composable
fun ThemeToggle(mode: String, setMode: (String) -> Unit) {
    val p = LocalPal.current
    Row(
        Modifier
            .clip(RoundedCornerShape(12.dp))
            .border(2.dp, p.fline, RoundedCornerShape(12.dp))
    ) {
        listOf("light" to "☀ 라이트", "dark" to "☾ 다크", "auto" to "자동").forEach { (k, t) ->
            val on = k == mode
            Text(
                t,
                Modifier
                    .background(if (on) p.pri else p.card)
                    .clickable { setMode(k) }
                    .padding(horizontal = 10.dp, vertical = 6.dp),
                color = if (on) p.onPri else p.sub, fontWeight = FontWeight.Bold, fontSize = 12.sp,
            )
        }
    }
}
