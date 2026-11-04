package com.ljk.highlight

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.net.Uri
import android.view.WindowManager
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.media3.transformer.Composition
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 탭을 옮겨도 저장이 끝까지 진행되도록 앱 전체에서 쓰는 작업 범위 */
private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

/** 저장(내보내기) 진행 상태 — 탭마다 하나 */
class ExportState {
    var running by mutableStateOf(false)
    var progress by mutableIntStateOf(0)
    var status by mutableStateOf("대기 중")
    var result by mutableStateOf<Uri?>(null)
    var job: Exporter.Job? = null
}

fun Context.findActivity(): Activity? {
    var c: Context? = this
    while (c is ContextWrapper) {
        if (c is Activity) return c
        c = c.baseContext
    }
    return null
}

fun outName(srcName: String, tag: String): String {
    val base = srcName.substringBeforeLast('.').ifBlank { "영상" }
    return base + "_" + tag + "_" + SimpleDateFormat("yyMMdd_HHmm", Locale.KOREA).format(Date()) + ".mp4"
}

fun startExport(
    ctx: Context,
    scope: CoroutineScope,
    st: ExportState,
    comp: Composition,
    sdrH264: Boolean,
    pixels: Int,
    displayName: String,
    alert: (String) -> Unit,
) {
    val act = ctx.findActivity()
    st.running = true
    st.progress = 0
    st.result = null
    st.status = "영상 만드는 중… (앱을 켜 둔 채로 기다려 주세요)"
    act?.window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    fun finish() {
        st.running = false
        st.job = null
        act?.window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }
    val job = Exporter.Job(
        ctx, sdrH264, pixels,
        onProgress = { st.progress = it },
        onDone = { file ->
            st.status = "갤러리에 저장하는 중…"
            appScope.launch {
                try {
                    val uri = withContext(Dispatchers.IO) { Exporter.saveToGallery(ctx, file, displayName) }
                    st.result = uri
                    st.status = "완료: 갤러리 › Movies/농구하이라이트 › $displayName"
                } catch (e: Exception) {
                    st.status = "저장 실패"
                    alert(e.message ?: "저장에 실패했습니다.")
                }
                finish()
            }
        },
        onError = { m ->
            st.status = "실패"
            finish()
            alert(m)
        },
    )
    st.job = job
    try {
        job.start(comp)
    } catch (e: Exception) {
        finish()
        st.status = "실패"
        alert("영상 만들기를 시작하지 못했습니다.\n(${e.message ?: e.javaClass.simpleName})")
    }
}

fun cancelExport(st: ExportState, ctx: Context) {
    st.job?.cancel()
    st.job = null
    st.running = false
    st.status = "취소했습니다."
    ctx.findActivity()?.window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
}

fun openVideo(ctx: Context, uri: Uri) {
    try {
        ctx.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "video/mp4")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
    } catch (_: Exception) {
    }
}

fun shareVideo(ctx: Context, uri: Uri) {
    try {
        val i = Intent(Intent.ACTION_SEND).setType("video/mp4").putExtra(Intent.EXTRA_STREAM, uri)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        ctx.startActivity(Intent.createChooser(i, "영상 공유"))
    } catch (_: Exception) {
    }
}

/** 하단 저장 카드: 진행 막대 + 상태 + [취소] [시작] + 완료 후 [보기] [공유] */
@Composable
fun ExportCard(
    title: String,
    st: ExportState,
    goText: String,
    info: String,
    onGo: () -> Unit,
) {
    val ctx = LocalContext.current
    SCard {
        H(title)
        if (info.isNotEmpty()) Sub(info)
        Progress(st.progress / 100f)
        Sub(st.status)
        BRow {
            PBtn("취소", { cancelExport(st, ctx) }, kind = Kind.Danger, enabled = st.running)
            PBtn(goText, onGo, Modifier.weight(1f), Kind.Go, enabled = !st.running, big = true)
        }
        st.result?.let { u ->
            BRow {
                PBtn("▶ 만든 영상 보기", { openVideo(ctx, u) }, Modifier.weight(1f), Kind.Soft)
                PBtn("공유", { shareVideo(ctx, u) }, Modifier.weight(1f), Kind.Soft)
            }
        }
    }
}

@Composable
fun rememberScope() = rememberCoroutineScope()
