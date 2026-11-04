# -*- coding: utf-8 -*-
"""
농구 하이라이트 편집기 - 웹(HTML) 버전  (Windows 10 / 64비트용)

화면은 Chrome 같은 브라우저(HTML)에 뜨고, 영상 자르기·자막·저장은 이 PC의
FFmpeg가 처리합니다. (영상은 인터넷으로 올라가지 않고 이 PC 안에서만 움직입니다.)

필요한 것: Python, FFmpeg  (PySide6는 필요 없습니다 / 자막 글꼴은 Noto Sans KR 권장)
실행:      이 파일(highlight_editor_web.pyw)을 더블클릭 → 브라우저가 자동으로 열립니다.
끝내기:    브라우저 화면의 [프로그램 종료] 버튼
"""
import glob
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

APP_TITLE = "농구 하이라이트 편집기"
IS_WIN = os.name == "nt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HERE = os.path.dirname(os.path.abspath(__file__))


def _fatal(text):
    """창을 띄울 수 없을 때 윈도우 기본 알림창으로 안내하고 종료합니다."""
    try:
        if IS_WIN:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, APP_TITLE, 0x10)
        else:
            sys.stderr.write(text + "\n")
    finally:
        sys.exit(1)


# 자막 위치 이름 -> (x 식, y 식)
POSITIONS = {
    "좌측 상단": ("w*0.03", "h*0.05"),
    "우측 상단": ("w-text_w-w*0.03", "h*0.05"),
    "좌측 하단": ("w*0.03", "h-text_h-h*0.06"),
    "우측 하단": ("w-text_w-w*0.03", "h-text_h-h*0.06"),
    "하단 중앙": ("(w-text_w)/2", "h-text_h-h*0.06"),
    "화면 중앙": ("(w-text_w)/2", "(h-text_h)/2"),
}
DEFAULT_POSITION = "우측 하단"
HDR_TRANSFERS = ("smpte2084", "arib-std-b67")
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".avi")

INK = "#111827"
SUBTLE = "#3B4656"
ACCENT = "#C2410C"
LINE = "#DDE1E8"


class EditError(Exception):
    """사용자에게 그대로 보여줄 오류 메시지"""


class Cancelled(Exception):
    """사용자가 취소함"""


class MarkError(Exception):
    """구간 지정 중 사용자에게 보여줄 안내 메시지"""


# ----------------------------------------------------------------------
# 도구/글꼴 찾기
# ----------------------------------------------------------------------
SETTINGS_FILE = os.path.join(HERE, "highlight_editor_settings.json")


def _load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        pass


def _exe(name):
    return name + (".exe" if IS_WIN else "")


def _env_dirs():
    env = os.environ
    local = env.get("LOCALAPPDATA", "")
    pf = env.get("ProgramFiles", "C:\\Program Files")
    pf86 = env.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
    home = env.get("USERPROFILE", "") or os.path.expanduser("~")
    return local, pf, pf86, home


def _registry_path_dirs():
    """탐색기에서 실행하면 방금 설치한 프로그램의 PATH를 못 볼 수 있어, 레지스트리에서 직접 읽습니다."""
    dirs = []
    if not IS_WIN:
        return dirs
    try:
        import winreg
    except ImportError:
        return dirs
    places = ((winreg.HKEY_CURRENT_USER, "Environment"),
              (winreg.HKEY_LOCAL_MACHINE,
               r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"))
    for hive, sub in places:
        try:
            with winreg.OpenKey(hive, sub) as key:
                value, _kind = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        dirs += [p for p in str(value).split(";") if p.strip()]
    return dirs


def _candidate_dirs():
    local, pf, pf86, home = _env_dirs()
    dirs = [_load_settings().get("ffmpeg_dir", ""), HERE, os.path.join(HERE, "ffmpeg", "bin")]
    dirs += os.environ.get("PATH", "").split(os.pathsep)
    dirs += _registry_path_dirs()
    if local:
        dirs.append(os.path.join(local, "Microsoft", "WinGet", "Links"))
    dirs += [os.path.join(pf, "WinGet", "Links"),
             os.path.join(pf, "ffmpeg", "bin"), os.path.join(pf86, "ffmpeg", "bin"),
             "C:\\ffmpeg\\bin", os.path.join(home, "ffmpeg", "bin"),
             "C:\\ProgramData\\chocolatey\\bin",
             os.path.join(home, "scoop", "shims"),
             os.path.join(home, "scoop", "apps", "ffmpeg", "current", "bin")]
    seen, out = set(), []
    for d in dirs:
        d = os.path.expandvars(str(d).strip().strip('"'))
        if d and d.lower() not in seen:
            seen.add(d.lower())
            out.append(d)
    return out


def _package_roots():
    local, pf, pf86, _home = _env_dirs()
    roots = [os.path.join(local, "Microsoft", "WinGet", "Packages")] if local else []
    roots += [os.path.join(pf, "WinGet", "Packages"), os.path.join(pf86, "WinGet", "Packages")]
    return roots


def _walk_find(exe, root, max_depth=4):
    if not os.path.isdir(root):
        return None
    base = root.rstrip("\\/").count(os.sep)
    for cur, dirs, files in os.walk(root):   # 접근이 막힌 폴더는 자동으로 건너뜁니다
        if exe in files:
            return os.path.join(cur, exe)
        if cur.count(os.sep) - base >= max_depth:
            dirs[:] = []
    return None


def _glob_find(exe):
    """다운로드·바탕화면 등에 압축을 풀어 둔 FFmpeg 폴더를 찾습니다."""
    _local, _pf, _pf86, home = _env_dirs()
    bases = [os.path.join(home, "Downloads"), os.path.join(home, "Desktop"),
             os.path.join(home, "Documents"), home, "C:\\"]
    for base in bases:
        for pat in ("ffmpeg*/bin", "ffmpeg*/*/bin", "*/ffmpeg*/bin"):
            hits = sorted(glob.glob(os.path.join(base, pat, exe)))
            if hits:
                return hits[-1]
    return None


def find_tool(name, prefer_dir=None):
    """ffmpeg, ffprobe 같은 도구의 위치를 찾습니다. 없으면 None."""
    exe = _exe(name)
    if prefer_dir:
        p = os.path.join(prefer_dir, exe)
        if os.path.isfile(p):
            return p
    found = shutil.which(name)
    if found:
        return found
    for d in _candidate_dirs():
        p = os.path.join(d, exe)
        if os.path.isfile(p):
            return p
    for root in _package_roots():
        hit = _walk_find(exe, root)
        if hit:
            return hit
    return _glob_find(exe)


def find_ffmpeg_pair():
    """(ffmpeg 경로, ffprobe 경로). ffprobe는 ffmpeg와 같은 폴더를 먼저 찾습니다."""
    ff = find_tool("ffmpeg")
    fp = find_tool("ffprobe", prefer_dir=os.path.dirname(ff) if ff else None)
    return ff, fp


def remember_ffmpeg(ffmpeg_path):
    data = _load_settings()
    data["ffmpeg_dir"] = os.path.dirname(ffmpeg_path)
    _save_settings(data)


def admin_install_suspected():
    """관리자 권한으로 설치한 WinGet FFmpeg 폴더가 있는데 못 찾은 경우를 알아봅니다."""
    _local, pf, pf86, _home = _env_dirs()
    for root in (pf, pf86):
        if glob.glob(os.path.join(root, "WinGet", "Packages", "*FFmpeg*")):
            return True
    return False


def _fonts_in(folder):
    out = []
    if folder and os.path.isdir(folder):
        try:
            for f in os.listdir(folder):
                if f.lower().endswith((".ttf", ".otf", ".ttc")):
                    out.append(os.path.join(folder, f))
        except OSError:
            pass
    return out


def find_font():
    """(글꼴 경로, 안내문). 글꼴이 없으면 (None, 안내문)."""
    local = os.environ.get("LOCALAPPDATA", "")
    win = os.environ.get("WINDIR", "C:\\Windows")
    folders = [
        HERE,
        os.path.join(HERE, "static"),
        os.path.join(HERE, "fonts"),
        os.path.join(local, "Microsoft", "Windows", "Fonts") if local else "",
        os.path.join(win, "Fonts"),
    ]
    noto = []
    for fo in folders:
        noto += [p for p in _fonts_in(fo)
                 if os.path.basename(p).lower().startswith("notosanskr")]
    static = [p for p in noto if "variable" not in os.path.basename(p).lower()]
    for weight in ("bold", "medium", "regular"):
        for p in static:
            if weight in os.path.basename(p).lower():
                return p, None
    if static:
        return static[0], None
    if noto:
        return noto[0], ("Noto Sans KR 가변 글꼴만 찾았습니다. 자막이 얇게 보이면 "
                         "static 폴더의 NotoSansKR-Bold.ttf를 이 프로그램 폴더에 넣어 주세요.")
    for name in ("malgunbd.ttf", "malgun.ttf"):
        p = os.path.join(win, "Fonts", name)
        if os.path.isfile(p):
            return p, "Noto Sans KR을 찾지 못해 윈도우 기본 글꼴(맑은 고딕)로 자막을 넣습니다."
    for p in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",):
        if os.path.isfile(p):
            return p, None
    return None, "한글 글꼴을 찾지 못했습니다. 자막을 넣으려면 Noto Sans KR 글꼴이 필요합니다."


# ----------------------------------------------------------------------
# 시간 처리
# ----------------------------------------------------------------------
def parse_time(text):
    """'12:30', '1:02:30', '90', '12:30.5' -> 초(float). 잘못되면 ValueError."""
    t = str(text).strip().replace("：", ":")
    if not t:
        raise ValueError("비어 있음")
    parts = t.split(":")
    if len(parts) > 3:
        raise ValueError("형식 오류")
    secs = 0.0
    for p in parts:
        secs = secs * 60 + float(p)
    if secs < 0:
        raise ValueError("음수")
    return secs


def fmt_time(sec):
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ----------------------------------------------------------------------
# 영상 정보
# ----------------------------------------------------------------------
def _fps(stream):
    for key in ("avg_frame_rate", "r_frame_rate"):
        val = stream.get(key, "0/0")
        try:
            n, d = val.split("/")
            n, d = int(n), int(d)
            if d and 1 <= n / d <= 120:
                return f"{n}/{d}"
        except (ValueError, ZeroDivisionError):
            pass
    return "30/1"


def probe(ffprobe, path):
    cmd = [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path]
    r = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL,
                       creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise EditError("영상 정보를 읽지 못했습니다.\n" + r.stderr.decode("utf-8", "replace")[-400:])
    data = json.loads(r.stdout.decode("utf-8", "replace"))
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if v is None:
        raise EditError("영상 스트림을 찾지 못했습니다.")
    w, h = int(v["width"]), int(v["height"])
    rot = 0
    try:
        rot = int(float(v.get("tags", {}).get("rotate", 0)))
    except (TypeError, ValueError):
        pass
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass
    if abs(rot) % 180 == 90:
        w, h = h, w
    dur = data.get("format", {}).get("duration") or v.get("duration") or 0
    return {
        "width": w - w % 2,
        "height": h - h % 2,
        "fps": _fps(v),
        "duration": float(dur),
        "codec": v.get("codec_name", "?"),
        "transfer": v.get("color_transfer", "") or "",
        "primaries": v.get("color_primaries", "") or "",
        "matrix": v.get("color_space", "") or "",
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "pix_fmt": v.get("pix_fmt", "") or "",
        "acodec": (next((s for s in streams if s.get("codec_type") == "audio"), {}) or {}).get("codec_name", ""),
        "arate": (next((s for s in streams if s.get("codec_type") == "audio"), {}) or {}).get("sample_rate", ""),
        "achannels": (next((s for s in streams if s.get("codec_type") == "audio"), {}) or {}).get("channels", 0),
    }


def has_tonemap_filters(ffmpeg):
    """HDR -> SDR 변환에 필요한 필터(zscale, tonemap)가 있는지."""
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        text = r.stdout.decode("utf-8", "replace")
    except OSError:
        return False
    return " zscale " in text and " tonemap " in text


# ----------------------------------------------------------------------
# 편집 엔진
# ----------------------------------------------------------------------
def _write_text(folder, name, text):
    with open(os.path.join(folder, name), "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\r\n", "\n").replace("\r", "\n").strip("\n"))


def has_encoder(ffmpeg, name):
    """FFmpeg에 해당 인코더(예: libx265)가 들어 있는지."""
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        return (" " + name + " ") in r.stdout.decode("utf-8", "replace")
    except OSError:
        return False


def _hdr_tags(info):
    trc = info["transfer"] if info["transfer"] in HDR_TRANSFERS else "smpte2084"
    prim = info["primaries"] if info["primaries"] else "bt2020"
    mat = info["matrix"] if info["matrix"] else "bt2020nc"
    return prim, trc, mat


def _hdr_codec_args(fps, info):
    prim, trc, mat = _hdr_tags(info)
    x265 = (f"colorprim={prim}:transfer={trc}:colormatrix={mat}:range=limited:"
            "log-level=error")
    return ["-r", fps,
            "-c:v", "libx265", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p10le",
            "-tag:v", "hvc1", "-x265-params", x265,
            "-colorspace", mat, "-color_primaries", prim, "-color_trc", trc,
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


def _drawtext(textfile, fontsize, x, y, color="white"):
    border = max(8, fontsize // 3)
    return (f"drawtext=fontfile=font.ttf:textfile={textfile}:expansion=none:"
            f"fontsize={fontsize}:fontcolor={color}:box=1:boxcolor=black@0.55:"
            f"boxborderw={border}:x={x}:y={y}")


TONEMAP_CHAIN = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                 "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")


def _codec_args(fps):
    return ["-r", fps,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


def _run(cmd, cwd, cancel):
    errfile = os.path.join(cwd, "ffmpeg_error.log")
    with open(errfile, "wb") as ef:
        p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=ef,
                             creationflags=NO_WINDOW)
        while True:
            try:
                rc = p.wait(timeout=0.3)
                break
            except subprocess.TimeoutExpired:
                if cancel.is_set():
                    p.terminate()
                    p.wait()
                    raise Cancelled()
    if rc != 0:
        with open(errfile, "rb") as ef:
            tail = ef.read().decode("utf-8", "replace")[-700:]
        raise EditError("FFmpeg 처리 중 오류가 발생했습니다.\n\n" + tail)


RATIOS = {"1:1": (1, 1), "4:3": (4, 3), "16:9": (16, 9)}
DEFAULT_RATIO = "16:9"


def _even(v):
    v = int(round(v))
    return max(2, v - v % 2)


def output_size(W, H, ratio_name):
    """저장 영상 크기. 가로 영상은 높이를 유지하고 가로를 비율에 맞춥니다. (1920x1080: 1:1→1080x1080, 4:3→1440x1080)"""
    rw, rh = RATIOS.get(ratio_name, RATIOS[DEFAULT_RATIO])
    r = rw / rh
    oh, ow = H, H * r
    longest = max(W, H)
    if ow > longest:
        ow, oh = longest, longest / r
    return _even(ow), _even(oh)


def normalize_crop(crop, W, H):
    """화면에서 온 범위(가로·세로 비율 0~1)를 영상 픽셀 (너비, 높이, x, y)로 바꿉니다. 없거나 전체이면 None."""
    if not crop:
        return None
    try:
        x, y, w, h = (float(crop[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        return None
    w = min(max(w, 0.02), 1.0)
    h = min(max(h, 0.02), 1.0)
    x = min(max(x, 0.0), 1.0 - w)
    y = min(max(y, 0.0), 1.0 - h)
    cw, ch = _even(w * W), _even(h * H)
    cx, cy = int(x * W), int(y * H)
    cx -= cx % 2
    cy -= cy % 2
    cw = min(cw, W - cx - (W - cx) % 2)
    ch = min(ch, H - cy - (H - cy) % 2)
    if cw >= W and ch >= H:
        return None
    return cw, ch, cx, cy


def make_highlight(ffmpeg, src, info, segments, title, font, out_path,
                   progress, cancel, tonemap_ok, keep_hdr=True, out_ratio=DEFAULT_RATIO,
                   out_size=None, label="득점 구간"):
    """
    segments: [{"start": 초, "end": 초, "text": 문자열, "pos": 위치이름, "crop": {x,y,w,h}(0~1) 또는 None}, ...]
    out_ratio: 저장 영상 비율 "1:1" / "4:3" / "16:9"  (비율이 다른 구간은 검은 여백으로 맞춤)
    title:    {"text": 문자열, "secs": 초} 또는 None  (메인화면)
    progress: progress(완료 수, 전체 수, 메시지)
    """
    needs_font = bool(title and title["text"]) or any(s["text"] for s in segments)
    if needs_font and not font:
        raise EditError("자막용 한글 글꼴을 찾지 못했습니다.\nNoto Sans KR 글꼴을 설치하거나 "
                        "프로그램 폴더에 넣어 주세요.")
    src = os.path.abspath(src)
    out_path = os.path.abspath(out_path)
    W, H, fps = info["width"], info["height"], info["fps"]
    OW, OH = out_size if out_size else output_size(W, H, out_ratio)
    is_hdr = info["transfer"] in HDR_TRANSFERS
    keep = is_hdr and keep_hdr and has_encoder(ffmpeg, "libx265")   # 원본 HDR 그대로 저장
    hdr = is_hdr and not keep and tonemap_ok                        # (대안) 일반 색상으로 변환
    pixfmt = "yuv420p10le" if keep else "yuv420p"
    # 자막 글자색: HDR 화면에서 눈부시지 않도록 기준 흰색(약 200nit) 수준의 회색
    txt_color = "white"
    if keep:
        txt_color = "#949494" if info["transfer"] == "smpte2084" else "#BFBFBF"
    codec = (lambda: _hdr_codec_args(fps, info)) if keep else (lambda: _codec_args(fps))
    tmp = tempfile.mkdtemp(prefix="hl_")
    try:
        if font:
            shutil.copyfile(font, os.path.join(tmp, "font.ttf"))
        total = (1 if title else 0) + len(segments) + 1
        done = 0
        parts = []

        if title:
            secs = f"{title['secs']:.3f}"
            progress(done, total, "메인화면 만드는 중...")
            _write_text(tmp, "title.txt", title["text"])
            fs = max(24, round(OH / 12))
            vf = ",".join([
                f"format={pixfmt}",
                _drawtext("title.txt", fs, "(w-text_w)/2", "(h-text_h)/2", txt_color),
            ])
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "lavfi", "-i", f"color=c=black:s={OW}x{OH}:r={fps}:d={secs}",
                   "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                   "-t", secs, "-map", "0:v", "-map", "1:a", "-vf", vf] + codec() + \
                  ["seg_title.mp4"]
            _run(cmd, tmp, cancel)
            parts.append("seg_title.mp4")
            done += 1

        for i, s in enumerate(segments, start=1):
            progress(done, total, f"{label} {i}/{len(segments)} 처리 중...")
            dur = s["end"] - s["start"]
            vf_parts = []
            cp = normalize_crop(s.get("crop"), W, H)
            if cp:
                vf_parts.append(f"crop={cp[0]}:{cp[1]}:{cp[2]}:{cp[3]}")
            # 저장 크기에 맞추고, 비율이 다르면 검은 여백
            vf_parts.append(f"scale={OW}:{OH}:force_original_aspect_ratio=decrease:flags=lanczos")
            vf_parts.append(f"pad={OW}:{OH}:(ow-iw)/2:(oh-ih)/2:black")
            vf_parts.append(TONEMAP_CHAIN if hdr else f"format={pixfmt}")
            if s["text"]:
                _write_text(tmp, f"sub_{i}.txt", s["text"])
                x, y = POSITIONS.get(s["pos"], POSITIONS[DEFAULT_POSITION])
                vf_parts.append(_drawtext(f"sub_{i}.txt", max(18, round(OH / 18)), x, y, txt_color))
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                   "-ss", f"{s['start']:.3f}", "-i", src, "-t", f"{dur:.3f}"]
            if info["has_audio"]:
                audio_map = "0:a:0"
            else:
                cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
                audio_map = "1:a:0"
            cmd += ["-map", "0:v:0", "-map", audio_map, "-vf", ",".join(vf_parts)]
            cmd += codec() + [f"seg_{i:03d}.mp4"]
            _run(cmd, tmp, cancel)
            parts.append(f"seg_{i:03d}.mp4")
            done += 1

        progress(done, total, "하나의 영상으로 합치는 중...")
        with open(os.path.join(tmp, "list.txt"), "w", encoding="utf-8") as f:
            for p in parts:
                f.write(f"file '{p}'\n")
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", "list.txt",
               "-c", "copy", "-movflags", "+faststart", "final.mp4"]
        _run(cmd, tmp, cancel)
        shutil.move(os.path.join(tmp, "final.mp4"), out_path)
        progress(total, total, "완료")
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)



# ----------------------------------------------------------------------
# 구간 삭제(컷 편집) / 영상 합치기
# ----------------------------------------------------------------------
def merge_ranges(ranges, dur=0.0):
    """겹치거나 붙은 구간을 합치고 영상 길이 안으로 자릅니다. [(시작, 끝)] -> 정렬된 [(시작, 끝)]"""
    out = []
    for s, e in sorted((max(0.0, float(a)), float(b)) for a, b in ranges):
        if dur:
            e = min(e, float(dur))
        if e - s <= 0.001:
            continue
        if out and s <= out[-1][1] + 0.001:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def keep_ranges(deletes, dur, min_len=0.2):
    """지울 구간을 뺀 나머지(남길 구간) 목록"""
    keep, cur = [], 0.0
    for s, e in merge_ranges(deletes, dur):
        if s - cur >= min_len:
            keep.append((cur, s))
        cur = max(cur, e)
    if dur - cur >= min_len:
        keep.append((cur, float(dur)))
    return keep


def _esc(path):
    return path.replace("'", "'\\''")


def _write_concat(folder, paths, name="list.txt"):
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        for p in paths:
            f.write("file '%s'\n" % _esc(p))
    return name


def _concat_copy(ffmpeg, tmp, paths, out_name, cancel):
    _write_concat(tmp, paths)
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
           "-i", "list.txt", "-c", "copy", "-movflags", "+faststart", out_name]
    _run(cmd, tmp, cancel)


def make_cut(ffmpeg, src, info, deletes, out_path, progress, cancel, tonemap_ok, fast=False):
    """영상에서 deletes([(시작, 끝)])를 지우고 나머지를 이어 붙여 저장합니다.
    fast=True: 다시 인코딩하지 않아 빠르고 화질 손실이 없지만, 경계가 가까운 키프레임으로 맞춰져 약간 어긋날 수 있습니다."""
    dur = info["duration"]
    keep = keep_ranges(deletes, dur)
    if not keep:
        raise EditError("지우고 남는 영상이 없습니다. 지울 구간을 확인해 주세요.")
    if not fast:
        segs = [{"start": s, "end": e, "text": "", "pos": DEFAULT_POSITION, "crop": None} for s, e in keep]
        return make_highlight(ffmpeg, src, info, segs, None, None, out_path, progress, cancel,
                              tonemap_ok, True, DEFAULT_RATIO,
                              out_size=(info["width"], info["height"]), label="남길 구간")
    src = os.path.abspath(src)
    out_path = os.path.abspath(out_path)
    tmp = tempfile.mkdtemp(prefix="hl_")
    try:
        total = len(keep) + 1
        parts = []
        for i, (s, e) in enumerate(keep, start=1):
            progress(i - 1, total, f"남길 구간 {i}/{len(keep)} 자르는 중...")
            name = f"seg_{i:03d}.mp4"
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{s:.3f}", "-i", src,
                   "-t", f"{e - s:.3f}", "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                   "-avoid_negative_ts", "make_zero"]
            if info["codec"] == "hevc":
                cmd += ["-tag:v", "hvc1"]
            _run(cmd + [name], tmp, cancel)
            parts.append(name)
        progress(len(keep), total, "하나의 영상으로 합치는 중...")
        _concat_copy(ffmpeg, tmp, parts, "final.mp4", cancel)
        shutil.move(os.path.join(tmp, "final.mp4"), out_path)
        progress(total, total, "완료")
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _most_common(values):
    counts, order = {}, []
    for v in values:
        if v not in counts:
            counts[v] = 0
            order.append(v)
        counts[v] += 1
    best = order[0]
    for v in order:
        if counts[v] > counts[best]:
            best = v
    return best, counts[best]


def merge_plan(clips, transition=False, can_hdr=True):
    """합칠 영상들의 저장 조건을 정합니다. (가장 많은 크기·fps를 따르고, 모두 HDR이면 HDR 유지)"""
    infos = [c["info"] for c in clips]
    (ow, oh), n_size = _most_common([(i["width"], i["height"]) for i in infos])
    fps, _ = _most_common([i["fps"] for i in infos])
    all_hdr = all(i["transfer"] in HDR_TRANSFERS for i in infos)
    same_tr = len({i["transfer"] for i in infos}) == 1
    keep = bool(all_hdr and same_tr and can_hdr)
    any_hdr = any(i["transfer"] in HDR_TRANSFERS for i in infos)
    keys = {(i["codec"], i["width"], i["height"], i["fps"], i["transfer"], i["pix_fmt"], i["has_audio"],
             i["acodec"], i["arate"], i["achannels"]) for i in infos}
    fast = bool(len(keys) == 1 and not transition)
    return {"width": ow, "height": oh, "fps": fps, "keep": keep, "mixed_hdr": bool(any_hdr and not all_hdr),
            "fast": fast, "n_same_size": n_size, "ref": infos[0]}


def make_merge(ffmpeg, clips, out_path, progress, cancel, tonemap_ok, transition=False):
    """여러 영상을 순서대로 하나의 MP4로 합칩니다.
    clips: [{"path": 경로, "info": probe 결과}, ...]
    모두 같은 조건이면 다시 인코딩하지 않고 붙이고, 크기·fps·HDR이 다르면 맞춰서 다시 인코딩합니다."""
    if len(clips) < 2:
        raise EditError("합칠 영상을 2개 이상 추가해 주세요.")
    out_path = os.path.abspath(out_path)
    paths = [os.path.abspath(c["path"]) for c in clips]
    if os.path.abspath(out_path) in paths:
        raise EditError("합칠 영상과 같은 이름으로는 저장할 수 없습니다.")
    plan = merge_plan(clips, transition, has_encoder(ffmpeg, "libx265"))
    OW, OH, fps, keep = plan["width"], plan["height"], plan["fps"], plan["keep"]
    pixfmt = "yuv420p10le" if keep else "yuv420p"
    tmp = tempfile.mkdtemp(prefix="hl_")
    try:
        if plan["fast"]:
            progress(0, 2, "영상을 이어 붙이는 중... (다시 인코딩하지 않습니다)")
            _concat_copy(ffmpeg, tmp, paths, "final.mp4", cancel)
            shutil.move(os.path.join(tmp, "final.mp4"), out_path)
            progress(2, 2, "완료")
            return out_path
        total = len(clips) + 1
        codec = (lambda: _hdr_codec_args(fps, plan["ref"])) if keep else (lambda: _codec_args(fps))
        norm, durs = [], []
        for i, (c, p) in enumerate(zip(clips, paths), start=1):
            progress(i - 1, total, f"영상 {i}/{len(clips)} 크기·색상 맞추는 중...")
            info = c["info"]
            is_hdr = info["transfer"] in HDR_TRANSFERS
            vf = [f"scale={OW}:{OH}:force_original_aspect_ratio=decrease:flags=lanczos",
                  f"pad={OW}:{OH}:(ow-iw)/2:(oh-ih)/2:black"]
            if is_hdr and not keep and tonemap_ok:
                vf.append(TONEMAP_CHAIN)
            else:
                vf.append(f"format={pixfmt}")
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", p]
            if info["has_audio"]:
                amap = "0:a:0"
            else:
                cmd += ["-f", "lavfi", "-t", f"{info['duration']:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
                amap = "1:a:0"
            cmd += ["-map", "0:v:0", "-map", amap, "-vf", ",".join(vf)] + codec()
            name = f"n_{i:03d}.mp4"
            _run(cmd + [name], tmp, cancel)
            norm.append(name)
            durs.append(float(info["duration"]))
        progress(len(clips), total, "하나의 영상으로 합치는 중...")
        if not transition:
            _concat_copy(ffmpeg, tmp, norm, "final.mp4", cancel)
        else:
            T = max(0.1, min(0.5, min(durs) / 3.0))
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
            for n in norm:
                cmd += ["-i", n]
            fv, fa, acc = [], [], 0.0
            prev_v, prev_a = "0:v", "0:a"
            for k in range(1, len(norm)):
                acc += durs[k - 1]
                off = acc - k * T
                fv.append(f"[{prev_v}][{k}:v]xfade=transition=fade:duration={T:.3f}:offset={off:.3f}[v{k}]")
                fa.append(f"[{prev_a}][{k}:a]acrossfade=d={T:.3f}[a{k}]")
                prev_v, prev_a = f"v{k}", f"a{k}"
            last = len(norm) - 1
            cmd += ["-filter_complex", ";".join(fv + fa), "-map", f"[v{last}]", "-map", f"[a{last}]"]
            cmd += codec() + ["-movflags", "+faststart", "final.mp4"]
            _run(cmd, tmp, cancel)
        shutil.move(os.path.join(tmp, "final.mp4"), out_path)
        progress(total, total, "완료")
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------
# 편집 로그 (불러온 영상·득점 구간·자막·범위 설정을 파일로 저장/복원)
# ----------------------------------------------------------------------
LOG_KIND = "basketball-highlight-log"


def build_log(video_path, video_name, info, rows, title):
    """편집 상태를 로그(dict)로 만듭니다. video_path가 비어 있으면(끌어다 놓은 파일) 이름만 기록합니다."""
    import datetime
    out_rows = []
    for r in rows:
        crop = r.get("crop") if r.get("cropOn") else None
        out_rows.append({"start": r.get("start"), "end": r.get("end"), "text": str(r.get("text") or ""),
                         "pos": r.get("pos"), "cropOn": bool(crop),
                         "cropRatio": r.get("cropRatio") if crop else None, "crop": crop})
    return {"kind": LOG_KIND, "version": 1,
            "saved": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "video": {"path": video_path or "", "name": video_name, "width": info["width"],
                      "height": info["height"], "duration": info["duration"]},
            "title": {"on": bool(title.get("on")), "text": str(title.get("text") or ""),
                      "secs": str(title.get("secs") or "3")},
            "rows": out_rows}


def get_log_dir():
    """로그를 저장할 폴더(구글 드라이브·OneDrive 같은 동기화 폴더 등). 지정하지 않았거나 없으면 빈 문자열."""
    d = _load_settings().get("log_dir", "")
    return d if d and os.path.isdir(d) else ""


def set_log_dir(path):
    data = _load_settings()
    data["log_dir"] = path
    _save_settings(data)


def get_theme():
    t = _load_settings().get("theme", "auto")
    return t if t in ("light", "dark", "auto") else "auto"


def set_theme(mode):
    if mode not in ("light", "dark", "auto"):
        return
    data = _load_settings()
    data["theme"] = mode
    _save_settings(data)


def log_default_name(video_name):
    """로그 기본 파일명: 저장한 날짜(YYMMDD) + 영상 파일명. 예) 261103_파미용배 2경기 하이라이트.json"""
    import datetime
    return datetime.datetime.now().strftime("%y%m%d") + "_" + os.path.splitext(os.path.basename(video_name))[0] + ".json"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f >= 0 else None


def clean_log_rows(raw_rows, duration=0.0):
    """로그의 구간 목록을 검사해 화면에서 쓰는 형태로 바꿉니다. (잘못된 값은 버립니다)"""
    out = []
    for r in raw_rows if isinstance(raw_rows, list) else []:
        if not isinstance(r, dict):
            continue
        st, en = _num(r.get("start")), _num(r.get("end"))
        if duration:
            st = min(st, duration) if st is not None else None
            en = min(en, duration) if en is not None else None
        if st is not None and en is not None and en <= st:
            en = None
        crop, ratio = None, r.get("cropRatio")
        c = r.get("crop")
        if isinstance(c, dict) and ratio in RATIOS:
            x, y, w, h = (_num(c.get(k)) for k in ("x", "y", "w", "h"))
            if None not in (x, y, w, h) and 0 < w <= 1 and 0 < h <= 1 and x + w <= 1.0001 and y + h <= 1.0001:
                crop = {"x": x, "y": y, "w": w, "h": h}
        out.append({"start": st, "end": en, "text": str(r.get("text") or ""),
                    "pos": r.get("pos") if r.get("pos") in POSITIONS else DEFAULT_POSITION,
                    "active": False, "cropOn": bool(crop), "cropRatio": ratio if crop else None, "crop": crop})
    return out


def read_log(path):
    """로그 파일을 읽어 검사한 뒤 dict로 돌려줍니다."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            log = json.load(f)
    except (OSError, ValueError):
        raise EditError("편집 로그 파일을 읽을 수 없습니다. 이 프로그램에서 저장한 로그 파일인지 확인해 주세요.")
    if not isinstance(log, dict) or log.get("kind") != LOG_KIND or not isinstance(log.get("video"), dict):
        raise EditError("이 프로그램에서 저장한 편집 로그 파일이 아닙니다.")
    v = log["video"]
    t = log.get("title") if isinstance(log.get("title"), dict) else {}
    return {"video": {"path": str(v.get("path") or ""), "name": str(v.get("name") or ""),
                      "duration": _num(v.get("duration")) or 0.0},
            "title": {"on": bool(t.get("on")), "text": str(t.get("text") or ""), "secs": str(t.get("secs") or "3")},
            "rows": log.get("rows") if isinstance(log.get("rows"), list) else []}


# ----------------------------------------------------------------------
# 득점 구간 목록 계산 (화면과 무관한 부분)
# ----------------------------------------------------------------------
def fmt_time1(sec):
    """초 -> '05:42.3' (0.1초 단위). None이면 빈 문자열."""
    if sec is None:
        return ""
    tenths = int(round(max(0.0, float(sec)) * 10))
    h, rem = divmod(tenths, 36000)
    m, rem = divmod(rem, 600)
    s = rem / 10
    return f"{h}:{m:02d}:{s:04.1f}" if h else f"{m:02d}:{s:04.1f}"


def fps_label(fps):
    """'30000/1001' -> '29.97', '30/1' -> '30'"""
    try:
        n, d = fps.split("/")
        v = int(n) / int(d)
    except (ValueError, ZeroDivisionError):
        return str(fps)
    return f"{v:.0f}" if abs(v - round(v)) < 0.005 else f"{v:.2f}"


def new_row(start=None, end=None, active=False):
    return {"start": start, "end": end, "text": "", "pos": DEFAULT_POSITION, "active": active,
            "cropOn": False, "cropRatio": None, "crop": None}


class Marks:
    """득점 구간 목록. [득점 시작]을 누르면 '지정 중' 행이 생기고, [득점 종료]에서 완성됩니다."""

    def __init__(self):
        self.rows = []

    def active_index(self):
        for i, r in enumerate(self.rows):
            if r["active"]:
                return i
        return None

    def begin(self, pos):
        if self.active_index() is not None:
            raise MarkError("이미 [득점 시작]을 눌렀습니다. 먼저 [득점 종료]를 눌러 주세요.")
        self.rows.append(new_row(start=float(pos), active=True))

    def finish(self, pos):
        i = self.active_index()
        if i is None:
            raise MarkError("먼저 [득점 시작]을 눌러 주세요.")
        r = self.rows[i]
        if pos <= r["start"]:
            raise MarkError("종료 위치가 시작 위치보다 앞입니다. 영상을 더 재생한 뒤 눌러 주세요.")
        r["end"] = float(pos)
        r["active"] = False
        return i

    def cancel(self):
        i = self.active_index()
        if i is None:
            return False
        del self.rows[i]
        return True

    def add_blank(self):
        self.rows.append(new_row())

    def delete(self, i):
        del self.rows[i]

    def set_time(self, i, key, value):
        """key는 'start' 또는 'end', value는 초 또는 None(비움)."""
        r = self.rows[i]
        other = r["end" if key == "start" else "start"]
        if value is not None and other is not None:
            s, e = (value, other) if key == "start" else (other, value)
            if e <= s:
                raise MarkError("종료 시간은 시작 시간보다 늦어야 합니다.")
        r[key] = value

    def nudge(self, i, key, delta, duration=0.0):
        """시작/종료 시간을 delta초만큼 움직입니다. 결과 시간을 돌려줍니다."""
        cur = self.rows[i][key]
        if cur is None:
            raise MarkError("먼저 시간을 입력해 주세요.")
        new = max(0.0, cur + delta)
        if duration and new > duration:
            new = float(duration)
        self.set_time(i, key, new)
        return new

    def complete_ranges(self):
        return [(r["start"], r["end"]) for r in self.rows
                if not r["active"] and r["start"] is not None
                and r["end"] is not None and r["end"] > r["start"]]


def auto_out_ratio(rows):
    """저장 영상 비율을 자동으로 정합니다: 완성된 구간 중 가장 많이 지정된 비율.
    범위를 쓰지 않은 구간은 전체 화면(16:9)으로 셉니다. 동률이면 먼저 나온 구간의 비율. 구간이 없으면 16:9."""
    counts, order = {}, []
    for r in rows:
        if r["active"] or r["start"] is None or r["end"] is None or r["end"] <= r["start"]:
            continue
        name = r["cropRatio"] if (r.get("cropOn") and r.get("crop") and r.get("cropRatio") in RATIOS) else DEFAULT_RATIO
        if name not in counts:
            order.append(name)
            counts[name] = 0
        counts[name] += 1
    if not counts:
        return DEFAULT_RATIO, 0, 0
    best = max(order, key=lambda n: (counts[n], -order.index(n)))
    return best, counts[best], sum(counts.values())


def crop_base(W, H, ratio):
    """비율 ratio에서 영상 안에 들어가는 가장 큰 사각형 (가로, 세로: 0~1)"""
    a, b = RATIOS[ratio]
    r = a / b
    return (r * H / W, 1.0) if r <= W / H else (1.0, W / (r * H))


def crop_make(W, H, ratio, zoom, cx=0.5, cy=0.5):
    """확대 배율 zoom(1~4)과 중심 (cx, cy)로 범위 사각형 {x,y,w,h} (0~1)을 만듭니다."""
    bw, bh = crop_base(W, H, ratio)
    zoom = min(4.0, max(1.0, float(zoom)))
    w, h = bw / zoom, bh / zoom
    return {"w": w, "h": h,
            "x": min(1.0 - w, max(0.0, cx - w / 2)),
            "y": min(1.0 - h, max(0.0, cy - h / 2))}


def crop_zoom(W, H, ratio, crop):
    return crop_base(W, H, ratio)[0] / crop["w"]


def crop_center(crop):
    return crop["x"] + crop["w"] / 2, crop["y"] + crop["h"] / 2


def crop_resize(W, H, ratio, crop, handle, px, py):
    """모서리(handle: tl/tr/bl/br)를 (px, py)로 끌었을 때의 새 범위. 반대쪽 모서리는 고정, 비율 유지."""
    a, b = RATIOS[ratio]
    k = (W / H) * (b / a)                     # 정규화 좌표에서 높이 = 너비 * k
    left = handle in ("tl", "bl")
    up = handle in ("tl", "tr")
    ax = crop["x"] + crop["w"] if left else crop["x"]
    ay = crop["y"] + crop["h"] if up else crop["y"]
    w = max(abs(px - ax), abs(py - ay) / k)
    avail_x = ax if left else 1.0 - ax
    avail_y = ay if up else 1.0 - ay
    w = min(w, avail_x, avail_y / k)
    w = max(w, crop_base(W, H, ratio)[0] / 4)  # 최대 4배 확대
    w = min(w, avail_x, avail_y / k)
    h = w * k
    return {"w": w, "h": h, "x": ax - w if left else ax, "y": ay - h if up else ay}


def len_text(r):
    if r["start"] is not None and r["end"] is not None and r["end"] > r["start"]:
        return f"{r['end'] - r['start']:.1f}초"
    return "-"


def collect_segments(rows, duration):
    """편집에 쓸 구간 목록을 만듭니다. 문제가 있으면 ValueError(안내문)."""
    segs = []
    for i, r in enumerate(rows, start=1):
        if r["active"]:
            raise ValueError(f"{i}번 구간은 아직 [득점 종료]를 누르지 않았습니다.\n"
                             "종료를 누르거나 [지정 취소]를 눌러 주세요.")
        s, e, t = r["start"], r["end"], r["text"].strip()
        if s is None and e is None and not t:
            continue
        if s is None or e is None:
            raise ValueError(f"{i}번 구간의 시작/종료 시간을 입력해 주세요.")
        if e <= s:
            raise ValueError(f"{i}번 구간은 종료 시간이 시작 시간보다 늦어야 합니다.")
        if duration and s >= duration:
            raise ValueError(f"{i}번 구간의 시작 시간이 영상 길이({fmt_time(duration)})를 넘었습니다.")
        if duration and e > duration + 0.5:
            e = duration
        segs.append({"start": s, "end": e, "text": t, "pos": r["pos"],
                     "crop": r.get("crop") if r.get("cropOn") else None})
    return segs




PAGE = r'''<!doctype html>
<html lang="ko">
<head>
<script>(function(){var m="__THEME__";var d=m==="dark"||(m==="auto"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.dataset.theme=d?"dark":"light";window.__themeMode=m;})()</script>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="icon" type="image/png" href="data:image/png;base64,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">
<style>
:root{--ink:#14263D;--sub:#5B6F86;--card:#FFFFFF;--cardline:#CFE6FA;--navy:#2F80ED;--navyl:#DCEBFF;--navyb:#9CC4F5;
--green:#18B26B;--orange:#FF7A45;--teal:#2F80ED;--purple:#7C5CFF;--red:#E5484D;--field:#F3F9FF;--fline:#B7D6F4;--acc:#FFC93C;--seg:#FF9F43;
--video:#0E2238;--hover:#EAF4FF;--dis:#E4EDF6;--disink:#8CA0B8;--rowsel:#FFF6D6;--rowact:#FFE9DA;--rowdel:#FFE4E4;--note:#FFF8E1;--noteline:#FFD97A;--noteink:#7A5200;
--clipbg:#F3F9FF;--clipsel:#E3F0FF;--shadow:0 4px 14px rgba(47,128,237,.12);--onacc:#14263D;--dstart:#E5484D;--dend:#9B2C34;
--bgfrom:#E8F4FF;--bgto:#FFF4CC;--grad:linear-gradient(135deg,#E8F4FF,#FFF4CC)}
html[data-theme=dark]{--ink:#EAF3FF;--sub:#9DB2CC;--card:#18283F;--cardline:#294262;--navy:#5BA8FF;--navyl:#22406A;--navyb:#3A6296;
--green:#2BD283;--orange:#FF8A57;--teal:#5BA8FF;--purple:#8E78FF;--red:#FF6B70;--field:#102036;--fline:#355278;--acc:#FFD35C;--seg:#FFA84F;
--video:#050C16;--hover:#22364F;--dis:#223149;--disink:#60758F;--rowsel:#3A3320;--rowact:#4A2E22;--rowdel:#4A2328;--note:#3A3320;--noteline:#6B5A25;--noteink:#FFD98A;
--clipbg:#102036;--clipsel:#22406A;--shadow:0 4px 16px rgba(0,0,0,.35);--onacc:#14263D;--dstart:#FF6B70;--dend:#C2454D;
--bgfrom:#0E1A2B;--bgto:#16233A;--grad:linear-gradient(135deg,#0E1A2B,#16233A)}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{background:var(--grad) fixed;color:var(--ink);font:15px/1.4 "Malgun Gothic","Noto Sans KR",system-ui,sans-serif;padding:14px;display:flex;flex-direction:column;gap:12px;min-width:980px}
.card{background:var(--card);border:1px solid var(--cardline);border-radius:16px;padding:12px 14px;box-shadow:var(--shadow)}
.h{font-weight:700;font-size:16px;white-space:nowrap}
.sub{color:var(--sub);font-size:13px}
.top{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.top .card{display:flex;align-items:center;gap:12px}
.main{display:grid;grid-template-columns:135fr 100fr;gap:12px;flex:1;min-height:0}
.main>.card{display:flex;flex-direction:column;gap:10px;min-height:0}
button{font:inherit;font-weight:700;border:2px solid var(--fline);border-radius:12px;background:var(--card);color:var(--ink);padding:4px 14px;min-height:34px;cursor:pointer}
button:hover:not(:disabled){background:var(--hover)}

button.file{background:var(--teal);border-color:var(--teal);color:#fff}
button.file:hover:not(:disabled){background:var(--teal);filter:brightness(.92)}
button.move{background:var(--navyl);color:var(--navy);border-color:var(--navyb)}
button.play{background:var(--navy);color:#fff;border-color:var(--navy);padding:4px 20px}
button.play:hover:not(:disabled){background:var(--navy);filter:brightness(.92)}
button.stop{background:var(--card);color:var(--navy);border-color:var(--navy);padding:4px 20px}
button.start{background:var(--green);border-color:var(--green);color:#fff;font-size:17px;border-radius:14px;min-height:48px}
button.start:hover:not(:disabled){background:var(--green);filter:brightness(.92)}
button.end{background:var(--orange);border-color:var(--orange);color:#fff;font-size:17px;border-radius:14px;min-height:48px}
button.end:hover:not(:disabled){background:var(--orange);filter:brightness(.92)}
button.danger{background:var(--card);color:var(--red);border-color:var(--red);border-radius:14px;min-height:48px}
button.danger:hover:not(:disabled){background:var(--rowdel)}
button.add{background:var(--card);color:var(--navy);border-color:var(--navy);width:100%}
button.add:hover:not(:disabled){background:var(--navyl)}
button.go{background:var(--purple);border-color:var(--purple);color:#fff;font-size:16px;min-height:44px;padding:4px 22px;border-radius:14px}
button.go:hover:not(:disabled){background:var(--purple);filter:brightness(.92)}
button.mini{width:34px;min-height:34px;padding:0;border-radius:10px}
button.mplay{background:var(--navyl);color:var(--navy);border-color:var(--navy)}
button.mdel{color:var(--red);border-color:var(--red)}
button.mdel:hover:not(:disabled){background:var(--rowdel)}
button.nudge{background:var(--navyl);color:var(--navy);border-color:var(--navyb);width:35px;min-height:30px;padding:0;border-radius:8px;font-size:13px}
button.num{border:0;background:transparent;width:30px;padding:0}
button.num:hover{background:var(--dis)!important}
input[type=text],select{font:inherit;border:2px solid var(--fline);border-radius:10px;padding:2px 8px;min-height:32px;background:var(--field);color:var(--ink);min-width:0}
select option{background:var(--card);color:var(--ink)}
input[type=text]:focus,select:focus{outline:0;border-color:var(--acc)}
input:disabled{background:var(--dis);color:var(--disink);border-color:var(--dis)}
input[type=checkbox]{width:20px;height:20px;accent-color:var(--navy)}
label.chk{display:flex;align-items:center;gap:6px;font-weight:700;white-space:nowrap}
.pill{background:var(--dis);color:var(--sub);border-radius:14px;padding:5px 14px;font-size:14px}
.pill.on{background:var(--orange);color:#fff;font-weight:700}
.vbox{background:var(--video);border-radius:14px;flex:1;min-height:200px;position:relative;display:flex;align-items:center;justify-content:center}
.vbox video{width:100%;height:100%;object-fit:contain;border-radius:14px}
.vbox .ph{position:absolute;color:#C9D1DD;text-align:center;padding:20px;pointer-events:none;white-space:pre-line}
.vbox.drag{outline:4px dashed var(--acc)}
#cropLayer{position:absolute;overflow:hidden;display:none;pointer-events:none;border-radius:2px}
#crect{position:absolute;border:3px solid var(--acc);box-shadow:0 0 0 9999px rgba(0,0,0,.55);pointer-events:auto;cursor:move;touch-action:none}
#crect .hd{position:absolute;width:14px;height:14px;background:var(--acc);border:1px solid #000a}
#crect .hd.tl{left:-9px;top:-9px;cursor:nwse-resize}#crect .hd.tr{right:-9px;top:-9px;cursor:nesw-resize}
#crect .hd.bl{left:-9px;bottom:-9px;cursor:nesw-resize}#crect .hd.br{right:-9px;bottom:-9px;cursor:nwse-resize}
#crect .tag{position:absolute;left:6px;top:6px;background:var(--acc);color:#14263D;font-weight:700;font-size:13px;padding:1px 8px;border-radius:10px;pointer-events:none;white-space:nowrap}
.cropbar{background:var(--field);border:2px solid var(--fline);border-radius:12px;padding:6px 10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.cropbar.on{border-color:var(--acc)}
.cropbar button{min-height:30px;padding:0 12px}
.seg2{display:inline-flex}.seg2 button{border-radius:0}.seg2 button:first-child{border-radius:12px 0 0 12px}.seg2 button:last-child{border-radius:0 12px 12px 0}
button.sel{background:var(--navy)!important;color:#fff!important;border-color:var(--navy)!important}
.item.sel{background:var(--rowsel);border-color:var(--acc)}
.seek{position:relative;height:18px;border:1px solid var(--fline);border-radius:9px;background:var(--field);cursor:pointer;margin:2px 0}
.seek .seg{position:absolute;top:2px;bottom:2px;background:var(--seg);border-radius:6px;opacity:.95}
.seek .seg.act{background:repeating-linear-gradient(45deg,var(--orange) 0 4px,#FFD0B5 4px 8px)}
.seek .head{position:absolute;top:-4px;bottom:-4px;width:4px;background:var(--ink);border-radius:2px;transform:translateX(-2px)}
.row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.spacer{flex:1}
.list{flex:1;overflow-y:auto;overflow-x:hidden;min-height:120px}
.lh,.l1{display:grid;grid-template-columns:30px minmax(90px,1fr) 112px 34px 34px;gap:6px;align-items:center}
.lh{color:var(--sub);font-size:13px;font-weight:700;padding:0 8px}
.lh span{text-align:center}
.item{border:2px solid transparent;border-radius:12px;padding:6px 8px;margin-bottom:4px;display:flex;flex-direction:column;gap:4px}
.item.act{background:var(--rowact);border-color:var(--orange)}
.l2{display:flex;align-items:center;gap:3px;flex-wrap:wrap;padding-left:30px}
.l2 input{width:68px;text-align:center;padding:2px 4px}
.l2 .lab{margin-left:2px}
.l2 .len{margin-left:4px;font-weight:700;white-space:nowrap}
.ghost{border:2px dashed var(--fline);border-radius:12px;padding:10px;color:var(--sub);font-size:13px;text-align:center}
.msg{color:var(--orange);font-weight:700;min-height:20px}
.prog{height:14px;border:1px solid var(--fline);background:var(--field);border-radius:7px;overflow:hidden;flex:none;width:100%}
.prog i{display:block;height:100%;width:0;background:var(--purple);transition:width .3s}
.bot{display:flex;align-items:center;gap:12px}
.bot .st{font-size:13px;color:var(--sub);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%}
dialog{border:2px solid var(--fline);border-radius:16px;padding:18px 22px;max-width:560px;color:var(--ink);background:var(--card)}
dialog::backdrop{background:rgba(15,23,42,.5)}
dialog pre{white-space:pre-wrap;font:inherit;margin:0 0 14px}
#dropAll{position:fixed;inset:0;background:rgba(255,201,60,.25);border:6px dashed var(--acc);display:none;align-items:center;justify-content:center;font-size:28px;font-weight:700;color:var(--ink);z-index:50;pointer-events:none}
[hidden]{display:none!important}
.tabs{display:flex;gap:6px;align-items:flex-end;margin-bottom:-6px}
.tabs>button[data-tab]{border:2px solid transparent;border-bottom:4px solid transparent;border-radius:14px 14px 0 0;background:transparent;color:var(--sub);min-height:40px;padding:6px 20px;font-size:15px}
.tabs>button[data-tab]:hover:not(:disabled){background:var(--card)}
.tabs>button[data-tab].on{background:var(--card);color:var(--ink);border-bottom-color:var(--acc);box-shadow:var(--shadow)}
html[data-theme=dark] button.file,html[data-theme=dark] button.play,html[data-theme=dark] button.sel{color:#0E1A2B!important}
.theme{margin-left:auto;display:inline-flex;margin-bottom:6px}
.theme button{min-height:30px;padding:0 12px;font-size:13px;border-radius:0}
.theme button:first-child{border-radius:12px 0 0 12px}.theme button:last-child{border-radius:0 12px 12px 0}
.tabpane{display:flex;flex-direction:column;gap:12px;flex:1;min-height:0}
button.dstart{background:var(--dstart);border-color:var(--dstart);color:#fff;font-size:17px;border-radius:14px;min-height:48px}
button.dstart:hover:not(:disabled){background:var(--dstart);filter:brightness(.92)}
button.dend{background:var(--dend);border-color:var(--dend);color:#fff;font-size:17px;border-radius:14px;min-height:48px}
button.dend:hover:not(:disabled){background:var(--dend);filter:brightness(.92)}
button.prev{background:var(--teal);border-color:var(--teal);color:#fff}
.seek .seg.del{background:var(--dstart)}
.seek .seg.del.act{background:repeating-linear-gradient(45deg,var(--dend) 0 4px,#FFB4B8 4px 8px)}
.dl,.dr{display:grid;grid-template-columns:34px 1fr 1fr 70px 34px 34px;gap:6px;align-items:center}
.dl{color:var(--sub);font-size:13px;font-weight:700;padding:0 8px}.dl span{text-align:center}
.dr{border:2px solid transparent;border-radius:12px;padding:5px 8px;margin-bottom:4px}
.dr.act{background:var(--rowdel);border-color:var(--dstart)}
.dr input{width:100%;text-align:center;padding:2px 4px}
.dr .n{text-align:center;font-weight:700}.dr .len{text-align:center;font-weight:700}
.note{background:var(--note);border:1px solid var(--noteline);border-radius:12px;padding:6px 10px;font-size:13px;color:var(--noteink)}
.clip{display:grid;grid-template-columns:22px 84px 1fr auto;gap:10px;align-items:center;border:2px solid transparent;border-radius:12px;padding:6px 8px;margin-bottom:4px;background:var(--clipbg);cursor:pointer}
.clip.sel{border-color:var(--acc);background:var(--clipsel)}
.clip.dragover{border-color:var(--acc);background:var(--rowsel)}
.clip .grip{cursor:grab;color:var(--sub);font-size:20px;text-align:center;user-select:none}
.clip img{width:84px;height:48px;object-fit:cover;border-radius:6px;background:var(--video);display:block}
.clip .nm{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.clip .meta{font-size:12px;color:var(--sub)}
.badge{display:inline-block;border-radius:10px;padding:0 8px;font-size:12px;font-weight:700;margin:2px 4px 0 0}
.badge.hdr{background:#FDE68A;color:#78350F}.badge.aud{background:#D1FAE5;color:#065F46}.badge.warn{background:#FFE4D5;color:#9A3412}
.clip .ops{display:flex;gap:4px}
.clip .ops button{width:30px;min-height:30px;padding:0;border-radius:8px}
.infobox{background:var(--field);border:2px solid var(--fline);border-radius:12px;padding:8px 12px;font-size:14px;display:flex;flex-direction:column;gap:3px}
.seg3{display:inline-flex}.seg3 button{border-radius:0}.seg3 button:first-child{border-radius:12px 0 0 12px}.seg3 button:last-child{border-radius:0 12px 12px 0}
.dropz{border:2px dashed var(--fline);border-radius:12px;padding:12px;color:var(--sub);font-size:13px;text-align:center}

/* ===== 영역별 색 · 조절 버튼 색 단계 ===== */
:root{--c-blue:#2F80ED;--t-blue:#E1EEFF;--c-vio:#8B5CF6;--t-vio:#F1EAFF;--c-teal:#0FA5A0;--t-teal:#DDF6F4;--c-sky:#0EA5E9;--t-sky:#E0F4FD;
--c-red:#E5484D;--t-red:#FFE8E8;--c-go:#7C5CFF;--t-go:#EEE9FF;--c-org:#FF7A45;--c-amb:#F59E0B;--t-amb:#FFF4D6;--selring:#14263D;
--st1:#FFF0C2;--st2:#FFDB7A;--st3:#FFC233;--st4:#F08A00;--stink:#5A3B00;
--zm1:#FFE9A8;--zm2:#FFD25E;--zm3:#FFB020;--zm4:#F08A00;
--sk1:#6CC0F2;--sk2:#2A8BD6;--sk3:#0B5FA8;
--sp1:#C9F2E6;--sp2:#7FDDC4;--sp3:#2FC2A0;--sp4:#0F8F78;--spink:#0B4F42}
html[data-theme=dark]{--c-blue:#5BA8FF;--t-blue:#1E3A62;--c-vio:#A78BFA;--t-vio:#2E2552;--c-teal:#2DD4BF;--t-teal:#15403F;--c-sky:#38BDF8;--t-sky:#123A52;
--c-red:#FF6B70;--t-red:#4A2328;--c-go:#8E78FF;--t-go:#2C2856;--c-org:#FF8A57;--c-amb:#FFC24D;--t-amb:#3A3020;--selring:#FFFFFF;
--st1:#5E4A1C;--st2:#80621E;--st3:#A67C14;--stink:#FFFFFF;
--zm1:#6B5420;--zm2:#8A6420;--zm3:#B07A10;--zm4:#D88A00;
--sk1:#5FB4EC;--sk2:#2F8ED6;--sk3:#1F6FB8;
--sp1:#1E5C50;--sp2:#1F7A68;--sp3:#24A088;--sp4:#2FC2A0;--spink:#FFFFFF}
.a-blue{--ac:var(--c-blue);--at:var(--t-blue)}.a-vio{--ac:var(--c-vio);--at:var(--t-vio)}.a-teal{--ac:var(--c-teal);--at:var(--t-teal)}
.a-sky{--ac:var(--c-sky);--at:var(--t-sky)}.a-red{--ac:var(--c-red);--at:var(--t-red)}.a-go{--ac:var(--c-go);--at:var(--t-go)}
.card[class*=" a-"]{border-top:4px solid var(--ac)}
.h .nb{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:8px;background:var(--ac,var(--c-sky));color:#fff;font-style:normal;font-size:13px;margin-right:7px;vertical-align:middle}
.tabs .tn{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;color:#fff;font-style:normal;font-size:12px;margin-right:6px}
.card[class*=" a-"] button.move,.card[class*=" a-"] button.add{background:var(--at);color:var(--ac);border-color:var(--ac)}
.card[class*=" a-"] button.move:hover:not(:disabled),.card[class*=" a-"] button.add:hover:not(:disabled){filter:brightness(.95)}
.card.a-teal .item{border-left:6px solid var(--c-teal)}
.card.a-red .dr{border-left:6px solid var(--c-red)}
button.mplay{background:var(--t-sky);color:var(--c-sky);border-color:var(--c-sky)}
button.mdel{background:var(--t-red)}
/* 비활성: 회색 대신 원래 색을 흐리게 */
button:disabled{opacity:.45;filter:saturate(.75);cursor:not-allowed}
/* 구간 범위(노랑 영역) */
.cropbar{background:var(--t-amb);border-color:var(--c-amb)}
#ratioBtns button,html body [data-zoom]{border:2px solid transparent!important;color:var(--stink)!important;font-weight:800}
#ratioBtns .st1{background:var(--st1)!important}#ratioBtns .st2{background:var(--st2)!important}#ratioBtns .st3{background:var(--st3)!important}
html body [data-zoom].st1{background:var(--zm1)!important}html body [data-zoom].st2{background:var(--zm2)!important}html body [data-zoom].st3{background:var(--zm3)!important;color:#fff!important}html body [data-zoom].st4{background:var(--zm4)!important;color:#fff!important}
#ratioBtns button.sel,[data-zoom].sel,button.spd.sel{outline:3px solid var(--selring);outline-offset:1px;z-index:1;position:relative}
#ratioBtns button.sel::before,[data-zoom].sel::before,button.spd.sel::before{content:"✓ "}
.seg2 button+button{margin-left:3px}
/* 재생 시간 조절: 가운데(1초) 밝게 → 5초 진하게 */
button.sk1,button.sk2,button.sk3{color:#fff!important;border-color:transparent!important;font-weight:800}
button.sk1{background:var(--sk1)!important}button.sk2{background:var(--sk2)!important}button.sk3{background:var(--sk3)!important}
html body button.play{background:var(--c-org)!important;border-color:var(--c-org)!important;color:#fff!important}
button.stop{background:var(--card)!important;border-color:var(--c-org)!important;color:var(--c-org)!important}
/* 배속 버튼 */
.spdbox{display:inline-flex;gap:3px;white-space:nowrap}
html body button.spd{min-height:32px;padding:0 10px;font-size:13px;border:2px solid transparent;font-weight:800;color:var(--spink)}
html body button.spd.sp1{background:var(--sp1)!important;color:var(--spink)!important}html body button.spd.sp2{background:var(--sp2)!important;color:var(--spink)!important}html body button.spd.sp3{background:var(--sp3)!important;color:#fff!important}html body button.spd.sp4{background:var(--sp4)!important;color:#fff!important}
</style>
</head>
<body>
<div id="dropAll">여기에 놓으면 영상을 불러옵니다</div>

<div class="tabs" id="tabs">
  <button class="on" data-tab="1"><i class="tn" style="background:var(--c-org)">1</i>득점 하이라이트</button>
  <button data-tab="2"><i class="tn" style="background:var(--c-red)">2</i>구간 삭제 (컷 편집)</button>
  <button data-tab="3"><i class="tn" style="background:var(--c-teal)">3</i>영상 합치기</button>
  <span class="theme" id="themeBox"><button data-th="light">☀ 라이트</button><button data-th="dark">☾ 다크</button><button data-th="auto">자동</button></span>
</div>

<div class="tabpane" id="tab1">

<div class="top">
  <div class="card a-blue">
    <span class="h"><i class="nb">1</i>영상</span>
    <button class="file" id="pickBtn">영상 파일 선택</button>
    <button class="move" id="logSave">로그 저장</button><button class="move" id="logLoad">로그 불러오기</button><button class="move" id="logDir" title="구글 드라이브·OneDrive 같은 동기화 폴더를 고르면 로그가 자동으로 클라우드에 보관됩니다.">로그 폴더</button>
    <div class="sub" id="info" style="flex:1">선택된 영상이 없습니다.</div>
  </div>
  <div class="card a-vio">
    <span class="h"><i class="nb">2</i>메인화면 자막</span>
    <label class="chk"><input type="checkbox" id="titleOn">사용</label>
    <input type="text" id="titleText" style="flex:1" placeholder="예: [팀명] 시즌 하이라이트" disabled>
    <span class="sub">표시(초)</span>
    <input type="text" id="titleSecs" value="3" style="width:56px;text-align:center" disabled>
  </div>
</div>

<div class="main">
  <div class="card">
    <div class="pill" id="pill">구간 지정 대기 · 득점 장면이 시작되면 [득점 시작]을 누르세요</div>
    <div class="vbox" id="vbox">
      <video id="vid" playsinline></video>
      <div class="ph" id="ph">영상 파일을 선택하거나
이곳에 끌어다 놓으세요</div>
      <div id="cropLayer"><div id="crect"><i class="hd tl"></i><i class="hd tr"></i><i class="hd bl"></i><i class="hd br"></i><span class="tag" id="ctag"></span></div></div>
    </div>
    <div class="cropbar" id="cropbar">
      <label class="chk"><input type="checkbox" id="cropOn" disabled><span id="cropLabel">구간 범위 사용</span></label>
      <span class="sub">비율</span>
      <span class="seg2" id="ratioBtns"><button class="move st1" data-ratio="16:9">16:9</button><button class="move st2" data-ratio="4:3">4:3</button><button class="move st3" data-ratio="1:1">1:1</button></span>
      <span class="sub">확대</span>
      <button class="move st1" data-zoom="1">1x</button><button class="move st2" data-zoom="1.5">1.5x</button><button class="move st3" data-zoom="2">2x</button><button class="move st4" data-zoom="3">3x</button>
      <input type="range" id="zoomRange" min="1" max="4" step="0.05" value="1.5" style="width:130px;accent-color:var(--navy)">
      <b id="zoomVal">1.5x</b>
      <span class="spacer"></span>
      <button class="danger" id="cropReset" style="border-radius:8px;font-size:13px;min-height:30px">이 구간 초기화</button>
    </div>
    <div class="sub" id="cropHelp">구간 목록에서 구간을 선택하면(주황색 표시) 그 구간의 범위를 설정합니다.</div>
    <div class="seek" id="seek"><div class="head" id="head"></div></div>
    <div class="row sub"><span id="clock">00:00.0 / 00:00.0</span><span class="spacer"></span></div>
    <div class="row">
      <button class="move sk3" data-seek="-5">-5초</button>
      <button class="move sk2" data-seek="-2">-2초</button>
      <button class="move sk1" data-seek="-1">-1초</button>
      <button class="play" id="playBtn">▶ 재생</button>
      <button class="stop" id="stopBtn">■ 정지</button>
      <button class="move sk1" data-seek="1">+1초</button>
      <button class="move sk2" data-seek="2">+2초</button>
      <button class="move sk3" data-seek="5">+5초</button>
      <select id="rate" hidden><option>0.5x</option><option selected>1x</option><option>1.5x</option><option>2x</option></select><span class="spdbox"><span class="sub" style="align-self:center;margin:0 4px 0 6px">배속</span><button class="spd sp1" data-rate-for="rate" data-v="0.5x">0.5x</button><button class="spd sp2 sel" data-rate-for="rate" data-v="1x">1x</button><button class="spd sp3" data-rate-for="rate" data-v="1.5x">1.5x</button><button class="spd sp4" data-rate-for="rate" data-v="2x">2x</button></span>
    </div>
    <div class="row">
      <button class="start" id="startBtn" style="flex:2">득점 시작 (S)</button>
      <button class="end" id="endBtn" style="flex:2">득점 종료 (E)</button>
      <button class="danger" id="cancelMark" style="flex:1">지정 취소</button>
    </div>
    <div class="sub">단축키: S 시작 · E 종료 · 스페이스 재생/정지 · ←/→ 5초 이동</div>
    <div class="msg" id="msg"></div>
  </div>

  <div class="card a-teal">
    <span class="h"><i class="nb">3</i>득점 구간 목록</span>
        <div class="lh"><span>번호</span><span style="text-align:left">자막 내용</span><span>자막 위치</span><span>재생</span><span>삭제</span></div>
    <div class="list" id="list"></div>
    <div class="row" style="flex-wrap:nowrap"><button class="add" id="addBtn" style="flex:1">＋ 구간 직접 추가</button><select id="bulkPos" title="고르면 모든 득점 구간의 자막 위치가 한 번에 바뀝니다." style="min-height:34px"><option>자막 위치 일괄 변경</option></select><button class="danger" id="resetAll" style="border-radius:8px;min-height:34px;white-space:nowrap">전체 초기화</button></div>
    <div style="font-weight:700;font-size:14px" id="summary"></div>
  </div>
</div>

<div class="card bot a-go">
  <span class="h"><i class="nb">4</i>편집 및 저장</span>
  <div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:4px">
    <div class="prog"><i id="bar"></i></div>
    <div class="st" id="status">준비 중...</div>
  </div>
  <div class="h" id="outLabel" style="font-size:14px;white-space:nowrap" title="지정한 구간들 중 가장 많이 쓴 비율로 자동으로 정해집니다.">저장 영상 크기(자동): 16:9</div>
  <button id="ffBtn" style="display:none">FFmpeg 위치 지정</button>
  <button class="danger" id="cancelJob" style="min-height:44px" disabled>취소</button>
  <button class="go" id="goBtn">편집 시작 (MP4로 저장)</button>
  <button id="quitBtn" title="프로그램을 완전히 끝냅니다">프로그램 종료</button>
</div>

</div>

<div class="tabpane" id="tab2" hidden>
  <div class="top">
    <div class="card a-blue">
      <span class="h"><i class="nb">1</i>영상</span>
      <button class="file" id="cPick">영상 파일 선택</button>
      <div class="sub" id="cInfo" style="flex:1">선택된 영상이 없습니다.</div>
    </div>
    <div class="card a-vio" style="flex-direction:column;align-items:flex-start;gap:4px">
      <label class="chk"><input type="checkbox" id="cFast">화질 손실 없이 빠르게 (재인코딩 안 함)</label>
      <div class="sub">체크하면 삭제 경계가 키프레임에 맞춰져 최대 약 2초 오차가 생길 수 있습니다. 체크하지 않으면 정확한 위치에서 자릅니다(다시 인코딩).</div>
    </div>
  </div>
  <div class="main">
    <div class="card">
      <div class="pill" id="cPill">지울 구간 지정 대기 · 지울 장면이 시작되면 [삭제 시작]을 누르세요</div>
      <div class="vbox"><video id="cVid" playsinline></video><div class="ph" id="cPh">영상 파일을 선택하거나
이곳에 끌어다 놓으세요</div></div>
      <div class="seek" id="cSeek"><div class="head" id="cHead"></div></div>
      <div class="row sub"><span id="cClock">00:00.0 / 00:00.0</span></div>
      <div class="row">
        <button class="move sk3" data-cseek="-5">-5초</button><button class="move sk2" data-cseek="-2">-2초</button><button class="move sk1" data-cseek="-1">-1초</button>
        <button class="play" id="cPlay">▶ 재생</button><button class="stop" id="cStop">■ 정지</button>
        <button class="move sk1" data-cseek="1">+1초</button><button class="move sk2" data-cseek="2">+2초</button><button class="move sk3" data-cseek="5">+5초</button>
        <select id="cRate" hidden><option>0.5x</option><option selected>1x</option><option>1.5x</option><option>2x</option></select><span class="spdbox"><span class="sub" style="align-self:center;margin:0 4px 0 6px">배속</span><button class="spd sp1" data-rate-for="cRate" data-v="0.5x">0.5x</button><button class="spd sp2 sel" data-rate-for="cRate" data-v="1x">1x</button><button class="spd sp3" data-rate-for="cRate" data-v="1.5x">1.5x</button><button class="spd sp4" data-rate-for="cRate" data-v="2x">2x</button></span>
      </div>
      <div class="row">
        <button class="dstart" id="cStart" style="flex:2">삭제 시작 (S)</button>
        <button class="dend" id="cEnd" style="flex:2">삭제 종료 (E)</button>
        <button class="danger" id="cCancelMark" style="flex:1">지정 취소</button>
      </div>
      <div class="row"><button class="prev" id="cPreview" style="flex:1">▶ 삭제 후 결과 미리보기</button></div>
      <div class="sub">단축키: S 시작 · E 종료 · 스페이스 재생/정지 · ←/→ 5초 이동</div>
      <div class="msg" id="cMsg"></div>
    </div>
    <div class="card a-red">
      <span class="h"><i class="nb">3</i>지울 구간 목록</span>
      <div class="dl"><span>번호</span><span>시작</span><span>종료</span><span>길이</span><span>확인</span><span>삭제</span></div>
      <div class="list" id="cList"></div>
      <div class="row" style="flex-wrap:nowrap"><button class="add" id="cAdd" style="flex:1">＋ 구간 직접 추가</button><button class="danger" id="cReset" style="border-radius:8px;min-height:34px;white-space:nowrap">전체 초기화</button></div>
      <div style="font-weight:700;font-size:14px" id="cSummary"></div>
    </div>
  </div>
  <div class="card bot a-go">
    <span class="h"><i class="nb">4</i>편집 및 저장</span>
    <div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:4px"><div class="prog"><i id="cBar"></i></div><div class="st" id="cStatus">대기 중</div></div>
    <button class="danger" id="cCancelJob" style="min-height:44px" disabled>취소</button>
    <button class="go" id="cGo">편집 시작 (MP4로 저장)</button>
  </div>
</div>

<div class="tabpane" id="tab3" hidden>
  <div class="top">
    <div class="card a-blue">
      <span class="h"><i class="nb">1</i>영상 추가</span>
      <button class="file" id="mPick">영상 파일 추가 (여러 개 선택 가능)</button>
      <div class="sub" style="flex:1">여기에 끌어다 놓아도 추가됩니다.</div>
    </div>
    <div class="card a-vio">
      <span class="h"><i class="nb">✦</i>합치기 방식</span>
      <span class="seg3"><button class="move sel" id="mTr0">바로 이어붙이기</button><button class="move" id="mTr1">부드럽게 전환(0.5초)</button></span>
    </div>
  </div>
  <div class="main">
    <div class="card a-teal">
      <span class="h"><i class="nb">2</i>합칠 영상 목록</span>
      <div class="list" id="mList"></div>
      <div class="dropz" id="mDrop">영상 파일을 여기에 끌어다 놓으면 목록 끝에 추가됩니다 · 줄 왼쪽 ≡ 를 끌어서 순서를 바꿉니다</div>
      <div class="row" style="flex-wrap:nowrap"><button class="add" id="mAdd" style="flex:1">＋ 영상 파일 추가</button><button class="danger" id="mReset" style="border-radius:8px;min-height:34px;white-space:nowrap">전체 초기화</button></div>
      <div style="font-weight:700;font-size:14px" id="mSummary"></div>
    </div>
    <div class="card a-sky">
      <span class="h"><i class="nb">▶</i>선택한 영상 미리보기</span>
      <div class="vbox"><video id="mVid" playsinline></video><div class="ph" id="mPh">목록에서 영상을 선택하면 여기에 나옵니다</div></div>
      <div class="row">
        <button class="move sk3" data-mseek="-5">-5초</button><button class="move sk2" data-mseek="-2">-2초</button><button class="move sk1" data-mseek="-1">-1초</button>
        <button class="play" id="mPlay">▶ 재생</button><button class="stop" id="mStop">■ 정지</button>
        <button class="move sk1" data-mseek="1">+1초</button><button class="move sk2" data-mseek="2">+2초</button><button class="move sk3" data-mseek="5">+5초</button>
      </div>
      <div class="infobox" id="mInfo"><div class="sub">영상을 추가하면 합친 영상의 크기·화질이 여기에 표시됩니다.</div></div>
      <div class="note" id="mNote" hidden></div>
    </div>
  </div>
  <div class="card bot a-go">
    <span class="h"><i class="nb">3</i>합치기 및 저장</span>
    <div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:4px"><div class="prog"><i id="mBar"></i></div><div class="st" id="mStatus">대기 중</div></div>
    <button class="danger" id="mCancelJob" style="min-height:44px" disabled>취소</button>
    <button class="go" id="mGo">합치기 시작 (MP4로 저장)</button>
  </div>
</div>

<dialog id="dlg"><pre id="dlgText"></pre><div class="row" id="dlgBtns"></div></dialog>

<script>
"use strict";
const TOKEN="__TOKEN__";
const $=id=>document.getElementById(id);
let ST={positions:[],defaultPosition:"우측 하단"};
let video=null, dur=0, rows=[], playUntil=null, canPlay=false, busy=false, selIdx=-1, outRatio="16:9";

// ---------- 서버 통신 ----------
async function api(path,body){
  const r=await fetch(path,{method:"POST",headers:{"X-Token":TOKEN,"Content-Type":"application/json"},body:JSON.stringify(body||{})});
  const d=await r.json().catch(()=>({}));
  if(!r.ok||d.error) throw new Error(d.error||"오류가 발생했습니다.");
  return d;
}
async function getState(){
  const r=await fetch("/api/state",{headers:{"X-Token":TOKEN}});
  return r.json();
}
function popup(text,buttons){
  return new Promise(res=>{
    $("dlgText").textContent=text; const box=$("dlgBtns"); box.innerHTML="";
    (buttons||[["확인",true]]).forEach(([t,v])=>{const b=document.createElement("button");b.textContent=t;b.onclick=()=>{$("dlg").close();res(v)};box.appendChild(b)});
    $("dlg").showModal();
  });
}

// ---------- 시간 도우미 (PC 앱과 같은 규칙) ----------
function fmt1(sec){
  if(sec==null||isNaN(sec)) return "";
  const t=Math.round(Math.max(0,sec)*10); let h=Math.floor(t/36000), m=Math.floor((t%36000)/600), s=(t%600)/10;
  const ss=(s<10?"0":"")+s.toFixed(1);
  return h? `${h}:${String(m).padStart(2,"0")}:${ss}` : `${String(m).padStart(2,"0")}:${ss}`;
}
function parseTime(txt){
  const t=String(txt).trim().replace(/：/g,":"); if(!t) throw 0;
  const p=t.split(":"); if(p.length>3) throw 0;
  let s=0; for(const x of p){ if(!/^\d+(\.\d+)?$/.test(x.trim())) throw 0; s=s*60+parseFloat(x);} return s;
}
function lenText(r){ return (r.start!=null&&r.end!=null&&r.end>r.start)? (r.end-r.start).toFixed(1)+"초":"-"; }

// ---------- 구간 목록 (Marks) ----------
const activeIdx=()=>rows.findIndex(r=>r.active);
function flash(t){ $("msg").textContent=t||""; }
function newRow(o){ return Object.assign({start:null,end:null,text:"",pos:ST.defaultPosition,active:false,cropOn:false,cropRatio:null,crop:null},o||{}); }
function setTime(i,key,val){
  const r=rows[i], other=r[key==="start"?"end":"start"];
  if(val!=null&&other!=null){ const [s,e]=key==="start"?[val,other]:[other,val]; if(e<=s) throw new Error("종료 시간은 시작 시간보다 늦어야 합니다."); }
  r[key]=val;
}
function nudge(i,key,d){
  const r=rows[i]; if(r[key]==null){flash("먼저 시간을 입력해 주세요.");return;}
  let n=Math.max(0,r[key]+d); if(dur&&n>dur) n=dur;
  try{ setTime(i,key,n); flash(""); }catch(e){ flash(e.message); }
  syncRow(i);
}
function curTime(){ return video? video.currentTime:0; }
function markStart(){
  if(!canPlay){flash("먼저 재생 가능한 영상을 선택해 주세요.");return;}
  if(activeIdx()>=0){flash("이미 [득점 시작]을 눌렀습니다. 먼저 [득점 종료]를 눌러 주세요.");return;}
  rows.push(newRow({start:curTime(),active:true})); flash(""); selIdx=rows.length-1; rebuild(true);
}
function markEnd(){
  if(!canPlay){flash("먼저 재생 가능한 영상을 선택해 주세요.");return;}
  const i=activeIdx(); if(i<0){flash("먼저 [득점 시작]을 눌러 주세요.");return;}
  const r=rows[i], t=curTime();
  if(t<=r.start){flash("종료 위치가 시작 위치보다 앞입니다. 영상을 더 재생한 뒤 눌러 주세요.");return;}
  r.end=t; r.active=false; selIdx=i; flash(`${i+1}번 구간을 지정했습니다. 다음 득점 장면에서 [득점 시작]을 누르세요.`); rebuild(true);
}
function cancelMark(){ const i=activeIdx(); if(i<0) return; rows.splice(i,1); if(selIdx>=rows.length) selIdx=rows.length-1; flash("지정 중이던 구간을 취소했습니다."); rebuild(); }
function playRow(i){
  const r=rows[i];
  if(!canPlay){flash("영상을 재생할 수 없는 상태입니다.");return;}
  if(r.start==null||r.end==null||r.end<=r.start){flash("시작과 종료 시간이 올바른 구간만 재생할 수 있습니다.");return;}
  video.currentTime=r.start; playUntil=r.end; video.play();
}

// ---------- 목록 그리기 ----------
function rebuild(scrollEnd){
  const L=$("list"); L.innerHTML="";
  rows.forEach((r,i)=>{
    const it=document.createElement("div"); it.className="item"+(r.active?" act":"");
    const l1=document.createElement("div"); l1.className="l1";
    const num=document.createElement("button"); num.className="num"; num.textContent=i+1; num.title="이 구간 시작 위치로 이동";
    num.onclick=()=>{ if(canPlay&&r.start!=null){video.currentTime=r.start;} };
    const tx=document.createElement("input"); tx.type="text"; tx.placeholder="자막 내용 (선택)"; tx.value=r.text;
    tx.oninput=()=>{r.text=tx.value};
    const ps=document.createElement("select");
    ST.positions.forEach(p=>{const o=document.createElement("option");o.textContent=p;if(p===r.pos)o.selected=true;ps.appendChild(o)});
    ps.onchange=()=>{r.pos=ps.value};
    const pb=document.createElement("button"); pb.className="mini mplay"; pb.textContent="▶"; pb.title="이 구간 재생"; pb.onclick=()=>playRow(i);
    const db=document.createElement("button"); db.className="mini mdel"; db.textContent="✕"; db.title="이 구간 삭제"; db.onclick=()=>{rows.splice(i,1); if(selIdx>=rows.length) selIdx=rows.length-1; rebuild()};
    l1.append(num,tx,ps,pb,db);
    const l2=document.createElement("div"); l2.className="l2";
    const ed=(key)=>{const e=document.createElement("input");e.type="text";e.value=fmt1(r[key]);e.placeholder="00:00.0";
      e.onchange=()=>{const t=e.value.trim(); try{ setTime(i,key,t===""?null:parseTime(t)); flash(""); }catch(err){ flash(err&&err.message?err.message:"시간 형식을 확인해 주세요. 예) 05:42.5"); }
        e.value=fmt1(r[key]); refresh();}; r._el=r._el||{}; r._el[key]=e; return e};
    const lab=(t)=>{const s=document.createElement("span");s.className="sub lab";s.textContent=t;return s};
    l2.append(lab("시작"),ed("start"));
    l2.append(lab("종료"));
    if(r.active){const s=document.createElement("b");s.style.color="var(--orange)";s.textContent="지정 중…";l2.append(s);}
    else l2.append(ed("end"));
    const ln=document.createElement("span"); ln.className="len"; ln.textContent="길이 "+lenText(r); r._len=ln; l2.append(ln);
    it.append(l1,l2); L.append(it);
    r._item=it; if(i===selIdx) it.classList.add("sel");
    it.addEventListener("pointerdown",()=>{ if(selIdx!==i) select(i); });
  });
  if(activeIdx()<0){const g=document.createElement("div");g.className="ghost";g.textContent=`${rows.length+1}번 구간: [득점 시작]을 누르면 여기에 추가됩니다`;L.append(g);}
  if(selIdx>=rows.length) selIdx=rows.length-1;
  if(scrollEnd) L.scrollTop=L.scrollHeight;
  refresh(); cropUI();
}
function syncRow(i){
  const r=rows[i]; if(r._el){ if(r._el.start) r._el.start.value=fmt1(r.start); if(r._el.end) r._el.end.value=fmt1(r.end); }
  if(r._len) r._len.textContent="길이 "+lenText(r); refresh();
}
function completeRanges(){ return rows.filter(r=>!r.active&&r.start!=null&&r.end!=null&&r.end>r.start); }
function refresh(){
  updateOutRatio();
  const ai=activeIdx(), pill=$("pill");
  if(ai>=0){pill.className="pill on"; pill.textContent=`${ai+1}번 구간 지정 중 · 시작 ${fmt1(rows[ai].start)} · 끝나는 지점에서 [득점 종료]를 누르세요`;}
  else{pill.className="pill"; pill.textContent="구간 지정 대기 · 득점 장면이 시작되면 [득점 시작]을 누르세요";}
  $("startBtn").disabled=!(canPlay&&ai<0); $("endBtn").disabled=!(canPlay&&ai>=0); $("cancelMark").disabled=ai<0;
  const cr=completeRanges(), total=cr.reduce((a,r)=>a+(r.end-r.start),0);
  const ts=parseFloat($("titleSecs").value); const extra=($("titleOn").checked&&$("titleText").value.trim()&&ts>0)?ts:0;
  $("summary").textContent=`득점 구간 ${cr.length}개 완료 · 합계 ${total.toFixed(0)}초 + 메인화면 ${extra.toFixed(0)}초 = 전체 약 ${(total+extra).toFixed(0)}초`;
  drawSeek();
}

// ---------- 재생 막대 ----------
function drawSeek(){
  const s=$("seek"); [...s.querySelectorAll(".seg")].forEach(e=>e.remove());
  if(!dur) {$("head").style.left="0%";return;}
  rows.forEach(r=>{
    if(r.start==null) return; const e=r.active? curTime(): r.end; if(e==null||e<=r.start) return;
    const d=document.createElement("div"); d.className="seg"+(r.active?" act":"");
    d.style.left=(r.start/dur*100)+"%"; d.style.width=Math.max(0.3,(e-r.start)/dur*100)+"%"; s.insertBefore(d,$("head"));
  });
  $("head").style.left=(curTime()/dur*100)+"%";
}
function tick(){
  if(video){
    if(playUntil!=null&&video.currentTime>=playUntil){video.pause();playUntil=null;}
    $("clock").textContent=`${fmt1(curTime())} / ${fmt1(dur)}`;
    $("playBtn").textContent=video.paused?"▶ 재생":"❚❚ 일시정지";
    drawSeek();
  }
}
setInterval(tick,100);
function seekRel(d){ if(canPlay) video.currentTime=Math.min(dur,Math.max(0,video.currentTime+d)); }
function togglePlay(){ if(!canPlay) return; playUntil=null; video.paused?video.play():video.pause(); }
(function(){
  const s=$("seek"); let down=false;
  const at=e=>{ if(!canPlay) return; const b=s.getBoundingClientRect(); video.currentTime=Math.min(1,Math.max(0,(e.clientX-b.left)/b.width))*dur; };
  s.addEventListener("pointerdown",e=>{down=true;s.setPointerCapture(e.pointerId);at(e)});
  s.addEventListener("pointermove",e=>{if(down)at(e)});
  s.addEventListener("pointerup",()=>{down=false});
})();

// ---------- 영상 불러오기 ----------
function applyState(d){
  ST=Object.assign(ST,d);
  const ff=$("ffBtn"); ff.style.display=d.ffmpeg?"none":"";
  if(!d.ffmpeg) $("status").textContent="FFmpeg를 찾지 못했습니다. [FFmpeg 위치 지정]을 눌러 ffmpeg.exe를 선택해 주세요.";
  else if(!busy && !(d.job&&d.job.state==="running")) $("status").textContent="대기 중 · FFmpeg 확인됨: "+d.ffmpegPath;
}
function showVideo(v){
  rows=[]; selIdx=-1; flash(""); canPlay=false; dur=v.duration||0;
  let t=`${v.name} · ${v.width}x${v.height} · ${v.fps} fps · ${fmt1(v.duration).replace(/\.\d$/,"")} · ${v.codec}`;
  if(v.hdr) t+=" · HDR";
  $("info").innerHTML=""; const a=document.createElement("div"); a.textContent=t; $("info").append(a);
  if(v.hdr){const b=document.createElement("div"); b.textContent="(원본 색상 그대로 HEVC로 저장)"; $("info").append(b);}
  const el=$("vid"); video=el; el.pause();
  el.onloadedmetadata=()=>{canPlay=true; dur=el.duration||dur; $("ph").style.display="none"; refresh(); cropUI();};
  el.onerror=()=>{canPlay=false; $("ph").style.display="";
    $("ph").textContent="이 브라우저에서 영상을 재생하지 못했습니다.\n(HEVC 영상은 Windows의 HEVC 확장이 필요하며, 그래도 안 되면 시간을 직접 입력하는 방식으로 구간을 추가할 수 있습니다.)"; refresh();};
  el.src="/video?t="+TOKEN+"&r="+Date.now(); el.load();
  rebuild();
}
async function confirmReplace(msg){      // 새 영상을 고르면 지금까지 지정한 구간이 지워지므로 먼저 확인
  if(!completeRanges().length) return true;
  return popup(msg||"새 영상을 선택하면 지금까지 지정한 득점 구간이 모두 지워집니다.\n계속할까요?",[["계속",true],["취소",false]]);
}
async function pick(){
  if(busy) return;
  if(!(await confirmReplace())) return;
  busy=true; $("status").textContent="파일 선택 창을 여는 중... (다른 창 뒤에 숨어 있을 수 있습니다)";
  try{ const d=await api("/api/pick"); if(!d.cancelled){applyState(d); if(d.video) showVideo(d.video);} }
  catch(e){ await popup(e.message); } finally{ busy=false; applyState(await getState()); }
}
async function upload(file){
  if(!/\.(mp4|mov|m4v|mkv|avi)$/i.test(file.name)){flash("동영상 파일(mp4, mov 등)만 불러올 수 있습니다.");return;}
  if(busy) return;
  if(!(await confirmReplace())) return;
  busy=true; flash("");
  const x=new XMLHttpRequest(); x.open("POST","/api/upload?name="+encodeURIComponent(file.name));
  x.setRequestHeader("X-Token",TOKEN);
  x.upload.onprogress=e=>{ if(e.lengthComputable){ $("status").textContent=`영상 불러오는 중... ${Math.round(e.loaded/e.total*100)}%`; $("bar").style.width=(e.loaded/e.total*100)+"%"; } };
  x.onload=async()=>{ busy=false; $("bar").style.width="0";
    let d={}; try{d=JSON.parse(x.responseText)}catch(_){}
    if(x.status!==200||d.error){ await popup(d.error||"영상을 불러오지 못했습니다."); }
    else{ applyState(d); showVideo(d.video); }
    applyState(await getState()); };
  x.onerror=()=>{busy=false; popup("영상을 불러오지 못했습니다.");};
  x.send(file);
}
let dragDepth=0;
addEventListener("dragenter",e=>{e.preventDefault(); if(typeof dragId!=="undefined"&&dragId!=null) return; dragDepth++;$("dropAll").style.display="flex"});
addEventListener("dragleave",e=>{dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)$("dropAll").style.display="none"});
addEventListener("dragover",e=>e.preventDefault());
addEventListener("drop",e=>{e.preventDefault();dragDepth=0;$("dropAll").style.display="none";const fl=e.dataTransfer.files; if(fl&&fl.length) dropRoute(fl);});

// ---------- 메인화면 자막 사용 체크 ----------
function toggleTitle(){
  const on=$("titleOn").checked; $("titleText").disabled=!on; $("titleSecs").disabled=!on;
  if(on){$("titleSecs").value="3";$("titleText").focus();} refresh();
}

// ---------- 저장 ----------
async function save(){
  if(busy) return;
  const t=$("titleOn").checked? {text:$("titleText").value.trim(),secs:$("titleSecs").value}:null;
  const payload={rows:rows.map(r=>({start:r.start,end:r.end,text:r.text,pos:r.pos,active:r.active,crop:(r.cropOn&&r.crop)?r.crop:null})),title:t,outRatio:outRatio};
  busy=true; $("status").textContent="저장할 위치를 선택해 주세요... (다른 창 뒤에 숨어 있을 수 있습니다)";
  try{ const d=await api("/api/save",payload); if(d.cancelled){busy=false;applyState(await getState());return;} poll(); }
  catch(e){ busy=false; await popup(e.message); applyState(await getState()); }
}
async function poll(){
  const d=await getState(); const j=d.job; applyState(d);
  if(j.state==="running"){
    $("goBtn").disabled=true; $("cancelJob").disabled=false; $("bar").style.width=(100*j.done/Math.max(1,j.total))+"%"; $("status").textContent=j.msg;
    setTimeout(poll,700); return;
  }
  busy=false; $("goBtn").disabled=false; $("cancelJob").disabled=true;
  if(j.state==="done"){ $("bar").style.width="100%"; $("status").textContent="완료: "+j.out;
    const open=await popup("저장했습니다.\n"+j.out+"\n\n저장 폴더를 열까요?",[["폴더 열기",true],["닫기",false]]); if(open) api("/api/openfolder"); }
  else if(j.state==="error"){ $("status").textContent="오류가 발생했습니다."; $("bar").style.width="0"; await popup(j.error); }
  else if(j.state==="cancelled"){ $("status").textContent="취소했습니다."; $("bar").style.width="0"; }
}


// ---------- 화면 범위(크롭) ----------
const RAT={"1:1":[1,1],"4:3":[4,3],"16:9":[16,9]};
function srcDims(){ const v=ST.video; return v? [v.width,v.height]:[16,9]; }
function baseSize(ratio){            // 비율 ratio에서 영상 안에 들어가는 가장 큰 사각형 (0~1)
  const [W,H]=srcDims(), [a,b]=RAT[ratio], r=a/b;
  return r<=W/H? {w:r*H/W,h:1} : {w:1,h:W/(r*H)};
}
function zoomOf(row){ return baseSize(row.cropRatio).w/row.crop.w; }
function setCrop(row,ratio,zoom,cx,cy){
  const b=baseSize(ratio); zoom=Math.min(4,Math.max(1,zoom));
  const w=b.w/zoom, h=b.h/zoom;
  cx=(cx==null)?0.5:cx; cy=(cy==null)?0.5:cy;
  row.cropRatio=ratio;
  row.crop={w:w,h:h,x:Math.min(1-w,Math.max(0,cx-w/2)),y:Math.min(1-h,Math.max(0,cy-h/2))};
}
function curRow(){ return (selIdx>=0&&selIdx<rows.length)? rows[selIdx]:null; }
function select(i){
  selIdx=i; rows.forEach((r,k)=>{ if(r._item) r._item.classList.toggle("sel",k===i); }); cropUI();
}
function layoutCrop(){            // 영상이 실제로 보이는 영역에 사각형 판을 맞춤
  const box=$("vbox"), layer=$("cropLayer"), v=ST.video; if(!v||!canPlay){layer.style.display="none";return;}
  const bw=box.clientWidth, bh=box.clientHeight, va=v.width/v.height;
  let w=bw,h=bw/va; if(h>bh){h=bh;w=bh*va;}
  layer.style.width=w+"px"; layer.style.height=h+"px"; layer.style.left=((bw-w)/2)+"px"; layer.style.top=((bh-h)/2)+"px";
  drawCrop();
}
function drawCrop(){
  const r=curRow(), layer=$("cropLayer");
  if(!r||!r.cropOn||!r.crop||!canPlay){layer.style.display="none";return;}
  layer.style.display="block"; const c=r.crop, el=$("crect");
  el.style.left=(c.x*100)+"%"; el.style.top=(c.y*100)+"%"; el.style.width=(c.w*100)+"%"; el.style.height=(c.h*100)+"%";
  $("ctag").textContent=`${selIdx+1}번 구간 · ${r.cropRatio} · ${zoomOf(r).toFixed(1)}배`;
}
function cropUI(){
  setTimeout(updateOutRatio,0);
  const r=curRow(), on=!!(r&&r.cropOn), bar=$("cropbar");
  bar.classList.toggle("on",on);
  $("cropOn").disabled=!(r&&canPlay); $("cropOn").checked=on;
  $("cropLabel").textContent=r? `${selIdx+1}번 구간 범위 사용` : "구간 범위 사용";
  document.querySelectorAll("#ratioBtns button").forEach(b=>{ b.disabled=!on; b.classList.toggle("sel",on&&b.dataset.ratio===r.cropRatio); });
  document.querySelectorAll("[data-zoom]").forEach(b=>{ b.disabled=!on; b.classList.toggle("sel",on&&Math.abs(zoomOf(r)-parseFloat(b.dataset.zoom))<0.05); });
  $("zoomRange").disabled=!on; $("cropReset").disabled=!on;
  if(on){ const z=zoomOf(r); $("zoomRange").value=z; $("zoomVal").textContent=z.toFixed(1)+"x"; } else $("zoomVal").textContent="-";
  $("cropHelp").textContent= !r? "구간 목록에서 구간을 선택하면(주황색 표시) 그 구간의 범위를 설정합니다."
    : on? "영상 위 주황색 사각형을 끌어서 옮기고, 모서리를 끌어 크기를 바꿉니다. 저장 영상 크기와 비율이 다르면 검은 여백으로 맞춰집니다."
        : "체크하면 이 구간의 화면 일부만 확대해서 저장합니다. (체크하지 않으면 전체 화면)";
  layoutCrop();
}
function toggleCrop(){
  const r=curRow(); if(!r) return;
  r.cropOn=$("cropOn").checked;
  if(r.cropOn&&!r.crop){ // 처음 켤 때: 저장 영상 크기와 같은 비율, 1.5배, 가운데
    setCrop(r,outRatio,1.5,0.5,0.5);
  }
  cropUI();
}
function cropCenter(r){ return [r.crop.x+r.crop.w/2, r.crop.y+r.crop.h/2]; }
document.querySelectorAll("#ratioBtns button").forEach(b=>b.onclick=()=>{
  const r=curRow(); if(!r||!r.cropOn) return; const z=zoomOf(r), c=cropCenter(r); setCrop(r,b.dataset.ratio,z,c[0],c[1]); cropUI(); });
document.querySelectorAll("[data-zoom]").forEach(b=>b.onclick=()=>{
  const r=curRow(); if(!r||!r.cropOn) return; const c=cropCenter(r); setCrop(r,r.cropRatio,parseFloat(b.dataset.zoom),c[0],c[1]); cropUI(); });
$("zoomRange").oninput=()=>{ const r=curRow(); if(!r||!r.cropOn) return; const c=cropCenter(r); setCrop(r,r.cropRatio,parseFloat($("zoomRange").value),c[0],c[1]); drawCrop(); $("zoomVal").textContent=parseFloat($("zoomRange").value).toFixed(1)+"x"; };
$("cropReset").onclick=()=>{ const r=curRow(); if(!r) return; r.cropOn=false; r.crop=null; r.cropRatio=null; cropUI(); };
$("cropOn").onchange=toggleCrop;
(function(){   // 사각형 끌기 / 모서리로 크기 조절
  const el=$("crect"); let mode=null, st=null;
  const pt=e=>{ const b=$("cropLayer").getBoundingClientRect(); return [(e.clientX-b.left)/b.width,(e.clientY-b.top)/b.height]; };
  el.addEventListener("pointerdown",e=>{
    const r=curRow(); if(!r||!r.cropOn) return; e.preventDefault(); el.setPointerCapture(e.pointerId);
    const p=pt(e), c=r.crop, hd=e.target.classList&&e.target.classList.contains("hd")? e.target.className.replace("hd","").trim():null;
    if(hd){ mode="size"; const ax=(hd==="tl"||hd==="bl")? c.x+c.w:c.x, ay=(hd==="tl"||hd==="tr")? c.y+c.h:c.y; st={ax,ay,hd}; }
    else { mode="move"; st={dx:p[0]-c.x, dy:p[1]-c.y}; }
  });
  el.addEventListener("pointermove",e=>{
    const r=curRow(); if(!mode||!r) return; const p=pt(e), c=r.crop, [W,H]=srcDims(), [a,b]=RAT[r.cropRatio], k=(W/H)*(b/a);
    if(mode==="move"){ c.x=Math.min(1-c.w,Math.max(0,p[0]-st.dx)); c.y=Math.min(1-c.h,Math.max(0,p[1]-st.dy)); }
    else{
      const goLeft=(st.hd==="tl"||st.hd==="bl"), goUp=(st.hd==="tl"||st.hd==="tr");
      const availX=goLeft? st.ax : 1-st.ax, availY=goUp? st.ay : 1-st.ay;
      let w=Math.max(Math.abs(p[0]-st.ax), Math.abs(p[1]-st.ay)/k);
      w=Math.min(w, availX, availY/k); w=Math.max(w, baseSize(r.cropRatio).w/4);
      c.w=w; c.h=w*k; c.x=goLeft? st.ax-w:st.ax; c.y=goUp? st.ay-c.h:st.ay;
    }
    drawCrop(); const z=zoomOf(r); $("zoomRange").value=z; $("zoomVal").textContent=z.toFixed(1)+"x";
  });
  const end=()=>{mode=null;st=null}; el.addEventListener("pointerup",end); el.addEventListener("pointercancel",end);
})();
addEventListener("resize",layoutCrop);
// 저장 영상 크기: 완성된 구간 중 가장 많이 지정된 비율로 자동 결정 (범위 미사용 구간은 16:9, 동률이면 먼저 나온 구간)
function autoRatio(){
  const cnt={}, order=[];
  rows.forEach(r=>{
    if(r.active||r.start==null||r.end==null||!(r.end>r.start)) return;
    const n=(r.cropOn&&r.crop&&RAT[r.cropRatio])? r.cropRatio:"16:9";
    if(!(n in cnt)){cnt[n]=0;order.push(n);} cnt[n]++;
  });
  if(!order.length) return ["16:9",0,0];
  let best=order[0]; order.forEach(n=>{ if(cnt[n]>cnt[best]) best=n; });
  return [best,cnt[best],order.reduce((a,n)=>a+cnt[n],0)];
}
function updateOutRatio(){
  const [n,c,t]=autoRatio(); outRatio=n;
  let size="";
  if(ST.video){ const W=ST.video.width,H=ST.video.height,[a,b]=RAT[n],r=a/b; let oh=H, ow=H*r; const lg=Math.max(W,H); if(ow>lg){ow=lg;oh=lg/r;}
    const ev=v=>{v=Math.round(v);return Math.max(2,v-v%2)}; size=` (${ev(ow)}x${ev(oh)})`; }
  $("outLabel").textContent=`저장 영상 크기(자동): ${n}${size}`+(t?` · ${t}개 중 ${c}개`:"");
}

// ---------- 연결 ----------
$("pickBtn").onclick=pick;
$("ffBtn").onclick=async()=>{ try{const d=await api("/api/ffmpeg"); if(!d.cancelled) applyState(d);}catch(e){await popup(e.message)} };
$("titleOn").onchange=toggleTitle; $("titleText").oninput=refresh; $("titleSecs").oninput=refresh;
$("startBtn").onclick=markStart; $("endBtn").onclick=markEnd; $("cancelMark").onclick=cancelMark;
$("addBtn").onclick=()=>{rows.push(newRow()); rebuild(true)};
$("resetAll").onclick=async()=>{
  if(busy) return;
  const ans=await popup("지정한 모든 득점 구간(자막·범위 포함)과 메인화면 자막 설정을 지우고 처음 상태로 되돌립니다.\n\n불러온 영상도 함께 초기화할까요?",[["구간·자막만 초기화","keep"],["불러온 영상까지 초기화","all"],["취소",false]]);
  if(!ans) return;
  playUntil=null; if(canPlay) video.pause();
  if(ans==="all") await clearVideo();
  rows=[]; selIdx=-1;
  $("titleText").value=""; $("titleOn").checked=false; toggleTitle(); $("titleSecs").value="3";
  $("bar").style.width="0"; flash("전체 초기화했습니다."+(ans==="all"?" (영상 포함)":"")); rebuild();
};
async function clearVideo(){
  try{ await api("/api/unload"); }catch(_){}
  video.pause(); video.removeAttribute("src"); video.load(); canPlay=false; dur=0; ST.video=null;
  $("ph").style.display=""; $("ph").textContent="영상 파일을 선택하거나\n이곳에 끌어다 놓으세요";
  $("info").textContent="선택된 영상이 없습니다."; $("clock").textContent="00:00.0 / 00:00.0";
  cropUI(); drawSeek();
}
async function saveLog(){
  if(!ST.video){ await popup("먼저 영상 파일을 선택해 주세요."); return; }
  const payload={rows:rows.map(r=>({start:r.start,end:r.end,text:r.text,pos:r.pos,cropOn:r.cropOn,cropRatio:r.cropRatio,crop:r.crop})),
    title:{on:$("titleOn").checked,text:$("titleText").value,secs:$("titleSecs").value}};
  try{ const d=await api("/api/log/save",payload); if(d.cancelled) return; flash("편집 로그를 저장했습니다: "+d.path); }
  catch(e){ await popup(e.message); }
}
async function loadLog(){
  if(busy) return;
  if(!(await confirmReplace("지금 지정한 득점 구간이 로그 내용으로 바뀝니다.\n계속할까요?"))) return;
  busy=true;
  try{
    const d=await api("/api/log/load"); if(d.cancelled) return;
    const log=d.log;
    if(d.videoFound){ applyState(d); showVideo(d.video); }
    else{
      await popup("원본 영상을 찾을 수 없습니다.\n("+(log.video.name||"")+")\n영상 파일을 직접 선택해 주세요.");
      const v=await api("/api/pick"); if(v.cancelled) return; applyState(v); showVideo(v.video);
    }
    rows=log.rows.map(r=>newRow(r)); selIdx=-1;
    $("titleOn").checked=!!log.title.on; toggleTitle(); $("titleText").value=log.title.text; $("titleSecs").value=log.title.secs;
    rebuild(); cropUI();
    let note=`편집 로그를 불러왔습니다. (구간 ${rows.length}개)`;
    if(log.video.duration&&ST.video&&Math.abs(log.video.duration-ST.video.duration)>1) note+=" 주의: 로그에 기록된 영상 길이와 다릅니다. 같은 영상인지 확인해 주세요.";
    flash(note);
  }catch(e){ await popup(e.message); }
  finally{ busy=false; applyState(await getState()); }
}
$("logDir").onclick=async()=>{ try{ const d=await api("/api/log/folder"); if(!d.cancelled) flash("로그 폴더를 지정했습니다: "+d.dir); }catch(e){ await popup(e.message); } };
$("logSave").onclick=saveLog; $("logLoad").onclick=loadLog;
function fillBulk(){
  const sel=$("bulkPos"); if(sel.options.length>1||!ST.positions.length) return;
  ST.positions.forEach(t=>{const o=document.createElement("option"); o.textContent=t; sel.appendChild(o);});
}
$("bulkPos").onchange=()=>{
  const sel=$("bulkPos"), v=sel.value; if(sel.selectedIndex<=0) return; sel.selectedIndex=0;
  if(!rows.length){ flash("자막 위치를 바꿀 득점 구간이 없습니다."); return; }
  rows.forEach(r=>{r.pos=v}); flash(`모든 구간(${rows.length}개)의 자막 위치를 '${v}'(으)로 바꿨습니다.`); rebuild();
};
$("playBtn").onclick=togglePlay; $("stopBtn").onclick=()=>{ if(canPlay){playUntil=null;video.pause();} };
$("rate").onchange=()=>{ if(video) video.playbackRate=parseFloat($("rate").value); };
document.querySelectorAll("[data-seek]").forEach(b=>b.onclick=()=>seekRel(parseFloat(b.dataset.seek)));
$("goBtn").onclick=save; $("cancelJob").onclick=()=>api("/api/cancel");
$("quitBtn").onclick=async()=>{ if(await popup("프로그램을 완전히 종료할까요?",[["종료",true],["계속 사용",false]])){ try{await api("/api/quit")}catch(_){} document.body.innerHTML="<p style='padding:30px;font-size:18px'>프로그램을 종료했습니다. 이 탭은 닫아도 됩니다.</p>"; } };
addEventListener("keydown",e=>{
  if(curTab!==1) return;
  const tag=(e.target.tagName||"").toLowerCase(); if(tag==="input"||tag==="select"||tag==="textarea"||$("dlg").open) return;
  const k=e.key;
  if(k==="s"||k==="S"){e.preventDefault();markStart();}
  else if(k==="e"||k==="E"){e.preventDefault();markEnd();}
  else if(k===" "){e.preventDefault();togglePlay();}
  else if(k==="ArrowLeft"){e.preventDefault();seekRel(-5);}
  else if(k==="ArrowRight"){e.preventDefault();seekRel(5);}
});
(async function init(){
  const d=await getState(); applyState(d); fillBulk(); if(d.video) showVideo(d.video); else rebuild();
  setInterval(async()=>{ try{ const s=await getState(); if(!busy) applyState(s);}catch(_){} },3000);
  if(!d.ffmpeg) await popup("FFmpeg를 찾지 못했습니다.\n\n화면 아래의 [FFmpeg 위치 지정]을 눌러 ffmpeg.exe 파일을 직접 선택해 주세요. (한 번만 지정하면 기억합니다)\n\n명령 프롬프트(cmd)에서 where ffmpeg 를 입력하면 설치 위치를 알 수 있습니다.");
  else if(!d.font) $("status").textContent+=" · 자막용 한글 글꼴(Noto Sans KR)을 찾지 못했습니다.";
})();
</script>
<script>
"use strict";
// ======================================================================
// 탭 전환
// ======================================================================
let curTab=1;
function showTab(n){
  curTab=n;
  document.querySelectorAll("#tabs button[data-tab]").forEach(b=>b.classList.toggle("on",b.dataset.tab==String(n)));
  [1,2,3].forEach(i=>$("tab"+i).hidden=(i!==n));
  if(n!==1&&video&&canPlay) video.pause();
  if(n!==2&&cCan) cV.pause();
  if(n!==3) mV.pause();
  if(n===2) cDraw();
}
document.querySelectorAll("#tabs button[data-tab]").forEach(b=>b.onclick=()=>showTab(parseInt(b.dataset.tab)));

// 탭 ②, ③ 가 공유하는 작은 도우미
function secText(sec){ sec=Math.round(sec); const h=Math.floor(sec/3600),m=Math.floor(sec%3600/60),s=sec%60;
  return h? `${h}시간 ${m}분 ${s}초` : (m? `${m}분 ${s}초`:`${s}초`); }
function mmss(sec){ sec=Math.round(sec); const h=Math.floor(sec/3600),m=Math.floor(sec%3600/60),s=sec%60;
  return h? `${h}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}` : `${m}:${String(s).padStart(2,"0")}`; }
function upTo(url,file,onProg){
  return new Promise(res=>{
    const x=new XMLHttpRequest(); x.open("POST",url+"?name="+encodeURIComponent(file.name));
    x.setRequestHeader("X-Token",TOKEN);
    x.upload.onprogress=e=>{ if(e.lengthComputable&&onProg) onProg(e.loaded/e.total); };
    x.onload=()=>{ let d={}; try{d=JSON.parse(x.responseText)}catch(_){} res(x.status===200&&!d.error? d:{error:d.error||"영상을 불러오지 못했습니다."}); };
    x.onerror=()=>res({error:"영상을 불러오지 못했습니다."});
    x.send(file);
  });
}
const VEXT=/\.(mp4|mov|m4v|mkv|avi)$/i;
// 이 탭에서 시작한 작업의 진행 상태를 보여줌
async function trackJob(kind,ui){
  const d=await getState(); const j=d.job; applyState(d);
  if(j.kind!==kind&&j.state==="running"){ setTimeout(()=>trackJob(kind,ui),1000); return; }
  if(j.state==="running"){
    ui.go.disabled=true; ui.cancel.disabled=false; ui.bar.style.width=(100*j.done/Math.max(1,j.total))+"%"; ui.st.textContent=j.msg;
    setTimeout(()=>trackJob(kind,ui),700); return;
  }
  ui.setBusy(false); ui.go.disabled=false; ui.cancel.disabled=true;
  if(j.kind!==kind) return;
  if(j.state==="done"){ ui.bar.style.width="100%"; ui.st.textContent="완료: "+j.out;
    const open=await popup("저장했습니다.\n"+j.out+"\n\n저장 폴더를 열까요?",[["폴더 열기",true],["닫기",false]]); if(open) api("/api/openfolder"); }
  else if(j.state==="error"){ ui.st.textContent="오류가 발생했습니다."; ui.bar.style.width="0"; await popup(j.error); }
  else if(j.state==="cancelled"){ ui.st.textContent="취소했습니다."; ui.bar.style.width="0"; }
}

// ======================================================================
// 탭 ② 구간 삭제 (컷 편집)
// ======================================================================
const cV=$("cVid");
let cDur=0, cCan=false, cBusy=false, crows=[], cPlayUntil=null, cSkip=false, cInfoV=null;
const cAct=()=>crows.findIndex(r=>r.active);
const cDone=()=>crows.filter(r=>!r.active&&r.start!=null&&r.end!=null&&r.end>r.start);
function cFlash(t){ $("cMsg").textContent=t||""; }
function cMerged(){            // 겹치는 구간을 합친 지울 구간 (서버와 같은 규칙)
  const a=cDone().map(r=>[r.start,Math.min(r.end,cDur||r.end)]).sort((x,y)=>x[0]-y[0]); const out=[];
  for(const [s,e] of a){ if(e-s<=0.001) continue; if(out.length&&s<=out[out.length-1][1]+0.001) out[out.length-1][1]=Math.max(out[out.length-1][1],e); else out.push([s,e]); }
  return out;
}
function cShowVideo(v){
  crows=[]; cFlash(""); cCan=false; cDur=v.duration||0; cInfoV=v;
  let t=`${v.name} · ${v.width}x${v.height} · ${v.fps} fps · ${mmss(v.duration)} · ${v.codec}`+(v.hdr?" · HDR":"");
  $("cInfo").textContent=t; cV.pause();
  cV.onloadedmetadata=()=>{cCan=true; cDur=cV.duration||cDur; $("cPh").style.display="none"; cRefresh();};
  cV.onerror=()=>{cCan=false; $("cPh").style.display=""; $("cPh").textContent="이 브라우저에서 영상을 재생하지 못했습니다.\n(시간을 직접 입력해서 구간을 추가할 수 있습니다.)"; cRefresh();};
  cV.src="/video?slot=cut&t="+TOKEN+"&r="+Date.now(); cV.load();
  cRebuild();
}
async function cConfirmReplace(){
  if(!cDone().length) return true;
  return popup("새 영상을 선택하면 지금까지 지정한 지울 구간이 모두 지워집니다.\n계속할까요?",[["계속",true],["취소",false]]);
}
async function cPick(){
  if(cBusy) return; if(!(await cConfirmReplace())) return;
  cBusy=true; $("cStatus").textContent="파일 선택 창을 여는 중... (다른 창 뒤에 숨어 있을 수 있습니다)";
  try{ const d=await api("/api/cut/pick"); if(!d.cancelled){applyState(d); if(d.cut) cShowVideo(d.cut);} }
  catch(e){ await popup(e.message); } finally{ cBusy=false; $("cStatus").textContent="대기 중"; }
}
async function cUpload(file){
  if(!VEXT.test(file.name)){cFlash("동영상 파일(mp4, mov 등)만 불러올 수 있습니다.");return;}
  if(cBusy) return; if(!(await cConfirmReplace())) return;
  cBusy=true;
  const d=await upTo("/api/cut/upload",file,p=>{$("cStatus").textContent=`영상 불러오는 중... ${Math.round(p*100)}%`;$("cBar").style.width=(p*100)+"%";});
  cBusy=false; $("cBar").style.width="0"; $("cStatus").textContent="대기 중";
  if(d.error) await popup(d.error); else { applyState(d); cShowVideo(d.cut); }
}
function cSetTime(i,key,val){
  const r=crows[i], other=r[key==="start"?"end":"start"];
  if(val!=null&&other!=null){ const [s,e]=key==="start"?[val,other]:[other,val]; if(e<=s) throw new Error("종료 시간은 시작 시간보다 늦어야 합니다."); }
  r[key]=val;
}
function cMarkStart(){
  if(!cCan){cFlash("먼저 재생 가능한 영상을 선택해 주세요.");return;}
  if(cAct()>=0){cFlash("이미 [삭제 시작]을 눌렀습니다. 먼저 [삭제 종료]를 눌러 주세요.");return;}
  crows.push({start:cV.currentTime,end:null,active:true}); cFlash(""); cRebuild(true);
}
function cMarkEnd(){
  if(!cCan){cFlash("먼저 재생 가능한 영상을 선택해 주세요.");return;}
  const i=cAct(); if(i<0){cFlash("먼저 [삭제 시작]을 눌러 주세요.");return;}
  const t=cV.currentTime; if(t<=crows[i].start){cFlash("종료 위치가 시작 위치보다 앞입니다. 영상을 더 재생한 뒤 눌러 주세요.");return;}
  crows[i].end=t; crows[i].active=false; cFlash(`${i+1}번 구간을 지정했습니다.`); cRebuild(true);
}
function cCancelMark(){ const i=cAct(); if(i<0) return; crows.splice(i,1); cFlash("지정 중이던 구간을 취소했습니다."); cRebuild(); }
function cPlayRow(i){       // 앞뒤 3초를 함께 보여줌
  const r=crows[i];
  if(!cCan){cFlash("영상을 재생할 수 없는 상태입니다.");return;}
  if(r.start==null||r.end==null||r.end<=r.start){cFlash("시작과 종료 시간이 올바른 구간만 확인할 수 있습니다.");return;}
  cSkip=false; cV.currentTime=Math.max(0,r.start-3); cPlayUntil=Math.min(cDur,r.end+3); cV.play();
}
function cPreview(){
  const m=cMerged(); if(!cCan){cFlash("영상을 재생할 수 없는 상태입니다.");return;}
  if(!m.length){cFlash("지울 구간을 먼저 지정해 주세요.");return;}
  cSkip=true; cPlayUntil=null; cV.currentTime=(m[0][0]<=0.01? m[0][1]:0); cV.play(); cFlash("삭제 후 결과를 미리 봅니다. (지운 구간은 건너뜁니다)");
}
function cRebuild(scrollEnd){
  const box=$("cList"); box.innerHTML="";
  crows.forEach((r,i)=>{
    const d=document.createElement("div"); d.className="dr"+(r.active?" act":"");
    const n=document.createElement("div"); n.className="n"; n.textContent=i+1; d.append(n);
    for(const key of ["start","end"]){
      const inp=document.createElement("input"); inp.type="text"; inp.value=r[key]==null?"":fmt1(r[key]);
      inp.onchange=()=>{ const txt=inp.value.trim();
        try{ if(!txt){cSetTime(i,key,null);} else { let v=parseTime(txt); if(cDur&&v>cDur) v=cDur; cSetTime(i,key,v);} cFlash(""); }
        catch(e){ cFlash(e&&e.message? e.message:"시간은 분:초 형식(예: 1:23.5)으로 입력해 주세요."); }
        cSyncRow(i); };
      inp.onkeydown=e=>{ if(e.key==="Enter") inp.blur(); };
      d.append(inp);
    }
    const len=document.createElement("div"); len.className="len"; len.textContent=lenText(r); d.append(len);
    const pb=document.createElement("button"); pb.className="mini mplay"; pb.textContent="▶"; pb.title="앞뒤 3초를 포함해 확인"; pb.onclick=()=>cPlayRow(i); d.append(pb);
    const db=document.createElement("button"); db.className="mini mdel"; db.textContent="✕"; db.onclick=()=>{crows.splice(i,1);cRebuild();}; d.append(db);
    box.append(d);
  });
  const g=document.createElement("div"); g.className="ghost"; g.textContent="다음 지울 구간은 [삭제 시작] 버튼으로 추가하세요"; box.append(g);
  if(scrollEnd) box.scrollTop=box.scrollHeight;
  cRefresh();
}
function cSyncRow(i){ cRebuild(); }
function cRefresh(){
  const a=cAct();
  const pill=$("cPill");
  if(a>=0){ pill.textContent=`${a+1}번 지울 구간 지정 중 · 지울 장면이 끝나면 [삭제 종료]를 누르세요`; pill.className="pill on"; }
  else { pill.textContent="지울 구간 지정 대기 · 지울 장면이 시작되면 [삭제 시작]을 누르세요"; pill.className="pill"; }
  const m=cMerged(), del=m.reduce((s,r)=>s+r[1]-r[0],0);
  if(cInfoV){ $("cSummary").textContent=`원본 ${mmss(cDur)} − 지울 구간 ${cDone().length}개 완료(${del<60? del.toFixed(1)+"초":mmss(del)}) = 결과 약 ${mmss(Math.max(0,cDur-del))}`; }
  else $("cSummary").textContent="";
  cDraw();
}
function cDraw(){
  const bar=$("cSeek"); bar.querySelectorAll(".seg").forEach(e=>e.remove());
  if(!cDur) { $("cHead").style.left="0"; return; }
  crows.forEach(r=>{
    if(r.start==null) return;
    const e=r.active? cV.currentTime : r.end; if(e==null) return;
    const a=Math.min(r.start,e), b=Math.max(r.start,e);
    const s=document.createElement("div"); s.className="seg del"+(r.active?" act":"");
    s.style.left=(100*a/cDur)+"%"; s.style.width=Math.max(0.3,100*(b-a)/cDur)+"%"; bar.insertBefore(s,$("cHead"));
  });
  $("cHead").style.left=(100*Math.min(1,cV.currentTime/cDur))+"%";
  $("cClock").textContent=`${fmt1(cV.currentTime)} / ${fmt1(cDur)}`;
}
function cTick(){
  if(cSkip){ for(const [s,e] of cMerged()){ if(cV.currentTime>=s-0.02&&cV.currentTime<e){ if(e>=cDur-0.05){cV.pause();cSkip=false;cV.currentTime=cDur;} else cV.currentTime=e; break; } } if(cV.ended) cSkip=false; }
  if(cPlayUntil!=null&&cV.currentTime>=cPlayUntil){ cV.pause(); cPlayUntil=null; }
  cDraw();
}
cV.addEventListener("timeupdate",cTick);
setInterval(()=>{ if(curTab===2&&!cV.paused) cTick(); },100);
$("cSeek").addEventListener("pointerdown",e=>{
  if(!cCan||!cDur) return; const rc=$("cSeek").getBoundingClientRect(); cSkip=false; cPlayUntil=null;
  cV.currentTime=cDur*Math.min(1,Math.max(0,(e.clientX-rc.left)/rc.width)); cDraw();
});
function cSeekRel(d){ if(cCan){ cSkip=false; cV.currentTime=Math.min(cDur,Math.max(0,cV.currentTime+d)); } }
function cToggle(){ if(!cCan) return; cPlayUntil=null; cSkip=false; cV.paused?cV.play():cV.pause(); }
const cUI={go:$("cGo"),cancel:$("cCancelJob"),bar:$("cBar"),st:$("cStatus"),setBusy:b=>{cBusy=b;}};
async function cSave(){
  if(cBusy) return;
  cBusy=true; $("cStatus").textContent="저장할 위치를 선택해 주세요... (다른 창 뒤에 숨어 있을 수 있습니다)";
  try{
    const d=await api("/api/cut/save",{deletes:cMerged(),fast:$("cFast").checked});
    if(d.cancelled){cBusy=false;$("cStatus").textContent="대기 중";return;}
    trackJob("cut",cUI);
  }catch(e){ cBusy=false; $("cStatus").textContent="대기 중"; await popup(e.message); }
}
$("cPick").onclick=cPick; $("cStart").onclick=cMarkStart; $("cEnd").onclick=cMarkEnd; $("cCancelMark").onclick=cCancelMark;
$("cPreview").onclick=cPreview; $("cGo").onclick=cSave; $("cCancelJob").onclick=()=>api("/api/cancel");
$("cPlay").onclick=cToggle; $("cStop").onclick=()=>{ if(cCan){cPlayUntil=null;cSkip=false;cV.pause();} };
$("cRate").onchange=()=>{ cV.playbackRate=parseFloat($("cRate").value); };
document.querySelectorAll("[data-cseek]").forEach(b=>b.onclick=()=>cSeekRel(parseFloat(b.dataset.cseek)));
$("cAdd").onclick=()=>{ crows.push({start:null,end:null,active:false}); cRebuild(true); cFlash("시작·종료 시간을 직접 입력해 주세요."); };
$("cReset").onclick=async()=>{
  const ok=await popup("지정한 지울 구간을 모두 지우고 처음 상태로 되돌립니다.\n불러온 영상은 그대로 둡니다.\n\n계속할까요?",[["초기화",true],["취소",false]]);
  if(!ok) return; cPlayUntil=null; cSkip=false; if(cCan) cV.pause(); crows=[]; $("cBar").style.width="0"; cFlash("전체 초기화했습니다."); cRebuild();
};

// ======================================================================
// 탭 ③ 영상 합치기
// ======================================================================
const mV=$("mVid");
let clips=[], plan=null, mSel=null, mBusy=false, mTrans=false, dragId=null;
const mUI={go:$("mGo"),cancel:$("mCancelJob"),bar:$("mBar"),st:$("mStatus"),setBusy:b=>{mBusy=b;}};
function ratioLabel(w,h){
  const g=(a,b)=>b?g(b,a%b):a, d=g(w,h), a=w/d, b=h/d, r=w/h;
  if(Math.abs(r-16/9)<0.02) return "16:9"; if(Math.abs(r-4/3)<0.02) return "4:3"; if(Math.abs(r-1)<0.02) return "1:1";
  if(Math.abs(r-9/16)<0.02) return "9:16"; return a<=30&&b<=30? `${a}:${b}`:`${w}x${h}`;
}
function mApply(d){
  clips=(d.clips&&d.clips.list)||[]; plan=(d.clips&&d.clips.plan)||null;
  if(!clips.some(c=>c.id===mSel)) mSel=clips.length? clips[0].id:null;
  mRender(); mSelect(mSel,true);
}
function mWarns(c){
  const w=[]; if(!plan) return w;
  if(c.width!==plan.width||c.height!==plan.height){
    const same=Math.abs(c.width/c.height-plan.width/plan.height)<0.02;
    w.push(same? `해상도 다름 → ${plan.width}x${plan.height}로 맞춤` : "해상도 다름 → 검은 여백");
  }
  if(c.fps!==plan.fps) w.push(`fps 다름 → ${plan.fps}fps로 맞춤`);
  if(plan.mixedHdr&&c.hdr) w.push("HDR → SDR로 변환");
  return w;
}
function mRender(){
  const box=$("mList"); box.innerHTML="";
  clips.forEach((c,i)=>{
    const d=document.createElement("div"); d.className="clip"+(c.id===mSel?" sel":""); d.draggable=true; d.dataset.id=c.id;
    d.onclick=()=>mSelect(c.id);
    d.ondragstart=e=>{dragId=c.id; e.dataTransfer.effectAllowed="move"; e.dataTransfer.setData("text/plain","clip");};
    d.ondragover=e=>{ if(dragId!=null){e.preventDefault(); d.classList.add("dragover");} };
    d.ondragleave=()=>d.classList.remove("dragover");
    d.ondrop=async e=>{ if(dragId==null) return; e.preventDefault(); e.stopPropagation(); d.classList.remove("dragover");
      const id=dragId; dragId=null; if(id!==c.id) mApply(await api("/api/clips/move",{id,to:i})); };
    d.ondragend=()=>{dragId=null; document.querySelectorAll(".clip.dragover").forEach(x=>x.classList.remove("dragover"));};
    const g=document.createElement("div"); g.className="grip"; g.textContent="≡"; d.append(g);
    const im=document.createElement("img"); im.src="/thumb?id="+c.id+"&t="+TOKEN; im.alt=""; im.draggable=false; im.onerror=()=>{im.style.visibility="hidden";}; d.append(im);
    const mid=document.createElement("div"); mid.style.minWidth="0";
    const nm=document.createElement("div"); nm.className="nm"; nm.textContent=`${i+1}. ${c.name}`; nm.title=c.name; mid.append(nm);
    const me=document.createElement("div"); me.className="meta"; me.textContent=`${c.width}x${c.height} · ${c.fps}fps · ${mmss(c.duration)} · ${c.codec}`; mid.append(me);
    const bd=document.createElement("div");
    const badge=(t,k)=>{const b=document.createElement("span"); b.className="badge "+k; b.textContent=t; bd.append(b);};
    if(c.hdr) badge("HDR","hdr"); badge(c.audio?"소리 있음":"소리 없음","aud");
    mWarns(c).forEach(t=>badge(t,"warn")); mid.append(bd); d.append(mid);
    const ops=document.createElement("div"); ops.className="ops";
    const mk=(t,fn,cls,dis)=>{const b=document.createElement("button"); b.textContent=t; b.className=cls||"move"; b.disabled=!!dis; b.onclick=async e=>{e.stopPropagation(); fn();}; ops.append(b);};
    mk("▲",async()=>mApply(await api("/api/clips/move",{id:c.id,to:i-1})),"move",i===0);
    mk("▼",async()=>mApply(await api("/api/clips/move",{id:c.id,to:i+1})),"move",i===clips.length-1);
    mk("✕",async()=>mApply(await api("/api/clips/remove",{id:c.id})),"mdel");
    d.append(ops); box.append(d);
  });
  mInfo();
}
function mInfo(){
  const tot=clips.reduce((s,c)=>s+c.duration,0);
  $("mSummary").textContent=clips.length? `영상 ${clips.length}개 · 합계 ${secText(tot)}`:"";
  const box=$("mInfo"), note=$("mNote");
  if(!plan){ box.innerHTML='<div class="sub">영상을 추가하면 합친 영상의 크기·화질이 여기에 표시됩니다.</div>'; note.hidden=true; return; }
  const rows=[`합친 영상 크기(자동): <b>${ratioLabel(plan.width,plan.height)} ${plan.width}x${plan.height}</b> · ${plan.fps}fps <span class="sub">(가장 많은 크기 기준)</span>`,
    `화질: <b>${plan.keepHdr? "원본 색상(HDR) 유지":"SDR(일반 색상)"}</b>`,
    `방식: <b>${(plan.fast&&!mTrans)? "다시 인코딩 없이 이어붙임 (빠름)":"크기·fps를 맞춰 다시 인코딩"}</b>`];
  box.innerHTML=rows.map(t=>`<div>${t}</div>`).join("");
  const diff=clips.some(c=>mWarns(c).length);
  let t="";
  if(plan.mixedHdr) t="HDR 영상과 일반(SDR) 영상이 섞여 있어 모두 SDR로 통일해 저장합니다. ";
  if(diff||mTrans) t+="크기·fps가 다르거나 부드러운 전환을 쓰면 다시 인코딩하므로 시간이 더 걸립니다.";
  note.textContent=t; note.hidden=!t;
}
function mSelect(id,quiet){
  mSel=id; document.querySelectorAll(".clip").forEach(el=>el.classList.toggle("sel",el.dataset.id==String(id)));
  if(id==null){ mV.removeAttribute("src"); mV.load(); $("mPh").style.display=""; return; }
  if(quiet&&mV.dataset.id===String(id)) return;
  mV.dataset.id=String(id); $("mPh").style.display="none"; mV.src="/video?clip="+id+"&t="+TOKEN+"&r="+Date.now(); mV.load();
}
async function mPick(){
  if(mBusy) return; mBusy=true; $("mStatus").textContent="파일 선택 창을 여는 중... (다른 창 뒤에 숨어 있을 수 있습니다)";
  try{ const d=await api("/api/clips/pick"); if(!d.cancelled){ mApply(d); if(d.warn) await popup(d.warn); } }
  catch(e){ await popup(e.message); } finally{ mBusy=false; $("mStatus").textContent="대기 중"; }
}
async function mUploadMany(files){
  const list=[...files].filter(f=>VEXT.test(f.name));
  if(!list.length){ await popup("동영상 파일(mp4, mov 등)만 추가할 수 있습니다."); return; }
  if(mBusy) return; mBusy=true; let bad=[];
  for(let k=0;k<list.length;k++){
    const f=list[k];
    const d=await upTo("/api/clips/upload",f,p=>{$("mStatus").textContent=`영상 불러오는 중 (${k+1}/${list.length}) ${Math.round(p*100)}%`;$("mBar").style.width=(p*100)+"%";});
    if(d.error) bad.push(`${f.name}: ${d.error}`); else mApply(d);
  }
  mBusy=false; $("mBar").style.width="0"; $("mStatus").textContent="대기 중";
  if(bad.length) await popup("일부 영상을 불러오지 못했습니다.\n"+bad.join("\n"));
}
function mSetTr(on){ mTrans=on; $("mTr0").classList.toggle("sel",!on); $("mTr1").classList.toggle("sel",on); mInfo(); }
async function mSave(){
  if(mBusy) return;
  if(clips.length<2){ await popup("합칠 영상을 2개 이상 추가해 주세요."); return; }
  mBusy=true; $("mStatus").textContent="저장할 위치를 선택해 주세요... (다른 창 뒤에 숨어 있을 수 있습니다)";
  try{
    const d=await api("/api/merge/save",{transition:mTrans});
    if(d.cancelled){mBusy=false;$("mStatus").textContent="대기 중";return;}
    trackJob("merge",mUI);
  }catch(e){ mBusy=false; $("mStatus").textContent="대기 중"; await popup(e.message); }
}
$("mPick").onclick=mPick; $("mAdd").onclick=mPick; $("mGo").onclick=mSave; $("mCancelJob").onclick=()=>api("/api/cancel");
$("mTr0").onclick=()=>mSetTr(false); $("mTr1").onclick=()=>mSetTr(true);
$("mReset").onclick=async()=>{
  if(!clips.length) return;
  const ok=await popup("합칠 영상 목록을 모두 비우고 처음 상태로 되돌립니다.\n(원본 파일은 지워지지 않습니다.)\n\n계속할까요?",[["초기화",true],["취소",false]]);
  if(!ok) return; mV.pause(); mApply(await api("/api/clips/clear")); $("mBar").style.width="0"; $("mStatus").textContent="대기 중"; mSetTr(false);
};
$("mPlay").onclick=()=>{ if(mSel!=null) mV.paused?mV.play():mV.pause(); };
$("mStop").onclick=()=>mV.pause();
document.querySelectorAll("[data-mseek]").forEach(b=>b.onclick=()=>{ if(mSel!=null) mV.currentTime=Math.min(mV.duration||0,Math.max(0,mV.currentTime+parseFloat(b.dataset.mseek))); });

// ---------- 끌어놓기 / 단축키: 현재 탭에 맞게 ----------
function dropRoute(files){
  if(curTab===2) cUpload(files[0]); else if(curTab===3) mUploadMany(files); else upload(files[0]);
}
addEventListener("keydown",e=>{
  if(curTab!==2) return;
  const tag=(e.target.tagName||"").toLowerCase(); if(tag==="input"||tag==="select"||tag==="textarea"||$("dlg").open) return;
  const k=e.key;
  if(k==="s"||k==="S"){e.preventDefault();cMarkStart();}
  else if(k==="e"||k==="E"){e.preventDefault();cMarkEnd();}
  else if(k===" "){e.preventDefault();cToggle();}
  else if(k==="ArrowLeft"){e.preventDefault();cSeekRel(-5);}
  else if(k==="ArrowRight"){e.preventDefault();cSeekRel(5);}
});
(async function initTabs(){ try{ const d=await getState(); if(d.cut) cShowVideo(d.cut); mApply(d); }catch(_){} })();

/* ---- 테마(라이트/다크/자동) ---- */
function applyTheme(m){
  window.__themeMode=m;
  const d=m==="dark"||(m==="auto"&&matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme=d?"dark":"light";
  document.querySelectorAll("#themeBox button").forEach(b=>b.classList.toggle("sel",b.dataset.th===m));
}
document.querySelectorAll("#themeBox button").forEach(b=>b.onclick=()=>{
  applyTheme(b.dataset.th);
  api("/api/theme",{mode:b.dataset.th}).catch(()=>{});
});
try{matchMedia("(prefers-color-scheme: dark)").addEventListener("change",()=>{if(window.__themeMode==="auto")applyTheme("auto");});}catch(e){}
applyTheme(window.__themeMode||"auto");

/* ---- 배속 버튼 (숨긴 목록 상자와 연결) ---- */
document.querySelectorAll("button.spd").forEach(b=>b.onclick=()=>{
  const sel=$(b.dataset.rateFor); sel.value=b.dataset.v; sel.dispatchEvent(new Event("change"));
  document.querySelectorAll(`button.spd[data-rate-for="${b.dataset.rateFor}"]`).forEach(x=>x.classList.toggle("sel",x===b));
});
</script>
</body>
</html>
'''



# ----------------------------------------------------------------------
# 웹 서버 (이 PC 안에서만 접속 가능: 127.0.0.1)
# ----------------------------------------------------------------------
TOKEN = os.urandom(12).hex()
S = {
    "ffmpeg": None, "ffprobe": None, "font": None, "font_note": "",
    "src": None, "info": None, "uploaded": False,
    "cut": {"src": None, "info": None, "uploaded": False},
    "clips": [], "next_id": 1,
    "tonemap_ok": None, "last_ping": 0.0,
    "job": {"state": "idle", "kind": "", "done": 0, "total": 1, "msg": "", "out": "", "error": ""},
}
THUMBS = {}
CANCEL = threading.Event()
UPLOAD_DIR = tempfile.mkdtemp(prefix="hl_upload_")
LOCK = threading.Lock()


def _dialog(kind, title, initial="", filetypes=None, default_name=""):
    """파일 선택/저장 창(윈도우 기본 창)을 따로 띄워 선택한 경로를 돌려줍니다."""
    code = (
        "import sys, json\n"
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "a = json.loads(sys.argv[1])\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        "ft = [tuple(x) for x in a['ft']] or [('모든 파일', '*.*')]\n"
        "if a['kind'] == 'save':\n"
        "    p = filedialog.asksaveasfilename(title=a['title'], initialdir=a['init'] or None,\n"
        "        initialfile=a['name'], defaultextension='.mp4', filetypes=ft)\n"
        "elif a['kind'] == 'dir':\n"
        "    p = filedialog.askdirectory(title=a['title'], initialdir=a['init'] or None)\n"
        "elif a['kind'] == 'openmulti':\n"
        "    p = '\\n'.join(filedialog.askopenfilenames(title=a['title'], initialdir=a['init'] or None, filetypes=ft))\n"
        "else:\n"
        "    p = filedialog.askopenfilename(title=a['title'], initialdir=a['init'] or None, filetypes=ft)\n"
        "sys.stdout.buffer.write((p or '').encode('utf-8'))\n"
    )
    arg = json.dumps({"kind": kind, "title": title, "init": initial,
                      "ft": filetypes or [], "name": default_name})
    exe = sys.executable
    if IS_WIN and exe.lower().endswith("pythonw.exe"):
        cand = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.isfile(cand):
            exe = cand
    r = subprocess.run([exe, "-c", code, arg], capture_output=True, stdin=subprocess.DEVNULL,
                       creationflags=NO_WINDOW)
    return r.stdout.decode("utf-8", "replace").strip("\r\n")


def load_tools():
    ff, fp = find_ffmpeg_pair()
    S["ffmpeg"], S["ffprobe"] = ff, fp
    S["font"], S["font_note"] = find_font()


def load_video(path, uploaded=False):
    if not (S["ffmpeg"] and S["ffprobe"]):
        raise EditError("FFmpeg를 먼저 찾아야 합니다. 화면 위쪽의 [FFmpeg 위치 지정]을 눌러 주세요.")
    info = probe(S["ffprobe"], path)
    old = S["src"]
    S["src"], S["info"], S["uploaded"] = path, info, uploaded
    if old and old != path and old.startswith(UPLOAD_DIR):
        try:
            os.remove(old)
        except OSError:
            pass


def info_json():
    i = S["info"]
    if not i:
        return None
    is_hdr = i["transfer"] in HDR_TRANSFERS
    return {"name": os.path.basename(S["src"]), "width": i["width"], "height": i["height"],
            "fps": fps_label(i["fps"]), "duration": i["duration"], "codec": i["codec"],
            "hdr": is_hdr}


def _brief(path, i, uploaded=False):
    return {"name": os.path.basename(path), "width": i["width"], "height": i["height"],
            "fps": fps_label(i["fps"]), "duration": i["duration"], "codec": i["codec"],
            "hdr": i["transfer"] in HDR_TRANSFERS, "audio": bool(i["has_audio"])}


def cut_json():
    c = S["cut"]
    return _brief(c["src"], c["info"]) if c["src"] else None


def clips_json():
    out = []
    for c in S["clips"]:
        d = _brief(c["path"], c["info"])
        d["id"] = c["id"]
        out.append(d)
    plan = None
    if len(S["clips"]) >= 1:
        p = merge_plan(S["clips"], False, bool(S["ffmpeg"]) and has_encoder(S["ffmpeg"], "libx265"))
        plan = {"width": p["width"], "height": p["height"], "fps": fps_label(p["fps"]),
                "fpsRaw": p["fps"], "keepHdr": p["keep"], "mixedHdr": p["mixed_hdr"],
                "fast": p["fast"]}
    return {"list": out, "plan": plan}


def state_json():
    return {"ffmpeg": bool(S["ffmpeg"] and S["ffprobe"]),
            "ffmpegPath": S["ffmpeg"] or "", "font": bool(S["font"]),
            "video": info_json(), "job": S["job"], "positions": list(POSITIONS.keys()),
            "defaultPosition": DEFAULT_POSITION, "cut": cut_json(), "clips": clips_json()}


def _clean(path, uploaded):
    if uploaded and path and path.startswith(UPLOAD_DIR):
        try:
            os.remove(path)
        except OSError:
            pass


def load_cut(path, uploaded=False):
    if not (S["ffmpeg"] and S["ffprobe"]):
        raise EditError("FFmpeg를 먼저 찾아야 합니다. 화면 위쪽의 [FFmpeg 위치 지정]을 눌러 주세요.")
    info = probe(S["ffprobe"], path)
    old = S["cut"]
    if old["src"] and old["src"] != path:
        _clean(old["src"], old["uploaded"])
    S["cut"] = {"src": path, "info": info, "uploaded": uploaded}


def add_clip(path, uploaded=False):
    if not (S["ffmpeg"] and S["ffprobe"]):
        raise EditError("FFmpeg를 먼저 찾아야 합니다. 화면 위쪽의 [FFmpeg 위치 지정]을 눌러 주세요.")
    info = probe(S["ffprobe"], path)
    S["clips"].append({"id": S["next_id"], "path": path, "info": info, "uploaded": uploaded})
    S["next_id"] += 1


def start_job(segments, title, out, out_ratio=DEFAULT_RATIO, kind="highlight", runner=None):
    CANCEL.clear()
    S["job"] = {"state": "running", "kind": kind, "done": 0, "total": 1, "msg": "준비 중...",
                "out": out, "error": ""}

    def progress(d, t, m):
        S["job"].update(done=d, total=max(t, 1), msg=m)

    def work():
        try:
            if S["tonemap_ok"] is None:
                S["tonemap_ok"] = has_tonemap_filters(S["ffmpeg"])
            if runner:
                runner(progress)
            else:
                make_highlight(S["ffmpeg"], S["src"], S["info"], segments, title, S["font"], out,
                               progress, CANCEL, S["tonemap_ok"], True, out_ratio)
            S["job"].update(state="done", done=1, total=1, msg="완료")
        except Cancelled:
            S["job"].update(state="cancelled", msg="취소했습니다.")
        except EditError as e:
            S["job"].update(state="error", error=str(e))
        except Exception:
            S["job"].update(state="error",
                            error="예상하지 못한 오류가 발생했습니다.\n\n" + traceback.format_exc()[-800:])

    threading.Thread(target=work, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HighlightEditor"

    def log_message(self, *a):
        pass

    # ---- 공통 ----
    def _ok_host(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _fail(self, text, code=400):
        self._json({"error": text}, code)

    def _authed(self):
        if self.headers.get("X-Token") == TOKEN:
            return True
        q = parse_qs(urlparse(self.path).query)
        return q.get("t", [""])[0] == TOKEN

    # ---- GET ----
    def do_GET(self):
        if not self._ok_host():
            return self._send(403)
        u = urlparse(self.path)
        if u.path == "/":
            page = PAGE.replace("__TOKEN__", TOKEN).replace("__TITLE__", APP_TITLE).replace("__THEME__", get_theme())
            return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        if not self._authed():
            return self._send(403)
        if u.path == "/api/state":
            S["last_ping"] = __import__("time").time()
            return self._json(state_json())
        if u.path == "/video":
            q = parse_qs(u.query)
            if q.get("slot", [""])[0] == "cut":
                return self._video(S["cut"]["src"])
            if q.get("clip", [""])[0]:
                cid = q["clip"][0]
                c = next((x for x in S["clips"] if str(x["id"]) == cid), None)
                return self._video(c["path"] if c else None)
            return self._video(S["src"])
        if u.path == "/thumb":
            return self._thumb(parse_qs(u.query).get("id", [""])[0])
        self._send(404)

    do_HEAD = do_GET

    def _thumb(self, cid):
        c = next((x for x in S["clips"] if str(x["id"]) == cid), None)
        if not c:
            return self._send(404)
        data = THUMBS.get(c["id"])
        if data is None:
            t = min(1.0, max(0.0, c["info"]["duration"] / 4))
            r = subprocess.run([S["ffmpeg"], "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}",
                                "-i", c["path"], "-frames:v", "1", "-vf", "scale=160:-2",
                                "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                               capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
            data = r.stdout if r.returncode == 0 else b""
            THUMBS[c["id"]] = data
        if not data:
            return self._send(404)
        self._send(200, data, "image/jpeg", {"Cache-Control": "max-age=3600"})

    def _video(self, path):
        if not path or not os.path.isfile(path):
            return self._send(404)
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "video/mp4"
        start, end, code = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            else:
                start = max(0, size - int(m.group(2)))
            if start >= size:
                return self._send(416, extra={"Content-Range": f"bytes */{size}"})
            code = 206
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionError, OSError):
            pass

    # ---- POST ----
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw.decode("utf-8")) if raw else {}

    def do_POST(self):
        if not self._ok_host() or not self._authed():
            return self._send(403)
        u = urlparse(self.path)
        try:
            if u.path == "/api/upload":
                return self._upload(u)
            if u.path == "/api/cut/upload":
                return self._upload(u, "cut")
            if u.path == "/api/clips/upload":
                return self._upload(u, "clip")
            data = self._body()
            fn = {"/api/pick": self._pick, "/api/ffmpeg": self._pick_ffmpeg,
                  "/api/save": self._save, "/api/cancel": self._cancel,
                  "/api/openfolder": self._openfolder, "/api/quit": self._quit,
                  "/api/unload": self._unload, "/api/theme": self._theme, "/api/log/save": self._log_save, "/api/log/folder": self._log_folder, "/api/log/load": self._log_load, "/api/cut/pick": self._cut_pick, "/api/cut/save": self._cut_save,
                  "/api/clips/pick": self._clips_pick, "/api/clips/remove": self._clips_remove,
                  "/api/clips/move": self._clips_move, "/api/clips/clear": self._clips_clear,
                  "/api/merge/save": self._merge_save}.get(u.path)
            if not fn:
                return self._send(404)
            return fn(data)
        except EditError as e:
            return self._fail(str(e))
        except (ConnectionError, OSError):
            raise
        except Exception:
            return self._fail("예상하지 못한 오류가 발생했습니다.\n\n" + traceback.format_exc()[-700:], 500)

    def _pick(self, _d):
        if not (S["ffmpeg"] and S["ffprobe"]):
            raise EditError("FFmpeg를 먼저 찾아야 합니다. [FFmpeg 위치 지정]을 눌러 주세요.")
        exts = " ".join("*" + e for e in VIDEO_EXTS)
        path = _dialog("open", "영상 파일 선택", "", [["영상", exts], ["모든 파일", "*.*"]])
        if not path:
            return self._json({"cancelled": True})
        load_video(path)
        self._json(state_json())

    def _upload(self, u, slot="main"):
        if not (S["ffmpeg"] and S["ffprobe"]):
            raise EditError("FFmpeg를 먼저 찾아야 합니다.")
        name = os.path.basename(parse_qs(u.query).get("name", ["video.mp4"])[0]) or "video.mp4"
        if not name.lower().endswith(VIDEO_EXTS):
            raise EditError("지원하는 영상 형식은 mp4, mov, m4v, mkv, avi 입니다.")
        folder = UPLOAD_DIR
        if slot != "main":
            folder = os.path.join(UPLOAD_DIR, slot + str(S["next_id"] if slot == "clip" else ""))
            os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, name)
        left = int(self.headers.get("Content-Length") or 0)
        with open(dest, "wb") as f:
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if slot == "cut":
            load_cut(dest, True)
        elif slot == "clip":
            add_clip(dest, True)
        else:
            load_video(dest, uploaded=True)
        self._json(state_json())

    def _log_save(self, d):
        if not S["src"]:
            raise EditError("먼저 영상 파일을 선택해 주세요.")
        t = d.get("title") if isinstance(d.get("title"), dict) else {}
        rows = d.get("rows") if isinstance(d.get("rows"), list) else []
        name = os.path.basename(S["src"])
        log = build_log("" if S["uploaded"] else os.path.abspath(S["src"]), name, S["info"], rows, t)
        base = get_log_dir() or (os.path.dirname(S["src"]) if not S["uploaded"] else os.path.expanduser("~"))
        path = _dialog("save", "편집 로그 저장", base, [["편집 로그", "*.json"]],
                       log_default_name(name))
        if not path:
            return self._json({"cancelled": True})
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(log, f, ensure_ascii=False, indent=1)
        except OSError as e:
            raise EditError(f"로그를 저장하지 못했습니다.\n{e}")
        self._json({"path": path})

    def _theme(self, d):
        set_theme(str(d.get("mode", "auto")))
        self._json({"ok": True})

    def _log_folder(self, _d):
        d = _dialog("dir", "로그를 저장할 폴더 선택 (구글 드라이브·OneDrive 폴더를 고르면 클라우드에 보관됩니다)", get_log_dir())
        if not d:
            return self._json({"cancelled": True})
        set_log_dir(d)
        self._json({"dir": d})

    def _log_load(self, _d):
        if S["job"]["state"] == "running":
            raise EditError("편집이 진행 중입니다. 끝난 뒤에 불러와 주세요.")
        if not (S["ffmpeg"] and S["ffprobe"]):
            raise EditError("FFmpeg를 먼저 찾아야 합니다. [FFmpeg 위치 지정]을 눌러 주세요.")
        path = _dialog("open", "편집 로그 불러오기", get_log_dir(), [["편집 로그", "*.json"], ["모든 파일", "*.*"]])
        if not path:
            return self._json({"cancelled": True})
        log = read_log(path)
        vp = log["video"]["path"]
        found = bool(vp and os.path.isfile(vp))
        if found:
            load_video(vp)
        dur = S["info"]["duration"] if (found and S["info"]) else 0.0
        log["rows"] = clean_log_rows(log["rows"], dur)
        out = state_json()
        out.update({"log": log, "videoFound": found})
        self._json(out)

    def _unload(self, _d):
        if S["job"]["state"] == "running":
            raise EditError("편집이 진행 중입니다. 끝난 뒤에 초기화해 주세요.")
        old, up = S["src"], S["uploaded"]
        S["src"], S["info"], S["uploaded"] = None, None, False
        _clean(old, up)
        self._json({"ok": True})

    def _cut_pick(self, _d):
        if not (S["ffmpeg"] and S["ffprobe"]):
            raise EditError("FFmpeg를 먼저 찾아야 합니다. [FFmpeg 위치 지정]을 눌러 주세요.")
        exts = " ".join("*" + e for e in VIDEO_EXTS)
        path = _dialog("open", "영상 파일 선택", "", [["영상", exts], ["모든 파일", "*.*"]])
        if not path:
            return self._json({"cancelled": True})
        load_cut(path)
        self._json(state_json())

    def _clips_pick(self, _d):
        if not (S["ffmpeg"] and S["ffprobe"]):
            raise EditError("FFmpeg를 먼저 찾아야 합니다. [FFmpeg 위치 지정]을 눌러 주세요.")
        exts = " ".join("*" + e for e in VIDEO_EXTS)
        res = _dialog("openmulti", "합칠 영상 선택 (여러 개 선택 가능)", "", [["영상", exts], ["모든 파일", "*.*"]])
        paths = [p for p in res.split("\n") if p.strip()]
        if not paths:
            return self._json({"cancelled": True})
        bad = []
        for p in paths:
            try:
                add_clip(p)
            except EditError as e:
                bad.append(f"{os.path.basename(p)}: {e}")
        out = state_json()
        if bad:
            out["warn"] = "일부 영상을 불러오지 못했습니다.\n" + "\n".join(bad)
        self._json(out)

    def _clips_remove(self, d):
        c = next((x for x in S["clips"] if x["id"] == d.get("id")), None)
        if c:
            S["clips"].remove(c)
            _clean(c["path"], c["uploaded"])
            THUMBS.pop(c["id"], None)
        self._json(state_json())

    def _clips_move(self, d):
        ids = [x["id"] for x in S["clips"]]
        cid, to = d.get("id"), d.get("to")
        if cid in ids and isinstance(to, int):
            c = S["clips"].pop(ids.index(cid))
            S["clips"].insert(max(0, min(to, len(S["clips"]))), c)
        self._json(state_json())

    def _clips_clear(self, _d):
        for c in S["clips"]:
            _clean(c["path"], c["uploaded"])
        S["clips"] = []
        THUMBS.clear()
        self._json(state_json())

    def _cut_save(self, d):
        c = S["cut"]
        if not c["src"]:
            raise EditError("먼저 영상을 선택해 주세요.")
        if S["job"]["state"] == "running":
            raise EditError("이미 편집이 진행 중입니다.")
        dels = []
        for r in d.get("deletes", []):
            try:
                a, b = float(r[0]), float(r[1])
            except (TypeError, ValueError, IndexError, KeyError):
                raise EditError("지울 구간의 시간이 올바르지 않습니다.")
            if b <= a:
                raise EditError("지울 구간의 종료 시간은 시작 시간보다 늦어야 합니다.")
            dels.append((a, b))
        if not dels:
            raise EditError("지울 구간을 1개 이상 지정해 주세요.")
        if not keep_ranges(dels, c["info"]["duration"]):
            raise EditError("지우고 남는 영상이 없습니다. 지울 구간을 확인해 주세요.")
        fast = bool(d.get("fast"))
        base = os.path.dirname(c["src"]) if not c["uploaded"] else os.path.expanduser("~")
        out = _dialog("save", "저장할 위치와 이름", base, [["MP4 동영상", "*.mp4"]], "구간삭제.mp4")
        if not out:
            return self._json({"cancelled": True})
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        if os.path.abspath(out) == os.path.abspath(c["src"]):
            raise EditError("원본 영상과 같은 이름으로는 저장할 수 없습니다.")
        src, info = c["src"], c["info"]
        start_job(None, None, out, kind="cut", runner=lambda pr: make_cut(
            S["ffmpeg"], src, info, dels, out, pr, CANCEL, S["tonemap_ok"], fast))
        self._json({"started": True})

    def _merge_save(self, d):
        if len(S["clips"]) < 2:
            raise EditError("합칠 영상을 2개 이상 추가해 주세요.")
        if S["job"]["state"] == "running":
            raise EditError("이미 편집이 진행 중입니다.")
        trans = bool(d.get("transition"))
        clips = [dict(c) for c in S["clips"]]
        first = clips[0]["path"]
        base = os.path.dirname(first) if not clips[0]["uploaded"] else os.path.expanduser("~")
        out = _dialog("save", "저장할 위치와 이름", base, [["MP4 동영상", "*.mp4"]], "합친영상.mp4")
        if not out:
            return self._json({"cancelled": True})
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        start_job(None, None, out, kind="merge", runner=lambda pr: make_merge(
            S["ffmpeg"], clips, out, pr, CANCEL, S["tonemap_ok"], trans))
        self._json({"started": True})

    def _pick_ffmpeg(self, _d):
        local = os.environ.get("LOCALAPPDATA", "")
        links = os.path.join(local, "Microsoft", "WinGet", "Links") if local else ""
        path = _dialog("open", "ffmpeg.exe 선택", links if os.path.isdir(links) else "",
                       [["FFmpeg", "ffmpeg.exe ffprobe.exe"], ["모든 파일", "*.*"]])
        if not path:
            return self._json({"cancelled": True})
        folder = os.path.dirname(path)
        ff, fp = os.path.join(folder, _exe("ffmpeg")), os.path.join(folder, _exe("ffprobe"))
        if not (os.path.isfile(ff) and os.path.isfile(fp)):
            raise EditError("선택한 폴더에 ffmpeg.exe와 ffprobe.exe가 모두 있어야 합니다.\n"
                            f"선택한 폴더: {folder}")
        S["ffmpeg"], S["ffprobe"] = ff, fp
        remember_ffmpeg(ff)
        self._json(state_json())

    def _save(self, d):
        if not S["src"]:
            raise EditError("먼저 영상을 선택해 주세요.")
        if S["job"]["state"] == "running":
            raise EditError("이미 편집이 진행 중입니다.")
        rows = [{"start": r.get("start"), "end": r.get("end"), "text": str(r.get("text") or ""),
                 "pos": r.get("pos") if r.get("pos") in POSITIONS else DEFAULT_POSITION,
                 "active": bool(r.get("active")),
                 "crop": r.get("crop") if isinstance(r.get("crop"), dict) else None,
                 "cropOn": isinstance(r.get("crop"), dict)}
                for r in d.get("rows", [])]
        out_ratio = d.get("outRatio") if d.get("outRatio") in RATIOS else DEFAULT_RATIO
        try:
            segs = collect_segments(rows, S["info"]["duration"])
        except ValueError as e:
            raise EditError(str(e))
        if not segs:
            raise EditError("득점 구간을 1개 이상 지정해 주세요.")
        title = None
        t = d.get("title")
        if t and str(t.get("text", "")).strip():
            try:
                secs = float(t.get("secs"))
            except (TypeError, ValueError):
                raise EditError("메인화면 표시 시간(초)을 숫자로 입력해 주세요.")
            if secs < 0:
                raise EditError("메인화면 표시 시간은 0 이상이어야 합니다.")
            if secs > 0:
                title = {"text": str(t["text"]).strip(), "secs": secs}
        base = os.path.dirname(S["src"]) if not S["uploaded"] else os.path.expanduser("~")
        out = _dialog("save", "저장할 위치와 이름", base, [["MP4 동영상", "*.mp4"]], "하이라이트.mp4")
        if not out:
            return self._json({"cancelled": True})
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        if os.path.abspath(out) == os.path.abspath(S["src"]):
            raise EditError("원본 영상과 같은 이름으로는 저장할 수 없습니다.")
        start_job(segs, title, out, out_ratio)
        self._json({"started": True})

    def _cancel(self, _d):
        CANCEL.set()
        self._json({"ok": True})

    def _openfolder(self, _d):
        out = S["job"].get("out")
        if out and IS_WIN:
            os.startfile(os.path.dirname(out))
        self._json({"ok": True})

    def _quit(self, _d):
        self._json({"ok": True})
        CANCEL.set()
        threading.Thread(target=_shutdown, daemon=True).start()


def _shutdown():
    import time
    time.sleep(0.4)
    shutil.rmtree(UPLOAD_DIR, ignore_errors=True)
    os._exit(0)


def _watchdog():
    """브라우저 탭을 닫아 신호가 1분 넘게 끊기면(편집 중이 아닐 때) 프로그램을 끝냅니다."""
    import time
    while True:
        time.sleep(5)
        lp = S["last_ping"]
        if lp and time.time() - lp > 60 and S["job"]["state"] != "running":
            _shutdown()


def main():
    load_tools()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=_watchdog, daemon=True).start()
    threading.Timer(0.6, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    try:
        srv.serve_forever()
    finally:
        shutil.rmtree(UPLOAD_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
