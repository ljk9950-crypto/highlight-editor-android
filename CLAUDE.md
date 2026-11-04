# 농구 하이라이트 편집기 — 작업 안내 (Claude용)

아들 농구 경기 영상(갤럭시 S25 촬영, HEVC, 수백 MB)에서 득점 장면을 골라 하이라이트를 만드는 프로그램.
사용자는 윈도우 10 사용자이고 명령 창(터미널) 작업에 익숙하지 않음 → 설명은 쉬운 말로, 명령은 그대로 복사해 쓸 수 있게.

## 1. 버전 명칭과 수정 규칙 (중요)

| 명칭 | 위치 | 내용 |
|---|---|---|
| **PC** | `pc_web/highlight_editor_qt.pyw` | PySide6 윈도우 프로그램 (단일 파일) |
| **WEB** | `pc_web/highlight_editor_web.pyw` | 파이썬 기본 기능만 쓰는 로컬 서버 + 크롬 화면 + FFmpeg |
| **MOBILE APP** | 저장소 루트 (`app/`) | 안드로이드 앱 (Kotlin, Jetpack Compose, Media3) |

- 사용자가 버전을 말하지 않고 수정을 요청하면 **PC와 WEB 둘 다 같게** 고친다. MOBILE APP은 사용자가 말할 때만 고친다.
- 휴대폰 화면 구성처럼 한 버전에만 해당하는 변경은 그 버전에만 적용한다.

## 2. 작업 방식

- 화면(모양)을 바꾸는 요청은 먼저 **시안 PNG**를 보여 주고, 사용자가 "코딩해줘"라고 하면 코딩한다. (`/시안` 명령을 자주 씀)
- 답변: 결론을 먼저, 간단하게, 모르는 것은 쓰지 않기, 판단 근거가 된 자료의 출처 표시.
- 확인하지 못한 것은 솔직하게 "확인 못 함"이라고 말한다.

## 3. 파일 구조

```
app/                         MOBILE APP 소스 (com.ljk.highlight)
.github/workflows/build.yml  MOBILE APP 자동 빌드 → GitHub Releases에 build-N APK 업로드
pc_web/
  highlight_editor_qt.pyw    PC (영상 처리 엔진 코드의 원본도 이 파일)
  highlight_editor_web.pyw   WEB (직접 고치지 말고 build_web.py로 다시 만들 것)
  build_web.py               WEB 파일 생성기
  web_src/head.py            WEB 앞부분
  web_src/engine_old.py      WEB 앞부분 보조 (POSITIONS 앞까지만 사용)
  web_src/page.html          WEB 화면 (HTML/CSS/JS). 안에 ''' (작은따옴표 3개) 금지
  web_src/tail.py            WEB 서버 (요청 처리, /api/...)
  hl_icon_app_v2.ico, hl_icon_web_v2.ico, icons/icon_source.png   아이콘
  바로가기_만들기.vbs         바탕화면 바로가기 생성 (UTF-16 저장)
  tests/test_web.py          WEB 화면 자동 점검 (Playwright) + tests/test.webm
```

### WEB 만드는 법
WEB = `head.py` + `engine_old.py`의 `POSITIONS = {` 앞부분 + **PC 파일의 `POSITIONS = {`부터 `# 화면(GUI)` 표시 앞까지(엔진)** + `PAGE = r'''page.html'''` + `tail.py`.
→ 엔진(영상 처리)을 고치면 PC 파일을 고친 뒤 `python pc_web/build_web.py`를 실행해 WEB도 갱신.

## 4. 공통 규칙

- 설정 파일: 프로그램 폴더의 `highlight_editor_settings.json` (theme, log_dir, ffmpeg_dir). PC·WEB 공유.
- 편집 로그(①하이라이트 탭만): JSON, `"kind": "basketball-highlight-log"`, 기본 이름 `YYMMDD_원본영상이름.json`. 세 버전이 같은 형식.
  - MOBILE APP은 저장 위치를 매번 직접 고름(안드로이드 저장 창). 사용자가 이 방식을 유지하기로 함.
- 자막 위치 6가지(POSITIONS), 비율 1:1 / 4:3 / 16:9, 저장 비율은 구간들 중 가장 많이 쓴 비율로 자동.

## 5. 디자인 (테마 A "스카이 팝" + 영역별 색)

- 라이트/다크/자동 전환 버튼, 선택은 설정 파일에 저장. 자동 = 윈도우 앱 색상 모드.
- 영역 색: 영상=파랑, 메인자막·합치기 방식=보라, 득점 목록·합칠 목록=청록, 지울 목록=빨강, 미리보기=하늘, 저장=진보라. 카드 위 색 띠 + 번호 배지. 탭 번호 ①주황 ②빨강 ③청록.
- 조절 버튼은 **버튼끼리 색 단계**(버튼 안 위아래 그라데이션 아님!): 비율 16:9→4:3→1:1, 확대 1x→3x, 재생 시간 ±1초 밝게→±5초 진하게, 배속 0.5x→2x 버튼. 선택값은 ✓ + 굵은 테두리. 재생/정지는 주황.
- 비활성 버튼은 회색 대신 원래 색을 흐리게.
- PC 구현: `THEME_MAP`(예전 색→라이트/다크), `THEME_TOK`(@토큰@), `themed()`, `EXTRA_STYLE`, `decorate_ui()`(화면 생성 후 배지·버튼 이름·배속 버튼을 붙임).
- WEB 구현: `page.html`의 CSS 변수(`:root`, `html[data-theme=dark]`), 서버가 `__THEME__`를 넣어 줌.

## 6. MOBILE APP

- Media3 Transformer 1.5.1로 편집. 하이라이트·합치기는 HDR을 일반(SDR)로 바꿔 H.264 저장, 컷 편집은 원본 형식 유지. 결과는 갤러리 Movies/농구하이라이트.
- 화면: 영상 크게 + 아래 고정 버튼(득점 시작/종료/저장 ▸) + 목록은 버튼 바로 위부터 쌓이고 넘치면 위로 스크롤 + [저장 ▸] 화면. ②구간 삭제도 같은 구성.
- 미적용: ③합치기 화면을 같은 구성으로 바꾸는 시안은 승인 대기(코딩 전). 부드럽게 전환(디졸브)은 미지원.
- 빌드: main에 푸시하면 GitHub Actions가 APK를 만들어 Releases(build-N)에 올림. 서명 키는 `app/debug.keystore` 고정(덮어 설치 가능). `pc_web/`이나 `*.md`만 바뀌면 빌드하지 않음.

## 7. 아직 확인 못 한 것 / 보류

- **PC: 최근 색상 변경(`decorate_ui`: 번호 배지, 버튼 색 단계, 배속 버튼)은 실제로 실행해 본 적이 없음.** 이 PC에서 먼저 실행해 화면을 확인할 것.
- PC·MOBILE 사이 로그 파일 주고받기는 실제로 시험해 보지 않음.
- 보류: Real-ESRGAN AI 선명화 (집 PC 그래픽 성능 문제로 사용자가 미룸).

## 8. 점검 방법

- PC: `python pc_web/highlight_editor_qt.pyw` 실행 후 화면 확인 (PySide6, FFmpeg 필요).
- WEB: `python pc_web/tests/test_web.py` → `pc_web/tests/out/`에 탭①②③ 라이트·다크 캡처.
- MOBILE APP: 푸시 후 Actions 빌드 성공 확인 → Releases의 APK를 휴대폰에 설치해 사용자가 확인.
