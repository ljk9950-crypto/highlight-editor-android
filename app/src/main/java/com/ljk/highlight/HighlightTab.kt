package com.ljk.highlight

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.layout.Box
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale

class HlState(ctx: Context) {
    val ph = PlayerHolder(ctx)
    val ex = ExportState()
    var uri by mutableStateOf<Uri?>(null)
    var info by mutableStateOf<VideoInfo?>(null)
    val rows = mutableStateListOf<Row>()
    var sel by mutableIntStateOf(-1)
    var titleOn by mutableStateOf(false)
    var titleText by mutableStateOf("")
    var titleSecs by mutableStateOf("3")
    var pendingLog: LoadedLog? = null
    var page by mutableIntStateOf(0)        // 0: 구간 지정, 1: 저장 설정
    var expanded by mutableIntStateOf(-1)   // 설정 창이 펼쳐진 구간

    val activeIndex: Int get() = rows.indexOfFirst { it.active }
    val dur: Double get() = info?.duration ?: 0.0

    fun clearRows() {
        rows.clear(); sel = -1; expanded = -1
        titleOn = false; titleText = ""; titleSecs = "3"
    }
}

@Composable
fun HighlightTab(s: HlState, ui: AppUi) {
    val ctx = LocalContext.current
    val scope = rememberScope()
    val p = LocalPal.current
    TrackPosition(s.ph)

    fun applyLog(log: LoadedLog) {
        val d = s.dur
        s.rows.clear()
        log.rows.forEach { r ->
            var st = r.start?.let { if (d > 0) minOf(it, d) else it }
            var en = r.end?.let { if (d > 0) minOf(it, d) else it }
            if (st != null && en != null && en <= st) en = null
            s.rows.add(r.copy(start = st, end = en))
        }
        s.sel = -1
        s.titleOn = log.titleOn; s.titleText = log.titleText; s.titleSecs = log.titleSecs
    }

    fun loadVideo(uri: Uri, then: (() -> Unit)? = null) {
        scope.launch {
            try {
                val info = withContext(Dispatchers.IO) { probe(ctx, uri) }
                s.uri = uri
                s.info = info
                s.ph.load(uri)
                s.ex.result = null
                s.ex.status = "대기 중"
                then?.invoke()
            } catch (e: Exception) {
                ui.alert(e.message ?: "영상을 열 수 없습니다.")
            }
        }
    }

    val pickVideo = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            takeRead(ctx, uri)
            val log = s.pendingLog
            s.pendingLog = null
            if (log != null) loadVideo(uri) { applyLog(log) }
            else loadVideo(uri) { s.clearRows() }
        } else s.pendingLog = null
    }

    val saveLog = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        val info = s.info
        if (uri != null && info != null) {
            try {
                ctx.contentResolver.openOutputStream(uri)?.use {
                    it.write(buildLog(s.uri, info, s.rows.toList(), s.titleOn, s.titleText, s.titleSecs).toByteArray())
                }
                ui.alert("편집 로그를 저장했습니다.\n(구글 드라이브 폴더에 저장하면 PC에서도 불러올 수 있습니다)")
            } catch (e: Exception) {
                ui.alert("로그를 저장하지 못했습니다.\n(${e.message})")
            }
        }
    }

    val openLog = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        val log = try {
            val text = ctx.contentResolver.openInputStream(uri)?.use { it.readBytes().toString(Charsets.UTF_8) } ?: ""
            readLog(text)
        } catch (e: Exception) {
            ui.alert(e.message ?: "로그를 읽을 수 없습니다."); return@rememberLauncherForActivityResult
        }
        val saved = log.uri.takeIf { it.isNotBlank() }?.let { Uri.parse(it) }
        fun askPick() {
            s.pendingLog = log
            ui.ask("로그의 원본 영상을 선택해 주세요.\n\n원본: ${log.name.ifBlank { "(이름 없음)" }}",
                "영상 선택" to { pickVideo.launch(arrayOf("video/*")) },
                "취소" to { s.pendingLog = null })
        }
        if (saved == null) askPick()
        else scope.launch {
            val ok = try { withContext(Dispatchers.IO) { probe(ctx, saved) }; true } catch (e: Exception) { false }
            if (ok) loadVideo(saved) { applyLog(log) } else askPick()
        }
    }

    // ───── 동작 ─────
    fun needVideo(): Boolean {
        if (s.info == null) { ui.alert("먼저 [영상 선택]으로 영상을 불러와 주세요."); return false }
        return true
    }

    fun markStart() {
        if (!needVideo()) return
        if (s.activeIndex >= 0) { ui.alert("이미 [득점 시작]을 눌렀습니다. 먼저 [득점 종료]를 눌러 주세요."); return }
        s.rows.add(Row(start = s.ph.position, active = true))
    }

    fun markEnd() {
        if (!needVideo()) return
        val i = s.activeIndex
        if (i < 0) { ui.alert("먼저 [득점 시작]을 눌러 주세요."); return }
        val r = s.rows[i]
        if (s.ph.position <= (r.start ?: 0.0)) { ui.alert("종료 위치가 시작 위치보다 앞입니다. 영상을 더 재생한 뒤 눌러 주세요."); return }
        s.rows[i] = r.copy(end = s.ph.position, active = false)
        s.sel = i
    }

    fun cancelMark() {
        val i = s.activeIndex
        if (i >= 0) { s.rows.removeAt(i); if (s.sel >= s.rows.size) s.sel = -1 }
        Unit
    }

    fun setTime(i: Int, start: Boolean, v: Double?): Boolean {
        val r = s.rows[i]
        val other = if (start) r.end else r.start
        if (v != null && other != null) {
            val (a, b) = if (start) v to other else other to v
            if (b <= a) { ui.alert("종료 시간은 시작 시간보다 늦어야 합니다."); return false }
        }
        val vv = v?.let { if (s.dur > 0) minOf(it, s.dur) else it }
        s.rows[i] = if (start) r.copy(start = vv) else r.copy(end = vv)
        return true
    }

    fun nudge(i: Int, start: Boolean, d: Double) {
        val r = s.rows[i]
        val cur = (if (start) r.start else r.end) ?: s.ph.position
        val nv = (cur + d).coerceIn(0.0, if (s.dur > 0) s.dur else Double.MAX_VALUE)
        if (setTime(i, start, nv)) s.ph.seek(nv)
    }

    fun setCrop(i: Int, on: Boolean, ratio: String? = null, zoom: Double? = null) {
        val info = s.info ?: return
        val r = s.rows[i]
        if (!on) { s.rows[i] = r.copy(crop = null, cropRatio = null); return }
        val rt = ratio ?: r.cropRatio ?: autoOutRatio(s.rows)
        val old = r.crop
        val z = zoom ?: if (old != null && r.cropRatio != null) cropZoom(info.width, info.height, r.cropRatio, old) else 1.5
        val cx = old?.let { it.x + it.w / 2 } ?: 0.5
        val cy = old?.let { it.y + it.h / 2 } ?: 0.5
        s.rows[i] = r.copy(cropRatio = rt, crop = cropMake(info.width, info.height, rt, z, cx, cy))
    }

    /** 영상 위 손가락: 한 손가락 끌기 = 이동, 두 손가락 벌리기/오므리기 = 확대/축소 */
    fun cropTransform(dx: Double, dy: Double, factor: Double) {
        val info = s.info ?: return
        val i = s.sel
        val r = s.rows.getOrNull(i) ?: return
        val c = r.crop ?: return
        val rt = r.cropRatio ?: return
        val z = (cropZoom(info.width, info.height, rt, c) * factor).coerceIn(1.0, 4.0)
        val cx = c.x + c.w / 2 + dx
        val cy = c.y + c.h / 2 + dy
        s.rows[i] = r.copy(crop = cropMake(info.width, info.height, rt, z, cx, cy))
    }

    fun go() {
        val info = s.info
        val uri = s.uri
        if (info == null || uri == null) { needVideo(); return }
        if (s.activeIndex >= 0) { ui.alert("지정 중인 구간이 있습니다. [득점 종료]를 누르거나 [지정 취소]를 눌러 주세요."); return }
        var title: Pair<String, Double>? = null
        if (s.titleOn && s.titleText.isNotBlank()) {
            val secs = s.titleSecs.toDoubleOrNull()
            if (secs == null || secs <= 0 || secs > 30) { ui.alert("메인화면 표시 시간은 0보다 크고 30초 이하로 입력해 주세요."); return }
            title = s.titleText.trim() to secs
        }
        try {
            val (comp, _) = Exporter.highlightComposition(ctx, uri, info, s.rows.toList(), title)
            val (ow, oh) = outputSize(info.width, info.height, autoOutRatio(s.rows))
            s.ph.stop()
            startExport(ctx, scope, s.ex, comp, true, ow * oh, outName(info.name, "하이라이트"), ui::alert)
        } catch (e: Exception) {
            ui.alert(e.message ?: "영상 만들기를 시작하지 못했습니다.")
        }
    }

    fun reset() {
        ui.ask("무엇을 초기화할까요?",
            "구간·자막만" to { s.clearRows() },
            "불러온 영상까지" to {
                s.clearRows(); s.uri = null; s.info = null; s.ph.load(null); s.ex.result = null; s.ex.status = "대기 중"
            },
            "취소" to {})
    }

    // ───── 화면 ─────
    val ai = s.activeIndex
    val selRow = s.rows.getOrNull(s.sel)
    val listState = rememberLazyListState()
    // 새 구간이 생기면 맨 아래(득점 버튼 바로 위)로 스크롤
    LaunchedEffect(s.rows.size) { if (s.rows.isNotEmpty()) listState.animateScrollToItem(s.rows.size - 1) }

    if (s.page == 1) {
        SaveScreen(s, ui, pickVideo = { pickVideo.launch(arrayOf("video/*")) },
            saveLog = { val info = s.info; if (info == null) needVideo() else saveLog.launch(logDefaultName(info.name)) },
            openLog = { openLog.launch(arrayOf("application/json", "text/plain", "application/octet-stream")) },
            reset = ::reset, go = ::go)
        return
    }

    @Composable
    fun PlayerPart(modifier: Modifier) {
        Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
            BRow {
                PBtn("📂 영상 선택", { pickVideo.launch(arrayOf("video/*")) }, kind = Kind.Soft, small = true)
                Sub(s.info?.let { "${it.name} · ${fmtTime(it.duration)}" } ?: "선택된 영상이 없습니다.", Modifier.weight(1f),
                    size = 12.sp)
            }
            VideoBox(
                s.ph, s.info, "[영상 선택]을 눌러\n경기 영상을 불러오세요",
                crop = selRow?.crop,
                onCropTransform = ::cropTransform,
            )
            SeekBar(
                s.dur, s.ph.position,
                s.rows.filter { it.complete }.map { it.start!! to it.end!! },
                if (ai >= 0) (s.rows[ai].start ?: 0.0) to s.ph.position else null,
                { s.ph.seek(it) },
            )
            BRow(gap = 4.dp) {
                listOf(-5.0, -2.0, -1.0).forEach { d ->
                    PBtn("${d.toInt()}", { s.ph.seekRel(d, s.dur) }, Modifier.weight(1f), Kind.Soft, small = true)
                }
                PBtn(if (s.ph.playing) "❚❚" else "▶", { s.ph.toggle() }, Modifier.weight(1.3f), Kind.Primary, s.info != null, small = true)
                listOf(1.0, 2.0, 5.0).forEach { d ->
                    PBtn("+${d.toInt()}", { s.ph.seekRel(d, s.dur) }, Modifier.weight(1f), Kind.Soft, small = true)
                }
            }
        }
    }

    @Composable
    fun ListPart(modifier: Modifier) {
        Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
            BRow {
                H("득점 구간 목록")
                val done = s.rows.filter { it.complete }
                Sub("${done.size}개 · 합계 ${fmtSecs(done.sumOf { it.length })}", Modifier.weight(1f))
                Sub(fmtTime(s.ph.position), size = 12.sp)
                Picker(s.ph.speed, listOf("0.5x", "1x", "1.5x", "2x"), { s.ph.changeSpeed(it) }, Modifier.width(72.dp))
            }
            Box(Modifier.weight(1f).fillMaxWidth()) {
                if (s.rows.isEmpty()) {
                    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Bottom) {
                        Ghost(if (s.info == null) "[영상 선택]으로 경기 영상을 불러오세요"
                              else "득점 장면이 시작되면 [득점 시작]을 누르세요.\n새 구간은 여기(버튼 바로 위)에 추가됩니다.")
                    }
                }
                LazyColumn(
                    Modifier.fillMaxSize(), state = listState,
                    verticalArrangement = Arrangement.spacedBy(6.dp, Alignment.Bottom),
                ) {
                    itemsIndexed(s.rows) { i, r ->
                        RowCard(s, i, r, ui,
                            onSelect = {
                                if (s.sel == i) s.expanded = if (s.expanded == i) -1 else i
                                else { s.sel = i; s.expanded = -1 }
                                r.start?.let { s.ph.seek(it) }
                            },
                            setTime = ::setTime, nudge = ::nudge, setCrop = ::setCrop)
                    }
                }
            }
            BRow {
                PBtn("득점 시작", ::markStart, Modifier.weight(1f), Kind.Start, s.info != null && ai < 0, big = true)
                PBtn("득점 종료", ::markEnd, Modifier.weight(1f), Kind.End, ai >= 0, big = true)
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

/** [저장 ▸] 화면: 영상·로그 / 메인화면 자막 / 목록 정리 / 편집 및 저장 */
@Composable
private fun SaveScreen(
    s: HlState, ui: AppUi,
    pickVideo: () -> Unit, saveLog: () -> Unit, openLog: () -> Unit, reset: () -> Unit, go: () -> Unit,
) {
    val p = LocalPal.current
    BackHandler { s.page = 0 }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        BRow {
            PBtn("◂ 구간 지정으로", { s.page = 0 }, kind = Kind.Soft, small = true)
            H("저장 설정")
        }
        SCard {
            H("1. 영상")
            Sub(s.info?.let { "${it.name} · ${it.width}×${it.height} · ${fmtTime(it.duration)}${if (it.hdr) " · HDR" else ""}" } ?: "선택된 영상이 없습니다.")
            BRow {
                PBtn("영상 선택", pickVideo, Modifier.weight(1f), Kind.Primary)
                PBtn("로그 저장", saveLog, Modifier.weight(1f), Kind.Soft)
                PBtn("로그 불러오기", openLog, Modifier.weight(1.2f), Kind.Soft)
            }
        }
        SCard {
            BRow { H("2. 메인화면 자막"); Row(Modifier.weight(1f)) {}; Check("사용", s.titleOn, { s.titleOn = it }) }
            BRow {
                Field(s.titleText, { s.titleText = it }, Modifier.weight(1f), "예: [팀명] 시즌 하이라이트", s.titleOn)
                Sub("표시(초)")
                Field(s.titleSecs, { s.titleSecs = it }, Modifier.width(56.dp), "3", s.titleOn, number = true, center = true)
            }
        }
        SCard {
            H("3. 목록 정리")
            BRow {
                PBtn("+ 구간 직접 추가", {
                    if (s.info == null) ui.alert("먼저 [영상 선택]으로 영상을 불러와 주세요.")
                    else { s.rows.add(Row()); s.sel = s.rows.size - 1; s.expanded = s.sel; s.page = 0 }
                }, Modifier.weight(1f), Kind.Soft)
                PBtn("전체 초기화", reset, kind = Kind.Danger)
            }
            Picker("자막 위치 일괄 변경", POSITIONS, { pos ->
                for (k in s.rows.indices) s.rows[k] = s.rows[k].copy(pos = pos)
                ui.alert("모든 구간의 자막 위치를 '$pos'(으)로 바꿨습니다.")
            }, Modifier.fillMaxWidth(), enabled = s.rows.isNotEmpty())
            val done = s.rows.filter { it.complete }
            val total = done.sumOf { it.length }
            val ts = if (s.titleOn && s.titleText.isNotBlank()) (s.titleSecs.toDoubleOrNull() ?: 0.0).coerceAtLeast(0.0) else 0.0
            Text("득점 구간 ${done.size}개 · 합계 ${fmtSecs(total)} + 메인화면 ${fmtSecs(ts)} = 전체 약 ${fmtSecs(total + ts)}",
                color = p.ink, fontWeight = FontWeight.Bold, fontSize = 13.sp)
        }
        val info = s.info
        val size = info?.let {
            val rt = autoOutRatio(s.rows); val (w, h) = outputSize(it.width, it.height, rt); "저장 영상 크기(자동): $rt (${w}×$h)"
        } ?: ""
        ExportCard("4. 편집 및 저장", s.ex, "편집 시작 (MP4로 저장)", size, go)
        if (info?.hdr == true) Note("HDR 영상은 휴대폰·카톡 어디서나 잘 보이도록 일반(SDR) 색상으로 바꿔 저장합니다.")
        Sub("※ 저장된 영상: 갤러리 › 앨범 › Movies(농구하이라이트)", Modifier.padding(4.dp), size = 12.sp)
    }
}

@Composable
private fun RowCard(
    s: HlState, i: Int, r: Row, ui: AppUi,
    onSelect: () -> Unit,
    setTime: (Int, Boolean, Double?) -> Boolean,
    nudge: (Int, Boolean, Double) -> Unit,
    setCrop: (Int, Boolean, String?, Double?) -> Unit,
) {
    val p = LocalPal.current
    val selected = s.sel == i
    val open = s.expanded == i
    val shape = RoundedCornerShape(14.dp)
    val bg = when { r.active -> p.rowAct; selected -> p.rowSel; else -> p.card }
    val bd = when { r.active -> p.end; selected -> p.acc; else -> p.line }
    Column(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(bg)
            .border(2.dp, bd, shape)
            .clickable { onSelect() }
            .padding(horizontal = 10.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        BRow {
            Text("${i + 1}", color = p.ink, fontWeight = FontWeight.Bold, fontSize = 15.sp, modifier = Modifier.width(20.dp))
            Field(r.text, { t -> s.rows[i] = s.rows[i].copy(text = t) }, Modifier.weight(1f), "자막 (예: 3점슛 #7)")
            PBtn("▶", { if (r.start != null && r.end != null && r.end > r.start) s.ph.playRange(r.start, r.end) },
                kind = Kind.Soft, small = true, enabled = r.complete)
            PBtn("✕", {
                s.rows.removeAt(i)
                if (s.sel == i || s.sel >= s.rows.size) s.sel = -1 else if (s.sel > i) s.sel -= 1
                s.expanded = -1
            }, kind = Kind.Danger, small = true)
        }
        BRow {
            val endTxt = if (r.active) "지정 중…" else fmtTime(r.end).ifEmpty { "--:--.-" }
            val extra = buildString {
                append(" · "); append(r.pos)
                if (r.crop != null) {
                    append(" · 범위 "); append(r.cropRatio)
                }
            }
            Text("${fmtTime(r.start).ifEmpty { "--:--.-" }} ~ $endTxt$extra", color = if (r.active) p.end else p.sub,
                fontSize = 12.sp, modifier = Modifier.weight(1f), maxLines = 1)
            Text(if (r.complete) fmtSecs(r.length) else "", color = p.ink, fontWeight = FontWeight.Bold, fontSize = 12.sp)
            if (selected && !r.active) Text(if (open) " 접기 ▴" else " 설정 ▾", color = p.pri, fontWeight = FontWeight.Bold, fontSize = 12.sp)
        }
        if (open && !r.active) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .background(p.field)
                    .border(2.dp, if (r.crop != null) p.acc else p.fline, RoundedCornerShape(12.dp))
                    .padding(8.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                BRow(gap = 3.dp) {
                    Sub("시작", Modifier.width(30.dp))
                    PBtn("−0.5", { nudge(i, true, -0.5) }, kind = Kind.Soft, small = true)
                    TimeField(r.start, { v -> setTime(i, true, v) }, Modifier.weight(1f))
                    PBtn("+0.5", { nudge(i, true, 0.5) }, kind = Kind.Soft, small = true)
                    PBtn("현재", { setTime(i, true, s.ph.position) }, kind = Kind.Normal, small = true)
                }
                BRow(gap = 3.dp) {
                    Sub("종료", Modifier.width(30.dp))
                    PBtn("−0.5", { nudge(i, false, -0.5) }, kind = Kind.Soft, small = true)
                    TimeField(r.end, { v -> setTime(i, false, v) }, Modifier.weight(1f))
                    PBtn("+0.5", { nudge(i, false, 0.5) }, kind = Kind.Soft, small = true)
                    PBtn("현재", { setTime(i, false, s.ph.position) }, kind = Kind.Normal, small = true)
                }
                BRow {
                    Sub("자막 위치", Modifier.width(56.dp))
                    Picker(r.pos, POSITIONS, { pos -> s.rows[i] = s.rows[i].copy(pos = pos) }, Modifier.weight(1f))
                }
                val info = s.info
                if (info != null) {
                    BRow {
                        Check("화면 범위(확대) 사용", r.crop != null, { on -> setCrop(i, on, null, null) })
                    }
                    if (r.crop != null) {
                        BRow { Sub("비율", Modifier.width(34.dp)); Seg(RATIOS.keys.toList(), r.cropRatio, { setCrop(i, true, it, null) }, Modifier.weight(1f)) }
                        val zNow = r.cropRatio?.let { cropZoom(info.width, info.height, it, r.crop) }
                        val zLabels = ZOOMS.map { z -> if (z % 1.0 == 0.0) "${z.toInt()}x" else String.format(Locale.US, "%.1fx", z) }
                        val zSel = zNow?.let { zn -> ZOOMS.indexOfFirst { kotlin.math.abs(it - zn) < 0.05 }.takeIf { it >= 0 }?.let { zLabels[it] } }
                        BRow { Sub("확대", Modifier.width(34.dp)); Seg(zLabels, zSel, { lb -> setCrop(i, true, null, ZOOMS[zLabels.indexOf(lb)]) }, Modifier.weight(1f)) }
                        Sub("영상 위에서 한 손가락으로 끌면 이동, 두 손가락으로 벌리면 확대됩니다.", size = 12.sp)
                    }
                }
            }
        }
    }
}
