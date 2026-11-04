package com.ljk.highlight

import android.content.Context
import android.graphics.Bitmap
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.provider.OpenableColumns
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

// ───────── PC판과 같은 규칙(자막 위치·비율·로그 형식) ─────────
val POSITIONS = listOf("좌측 상단", "우측 상단", "좌측 하단", "우측 하단", "하단 중앙", "화면 중앙")
const val DEFAULT_POSITION = "우측 하단"
val RATIOS: Map<String, Pair<Int, Int>> = linkedMapOf("1:1" to (1 to 1), "4:3" to (4 to 3), "16:9" to (16 to 9))
const val DEFAULT_RATIO = "16:9"
val ZOOMS = listOf(1.0, 1.5, 2.0, 3.0)
const val LOG_KIND = "basketball-highlight-log"

data class Crop(val x: Double, val y: Double, val w: Double, val h: Double)

data class Row(
    val start: Double? = null,
    val end: Double? = null,
    val text: String = "",
    val pos: String = DEFAULT_POSITION,
    val active: Boolean = false,
    val cropRatio: String? = null,
    val crop: Crop? = null,
) {
    val complete: Boolean get() = !active && start != null && end != null && end > start
    val length: Double get() = if (start != null && end != null && end > start) end - start else 0.0
}

data class VideoInfo(
    val name: String,
    val width: Int,          // 회전을 반영한 화면 기준 가로
    val height: Int,
    val duration: Double,
    val hasAudio: Boolean,
    val hdr: Boolean,
)

class EditError(msg: String) : Exception(msg)

fun fmtTime(sec: Double?): String {
    if (sec == null) return ""
    val tenths = (max(0.0, sec) * 10).roundToInt()
    val h = tenths / 36000
    val m = (tenths % 36000) / 600
    val s = (tenths % 600) / 10.0
    return if (h > 0) String.format(Locale.US, "%d:%02d:%04.1f", h, m, s)
    else String.format(Locale.US, "%02d:%04.1f", m, s)
}

/** "05:42.3", "1:05:42.3", "42.3" → 초. 잘못되면 null */
fun parseTime(text: String): Double? {
    val t = text.trim()
    if (t.isEmpty()) return null
    val parts = t.split(":")
    return try {
        var v = 0.0
        for (p in parts) v = v * 60 + p.toDouble()
        if (v < 0) null else v
    } catch (e: NumberFormatException) {
        null
    }
}

fun fmtSecs(v: Double): String = String.format(Locale.US, "%.1f초", v)

fun queryName(ctx: Context, uri: Uri): String {
    try {
        ctx.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) return c.getString(0) ?: "영상"
        }
    } catch (_: Exception) {
    }
    return uri.lastPathSegment ?: "영상"
}

fun probe(ctx: Context, uri: Uri): VideoInfo {
    val r = MediaMetadataRetriever()
    try {
        r.setDataSource(ctx, uri)
        val w = r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toIntOrNull() ?: 0
        val h = r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toIntOrNull() ?: 0
        val rot = r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_ROTATION)?.toIntOrNull() ?: 0
        val dur = (r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L) / 1000.0
        val audio = r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_AUDIO) == "yes"
        val transfer = r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_COLOR_TRANSFER)?.toIntOrNull() ?: 0
        if (w <= 0 || h <= 0) throw EditError("영상 정보를 읽지 못했습니다. 다른 영상 파일을 선택해 주세요.")
        val swap = rot == 90 || rot == 270
        // 6 = ST2084(HDR10), 7 = HLG
        return VideoInfo(queryName(ctx, uri), if (swap) h else w, if (swap) w else h, dur, audio, transfer == 6 || transfer == 7)
    } catch (e: EditError) {
        throw e
    } catch (e: Exception) {
        throw EditError("영상 파일을 열 수 없습니다.\n(${e.message ?: e.javaClass.simpleName})")
    } finally {
        try { r.release() } catch (_: Exception) {}
    }
}

fun thumbnail(ctx: Context, uri: Uri): Bitmap? {
    val r = MediaMetadataRetriever()
    return try {
        r.setDataSource(ctx, uri)
        r.getScaledFrameAtTime(1_000_000, MediaMetadataRetriever.OPTION_CLOSEST_SYNC, 192, 108)
    } catch (_: Exception) {
        null
    } finally {
        try { r.release() } catch (_: Exception) {}
    }
}

// ───────── 저장 크기·범위(크롭) ─────────
fun even(v: Double): Int {
    val i = v.roundToInt()
    return max(2, i - i % 2)
}

/** 저장 영상 크기. 높이를 유지하고 가로를 비율에 맞춥니다(1920x1080: 1:1→1080x1080). */
fun outputSize(w: Int, h: Int, ratio: String): Pair<Int, Int> {
    val (a, b) = RATIOS[ratio] ?: RATIOS.getValue(DEFAULT_RATIO)
    val r = a.toDouble() / b
    var oh = h.toDouble()
    var ow = h * r
    val longest = max(w, h).toDouble()
    if (ow > longest) {
        ow = longest; oh = longest / r
    }
    return even(ow) to even(oh)
}

fun cropBase(w: Int, h: Int, ratio: String): Pair<Double, Double> {
    val (a, b) = RATIOS.getValue(ratio)
    val r = a.toDouble() / b
    return if (r <= w.toDouble() / h) (r * h / w) to 1.0 else 1.0 to (w / (r * h))
}

fun cropMake(w: Int, h: Int, ratio: String, zoom: Double, cx: Double = 0.5, cy: Double = 0.5): Crop {
    val (bw, bh) = cropBase(w, h, ratio)
    val z = min(4.0, max(1.0, zoom))
    val cw = bw / z
    val ch = bh / z
    return Crop(min(1.0 - cw, max(0.0, cx - cw / 2)), min(1.0 - ch, max(0.0, cy - ch / 2)), cw, ch)
}

fun cropZoom(w: Int, h: Int, ratio: String, crop: Crop): Double = cropBase(w, h, ratio).first / crop.w

/** 저장 비율 자동 결정: 완성된 구간에서 가장 많이 지정한 비율(범위 미사용은 16:9). */
fun autoOutRatio(rows: List<Row>): String {
    val counts = linkedMapOf<String, Int>()
    for (r in rows) {
        if (!r.complete) continue
        val n = if (r.crop != null && r.cropRatio in RATIOS) r.cropRatio!! else DEFAULT_RATIO
        counts[n] = (counts[n] ?: 0) + 1
    }
    if (counts.isEmpty()) return DEFAULT_RATIO
    val best = counts.values.max()
    return counts.entries.first { it.value == best }.key
}

// ───────── 구간 삭제(컷 편집) ─────────
fun mergeRanges(ranges: List<Pair<Double, Double>>, dur: Double): List<Pair<Double, Double>> {
    val clean = ranges.map { (s, e) -> max(0.0, s) to (if (dur > 0) min(dur, e) else e) }
        .filter { it.second > it.first }.sortedBy { it.first }
    val out = mutableListOf<Pair<Double, Double>>()
    for (r in clean) {
        if (out.isNotEmpty() && r.first <= out.last().second) {
            out[out.size - 1] = out.last().first to max(out.last().second, r.second)
        } else out.add(r)
    }
    return out
}

fun keepRanges(deletes: List<Pair<Double, Double>>, dur: Double, minLen: Double = 0.2): List<Pair<Double, Double>> {
    val keep = mutableListOf<Pair<Double, Double>>()
    var cur = 0.0
    for ((s, e) in mergeRanges(deletes, dur)) {
        if (s - cur >= minLen) keep.add(cur to s)
        cur = max(cur, e)
    }
    if (dur - cur >= minLen) keep.add(cur to dur)
    return keep
}

// ───────── 편집 로그 (PC판과 같은 형식) ─────────
fun logDefaultName(videoName: String): String {
    val d = SimpleDateFormat("yyMMdd", Locale.KOREA).format(Date())
    return d + "_" + videoName.substringBeforeLast('.') + ".json"
}

fun buildLog(uri: Uri?, info: VideoInfo, rows: List<Row>, titleOn: Boolean, titleText: String, titleSecs: String): String {
    val arr = JSONArray()
    for (r in rows) {
        val o = JSONObject()
        o.put("start", r.start ?: JSONObject.NULL)
        o.put("end", r.end ?: JSONObject.NULL)
        o.put("text", r.text)
        o.put("pos", r.pos)
        val c = r.crop
        o.put("cropOn", c != null)
        o.put("cropRatio", if (c != null) r.cropRatio else JSONObject.NULL)
        o.put("crop", if (c != null) JSONObject().put("x", c.x).put("y", c.y).put("w", c.w).put("h", c.h) else JSONObject.NULL)
        arr.put(o)
    }
    val root = JSONObject()
    root.put("kind", LOG_KIND)
    root.put("version", 1)
    root.put("saved", SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.KOREA).format(Date()))
    root.put("video", JSONObject().put("path", "").put("uri", uri?.toString() ?: "").put("name", info.name)
        .put("width", info.width).put("height", info.height).put("duration", info.duration))
    root.put("title", JSONObject().put("on", titleOn).put("text", titleText).put("secs", titleSecs.ifBlank { "3" }))
    root.put("rows", arr)
    return root.toString(2)
}

data class LoadedLog(val name: String, val uri: String, val titleOn: Boolean, val titleText: String,
                     val titleSecs: String, val rows: List<Row>)

private fun num(o: JSONObject, k: String): Double? {
    if (!o.has(k) || o.isNull(k)) return null
    val v = o.optDouble(k, Double.NaN)
    return if (v.isNaN() || v < 0) null else v
}

fun readLog(text: String): LoadedLog {
    val root = try {
        JSONObject(text)
    } catch (e: Exception) {
        throw EditError("편집 로그 파일을 읽을 수 없습니다. 이 프로그램에서 저장한 로그 파일인지 확인해 주세요.")
    }
    if (root.optString("kind") != LOG_KIND || root.optJSONObject("video") == null)
        throw EditError("이 프로그램에서 저장한 편집 로그 파일이 아닙니다.")
    val v = root.getJSONObject("video")
    val t = root.optJSONObject("title") ?: JSONObject()
    val rows = mutableListOf<Row>()
    val arr = root.optJSONArray("rows") ?: JSONArray()
    for (i in 0 until arr.length()) {
        val r = arr.optJSONObject(i) ?: continue
        val st = num(r, "start")
        var en = num(r, "end")
        if (st != null && en != null && en <= st) en = null
        var crop: Crop? = null
        val ratio = if (r.isNull("cropRatio")) null else r.optString("cropRatio")
        val c = r.optJSONObject("crop")
        if (c != null && ratio in RATIOS) {
            val x = num(c, "x"); val y = num(c, "y"); val w = num(c, "w"); val h = num(c, "h")
            if (x != null && y != null && w != null && h != null && w > 0 && w <= 1 && h > 0 && h <= 1 &&
                x + w <= 1.0001 && y + h <= 1.0001) crop = Crop(x, y, w, h)
        }
        val pos = r.optString("pos").let { if (it in POSITIONS) it else DEFAULT_POSITION }
        rows.add(Row(st, en, r.optString("text"), pos, false, if (crop != null) ratio else null, crop))
    }
    return LoadedLog(v.optString("name"), v.optString("uri"), t.optBoolean("on"), t.optString("text"),
        t.optString("secs", "3").ifBlank { "3" }, rows)
}
