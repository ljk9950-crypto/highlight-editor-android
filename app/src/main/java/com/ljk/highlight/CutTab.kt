package com.ljk.highlight

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
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
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** 지울 구간 한 줄. end == null 이면 '지정 중' */
data class Del(val start: Double, val end: Double?)

class CutState(ctx: Context) {
    val ph = PlayerHolder(ctx)
    val ex = ExportState()
    var uri by mutableStateOf<Uri?>(null)
    var info by mutableStateOf<VideoInfo?>(null)
    val dels = mutableStateListOf<Del>()
    val dur: Double get() = info?.duration ?: 0.0
    val activeIndex: Int get() = dels.indexOfFirst { it.end == null }
}

@Composable
fun CutTab(s: CutState, ui: AppUi) {
    val ctx = LocalContext.current
    val scope = rememberScope()
    val p = LocalPal.current
    TrackPosition(s.ph)

    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            takeRead(ctx, uri)
            scope.launch {
                try {
                    val info = withContext(Dispatchers.IO) { probe(ctx, uri) }
                    s.uri = uri; s.info = info; s.dels.clear(); s.ph.load(uri)
                    s.ex.result = null; s.ex.status = "대기 중"
                } catch (e: Exception) {
                    ui.alert(e.message ?: "영상을 열 수 없습니다.")
                }
            }
        }
    }

    val ai = s.activeIndex
    val done = s.dels.filter { it.end != null }.map { it.start to it.end!! }
    val keep = keepRanges(done, s.dur)
    val delTotal = mergeRanges(done, s.dur).sumOf { it.second - it.first }

    fun start() {
        if (s.info == null) { ui.alert("먼저 [영상 선택]으로 영상을 불러와 주세요."); return }
        if (ai >= 0) { ui.alert("이미 [삭제 시작]을 눌렀습니다. 먼저 [삭제 종료]를 눌러 주세요."); return }
        s.dels.add(Del(s.ph.position, null))
    }

    fun end() {
        if (ai < 0) { ui.alert("먼저 [삭제 시작]을 눌러 주세요."); return }
        val d = s.dels[ai]
        if (s.ph.position <= d.start) { ui.alert("종료 위치가 시작 위치보다 앞입니다. 영상을 더 재생한 뒤 눌러 주세요."); return }
        s.dels[ai] = d.copy(end = s.ph.position)
    }

    fun go() {
        val uri = s.uri ?: run { ui.alert("먼저 영상을 불러와 주세요."); return }
        val info = s.info ?: return
        if (ai >= 0) { ui.alert("지정 중인 구간이 있습니다. [삭제 종료]를 누르거나 [지정 취소]를 눌러 주세요."); return }
        if (done.isEmpty()) { ui.alert("지울 구간이 없습니다. [삭제 시작] → [삭제 종료]로 지울 부분을 지정해 주세요."); return }
        try {
            val comp = Exporter.cutComposition(uri, keep)
            s.ph.stop()
            // 컷 편집은 원본 형식(코덱·HDR)을 그대로 유지합니다.
            startExport(ctx, scope, s.ex, comp, false, info.width * info.height, outName(info.name, "컷편집"), ui::alert)
        } catch (e: Exception) {
            ui.alert(e.message ?: "시작하지 못했습니다.")
        }
    }

    @Composable
    fun PlayerPart(modifier: Modifier) {
        Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Pill(
                when {
                    s.info == null -> "영상을 선택하면 지울 구간을 지정할 수 있습니다"
                    ai >= 0 -> "지울 구간 지정 중 · ${fmtTime(s.dels[ai].start)}부터"
                    else -> "지울 장면이 시작되면 [삭제 시작]을 누르세요"
                }, ai >= 0
            )
            VideoBox(s.ph, s.info, "[영상 선택]을 눌러\n자를 영상을 불러오세요")
            SeekBar(s.dur, s.ph.position, done, if (ai >= 0) s.dels[ai].start to s.ph.position else null, { s.ph.seek(it) }, p.dstart)
            BRow {
                Sub("${fmtTime(s.ph.position)} / ${fmtTime(s.dur)}", Modifier.weight(1f))
                Sub("배속")
                Picker(s.ph.speed, listOf("0.5x", "1x", "1.5x", "2x"), { s.ph.setSpeed(it) }, Modifier.width(84.dp))
            }
            BRow(gap = 4.dp) {
                listOf(-5.0, -2.0, -1.0).forEach { d -> PBtn("${d.toInt()}", { s.ph.seekRel(d, s.dur) }, Modifier.weight(1f), Kind.Soft, small = true) }
                PBtn(if (s.ph.playing) "❚❚" else "▶", { s.ph.toggle() }, Modifier.weight(1.3f), Kind.Primary, s.info != null)
                listOf(1.0, 2.0, 5.0).forEach { d -> PBtn("+${d.toInt()}", { s.ph.seekRel(d, s.dur) }, Modifier.weight(1f), Kind.Soft, small = true) }
            }
            BRow {
                PBtn("삭제 시작", ::start, Modifier.weight(1f), Kind.DStart, s.info != null && ai < 0, big = true)
                PBtn("삭제 종료", ::end, Modifier.weight(1f), Kind.DEnd, ai >= 0, big = true)
                PBtn("지정 취소", { if (ai >= 0) s.dels.removeAt(ai) }, Modifier.weight(0.8f), Kind.Danger, ai >= 0, big = true)
            }
        }
    }

    fun LazyListScope.listPart() {
        item {
            SCard {
                BRow { H("1. 영상"); Sub(s.info?.let { "${it.name} · ${it.width}×${it.height} · ${fmtTime(it.duration)}" } ?: "선택된 영상이 없습니다.", Modifier.weight(1f)) }
                PBtn("영상 선택", { pick.launch(arrayOf("video/*")) }, Modifier.fillMaxWidth(), Kind.Primary)
            }
        }
        item {
            SCard {
                H("2. 지울 구간 목록")
                if (s.dels.isEmpty()) Ghost("[삭제 시작]을 누르면 여기에 추가됩니다")
            }
        }
        itemsIndexed(s.dels) { i, d ->
            val shape = RoundedCornerShape(12.dp)
            val act = d.end == null
            BRow(
                Modifier
                    .clip(shape)
                    .background(if (act) p.rowDel else p.card)
                    .border(2.dp, if (act) p.dstart else p.line, shape)
                    .padding(8.dp)
            ) {
                Text("${i + 1}", color = p.ink, fontWeight = FontWeight.Bold, modifier = Modifier.width(20.dp))
                TimeField(d.start, { v ->
                    if (v == null || (d.end != null && v >= d.end)) { ui.alert("시작은 종료보다 앞이어야 합니다."); false }
                    else { s.dels[i] = d.copy(start = v); true }
                }, Modifier.weight(1f))
                if (act) Text("지정 중…", color = p.dstart, fontWeight = FontWeight.Bold, fontSize = 13.sp, modifier = Modifier.weight(1f))
                else TimeField(d.end, { v ->
                    if (v == null || v <= d.start) { ui.alert("종료는 시작보다 뒤여야 합니다."); false }
                    else { s.dels[i] = d.copy(end = minOf(v, s.dur)); true }
                }, Modifier.weight(1f))
                Text(d.end?.let { fmtSecs(it - d.start) } ?: "-", color = p.ink, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                PBtn("▶", { d.end?.let { e -> s.ph.playRange(d.start, e) } }, kind = Kind.Soft, small = true, enabled = !act)
                PBtn("✕", { s.dels.removeAt(i) }, kind = Kind.Danger, small = true)
            }
        }
        item {
            SCard {
                BRow {
                    Text("지울 구간 ${done.size}개 · ${fmtSecs(delTotal)} 삭제 → 남는 길이 약 ${fmtSecs((s.dur - delTotal).coerceAtLeast(0.0))}",
                        color = p.ink, fontWeight = FontWeight.Bold, fontSize = 13.sp, modifier = Modifier.weight(1f))
                    PBtn("전체 초기화", { s.dels.clear() }, kind = Kind.Danger, small = true, enabled = s.dels.isNotEmpty())
                }
                Note("휴대폰판은 정확한 위치에서 자르도록 영상을 다시 만듭니다(원본 화질·HDR 유지). 길이가 길면 시간이 걸립니다.")
            }
        }
        item { ExportCard("3. 잘라내고 저장", s.ex, "잘라내기 시작 (MP4로 저장)", "", ::go) }
    }

    BoxWithConstraints(Modifier.fillMaxSize()) {
        if (maxWidth > maxHeight) {
            Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                PlayerPart(Modifier.weight(1.1f).fillMaxHeight().verticalScroll(rememberScrollState()))
                LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) { listPart() }
            }
        } else {
            Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                PlayerPart(Modifier.fillMaxWidth())
                LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) { listPart() }
            }
        }
    }
}
