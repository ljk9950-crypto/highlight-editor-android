package com.ljk.highlight

import android.content.Context
import android.net.Uri
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import kotlinx.coroutines.delay

/** 탭마다 하나씩 쓰는 재생기 + 재생 위치 상태 */
class PlayerHolder(ctx: Context) {
    val player: ExoPlayer = ExoPlayer.Builder(ctx).build()
    var position by mutableDoubleStateOf(0.0)
    var playing by mutableStateOf(false)
    var speed by mutableStateOf("1x")
    /** 구간 재생: 이 시간(초)에 도달하면 멈춤 */
    var stopAt: Double? = null

    init {
        player.addListener(object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                playing = isPlaying
            }
        })
    }

    fun load(uri: Uri?) {
        player.stop()
        player.clearMediaItems()
        position = 0.0
        stopAt = null
        if (uri != null) {
            player.setMediaItem(MediaItem.fromUri(uri))
            player.prepare()
        }
    }

    fun seek(sec: Double) {
        player.seekTo((sec * 1000).toLong().coerceAtLeast(0))
        position = sec.coerceAtLeast(0.0)
    }

    fun seekRel(d: Double, dur: Double) = seek((position + d).coerceIn(0.0, if (dur > 0) dur else Double.MAX_VALUE))

    fun toggle() {
        stopAt = null
        if (player.isPlaying) player.pause() else player.play()
    }

    fun stop() {
        stopAt = null
        player.pause()
    }

    fun playRange(s: Double, e: Double) {
        seek(s)
        stopAt = e
        player.play()
    }

    fun setSpeed(label: String) {
        speed = label
        player.setPlaybackSpeed(label.removeSuffix("x").toFloatOrNull() ?: 1f)
    }

    fun release() = player.release()
}

@Composable
fun TrackPosition(h: PlayerHolder) {
    LaunchedEffect(h) {
        while (true) {
            h.position = h.player.currentPosition / 1000.0
            h.stopAt?.let { if (h.position >= it) { h.player.pause(); h.stopAt = null } }
            delay(100)
        }
    }
}

/**
 * 영상 화면. crop이 있으면 범위 사각형을 겹쳐 그리고, 손가락으로 끌어 위치를 옮길 수 있습니다.
 */
@Composable
fun VideoBox(
    h: PlayerHolder,
    info: VideoInfo?,
    placeholder: String,
    crop: Crop? = null,
    onCropMove: ((Crop) -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    val p = LocalPal.current
    val cur by rememberUpdatedState(crop)
    val move by rememberUpdatedState(onCropMove)
    Box(
        modifier
            .fillMaxWidth()
            .aspectRatio(16f / 9f)
            .clip(RoundedCornerShape(14.dp))
            .background(p.video),
        contentAlignment = Alignment.Center,
    ) {
        AndroidView(
            factory = { c ->
                PlayerView(c).apply {
                    useController = false
                    resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT
                    setShutterBackgroundColor(android.graphics.Color.TRANSPARENT)
                    setBackgroundColor(android.graphics.Color.TRANSPARENT)
                    player = h.player
                }
            },
            update = { v -> if (v.player !== h.player) v.player = h.player },
            modifier = Modifier.fillMaxSize(),
        )
        if (info == null) {
            Text(placeholder, color = Color(0xFFC9D1DD), fontSize = 14.sp, textAlign = TextAlign.Center,
                modifier = Modifier.padding(16.dp))
        }
        if (info != null && crop != null) {
            BoxWithConstraints(Modifier.fillMaxSize()) {
                val bw = constraints.maxWidth.toFloat()
                val bh = constraints.maxHeight.toFloat()
                val a = info.width.toFloat() / info.height
                val vw = if (bw / bh > a) bh * a else bw
                val vh = if (bw / bh > a) bh else bw / a
                val ox = (bw - vw) / 2
                val oy = (bh - vh) / 2
                Canvas(
                    Modifier
                        .fillMaxSize()
                        .pointerInput(vw, vh) {
                            detectDragGestures { ch, d ->
                                ch.consume()
                                val c = cur ?: return@detectDragGestures
                                val nx = (c.x + d.x / vw).coerceIn(0.0, 1.0 - c.w)
                                val ny = (c.y + d.y / vh).coerceIn(0.0, 1.0 - c.h)
                                move?.invoke(c.copy(x = nx, y = ny))
                            }
                        }
                ) {
                    val l = ox + (crop.x * vw).toFloat()
                    val t = oy + (crop.y * vh).toFloat()
                    val w = (crop.w * vw).toFloat()
                    val hh = (crop.h * vh).toFloat()
                    val dim = Color(0x8C000000)
                    drawRect(dim, Offset(ox, oy), Size(vw, t - oy))
                    drawRect(dim, Offset(ox, t + hh), Size(vw, oy + vh - t - hh))
                    drawRect(dim, Offset(ox, t), Size(l - ox, hh))
                    drawRect(dim, Offset(l + w, t), Size(ox + vw - l - w, hh))
                    drawRect(p.acc, Offset(l, t), Size(w, hh), style = Stroke(3.dp.toPx()))
                }
            }
        }
    }
}
