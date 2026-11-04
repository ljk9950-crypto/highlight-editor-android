package com.ljk.highlight

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.ui.Alignment
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.layout.Box
import androidx.activity.compose.BackHandler
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
    var page by mutableIntStateOf(0)
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

    val listState = rememberLazyListState()
    LaunchedEffect(s.dels.size) { if (s.dels.isNotEmpty()) listState.animateScrollToItem(s.dels.size - 1) }

    if (s.page == 1) {
        BackHandler { s.page = 0 }
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            BRow { PBtn("◂ 구간 지정으로", { s.page = 0 }, kind = Kind.Soft, small = true); H("저장 설정") }
            SCard {
                H("1. 영상")
                Sub(s.info?.let { "${it.name} · ${it.width}×${it.height} · ${fmtTime(it.duration)}" } ?: "선택된 영상이 없습니다.")
                PBtn("영상 선택", { pick.launch(arrayOf("video/*")) }, Modifier.fillMaxWidth(), Kind.Primary)
            }
            SCard {
                H("2. 목록 정리")
                BRow {
                    Text("지울 구간 ${done.size}개 · ${fmtSecs(delTotal)} 삭제 → 남는 길이 약 ${fmtSecs((s.dur - delTotal).coerceAtLeast(0.0))}",
                        color = p.ink, fontWeight = FontWeight.Bold, fontSize = 13.sp, modifier = Modifier.weight(1f))
                    PBtn("전체 초기화", { s.dels.clear() }, kind = Kind.Danger, small = true, enabled = s.dels.isNotEmpty())
                }
                Note("휴대폰판은 정확한 위치에서 자르도록 영상을 다시 만듭니다(원본 화질·HDR 유지). 길이가 길면 시간이 걸립니다.")
            }
            ExportCard("3. 잘라내고 저장", s.ex, "잘라내기 시작 (MP4로 저장)", "", ::go)
            Sub("※ 저장된 영상: 갤러리 › 앨범 › Movies(농구하이라이트)", Modifier.padding(4.dp), size = 12.sp)
        }
        return
    }

    @Composable
    fun PlayerPart(modifier: Modifier) {
        Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
            BRow {
                PBtn("📂 영상 선택", { pick.launch(arrayOf("video/*")) }, kind = Kind.Soft, small = true)
                Sub(s.info?.let { "${it.name} · ${fmtTime(it.duration)}" } ?: "선택된 영상이 없습니다.", Modifier.weight(1f), size = 12.sp)
            }
            VideoBox(s.ph, s.info, "[영상 선택]을 눌러\n자를 영상을 불러오세요")
            SeekBar(s.dur, s.ph.position, done, if (ai >= 0) s.dels[ai].start to s.ph.position else null, { s.ph.seek(it) }, p.dstart)
            BRow(gap = 4.dp) {
                listOf(-5.0, -2.0, -1.0).forEach { d -> PBtn("${d.toInt()}", { s.ph.seekRel(d, s.dur) }, Modifier.weight(1f), Kind.Soft, small = true) }
                PBtn(if (s.ph.playing) "❚❚" else "▶", { s.ph.toggle() }, Modifier.weight(1.3f), Kind.Primary, s.info != null, small = true)
                listOf(1.0, 2.0, 5.0).forEach { d -> PBtn("+${d.toInt()}", { s.ph.seekRel(d, s.dur) }, Modifier.weight(1f), Kind.Soft, small = true) }
            }
        }
    }

    @Composable
    fun ListPart(modifier: Modifier) {
        Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
            BRow {
                H("지울 구간 목록")
                Sub("${done.size}개 · ${fmtSecs(delTotal)} 삭제", Modifier.weight(1f))
                Sub(fmtTime(s.ph.position), size = 12.sp)
                Picker(s.ph.speed, listOf("0.5x", "1x", "1.5x", "2x"), { s.ph.changeSpeed(it) }, Modifier.width(72.dp))
            }
            Box(Modifier.weight(1f).fillMaxWidth()) {
                if (s.dels.isEmpty()) {
                    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Bottom) {
                        Ghost(if (s.info == null) "[영상 선택]으로 자를 영상을 불러오세요"
                              else "지울 장면이 시작되면 [삭제 시작]을 누르세요.\n새 구간은 여기(버튼 바로 위)에 추가됩니다.")
                    }
                }
                LazyColumn(Modifier.fillMaxSize(), state = listState,
                    verticalArrangement = Arrangement.spacedBy(6.dp, Alignment.Bottom)) {
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
                            Text(d.end?.let { fmtSecs(it - d.start) } ?: "-", color = p.ink, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                            PBtn("▶", { d.end?.let { e -> s.ph.playRange(d.start, e) } }, kind = Kind.Soft, small = true, enabled = !act)
                            PBtn("✕", { s.dels.removeAt(i) }, kind = Kind.Danger, small = true)
                        }
                    }
                }
            }
            BRow {
                PBtn("삭제 시작", ::start, Modifier.weight(1f), Kind.DStart, s.info != null && ai < 0, big = true)
                PBtn("삭제 종료", ::end, Modifier.weight(1f), Kind.DEnd, ai >= 0, big = true)
                PBtn(if (s.ex.running) "저장 중 ${s.ex.progress}%" else "저장 ▸", { s.page = 1 }, Modifier.weight(0.85f), Kind.Go, big = true)
            }
        }
    }

    BoxWithConstraints(Modifier.fillMaxSize()) {
        if (maxWidth > maxHeight) {
            Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                PlayerPart(Modifier.weight(1.1f).fillMaxHeight().verticalScroll(rememberScrollState()))
                ListPart(Modifier.weight(1f).fillMaxHeight())
            }
        } else {
            Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                PlayerPart(Modifier.fillMaxWidth())
                ListPart(Modifier.weight(1f).fillMaxWidth())
            }
        }
    }
}
