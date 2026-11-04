package com.ljk.highlight

import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import androidx.media3.common.Effect
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.audio.AudioProcessor
import androidx.media3.effect.BitmapOverlay
import androidx.media3.effect.Crop as CropEffect
import androidx.media3.effect.OverlayEffect
import androidx.media3.effect.Presentation
import androidx.media3.effect.TextureOverlay
import androidx.media3.transformer.Composition
import androidx.media3.transformer.DefaultEncoderFactory
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.EditedMediaItemSequence
import androidx.media3.transformer.Effects
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.ProgressHolder
import androidx.media3.transformer.Transformer
import androidx.media3.transformer.VideoEncoderSettings
import com.google.common.collect.ImmutableList
import java.io.File
import java.io.FileOutputStream
import kotlin.math.max
import kotlin.math.roundToInt

/** 휴대폰 기본 영상 엔진(Media3 Transformer)으로 하이라이트·컷 편집·합치기를 만듭니다. */
object Exporter {

    // ───────── 자막 그림 ─────────
    private fun captionPaint(fs: Float) = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textSize = fs
        typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
    }

    /** 화면 크기(ow×oh)의 투명 그림에 자막(검은 반투명 상자 + 흰 글자)을 위치에 맞춰 그립니다. */
    fun captionBitmap(ow: Int, oh: Int, text: String, pos: String): Bitmap {
        val bmp = Bitmap.createBitmap(ow, oh, Bitmap.Config.ARGB_8888)
        val c = Canvas(bmp)
        val fs = max(18, (oh / 18.0).roundToInt()).toFloat()
        val p = captionPaint(fs)
        val lines = text.split("\n")
        val fm = p.fontMetrics
        val lineH = fm.descent - fm.ascent
        val tw = lines.maxOf { p.measureText(it) }
        val th = lineH * lines.size
        val x = when (pos) {
            "좌측 상단", "좌측 하단" -> ow * 0.03f
            "우측 상단", "우측 하단" -> ow - tw - ow * 0.03f
            else -> (ow - tw) / 2f
        }
        val y = when (pos) {
            "좌측 상단", "우측 상단" -> oh * 0.05f
            "화면 중앙" -> (oh - th) / 2f
            else -> oh - th - oh * 0.06f
        }
        val border = max(8f, fs / 3f)
        val box = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(140, 0, 0, 0) }
        c.drawRoundRect(RectF(x - border, y - border, x + tw + border, y + th + border), border / 2, border / 2, box)
        lines.forEachIndexed { i, s -> c.drawText(s, x, y + i * lineH - fm.ascent, p) }
        return bmp
    }

    /** 메인화면: 검은 바탕 가운데 큰 글자 */
    fun titleBitmap(ow: Int, oh: Int, text: String): Bitmap {
        val bmp = Bitmap.createBitmap(ow, oh, Bitmap.Config.ARGB_8888)
        val c = Canvas(bmp)
        c.drawColor(Color.BLACK)
        val p = captionPaint(max(24, (oh / 12.0).roundToInt()).toFloat())
        val lines = text.split("\n")
        val fm = p.fontMetrics
        val lineH = fm.descent - fm.ascent
        val top = (oh - lineH * lines.size) / 2f
        lines.forEachIndexed { i, s ->
            c.drawText(s, (ow - p.measureText(s)) / 2f, top + i * lineH - fm.ascent, p)
        }
        return bmp
    }

    /** 자막 그림은 필요할 때 만들고, 최근 2개만 기억합니다(메모리 절약). */
    private object CaptionCache {
        private val keys = ArrayDeque<String>()
        private val maps = HashMap<String, Bitmap>()

        @Synchronized
        fun get(key: String, make: () -> Bitmap): Bitmap {
            maps[key]?.let { return it }
            val b = make()
            maps[key] = b
            keys.addLast(key)
            while (keys.size > 2) maps.remove(keys.removeFirst())
            return b
        }

        @Synchronized
        fun clear() {
            keys.clear(); maps.clear()
        }
    }

    private class CaptionOverlay(private val key: String, private val make: () -> Bitmap) : BitmapOverlay() {
        override fun getBitmap(presentationTimeUs: Long): Bitmap = CaptionCache.get(key, make)
    }

    // ───────── 구성 요소 ─────────
    private fun clipped(uri: Uri, start: Double, end: Double): MediaItem =
        MediaItem.Builder().setUri(uri).setClippingConfiguration(
            MediaItem.ClippingConfiguration.Builder()
                .setStartPositionMs((start * 1000).toLong())
                .setEndPositionMs((end * 1000).toLong())
                .build()
        ).build()

    private fun cropEffect(c: Crop): Effect {
        // 화면 좌표(0~1, 위가 0) → 그래픽 좌표(-1~1, 위가 +1)
        val left = (-1 + 2 * c.x).toFloat()
        val right = (-1 + 2 * (c.x + c.w)).toFloat()
        val top = (1 - 2 * c.y).toFloat()
        val bottom = (1 - 2 * (c.y + c.h)).toFloat()
        return CropEffect(left, right, bottom, top)
    }

    private fun videoItem(uri: Uri, start: Double, end: Double, crop: Crop?, ow: Int, oh: Int,
                          text: String, pos: String, key: String): EditedMediaItem {
        val video = mutableListOf<Effect>()
        if (crop != null) video.add(cropEffect(crop))
        video.add(Presentation.createForWidthAndHeight(ow, oh, Presentation.LAYOUT_SCALE_TO_FIT))
        if (text.isNotBlank()) {
            val overlays: ImmutableList<TextureOverlay> =
                ImmutableList.of(CaptionOverlay(key) { captionBitmap(ow, oh, text, pos) })
            video.add(OverlayEffect(overlays))
        }
        return EditedMediaItem.Builder(clipped(uri, start, end))
            .setEffects(Effects(ImmutableList.of<AudioProcessor>(), ImmutableList.copyOf(video)))
            .build()
    }

    private fun imageItem(ctx: Context, bmp: Bitmap, secs: Double, name: String): EditedMediaItem {
        val f = File(ctx.cacheDir, name)
        FileOutputStream(f).use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
        val item = MediaItem.Builder().setUri(Uri.fromFile(f))
            .setImageDurationMs((secs * 1000).toLong()).build()
        return EditedMediaItem.Builder(item).setFrameRate(30).build()
    }

    // ───────── 편집 묶음 만들기 ─────────
    fun highlightComposition(ctx: Context, uri: Uri, info: VideoInfo, rows: List<Row>,
                             title: Pair<String, Double>?): Pair<Composition, String> {
        val segs = rows.filter { it.complete }
        if (segs.isEmpty()) throw EditError("완성된 득점 구간이 없습니다. [득점 시작] → [득점 종료]로 구간을 지정해 주세요.")
        val ratio = autoOutRatio(rows)
        val (ow, oh) = outputSize(info.width, info.height, ratio)
        CaptionCache.clear()
        val items = mutableListOf<EditedMediaItem>()
        if (title != null) items.add(imageItem(ctx, titleBitmap(ow, oh, title.first), title.second, "title.png"))
        segs.forEachIndexed { i, r ->
            items.add(videoItem(uri, r.start!!, r.end!!, r.crop, ow, oh, r.text.trim(), r.pos, "seg$i"))
        }
        val comp = Composition.Builder(EditedMediaItemSequence(items))
            .experimentalSetForceAudioTrack(true)
            .setHdrMode(Composition.HDR_MODE_TONE_MAP_HDR_TO_SDR_USING_OPEN_GL)
            .build()
        return comp to "$ratio (${ow}x$oh)"
    }

    fun cutComposition(uri: Uri, keep: List<Pair<Double, Double>>): Composition {
        if (keep.isEmpty()) throw EditError("남길 구간이 없습니다. 지울 구간을 다시 확인해 주세요.")
        val items = keep.map { (s, e) -> EditedMediaItem.Builder(clipped(uri, s, e)).build() }
        return Composition.Builder(EditedMediaItemSequence(items)).build()
    }

    fun mergeComposition(clips: List<Pair<Uri, VideoInfo>>): Pair<Composition, String> {
        if (clips.size < 2) throw EditError("합칠 영상을 2개 이상 추가해 주세요.")
        val ow = even(clips[0].second.width.toDouble())
        val oh = even(clips[0].second.height.toDouble())
        val items = clips.map { (u, _) ->
            EditedMediaItem.Builder(MediaItem.fromUri(u)).setEffects(
                Effects(ImmutableList.of<AudioProcessor>(),
                    ImmutableList.of<Effect>(Presentation.createForWidthAndHeight(ow, oh, Presentation.LAYOUT_SCALE_TO_FIT)))
            ).build()
        }
        val comp = Composition.Builder(EditedMediaItemSequence(items))
            .experimentalSetForceAudioTrack(true)
            .setHdrMode(Composition.HDR_MODE_TONE_MAP_HDR_TO_SDR_USING_OPEN_GL)
            .build()
        return comp to "${ow}x$oh"
    }

    // ───────── 실행 ─────────
    class Job(
        private val ctx: Context,
        private val sdrH264: Boolean,
        private val pixels: Int,
        private val onProgress: (Int) -> Unit,
        private val onDone: (File) -> Unit,
        private val onError: (String) -> Unit,
    ) {
        private val handler = Handler(Looper.getMainLooper())
        private var transformer: Transformer? = null
        private val out = File(ctx.cacheDir, "export_out.mp4")
        private var finished = false

        private val poll = object : Runnable {
            override fun run() {
                val t = transformer ?: return
                if (finished) return
                val h = ProgressHolder()
                if (t.getProgress(h) == Transformer.PROGRESS_STATE_AVAILABLE) onProgress(h.progress)
                handler.postDelayed(this, 500)
            }
        }

        fun start(comp: Composition) {
            out.delete()
            val b = Transformer.Builder(ctx)
            if (sdrH264) {
                // 화질: 1080p 기준 약 12Mbps
                val bitrate = max(4_000_000, (pixels * 30 * 0.2).toInt())
                b.setVideoMimeType(MimeTypes.VIDEO_H264)
                    .setAudioMimeType(MimeTypes.AUDIO_AAC)
                    .setEncoderFactory(
                        DefaultEncoderFactory.Builder(ctx)
                            .setRequestedVideoEncoderSettings(VideoEncoderSettings.Builder().setBitrate(bitrate).build())
                            .build()
                    )
            }
            b.addListener(object : Transformer.Listener {
                override fun onCompleted(composition: Composition, exportResult: ExportResult) {
                    finished = true
                    onProgress(100)
                    onDone(out)
                }

                override fun onError(composition: Composition, exportResult: ExportResult, exportException: ExportException) {
                    finished = true
                    onError("영상 만들기에 실패했습니다.\n(${exportException.errorCodeName}: ${exportException.message ?: ""})")
                }
            })
            val t = b.build()
            transformer = t
            t.start(comp, out.absolutePath)
            handler.post(poll)
        }

        fun cancel() {
            finished = true
            transformer?.cancel()
            out.delete()
        }
    }

    /** 만든 영상을 갤러리(동영상/Movies/농구하이라이트)에 저장합니다. (작업 스레드에서 호출) */
    fun saveToGallery(ctx: Context, file: File, displayName: String): Uri {
        val cr = ctx.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Video.Media.DISPLAY_NAME, displayName)
            put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
            put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/농구하이라이트")
            put(MediaStore.Video.Media.IS_PENDING, 1)
        }
        val uri = cr.insert(MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY), values)
            ?: throw EditError("갤러리에 저장할 수 없습니다.")
        cr.openOutputStream(uri)?.use { o -> file.inputStream().use { it.copyTo(o, 1 shl 20) } }
            ?: throw EditError("갤러리에 저장할 수 없습니다.")
        values.clear()
        values.put(MediaStore.Video.Media.IS_PENDING, 0)
        cr.update(uri, values, null, null)
        file.delete()
        return uri
    }
}
