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
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

