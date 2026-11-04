package com.ljk.highlight

import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class Clip(val uri: Uri, val info: VideoInfo, val thumb: Bitmap?)

class MergeState(ctx: Context) {
    val ph = PlayerHolder(ctx)
    val ex = ExportState()
    val clips = mutableStateListOf<Clip>()
    var sel by mutableIntStateOf(-1)
}

@Composable
fun MergeTab(s: MergeState, ui: AppUi) {
    val ctx = LocalContext.current
    val scope = rememberScope()
    val p = LocalPal.current
    TrackPosition(s.ph)

    fun select(i: Int) {
        s.sel = i
        s.ph.load(s.clips.getOrNull(i)?.uri)
    }

    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isEmpty()) return@rememberLauncherForActivityResult
        scope.launch {
            val bad = mutableListOf<String>()
            for (u in uris) {
                takeRead(ctx, u)
                try {
                    val c = withContext(Dispatchers.IO) { Clip(u, probe(ctx, u), thumbnail(ctx, u)) }
                    s.clips.add(c)
                } catch (e: Exception) {
                    bad.add(queryName(ctx, u))
                }
            }
            if (s.sel < 0 && s.clips.isNotEmpty()) select(0)
            if (bad.isNotEmpty()) ui.alert("열 수 없는 파일은 빼고 추가했습니다:\n" + bad.joinToString("\n"))
        }
    }

    fun move(i: Int, d: Int) {
        val j = i + d
        if (j !in s.clips.indices) return
        val c = s.clips.removeAt(i)
        s.clips.add(j, c)
        if (s.sel == i) s.sel = j else if (s.sel == j) s.sel = i
    }

    fun warns(c: Clip): List<String> {
        val f = s.clips.firstOrNull() ?: return emptyList()
        val w = mutableListOf<String>()
        if (c !== f && (c.info.width != f.info.width || c.info.height != f.info.height)) w.add("크기 다름 → 맞춤")
        return w
    }

    fun go() {
        try {
            val (comp, _) = Exporter.mergeComposition(s.clips.map { it.uri to it.info })
            val f = s.clips[0].info
            s.ph.stop()
            startExport(ctx, scope, s.ex, comp, true, f.width * f.height, outName(f.name, "합치기"), ui::alert)
        } catch (e: Exception) {
            ui.alert(e.message ?: "시작하지 못했습니다.")
        }
    }

    val cur = s.clips.getOrNull(s.sel)

    @Composable
    fun PreviewPart(modifier: Modifier) {
        Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
            VideoBox(s.ph, cur?.info, "목록에서 영상을 선택하면\n여기에 나옵니다")
            SeekBar(cur?.info?.duration ?: 0.0, s.ph.position, emptyList(), null, { s.ph.seek(it) })
            BRow(gap = 4.dp) {
                val d = cur?.info?.duration ?: 0.0
                listOf(-5.0, -2.0, -1.0).forEach { x -> PBtn("${x.toInt()}", { s.ph.seekRel(x, d) }, Modifier.weight(1f), Kind.Soft, small = true) }
                PBtn(if (s.ph.playing) "❚❚" else "▶", { s.ph.toggle() }, Modifier.weight(1.3f), Kind.Primary, cur != null)
                listOf(1.0, 2.0, 5.0).forEach { x -> PBtn("+${x.toInt()}", { s.ph.seekRel(x, d) }, Modifier.weight(1f), Kind.Soft, small = true) }
            }
            val total = s.clips.sumOf { it.info.duration }
            Sub(if (s.clips.isEmpty()) "영상을 추가하면 합친 영상의 크기·길이가 여기에 표시됩니다."
                else "합친 영상: ${s.clips[0].info.width}×${s.clips[0].info.height} · ${s.clips.size}개 · 약 ${fmtTime(total)}")
        }
    }

    fun LazyListScope.listPart() {
        item {
            SCard {
                H("1. 영상 추가")
                PBtn("영상 파일 추가 (여러 개 선택 가능)", { pick.launch(arrayOf("video/*")) }, Modifier.fillMaxWidth(), Kind.Primary)
                Note("목록 순서대로 이어 붙입니다. ↑↓로 순서를 바꾸세요. (부드럽게 전환 기능은 휴대폰판에서 지원하지 않습니다)")
            }
        }
        item { SCard { H("2. 합칠 영상 목록"); if (s.clips.isEmpty()) Ghost("[영상 파일 추가]를 누르면 여기에 추가됩니다") } }
        itemsIndexed(s.clips) { i, c ->
            val shape = RoundedCornerShape(12.dp)
            val selected = i == s.sel
            BRow(
                Modifier
                    .clip(shape)
                    .background(if (selected) p.rowSel else p.field)
                    .border(2.dp, if (selected) p.acc else p.line, shape)
                    .clickable { select(i) }
                    .padding(8.dp),
                gap = 8.dp,
            ) {
                Box(Modifier.size(84.dp, 48.dp).clip(RoundedCornerShape(6.dp)).background(p.video)) {
                    c.thumb?.let { Image(it.asImageBitmap(), null, Modifier.fillMaxSize(), contentScale = ContentScale.Crop) }
                }
                Column(Modifier.weight(1f)) {
                    Text("${i + 1}. ${c.info.name}", color = p.ink, fontWeight = FontWeight.Bold, fontSize = 14.sp,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Sub("${c.info.width}×${c.info.height} · ${fmtTime(c.info.duration)}${if (c.info.hdr) " · HDR" else ""}${if (!c.info.hasAudio) " · 소리 없음" else ""}", size = 12.sp)
                    warns(c).forEach { Sub(it, color = p.end, size = 12.sp) }
                }
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    PBtn("↑", { move(i, -1) }, Modifier.width(40.dp), Kind.Soft, i > 0, small = true)
                    PBtn("↓", { move(i, 1) }, Modifier.width(40.dp), Kind.Soft, i < s.clips.size - 1, small = true)
                }
                PBtn("✕", {
                    s.clips.removeAt(i)
                    if (s.sel == i) select(if (s.clips.isEmpty()) -1 else minOf(i, s.clips.size - 1))
                    else if (s.sel > i) s.sel -= 1
                    Unit
                }, kind = Kind.Danger, small = true)
            }
        }
        item {
            SCard {
                PBtn("전체 초기화", { s.clips.clear(); select(-1) }, Modifier.fillMaxWidth(), Kind.Danger, s.clips.isNotEmpty())
            }
        }
        item {
            ExportCard("3. 합치기 및 저장", s.ex, "합치기 시작 (MP4로 저장)", "", ::go)
            if (s.clips.any { it.info.hdr }) Note("HDR 영상은 일반(SDR) 색상으로 바꿔 합칩니다.")
        }
    }

    BoxWithConstraints(Modifier.fillMaxSize()) {
        if (maxWidth > maxHeight) {
            Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                PreviewPart(Modifier.weight(1.1f).fillMaxHeight().verticalScroll(rememberScrollState()))
                LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) { listPart() }
            }
        } else {
            Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                PreviewPart(Modifier.fillMaxWidth())
                LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) { listPart() }
            }
        }
    }
}
