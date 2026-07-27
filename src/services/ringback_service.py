"""통화 연결음(Ringback) 서비스.

기능:
- ringback_settings DB CRUD
- Suno API(sunoapi.org) 음원 생성 및 폴링
- MP3 다운로드·로컬 캐시
- LLM 가사 자동 생성 (페르소나 KB 참조)
- 스타일 태그 자동 생성

Suno ``callBackUrl`` (공식: https://docs.sunoapi.org/suno-api/generate-music):

- **브라우저 → 이 PBX** (`/api/ringback/generate-music`, 착신 제어 저장 등): JSON에
  ``callBackUrl`` 필드를 넣지 않는다. (운영 URL은 서버 설정으로 통일.)
- **이 PBX → api.sunoapi.org** ``POST /api/v1/generate``: 요청 본문에 반드시
  ``callBackUrl``(공개 HTTPS)을 넣으며, 완료 시 Suno가 해당 URL로 POST 콜백한다.
  동일 필드명 ``callBackUrl`` (camelCase, OpenAPI 필수).

환경변수:
    SUNO_API_KEY           : sunoapi.org API 키
    SUNO_API_BASE          : API 베이스 URL (기본 https://api.sunoapi.org)
    SUNO_MODEL             : 모델 버전 (기본 V4_5)
    SUNO_CALLBACK_URL      : Suno generate 필수 callBackUrl (전체 URL)
    PUBLIC_API_BASE_URL    : 공개 API 베이스(ngrok 등). ringback.public_api_base_url 과 동등;
                             …/api/ringback/suno-callback 이 자동으로 붙음
    ringback.use_ngrok_tunnel (config.yaml): ``true`` 이면 ngrok 로컬 API에서 공개 베이스 자동 조회
    ringback.ngrok_local_api_url : 기본 ``http://127.0.0.1:4040`` (에이전트 API 베이스)
    RINGBACK_USE_NGROK_TUNNEL / RINGBACK_NGROK_LOCAL_API_URL : (선택) 환경변수로 동일 값 오버라이드
"""

from __future__ import annotations

import os
import random
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger(__name__)

# ── 설정 읽기 ────────────────────────────────────────────────────────────────


def ringback_config_yaml_path() -> str:
    """``sip-pbx/config/config.yaml`` (프로젝트 루트 기준) 절대 경로."""
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.yaml")
    )


def ringback_config_load_diag() -> dict[str, Any]:
    """Suno 콜백 미설정 원인 점검용 — 파일 유무·``ringback`` 섹션 키."""
    path = ringback_config_yaml_path()
    exists = os.path.isfile(path)
    keys: list[str] = []
    if exists:
        try:
            import yaml

            with open(path, "r", encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
            rb = doc.get("ringback") or {}
            if isinstance(rb, dict):
                keys = list(rb.keys())[:40]
        except Exception as e:
            keys = [f"<yaml_error:{e}>"]
    return {
        "config_yaml_path": path,
        "config_yaml_exists": exists,
        "ringback_section_keys": keys,
    }


def _cfg() -> dict:
    try:
        import yaml

        cfg_path = ringback_config_yaml_path()
        with open(cfg_path, "r", encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}).get("ringback", {})
    except Exception:
        return {}


def _suno_api_key() -> str:
    return os.environ.get("SUNO_API_KEY") or _cfg().get("suno_api_key", "")


def _suno_api_base() -> str:
    return (
        os.environ.get("SUNO_API_BASE")
        or _cfg().get("suno_api_base", "https://api.sunoapi.org")
    ).rstrip("/")


def _suno_model() -> str:
    return os.environ.get("SUNO_MODEL") or _cfg().get("suno_model", "V4_5")


def _reject_localhost_callback_host(url: str) -> None:
    """Suno 측에서 도달할 수 없는 주소는 거절 (문서: 공개 URL 필수)."""
    try:
        p = urlparse(url)
        h = (p.hostname or "").lower()
    except Exception:
        raise ValueError("callBackUrl 파싱에 실패했습니다.") from None
    if h in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
        raise ValueError(
            "callBackUrl 호스트는 localhost/127.0.0.1 일 수 없습니다. "
            "Suno는 인터넷에서 POST 하므로 ngrok 등 공개 HTTPS 베이스가 필요합니다."
        )


def _yaml_truthy(val: Any) -> bool:
    """config/환경에서 불리언에 가까운 값 해석."""
    if val is True:
        return True
    if val is False or val is None:
        return False
    s = str(val).strip().lower()
    if not s:
        return False
    return s in ("1", "true", "yes", "on")


def _use_ngrok_tunnel_enabled() -> bool:
    """``ringback.use_ngrok_tunnel`` (config) 또는 ``RINGBACK_USE_NGROK_TUNNEL`` (env) 중 하나라도 참이면 True."""
    return _yaml_truthy(_cfg().get("use_ngrok_tunnel")) or _yaml_truthy(
        os.environ.get("RINGBACK_USE_NGROK_TUNNEL")
    )


def _ngrok_local_api_base_url() -> str:
    """ngrok 에이전트 로컬 API 베이스 (env 우선, 그다음 config, 기본 4040)."""
    env_u = (os.environ.get("RINGBACK_NGROK_LOCAL_API_URL") or "").strip()
    if env_u:
        return env_u.rstrip("/")
    cfg_u = (_cfg().get("ngrok_local_api_url") or "").strip()
    if cfg_u:
        return cfg_u.rstrip("/")
    return "http://127.0.0.1:4040"


def _try_public_base_from_ngrok_local_api() -> tuple[str | None, dict[str, Any]]:
    """ngrok 에이전트 로컬 API(기본 ``127.0.0.1:4040``)에서 공개 origin 을 가져온다.

    ``ringback.use_ngrok_tunnel`` 또는 ``RINGBACK_USE_NGROK_TUNNEL`` 이 참일 때만 시도한다.
    """
    if not _use_ngrok_tunnel_enabled():
        return None, {
            "ngrok_tunnel_enabled": False,
            "use_ngrok_tunnel_config": _yaml_truthy(_cfg().get("use_ngrok_tunnel")),
            "use_ngrok_tunnel_env": _yaml_truthy(os.environ.get("RINGBACK_USE_NGROK_TUNNEL")),
        }
    api_base = _ngrok_local_api_base_url()
    list_url = f"{api_base}/api/tunnels"
    diag: dict[str, Any] = {
        "ngrok_tunnel_enabled": True,
        "ngrok_local_api_url": list_url,
    }
    try:
        import json
        import urllib.request

        req = urllib.request.Request(list_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        diag["ngrok_fetch_error"] = str(e)[:240]
        diag["ngrok_fetch_error_type"] = type(e).__name__
        logger.info("ngrok_local_api_fetch_failed", **diag)
        return None, diag

    tunnels = doc.get("tunnels") if isinstance(doc, dict) else None
    if not isinstance(tunnels, list):
        diag["ngrok_tunnel_found"] = False
        return None, diag

    https_urls: list[str] = []
    http_urls: list[str] = []
    for t in tunnels:
        if not isinstance(t, dict):
            continue
        pu = (t.get("public_url") or "").strip()
        if pu.startswith("https://"):
            https_urls.append(pu)
        elif pu.startswith("http://"):
            http_urls.append(pu)

    chosen = https_urls[0] if https_urls else (http_urls[0] if http_urls else None)
    if not chosen:
        diag["ngrok_tunnel_found"] = False
        return None, diag

    p = urlparse(chosen)
    origin = f"{p.scheme}://{p.netloc}".rstrip("/")
    diag["ngrok_tunnel_found"] = True
    diag["ngrok_public_host"] = p.netloc or None
    diag["ngrok_public_scheme"] = p.scheme or None
    logger.info("ngrok_local_api_tunnel_resolved", **diag)
    return origin, diag


def ensure_suno_generation_prerequisites() -> None:
    """Suno ``/generate`` 호출 전제(API 키·callBackUrl). 미충족 시 ``ValueError``."""
    if not (_suno_api_key() or "").strip():
        msg = (
            "SUNO_API_KEY가 설정되지 않았습니다. config.yaml의 ringback.suno_api_key 또는 "
            "환경변수 SUNO_API_KEY를 설정하세요."
        )
        logger.warning("suno_prerequisite_missing_api_key", note=msg)
        raise ValueError(msg)
    try:
        _suno_callback_url()
    except ValueError as e:
        diag = ringback_config_load_diag()
        logger.warning(
            "suno_prerequisite_callback_url",
            error=str(e),
            suno_callback_url_env=bool((os.environ.get("SUNO_CALLBACK_URL") or "").strip()),
            public_api_base_url_env=bool((os.environ.get("PUBLIC_API_BASE_URL") or "").strip()),
            **diag,
        )
        raise


def _suno_callback_url() -> str:
    """Suno ``POST /api/v1/generate`` JSON 의 ``callBackUrl`` 값 (서버 env/config 전용).

    우선순위:

    1. ``SUNO_CALLBACK_URL`` 환경변수 (전체 URL)
    2. ``config.yaml`` ``ringback.suno_callback_url``
    3. ``ringback.public_api_base_url`` 또는 ``PUBLIC_API_BASE_URL`` + ``/api/ringback/suno-callback``
    4. (선택) ``ringback.use_ngrok_tunnel`` (또는 ``RINGBACK_USE_NGROK_TUNNEL``) + ngrok ``/api/tunnels`` 로 공개 베이스 조회

    공식: https://docs.sunoapi.org/suno-api/generate-music-callbacks
    """
    url: str | None = None
    ngrok_diag: dict[str, Any] = {}

    direct = (os.environ.get("SUNO_CALLBACK_URL") or "").strip()
    if direct:
        url = direct
    else:
        cfg = _cfg()
        u = (cfg.get("suno_callback_url") or "").strip()
        if u:
            url = u
        else:
            base = (
                (cfg.get("public_api_base_url") or "")
                or (os.environ.get("PUBLIC_API_BASE_URL") or "")
            ).strip().rstrip("/")
            if base:
                url = f"{base}/api/ringback/suno-callback"
            else:
                ngrok_base, ngrok_diag = _try_public_base_from_ngrok_local_api()
                if ngrok_base:
                    url = f"{ngrok_base}/api/ringback/suno-callback"
                    cb_p = urlparse(url)
                    logger.info(
                        "suno_callback_url_from_ngrok",
                        callBackUrl_scheme=cb_p.scheme or None,
                        callBackUrl_netloc=cb_p.netloc or None,
                    )
                else:
                    msg = (
                        "[PBX 사전 검사 400] Suno ``generate`` 에 넣을 callBackUrl 을 만들 수 없습니다 "
                        "(아직 api.sunoapi.org 까지 요청이 가지 않음). "
                        "서버에서 다음 중 하나를 설정하세요: "
                        "① 환경변수 SUNO_CALLBACK_URL(전체 URL), "
                        "② config.yaml ``ringback.suno_callback_url``, "
                        "③ ``ringback.public_api_base_url`` 또는 환경변수 PUBLIC_API_BASE_URL + 자동 경로 "
                        "``/api/ringback/suno-callback``, "
                        "④ 로컬 개발: ``ngrok http <포트>`` 실행 후 config ``ringback.use_ngrok_tunnel: true`` "
                        "(선택 ``ringback.ngrok_local_api_url`` 또는 환경변수 ``RINGBACK_*``). "
                        "Suno 콜백 규격: https://docs.sunoapi.org/suno-api/generate-music-callbacks"
                    )
                    diag = ringback_config_load_diag()
                    logger.warning(
                        "suno_callback_url_missing",
                        has_config_suno_callback=bool((cfg.get("suno_callback_url") or "").strip()),
                        has_config_public_base=bool((cfg.get("public_api_base_url") or "").strip()),
                        use_ngrok_tunnel_config=_yaml_truthy(cfg.get("use_ngrok_tunnel")),
                        use_ngrok_tunnel_env=_yaml_truthy(os.environ.get("RINGBACK_USE_NGROK_TUNNEL")),
                        suno_callback_url_env=bool((os.environ.get("SUNO_CALLBACK_URL") or "").strip()),
                        public_api_base_url_env=bool((os.environ.get("PUBLIC_API_BASE_URL") or "").strip()),
                        ngrok_local_api_tried=bool(ngrok_diag.get("ngrok_tunnel_enabled")),
                        ngrok_tunnel_found=bool(ngrok_diag.get("ngrok_tunnel_found")),
                        note="PBX→Suno POST JSON 에 callBackUrl 포함(이 함수 결과).",
                        **diag,
                        **{k: v for k, v in ngrok_diag.items() if k not in diag},
                    )
                    raise ValueError(msg)

    assert url is not None
    if not url.startswith("http://") and not url.startswith("https://"):
        bad = (url or "")[:120]
        logger.warning("suno_callback_url_invalid_scheme", url_preview=bad)
        raise ValueError("callBackUrl은 http:// 또는 https:// 로 시작하는 전체 URL이어야 합니다.")
    _reject_localhost_callback_host(url)
    return url


def _audio_cache_dir() -> str:
    d = os.environ.get("RINGBACK_CACHE_DIR") or _cfg().get("audio_cache_dir", "./data/ringback")
    Path(d).mkdir(parents=True, exist_ok=True)
    return d


# ── DB CRUD ──────────────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm_vg(raw: str) -> str:
    """Suno vocalGender: m 또는 f."""
    c = (raw or "m").strip().lower()[:1]
    return c if c in ("m", "f") else "m"


def get_settings(owner: str) -> dict | None:
    from src.booking.database import get_connection
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM ringback_settings WHERE owner = ?", (owner,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_settings(owner: str, data: dict) -> None:
    """ringback_settings UPSERT.

    ``data``에 일부 키만 있어도 된다. 기존 행과 병합한 뒤 INSERT 하므로
    ``NOT NULL`` 컬럼에 NULL이 들어가 500이 나는 일을 막는다
    (예: ``generate_music`` 이 ``suno_task_id`` 만 갱신).
    """
    from src.booking.database import get_db

    _defaults: dict[str, Any] = {
        "greeting_text": "",
        "greeting_audio_path": "",
        "suno_task_id": "",
        "suno_audio_url": "",
        "suno_audio_path": "",
        "suno_lyrics": "",
        "suno_style": "",
        "suno_title": "",
        "suno_vocal_gender": "m",
        "suno_duration_target": 60,
        "enabled_greeting": 0,
        "enabled_ringback": 0,
    }

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM ringback_settings WHERE owner = ?", (owner,)
        ).fetchone()
        if row:
            merged: dict[str, Any] = dict(row)
        else:
            merged = {"owner": owner, **_defaults}
        for k, v in data.items():
            if v is not None:
                merged[k] = v

        eg = 1 if merged.get("enabled_greeting") else 0
        er = 1 if merged.get("enabled_ringback") else 0
        dur = int(merged.get("suno_duration_target") or 60)

        conn.execute(
            """
            INSERT INTO ringback_settings
                (owner, greeting_text, greeting_audio_path,
                 suno_task_id, suno_audio_url, suno_audio_path,
                 suno_lyrics, suno_style, suno_title,
                 suno_vocal_gender, suno_duration_target,
                 enabled_greeting, enabled_ringback, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner) DO UPDATE SET
                greeting_text        = COALESCE(excluded.greeting_text,        ringback_settings.greeting_text),
                greeting_audio_path  = COALESCE(excluded.greeting_audio_path,  ringback_settings.greeting_audio_path),
                suno_task_id         = COALESCE(excluded.suno_task_id,         ringback_settings.suno_task_id),
                suno_audio_url       = COALESCE(excluded.suno_audio_url,       ringback_settings.suno_audio_url),
                suno_audio_path      = COALESCE(excluded.suno_audio_path,      ringback_settings.suno_audio_path),
                suno_lyrics          = COALESCE(excluded.suno_lyrics,          ringback_settings.suno_lyrics),
                suno_style           = COALESCE(excluded.suno_style,           ringback_settings.suno_style),
                suno_title           = COALESCE(excluded.suno_title,           ringback_settings.suno_title),
                suno_vocal_gender    = COALESCE(excluded.suno_vocal_gender,    ringback_settings.suno_vocal_gender),
                suno_duration_target = COALESCE(excluded.suno_duration_target, ringback_settings.suno_duration_target),
                enabled_greeting     = COALESCE(excluded.enabled_greeting,     ringback_settings.enabled_greeting),
                enabled_ringback     = COALESCE(excluded.enabled_ringback,     ringback_settings.enabled_ringback),
                updated_at           = excluded.updated_at
            """,
            (
                owner,
                merged.get("greeting_text", ""),
                merged.get("greeting_audio_path", ""),
                merged.get("suno_task_id", ""),
                merged.get("suno_audio_url", ""),
                merged.get("suno_audio_path", ""),
                merged.get("suno_lyrics", ""),
                merged.get("suno_style", ""),
                merged.get("suno_title", ""),
                _norm_vg(str(merged.get("suno_vocal_gender") or "m")),
                dur,
                eg,
                er,
                _now_str(),
            ),
        )
    logger.info("ringback_settings_saved", owner=owner)


# ── ringback_music_items CRUD ─────────────────────────────────────────────────

def save_music_items(owner: str, task_id: str, items: list[dict]) -> None:
    """생성 완료된 Suno 음원 아이템들을 DB에 저장한다.

    같은 task_id의 기존 행은 삭제 후 재삽입(upsert 대신 DELETE+INSERT).
    """
    from src.booking.database import get_db
    with get_db() as conn:
        conn.execute(
            "DELETE FROM ringback_music_items WHERE owner = ? AND task_id = ?",
            (owner, task_id),
        )
        for idx, item in enumerate(items):
            conn.execute(
                """
                INSERT INTO ringback_music_items
                    (owner, task_id, index_in_task, audio_url, local_path, title, duration, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    owner,
                    task_id,
                    idx,
                    item.get("audio_url", ""),
                    item.get("local_path", ""),
                    item.get("title", ""),
                    float(item.get("duration", 0) or 0),
                ),
            )
    logger.info("ringback_music_items_saved", owner=owner, task_id=task_id, count=len(items))


def get_music_items(owner: str, limit: int = 20) -> list[dict]:
    """owner의 음원 목록을 최신순으로 반환한다."""
    from src.booking.database import get_connection
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, owner, task_id, index_in_task, audio_url, local_path,
                   title, duration, is_active, created_at
            FROM ringback_music_items
            WHERE owner = ?
            ORDER BY created_at DESC, index_in_task ASC
            LIMIT ?
            """,
            (owner, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def set_active_music_item(owner: str, item_id: int) -> None:
    """특정 음원을 현재 사용 중으로 설정한다 (다른 항목은 비활성)."""
    from src.booking.database import get_db
    with get_db() as conn:
        conn.execute(
            "UPDATE ringback_music_items SET is_active = 0 WHERE owner = ?",
            (owner,),
        )
        conn.execute(
            "UPDATE ringback_music_items SET is_active = 1 WHERE id = ? AND owner = ?",
            (item_id, owner),
        )
    logger.info("ringback_active_item_set", owner=owner, item_id=item_id)


def delete_music_item(item_id: int, owner: str) -> None:
    """음원 아이템을 DB에서 삭제한다."""
    from src.booking.database import get_db
    with get_db() as conn:
        conn.execute(
            "DELETE FROM ringback_music_items WHERE id = ? AND owner = ?",
            (item_id, owner),
        )
    logger.info("ringback_music_item_deleted", item_id=item_id, owner=owner)


def _owner_from_ringback_settings_by_suno_task_id(task_id: str) -> str | None:
    """``ringback_settings`` 에서 ``suno_task_id`` 가 일치하는 owner (전역 링백 생성용)."""
    from src.booking.database import get_connection

    tid = (task_id or "").strip()
    if not tid:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT owner FROM ringback_settings WHERE TRIM(COALESCE(suno_task_id, '')) = ? LIMIT 1",
            (tid,),
        ).fetchone()
        return str(row["owner"]) if row else None
    finally:
        conn.close()


def _items_from_suno_callback_track_list(tracks: Any) -> list[dict[str, Any]]:
    """Suno 콜백 ``data.data`` 배열을 ``save_music_items`` / 폴링과 동일 형태로 정규화."""
    if not isinstance(tracks, list):
        return []
    out: list[dict[str, Any]] = []
    for it in tracks:
        if not isinstance(it, dict):
            continue
        au = str(it.get("audio_url") or "").strip()
        if not au:
            continue
        out.append(
            {
                "id": it.get("id", ""),
                "audio_url": au,
                "stream_audio_url": str(it.get("stream_audio_url") or "").strip(),
                "title": it.get("title", ""),
                "duration": it.get("duration", 0),
            }
        )
    return out


async def _finalize_suno_generation_success(
    owner: str,
    task_id: str,
    items: list[dict[str, Any]],
    ringback_assignment_id: str | None,
) -> None:
    """Suno 생성 완료 후 DB·로컬 MP3·WS — ``poll_and_notify`` 완료 분기와 동일."""
    save_music_items(owner, task_id, items)
    emit_ws = True
    if ringback_assignment_id:
        from src.call_control import db as cc_db

        row = cc_db.get_ringback_schedule_assignment(ringback_assignment_id)
        if not row or str(row.get("suno_task_id") or "") != str(task_id):
            logger.info(
                "ringback_suno_finalize_stale_assignment",
                assignment_id=ringback_assignment_id,
                task_id=task_id,
                row_tid=(row.get("suno_task_id") if row else None),
            )
            emit_ws = False
        else:
            audio_url = ""
            if items and isinstance(items[0], dict):
                audio_url = str(items[0].get("audio_url") or "").strip()
            if not audio_url:
                cc_db.update_ringback_schedule_assignment(
                    ringback_assignment_id,
                    {"suno_generation_status": "failed"},
                )
                err = "완료 응답에 audio_url 없음"
                try:
                    from src.websocket.server import emit_ringback_music_failed

                    await emit_ringback_music_failed(owner=owner, task_id=task_id, error=err)
                except Exception as ws_err:
                    logger.warning("ringback_ws_failed_emit_error", error=str(ws_err))
                logger.warning("ringback_finalize_no_audio_url", task_id=task_id)
                return
            stem = f"{owner}_rsa_{ringback_assignment_id.replace('-', '')}"[:120]
            try:
                local_path = await download_and_cache_audio(owner, audio_url, 0, file_stem=stem)
            except Exception as dl_err:
                logger.exception("ringback_finalize_download_failed", error=str(dl_err))
                cc_db.update_ringback_schedule_assignment(
                    ringback_assignment_id,
                    {"suno_generation_status": "failed"},
                )
                try:
                    from src.websocket.server import emit_ringback_music_failed

                    await emit_ringback_music_failed(
                        owner=owner,
                        task_id=task_id,
                        error=f"MP3 저장 실패: {dl_err}",
                    )
                except Exception as ws_err:
                    logger.warning("ringback_ws_failed_emit_error", error=str(ws_err))
                return
            cc_db.update_ringback_schedule_assignment(
                ringback_assignment_id,
                {
                    "suno_task_id": task_id,
                    "suno_audio_url": audio_url,
                    "suno_audio_path": local_path,
                    "suno_generation_status": "complete",
                },
            )
    else:
        save_settings(owner, {"suno_task_id": task_id})

    if emit_ws:
        try:
            from src.websocket.server import emit_ringback_music_ready

            await emit_ringback_music_ready(owner=owner, items=items, task_id=task_id)
        except Exception as ws_err:
            logger.warning("ringback_ws_emit_failed", error=str(ws_err))

    logger.info(
        "ringback_suno_generation_finalized",
        owner=owner,
        task_id=task_id,
        count=len(items),
        assignment_id=ringback_assignment_id,
    )


async def _fail_suno_generation_from_callback(task_id: str, error_msg: str) -> None:
    """콜백 실패 시 할당 행·WS 처리."""
    from src.call_control import db as cc_db

    owner_out = ""
    row = cc_db.get_ringback_schedule_assignment_by_suno_task_id(task_id)
    if row and str(row.get("suno_task_id") or "") == str(task_id):
        owner_out = str(row.get("owner") or "")
        st = str(row.get("suno_generation_status") or "").lower()
        if st == "pending":
            cc_db.update_ringback_schedule_assignment(
                str(row["id"]),
                {"suno_generation_status": "failed"},
            )
    if not owner_out:
        owner_out = _owner_from_ringback_settings_by_suno_task_id(task_id) or ""
    if owner_out:
        try:
            from src.websocket.server import emit_ringback_music_failed

            await emit_ringback_music_failed(owner=owner_out, task_id=task_id, error=error_msg[:500])
        except Exception:
            pass


async def process_suno_music_callback_payload(payload: Any) -> None:
    """Suno ``callBackUrl`` POST 본문 처리 — 완료 시 로컬 저장·DB·WebSocket.

    Suno 스키마: ``code``, ``msg``, ``data.task_id``, ``data.callbackType``, ``data.data``(곡 배열).
    """
    if not isinstance(payload, dict):
        logger.warning("ringback_suno_callback_invalid_payload", type_name=type(payload).__name__)
        return

    cb_outer = payload.get("data")
    if not isinstance(cb_outer, dict):
        cb_outer = {}

    code = payload.get("code")
    msg = str(payload.get("msg") or "")
    task_id = str(cb_outer.get("task_id") or "").strip()
    callback_type = str(cb_outer.get("callbackType") or "").strip().lower()
    tracks_raw = cb_outer.get("data")

    logger.info(
        "ringback_suno_callback_dispatch",
        code=code,
        msg_preview=msg[:200] if msg else None,
        task_id=task_id or None,
        callback_type=callback_type or None,
        tracks_is_list=isinstance(tracks_raw, list),
    )

    if not task_id:
        logger.warning("ringback_suno_callback_no_task_id")
        return

    if code != 200 or callback_type == "error":
        err = msg or f"Suno 콜백 실패(code={code})"
        await _fail_suno_generation_from_callback(task_id, err)
        logger.warning("ringback_suno_callback_error_branch", task_id=task_id, code=code, detail=err[:300])
        return

    if callback_type in ("first", "text"):
        logger.info("ringback_suno_callback_ignored_early", task_id=task_id, callback_type=callback_type)
        return

    if callback_type and callback_type != "complete":
        logger.info("ringback_suno_callback_ignored_type", task_id=task_id, callback_type=callback_type)
        return

    items = _items_from_suno_callback_track_list(tracks_raw)
    if not items:
        logger.warning(
            "ringback_suno_callback_no_audio_items",
            task_id=task_id,
            callback_type=callback_type or None,
        )
        return

    from src.call_control import db as cc_db

    row = cc_db.get_ringback_schedule_assignment_by_suno_task_id(task_id)
    if row:
        owner = str(row.get("owner") or "")
        ass_id = str(row.get("id") or "")
        st = str(row.get("suno_generation_status") or "").lower()
        if st == "complete":
            logger.info("ringback_suno_callback_idempotent_skip", task_id=task_id, reason="already_complete")
            return
    else:
        owner = _owner_from_ringback_settings_by_suno_task_id(task_id) or ""
        ass_id = None
        if not owner:
            logger.warning("ringback_suno_callback_unknown_task", task_id=task_id)
            return

    await _finalize_suno_generation_success(owner, task_id, items, ass_id)
    logger.info(
        "ringback_suno_callback_applied",
        task_id=task_id,
        assignment_id=ass_id,
        item_count=len(items),
        owner=owner,
    )


def get_music_item_local_path(owner: str, item_id: int) -> str | None:
    """ringback_music_items 의 로컬 MP3 경로(존재하는 파일만)."""
    from src.booking.database import get_connection

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT local_path FROM ringback_music_items WHERE id = ? AND owner = ?",
            (item_id, owner),
        ).fetchone()
        if not row:
            return None
        p = (dict(row).get("local_path") or "").strip()
        return p if p and os.path.isfile(p) else None
    finally:
        conn.close()


def resolve_ringback_segment(owner: str) -> dict[str, Any]:
    """스케줄 할당 목록 순서대로 매칭되는 통화 연결음 구간.

    Returns:
        dict: kind ``mp3`` | ``tts`` | ``none``, path/text, assignment_id, reason
    """
    from datetime import timezone

    from src.call_control import db as cc_db
    from src.call_control.routing_engine import schedule_active_now

    now = datetime.now(timezone.utc)
    for row in cc_db.list_ringback_schedule_assignments(owner):
        if not row.get("enabled"):
            continue
        sid = row.get("schedule_id")
        if sid and str(sid).strip():
            if not schedule_active_now(str(sid), now):
                continue
        mode = (row.get("generation_mode") or "suno").strip().lower()
        aid = row.get("id")
        if mode == "tts":
            wav = (row.get("tts_audio_path") or "").strip()
            if wav and os.path.isfile(wav):
                return {
                    "kind": "mp3",
                    "path": wav,
                    "assignment_id": aid,
                    "reason": f"schedule_assignment:tts_wav:{aid}",
                }
            # TTS 통화 연결음은 설정 저장 시 WAV 사전 생성(링 중 실시간 합성 아님)
            continue
        p = (row.get("suno_audio_path") or "").strip()
        if p and os.path.isfile(p):
            return {
                "kind": "mp3",
                "path": p,
                "assignment_id": aid,
                "reason": f"schedule_assignment:suno:{aid}",
            }

    st = get_settings(owner)
    if not st:
        return {"kind": "none", "reason": "no_settings", "path": None, "text": None, "assignment_id": None}
    fb = (st.get("suno_audio_path") or "").strip()
    if fb and os.path.isfile(fb):
        return {
            "kind": "mp3",
            "path": fb,
            "assignment_id": None,
            "reason": "ringback_settings",
        }
    return {"kind": "none", "reason": "no_local_audio", "path": None, "text": None, "assignment_id": None}


def get_effective_ringback_settings_for_player(owner: str) -> dict[str, Any] | None:
    """SIP 링백 플레이어용 설정: DB 행이 없어도 스케줄 MP3만 있으면 합성한다.

    ``ringback_settings`` 에 owner 행이 없으면 기존 로직은 즉시 스킵했지만,
    :func:`resolve_ringback_segment` 는 ``ringback_schedule_assignments`` 등으로
    로컬 MP3를 고를 수 있다. 이 경우 ``enabled_ringback=1`` 인 최소 dict 를
    반환해 연결음만 재생한다.
    """
    own = (owner or "").strip()
    if not own:
        return None
    st = get_settings(own)
    if st:
        return dict(st)
    seg = resolve_ringback_segment(own)
    if seg.get("kind") == "mp3" and seg.get("path"):
        path = str(seg["path"]).strip()
        if path and os.path.isfile(path):
            logger.info(
                "ringback_effective_settings_synthesized",
                owner=own,
                segment_reason=seg.get("reason"),
                path_preview=path[:120],
            )
            return {
                "owner": own,
                "enabled_greeting": 0,
                "enabled_ringback": 1,
                "greeting_text": "",
            }
    return None


def resolve_ringback_mp3_path_for_call(owner: str) -> tuple[str | None, str]:
    """하위 호환: MP3 경로만 필요할 때 ``resolve_ringback_segment`` 위임."""
    seg = resolve_ringback_segment(owner)
    if seg.get("kind") == "mp3" and seg.get("path"):
        return str(seg["path"]), str(seg.get("reason") or "mp3")
    return None, str(seg.get("reason") or "no_mp3")


# ── Suno API ─────────────────────────────────────────────────────────────────

def _suno_json_dict(resp_body: Any) -> dict[str, Any]:
    """Suno HTTP 응답 JSON이 dict가 아니면 빈 dict."""
    return resp_body if isinstance(resp_body, dict) else {}


def _suno_inner_object(payload: dict[str, Any]) -> dict[str, Any]:
    """payload['data']가 dict일 때만 반환. null 이면 {} (dict.get('data', {})는 null일 때 None 반환)."""
    raw = payload.get("data")
    return raw if isinstance(raw, dict) else {}


async def generate_suno_music(
    lyrics: str,
    style: str,
    title: str,
    vocal_gender: str = "m",
    duration_target: int = 60,
) -> dict[str, Any]:
    """Suno ``POST /api/v1/generate`` 호출 — 응답의 ``taskId`` 반환.

    공식 스키마(필수): ``customMode``, ``instrumental``, ``model``, ``callBackUrl``.
    커스텀 모드·보컬 곡: ``style``, ``title``, ``prompt``(가사) 필요.
    콜백 형식: https://docs.sunoapi.org/suno-api/generate-music-callbacks
    """
    import httpx

    api_key = _suno_api_key()
    if not api_key:
        raise ValueError("SUNO_API_KEY가 설정되지 않았습니다. config.yaml 또는 환경변수를 확인하세요.")

    # 목표 시간에 맞게 가사에 힌트 추가
    duration_hint = f"under {duration_target} seconds" if duration_target <= 60 else f"about {duration_target} seconds"
    full_style = f"{style}, {duration_hint}" if style else duration_hint

    callback_url = _suno_callback_url()
    payload = {
        "customMode": True,
        "instrumental": False,
        "model": _suno_model(),
        "prompt": lyrics,
        "style": full_style,
        "title": title or "통화 연결음",
        "vocalGender": vocal_gender,  # "m" or "f"
        "callBackUrl": callback_url,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    cb_p = urlparse(callback_url)
    logger.info(
        "suno_generate_outbound",
        endpoint=f"{_suno_api_base()}/api/v1/generate",
        payload_has_callBackUrl=True,
        callBackUrl_scheme=cb_p.scheme or None,
        callBackUrl_netloc=cb_p.netloc or None,
        callBackUrl_path=cb_p.path or None,
        model=payload.get("model"),
        title_len=len((payload.get("title") or "")),
        prompt_len=len((payload.get("prompt") or "")),
        style_len=len((payload.get("style") or "")),
    )

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{_suno_api_base()}/api/v1/generate",
            json=payload,
            headers=headers,
        )

    if resp.status_code != 200:
        logger.error("suno_generate_failed", status=resp.status_code, body=resp.text[:300])
        raise RuntimeError(f"Suno API 오류 {resp.status_code}: {resp.text[:200]}")

    try:
        parsed = resp.json()
    except Exception as je:
        logger.error("suno_generate_json_parse_failed", error=str(je), body=resp.text[:300])
        raise RuntimeError(f"Suno API JSON 파싱 실패: {je}") from je

    data = _suno_json_dict(parsed)
    inner = _suno_inner_object(data)
    task_id = str(inner.get("taskId") or data.get("taskId") or "").strip()
    if not task_id:
        logger.error(
            "suno_generate_no_task_id",
            top_keys=list(data.keys())[:20],
            data_is_none=data.get("data") is None,
            body_preview=resp.text[:400],
        )
        raise RuntimeError(
            "Suno API 응답에 taskId가 없습니다. 응답 형식·크레딧·모델 제한을 확인하세요."
        )
    logger.info("suno_generate_started", task_id=task_id)
    return {"task_id": task_id, "status": "pending"}


async def poll_suno_task(task_id: str) -> dict[str, Any]:
    """Suno 생성 상태를 폴링한다.

    반환:
        status: "pending" | "processing" | "complete" | "failed"
        audio_url: 완료 시 MP3 URL
        stream_audio_url: 스트리밍 URL
        items: 생성된 곡 목록 (2곡)
    """
    import httpx

    api_key = _suno_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{_suno_api_base()}/api/v1/feed/{task_id}",
            headers=headers,
        )

    # Suno feed 는 생성 직후 잠시 404 를 주는 경우가 있어(태스크 인덱싱 지연), 곧바로 실패로 두면
    # 콜백으로는 정상 완료되는데 폴링만 ringback_poll_failed·DB failed·WS 오탐이 난다.
    if resp.status_code == 404:
        logger.info(
            "suno_poll_feed_not_ready",
            task_id=task_id,
            status=404,
            note="feed 404 → pending 유지(다음 폴링에서 재시도)",
        )
        return {"status": "pending", "task_id": task_id}

    if resp.status_code != 200:
        logger.warning("suno_poll_failed", task_id=task_id, status=resp.status_code)
        return {"status": "failed", "error": f"HTTP {resp.status_code}"}

    try:
        parsed = resp.json()
    except Exception:
        return {"status": "failed", "error": "poll JSON 파싱 실패"}

    data = _suno_json_dict(parsed)
    raw_items = data.get("data")
    if raw_items is None:
        items = []
    elif isinstance(raw_items, list):
        items = raw_items
    else:
        items = [raw_items]

    if not items:
        return {"status": "pending", "task_id": task_id}

    # complete 판단: 첫 번째 아이템에 audio_url이 있으면 완료
    first = items[0] if isinstance(items, list) else items
    if isinstance(first, dict) and first.get("audio_url"):
        result_items = [
            {
                "id": it.get("id", ""),
                "audio_url": it.get("audio_url", ""),
                "stream_audio_url": it.get("stream_audio_url", ""),
                "title": it.get("title", ""),
                "duration": it.get("duration", 0),
            }
            for it in (items if isinstance(items, list) else [items])
        ]
        logger.info("suno_poll_complete", task_id=task_id, count=len(result_items))
        return {
            "status": "complete",
            "task_id": task_id,
            "items": result_items,
            "audio_url": result_items[0]["audio_url"],
            "stream_audio_url": result_items[0]["stream_audio_url"],
        }

    return {"status": "processing", "task_id": task_id}


async def download_and_cache_audio(
    owner: str,
    audio_url: str,
    index: int = 0,
    *,
    file_stem: str | None = None,
) -> str:
    """MP3를 다운로드하여 로컬에 저장하고 경로를 반환한다.

    ``file_stem`` 이 있으면 ``{file_stem}{suffix}.mp3`` 로 저장(할당별 파일 분리).
    """
    import httpx

    cache_dir = _audio_cache_dir()
    suffix = f"_{index}" if index else ""
    safe_stem = (file_stem or owner).replace("/", "_").replace("\\", "_")[:120]
    filename = f"{safe_stem}{suffix}.mp3"
    dest = os.path.join(cache_dir, filename)

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(audio_url)
        if resp.status_code != 200:
            raise RuntimeError(f"음원 다운로드 실패: HTTP {resp.status_code}")
        with open(dest, "wb") as f:
            f.write(resp.content)

    logger.info("ringback_audio_cached", owner=owner, path=dest, size=len(resp.content))
    return dest


# ── LLM 가사 자동 생성 ────────────────────────────────────────────────────────

_LYRICS_SYSTEM_PROMPT = """\
당신은 광고 CM송 작사가입니다.
아래 업체 정보를 참고하여 통화 연결음용 CM송 가사를 작성해주세요.

요구사항:
- 재생 시간: {duration}초 이내 (일반적으로 4줄 verse 1개 + 8줄 이하)
- 언어: 한국어
- 형식: [Intro], [Verse], [Chorus] 등 Suno 태그 사용
- 업체의 특징·서비스·분위기를 자연스럽게 담을 것
- 친근하고 따뜻한 톤
- 전화 연결 대기 중 듣기 좋은 밝고 경쾌한 가사
{user_brief_section}

업체 정보:
{persona_info}

가사만 출력하세요. 설명이나 부가 설명 없이 가사 텍스트만."""

_STYLE_CONTEXT_PROMPT = """You are a Suno AI music style tag expert.
Output exactly ONE LINE: comma-separated English tags only (genre, mood, tempo or BPM hint, vocal type, hold music or commercial jingle, length hint).
Rules: no quotes, no JSON, no Korean, no label prefixes, no explanation.

User creative brief (may be Korean — reflect intent in English tags):
{brief}

Lyrics excerpt to match mood and pacing (may be Korean; infer energy and theme):
{lyrics}

Fixed:
- Include exactly one of: male vocal, female vocal → use: {vocal_tag}
- Duration context: {duration_hint}
"""

# `_call_llm` 예외·무키·빈응답 시 반환하는 고정 가사 (페르소나 미반영 아님, LLM 미사용)
_FALLBACK_LYRICS = (
    "[Intro]\n전화 주셔서 감사합니다\n\n"
    "[Verse]\n잠시만 기다려 주세요\n곧 연결해 드리겠습니다\n"
    "소중한 고객님을 위해\n최선을 다하겠습니다\n\n"
    "[Outro]\n감사합니다"
)

# `_call_llm`/`_call_llm_style_line`이 get_llm_client() 싱글턴을 못 구할 때만 쓰는 폴백 모델명.
# [2026-07-27] 예전에는 "gemini-2.0-flash"를 하드코딩했는데 이 계정에서 이미 404로 폐지되어
# 있어 링백 가사/스타일 생성이 항상 실패하고 있었다(Story 6.3 리포트에서 발견). 다른 모든
# LLM 호출 경로(LLMClient)와 동일한 모델을 쓰도록 get_llm_client().model_name을 우선
# 사용하고, 싱글턴이 없는 예외적 상황에서만 이 상수를 쓴다 — 반드시 config.yaml의
# gemini.model 기본값과 동일하게 유지할 것(불일치 시 이 상수도 함께 갱신).
_RINGBACK_LLM_MODEL_FALLBACK = "gemini-2.5-flash"


def _resolve_ringback_llm_client_and_model() -> tuple[Any, str]:
    """다른 LLM 호출 경로와 동일한 client/모델을 재사용한다.

    시스템 전역 `LLMClient` 싱글턴(`factory.get_llm_client()`)이 초기화되어 있으면 그
    `_client`(google.genai.Client)와 `model_name`을 그대로 재사용해, 통화 응대·의도분류 등과
    **완전히 동일한 모델**을 쓰도록 보장한다. 싱글턴이 없는 예외적 컨텍스트(독립 스크립트 등)
    에서만 새 클라이언트를 만들되, 모델명은 `_RINGBACK_LLM_MODEL_FALLBACK`(config.yaml
    gemini.model 기본값과 동일)을 사용한다.
    """
    client: Any = None
    model_name = _RINGBACK_LLM_MODEL_FALLBACK
    try:
        from src.ai_voicebot.factory import get_llm_client

        llm_client = get_llm_client()
        if llm_client is not None:
            client = getattr(llm_client, "_client", None)
            model_name = getattr(llm_client, "model_name", None) or model_name
    except Exception as e:
        logger.debug("ringback_llm_singleton_unavailable", error=str(e))
    return client, model_name


def _is_fallback_lyrics(text: str) -> bool:
    return (text or "").strip() == _FALLBACK_LYRICS.strip()


def _extract_gemini_text(resp: Any) -> str:
    """resp.text 가 비어 있을 때 candidates.parts 에서 본문을 꺼낸다."""
    raw = (getattr(resp, "text", None) or "").strip()
    if raw:
        return raw
    for cand in getattr(resp, "candidates", None) or []:
        content = getattr(cand, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", None) or []:
            tx = getattr(part, "text", None)
            if tx and str(tx).strip():
                return str(tx).strip()
    return ""


async def auto_generate_lyrics(
    owner: str,
    duration_target: int = 60,
    brief: str | None = None,
) -> dict[str, Any]:
    """페르소나·KB를 모아 프롬프트에 넣고 Gemini 로 가사를 생성한다.

    반환 dict:
        lyrics: 생성 텍스트 (LLM 실패 시 고정 폴백과 동일할 수 있음)
        used_llm: True 이면 폴백 문자열이 아닌 모델 출력으로 판단
        used_default_persona: Chroma/KB 에서 블록을 하나도 못 모았을 때
        has_org_persona: 조직 페르소나 블록 포함 여부
        warning: UI/운영자용 안내 (폴백·무키 등)
    """
    owner_key = (owner or "").strip()
    persona_info = await _fetch_persona_info(owner_key)
    has_org = "[조직 페르소나]" in persona_info
    used_default_persona = not (persona_info or "").strip()

    if used_default_persona:
        persona_info = _default_persona(owner_key)
        logger.info(
            "ringback_lyrics_using_default_persona",
            owner=owner_key,
            reason="kb_empty",
        )

    brief_t = (brief or "").strip()
    if brief_t:
        user_brief_section = (
            "\n운영자 추가 요청(반드시 반영 — 톤·소재·강조 메시지):\n"
            f"{brief_t}\n"
        )
    else:
        user_brief_section = ""

    prompt = _LYRICS_SYSTEM_PROMPT.format(
        duration=duration_target,
        persona_info=persona_info,
        user_brief_section=user_brief_section,
    )

    lyrics, llm_err = await _call_llm(prompt)
    used_llm = not _is_fallback_lyrics(lyrics)

    warning: str | None = None
    if not used_llm:
        warning = (
            "LLM 이 결과를 내지 못해 기본 대기 가사가 반환되었습니다. "
            "서버에 GEMINI_API_KEY 또는 GOOGLE_API_KEY 설정·네트워크·모델 응답을 확인하세요."
        )
        if llm_err:
            warning += f" (원인: {llm_err[:200]})"

    logger.info(
        "ringback_lyrics_generated",
        owner=owner_key,
        length=len(lyrics),
        used_llm=used_llm,
        has_org_persona=has_org,
        used_default_persona_block=used_default_persona,
        llm_error_preview=(llm_err[:120] if llm_err else None),
        brief_len=len(brief_t),
    )
    return {
        "lyrics": lyrics,
        "used_llm": used_llm,
        "used_default_persona": used_default_persona,
        "has_org_persona": has_org,
        "warning": warning,
    }


def _default_persona(owner: str) -> str:
    """KB 페르소나 데이터가 없을 때 사용할 기본 업체 정보를 반환한다."""
    return (
        f"업체명: {owner}\n"
        "서비스: 고객 전화 응대 서비스\n"
        "분위기: 친근하고 따뜻한 서비스\n"
        "톤: 밝고 경쾌하며 전문적"
    )


def _internal_api_base() -> str:
    """서버 프로세스 내에서 자기 자신 API를 호출할 때 사용하는 베이스 URL."""
    return (
        os.environ.get("INTERNAL_API_BASE_URL")
        or os.environ.get("API_BASE_URL")
        or "http://127.0.0.1:8000"
    ).rstrip("/")


async def _fetch_persona_info(owner: str) -> str:
    """조직 페르소나(Persona API / Chroma) + KB 지식 문서에서 업체 정보를 수집한다.

    설정 UI의 `/api/persona`에 저장된 조직 페르소나를 **우선** 반영한다.
    기존에는 `/api/knowledge` 카테고리만 조회해 페르소나 설정이 가사에 반영되지 않는 경우가 많았다.
    """
    import httpx

    parts: list[str] = []

    # 1) 조직 페르소나 (설정 > 페르소나, Chroma persona 컬렉션)
    try:
        from src.ai_voicebot.knowledge.persona_service import ensure_persona_service

        svc = await ensure_persona_service()
        if svc:
            persona = await svc.get_persona(owner)
            if persona:
                kw = ", ".join(persona.scope_keywords or [])
                block_lines = [
                    "[조직 페르소나]",
                    f"이름/상호: {persona.name}",
                    f"소개: {persona.description}",
                ]
                if kw:
                    block_lines.append(f"핵심 키워드: {kw}")
                if persona.chitchat_response_template:
                    block_lines.append(f"응답 톤 참고: {persona.chitchat_response_template}")
                parts.append("\n".join(block_lines))
                logger.info(
                    "ringback_org_persona_included",
                    owner=owner,
                    persona_name=persona.name,
                )
    except Exception as e:
        logger.warning("ringback_org_persona_fetch_failed", owner=owner, error=str(e))

    # 2) KB 지식 (인사말·업무 정보 등 보조)
    api_base = _internal_api_base()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            for category in ["greeting_phase1", "greeting", "persona", "business_info"]:
                resp = await client.get(
                    f"{api_base}/api/knowledge",
                    params={"owner": owner, "category": category},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", data) if isinstance(data, dict) else data
                    cat_texts = [
                        item.get("text", "")
                        for item in (items if isinstance(items, list) else [])
                        if item.get("text", "")
                    ]
                    logger.debug(
                        "ringback_persona_kb_fetch",
                        owner=owner,
                        category=category,
                        found=len(cat_texts),
                    )
                    parts.extend(cat_texts[:3])  # 카테고리당 최대 3개
        logger.info(
            "ringback_persona_fetch_done",
            owner=owner,
            total_blocks=len(parts),
            has_org_persona=any(p.startswith("[조직 페르소나]") for p in parts),
        )
    except Exception as e:
        logger.warning("ringback_persona_kb_http_failed", owner=owner, error=str(e))

    return "\n\n".join(parts) if parts else ""


async def _call_llm(prompt: str) -> tuple[str, str | None]:
    """Gemini 로 가사 생성. (가사, 오류시 짧은 메시지) — 실패 시 고정 폴백.

    [2026-07-27] 다른 LLM 호출 경로(LLMClient)와 동일한 client/모델을 재사용하도록 수정 —
    예전에는 "gemini-2.0-flash"를 하드코딩했는데 이 계정에서 이미 404로 폐지되어 있어 항상
    실패하고 있었다(Story 6.3에서 발견). `_resolve_ringback_llm_client_and_model()` 참고.
    """
    client, model_name = _resolve_ringback_llm_client_and_model()

    if client is None:
        from src.common.gemini_api_key import resolve_gemini_api_key

        api_key = resolve_gemini_api_key() or ""
        if not api_key:
            logger.error("ringback_llm_no_api_key", hint="GEMINI_API_KEY 또는 GOOGLE_API_KEY")
            return _FALLBACK_LYRICS, "no_api_key"
        from google import genai

        client = genai.Client(api_key=api_key)

    try:
        resp = await client.aio.models.generate_content(
            model=model_name, contents=prompt
        )
        text = _extract_gemini_text(resp)
        if not text:
            pf = getattr(resp, "prompt_feedback", None)
            logger.error(
                "ringback_llm_empty_response",
                prompt_feedback=str(pf) if pf is not None else None,
            )
            return _FALLBACK_LYRICS, "empty_model_response"
        return text, None
    except Exception as e:
        logger.error("ringback_llm_failed", error=str(e))
        return _FALLBACK_LYRICS, str(e)[:500]


async def _call_llm_style_line(prompt: str) -> tuple[str, str | None]:
    """Suno용 스타일 한 줄. 실패 시 ("", reason).

    [2026-07-27] `_call_llm`과 동일하게 시스템 전역 LLMClient와 동일한 모델을 재사용하도록
    수정(과거 gemini-2.0-flash 하드코딩 404 결함 수정, Story 6.3 참고).
    """
    client, model_name = _resolve_ringback_llm_client_and_model()

    if client is None:
        from src.common.gemini_api_key import resolve_gemini_api_key

        api_key = resolve_gemini_api_key() or ""
        if not api_key:
            logger.error("ringback_style_llm_no_api_key", hint="GEMINI_API_KEY 또는 GOOGLE_API_KEY")
            return "", "no_api_key"
        from google import genai

        client = genai.Client(api_key=api_key)

    try:
        resp = await client.aio.models.generate_content(
            model=model_name, contents=prompt
        )
        text = _extract_gemini_text(resp)
        if not text:
            pf = getattr(resp, "prompt_feedback", None)
            logger.error(
                "ringback_style_llm_empty_response",
                prompt_feedback=str(pf) if pf is not None else None,
            )
            return "", "empty_model_response"
        one_line = " ".join(text.strip().splitlines())
        return one_line, None
    except Exception as e:
        logger.error("ringback_style_llm_failed", error=str(e))
        return "", str(e)[:500]


async def auto_generate_style_with_context(
    vocal_gender: str = "m",
    duration_target: int = 60,
    brief: str | None = None,
    lyrics: str | None = None,
) -> tuple[str, bool]:
    """brief/lyrics 가 있으면 LLM으로 Suno 태그 한 줄, 없으면 기존 무작위.

    Returns:
        (style_string, used_llm)
    """
    b = (brief or "").strip()
    l = (lyrics or "").strip()
    if not b and not l:
        return auto_generate_style(vocal_gender, duration_target), False

    vocal_tag = "male vocal" if (vocal_gender or "m").lower().startswith("m") else "female vocal"
    if duration_target <= 30:
        duration_hint = "very short, under 30 seconds"
    elif duration_target <= 60:
        duration_hint = "short, under 60 seconds, jingle"
    else:
        duration_hint = f"about {duration_target} seconds"

    lyrics_excerpt = l[:1200] + ("…" if len(l) > 1200 else "") if l else "(none)"
    brief_block = b if b else "(none)"

    prompt = _STYLE_CONTEXT_PROMPT.format(
        brief=brief_block,
        lyrics=lyrics_excerpt,
        vocal_tag=vocal_tag,
        duration_hint=duration_hint,
    )
    line, err = await _call_llm_style_line(prompt)
    if line and vocal_tag in line.lower():
        logger.info(
            "ringback_style_generated",
            used_llm=True,
            brief_len=len(b),
            lyrics_len=len(l),
            style_len=len(line),
        )
        return line, True
    if line:
        # 모델이 보컬 태그 누락 시 보강
        line = f"{line}, {vocal_tag}, {duration_hint}"
        logger.info(
            "ringback_style_generated",
            used_llm=True,
            brief_len=len(b),
            lyrics_len=len(l),
            style_len=len(line),
            note="appended_vocal_duration",
        )
        return line, True

    fb = auto_generate_style(vocal_gender, duration_target)
    logger.warning(
        "ringback_style_llm_fallback_random",
        error_preview=(err[:120] if err else None),
    )
    return fb, False


# ── 스타일 자동 생성 ──────────────────────────────────────────────────────────

_GENRE_POOL = [
    "K-Pop", "J-Pop", "Bossa Nova", "Lo-fi", "Corporate Pop",
    "Acoustic Pop", "Soft Jazz", "Light Funk", "Indie Pop",
]

_MOOD_POOL = [
    "uplifting", "warm", "cheerful", "professional", "friendly",
    "bright", "calm", "positive",
]

_BPM_POOL = [
    "90 BPM", "95 BPM", "100 BPM", "105 BPM", "moderate tempo",
]

_JINGLE_TAGS = [
    "advertisement jingle", "brand music", "hold music", "commercial",
]


def auto_generate_style(vocal_gender: str = "m", duration_target: int = 60) -> str:
    """CM송에 적합한 Suno 스타일 태그를 무작위로 조합한다.

    Args:
        vocal_gender: "m" (남성) 또는 "f" (여성)
        duration_target: 목표 재생 시간 (초)

    Returns:
        콤마 구분 스타일 태그 문자열
    """
    genre = random.choice(_GENRE_POOL)
    mood1 = random.choice(_MOOD_POOL)
    mood2 = random.choice([m for m in _MOOD_POOL if m != mood1])
    bpm = random.choice(_BPM_POOL)
    jingle = random.choice(_JINGLE_TAGS)
    vocal = "male vocal" if vocal_gender == "m" else "female vocal"

    # 시간 태그
    if duration_target <= 30:
        time_tag = "very short, under 30 seconds"
    elif duration_target <= 60:
        time_tag = "short, under 60 seconds, jingle"
    else:
        time_tag = f"about {duration_target} seconds"

    tags = [genre, mood1, mood2, bpm, jingle, vocal, time_tag]
    return ", ".join(tags)


# ── 서버 사이드 폴링 + WebSocket 알림 ────────────────────────────────────────

async def poll_and_notify(
    owner: str,
    task_id: str,
    max_wait: int = 300,
    poll_interval: int = 5,
    ringback_assignment_id: str | None = None,
) -> None:
    """Suno 음원 생성 완료를 서버에서 폴링하고 WebSocket으로 프론트엔드에 알린다.

    완료 시:
        1. save_music_items() 로 DB에 저장
        2. ``ringback_assignment_id`` 가 있으면 MP3 다운로드 후 할당 행에 경로·``complete`` 반영
        3. 없으면 ``ringback_settings`` 의 ``suno_task_id`` 만 갱신
        4. (스테일 할당이 아니면) emit_ringback_music_ready

    실패/타임아웃 시:
        할당 행이면 ``suno_generation_status=failed`` 갱신 후 emit_ringback_music_failed
    """
    import asyncio

    elapsed = 0
    logger.info("ringback_poll_and_notify_start", owner=owner, task_id=task_id, max_wait=max_wait)

    while elapsed < max_wait:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        if ringback_assignment_id:
            from src.call_control import db as cc_db

            cur = cc_db.get_ringback_schedule_assignment(ringback_assignment_id)
            if (
                cur
                and str(cur.get("suno_task_id") or "") == str(task_id)
                and str(cur.get("suno_generation_status") or "").lower() == "complete"
            ):
                logger.info(
                    "ringback_poll_skip_already_complete",
                    task_id=task_id,
                    assignment_id=ringback_assignment_id,
                )
                return

        try:
            result = await poll_suno_task(task_id)
        except Exception as e:
            logger.warning("ringback_poll_error", task_id=task_id, error=str(e))
            continue

        status = result.get("status", "pending")
        logger.debug("ringback_poll_status", task_id=task_id, status=status, elapsed=elapsed)

        if status == "complete":
            items = result.get("items", []) or []
            await _finalize_suno_generation_success(owner, task_id, items, ringback_assignment_id)
            logger.info("ringback_poll_complete", owner=owner, task_id=task_id, count=len(items))
            return

        if status == "failed":
            error_msg = result.get("error", "Suno 생성 실패")
            if ringback_assignment_id:
                from src.call_control import db as cc_db

                row = cc_db.get_ringback_schedule_assignment(ringback_assignment_id)
                if row and str(row.get("suno_task_id") or "") == str(task_id):
                    cc_db.update_ringback_schedule_assignment(
                        ringback_assignment_id,
                        {"suno_generation_status": "failed"},
                    )
            try:
                from src.websocket.server import emit_ringback_music_failed

                await emit_ringback_music_failed(owner=owner, task_id=task_id, error=error_msg)
            except Exception as ws_err:
                logger.warning("ringback_ws_failed_emit_error", error=str(ws_err))
            logger.warning("ringback_poll_failed", owner=owner, task_id=task_id, error=error_msg)
            return

    # 타임아웃
    timeout_msg = f"최대 대기 시간({max_wait}초) 초과"
    if ringback_assignment_id:
        from src.call_control import db as cc_db

        row = cc_db.get_ringback_schedule_assignment(ringback_assignment_id)
        if row and str(row.get("suno_task_id") or "") == str(task_id):
            cc_db.update_ringback_schedule_assignment(
                ringback_assignment_id,
                {"suno_generation_status": "failed"},
            )
    try:
        from src.websocket.server import emit_ringback_music_failed

        await emit_ringback_music_failed(owner=owner, task_id=task_id, error=timeout_msg)
    except Exception:
        pass
    logger.warning("ringback_poll_timeout", owner=owner, task_id=task_id, max_wait=max_wait)


async def render_ringback_assignment_tts_wav(assignment_id: str) -> None:
    """통화 연결음(TTS 모드) 문구를 Google TTS로 합성해 WAV 파일로 저장한다.

    링 단계에서는 이 파일만 루프 재생한다(실시간 스트리밍 합성 없음).
    """
    import wave

    from src.call_control import db as cc_db

    row = cc_db.get_ringback_schedule_assignment(assignment_id)
    if not row:
        return
    if (row.get("generation_mode") or "").lower() != "tts":
        return
    text = (row.get("tts_text") or "").strip()
    owner = str(row.get("owner") or "")
    if not text:
        cc_db.update_ringback_schedule_assignment(assignment_id, {"tts_audio_path": None})
        return
    try:
        from src.ai_voicebot.ai_pipeline.tts_client import TTSClient
        from src.config.config_loader import load_config

        cfg = load_config()
        tts_cfg = getattr(cfg, "tts", None)
        tts_dict = (
            tts_cfg.model_dump()
            if tts_cfg is not None and hasattr(tts_cfg, "model_dump")
            else (dict(tts_cfg) if tts_cfg else {})
        )
        tts = TTSClient(tts_dict)
        pcm = await tts.synthesize(text)
    except Exception as e:
        logger.error(
            "ringback_tts_render_failed",
            assignment_id=assignment_id,
            error=str(e),
            exc_info=True,
        )
        return
    if not pcm:
        logger.warning("ringback_tts_render_empty_pcm", assignment_id=assignment_id)
        return

    cache_dir = _audio_cache_dir()
    safe_id = assignment_id.replace("-", "")[:24]
    dest = os.path.join(cache_dir, f"{owner}_rb_tts_{safe_id}.wav")
    try:
        with wave.open(dest, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm)
    except Exception as e:
        logger.error("ringback_tts_wav_write_failed", path=dest, error=str(e), exc_info=True)
        return

    cc_db.update_ringback_schedule_assignment(assignment_id, {"tts_audio_path": dest})
    logger.info(
        "ringback_tts_wav_saved",
        assignment_id=assignment_id,
        path=dest,
        pcm_bytes=len(pcm),
    )


async def kickoff_suno_after_assignment_saved(assignment_id: str) -> None:
    """착신 제어 통화 연결음 할당 저장 직후 Suno 생성을 시작한다 (백그라운드 태스크용)."""
    import asyncio

    from src.call_control import db as cc_db

    row = cc_db.get_ringback_schedule_assignment(assignment_id)
    if not row:
        return
    if (row.get("generation_mode") or "").lower() != "suno":
        return
    lyrics = (row.get("suno_lyrics") or "").strip()
    style = (row.get("suno_style") or "").strip()
    if not lyrics or not style:
        return
    owner = row["owner"]
    title = (row.get("suno_title") or row.get("name") or "통화 연결음").strip() or "통화 연결음"
    vg = ((row.get("suno_vocal_gender") or "m").strip().lower()[:1] or "m")
    if vg not in ("m", "f"):
        vg = "m"
    dur = int(row.get("suno_duration_target") or 60)

    try:
        result = await generate_suno_music(
            lyrics=lyrics,
            style=style,
            title=title,
            vocal_gender=vg,
            duration_target=dur,
        )
    except ValueError as e:
        logger.warning(
            "kickoff_suno_prerequisite_failed",
            assignment_id=assignment_id,
            error=str(e),
        )
        cur = cc_db.get_ringback_schedule_assignment(assignment_id)
        if cur and (cur.get("suno_generation_status") == "pending"):
            cc_db.update_ringback_schedule_assignment(
                assignment_id,
                {"suno_generation_status": "failed", "suno_task_id": None},
            )
        try:
            from src.websocket.server import emit_ringback_music_failed

            await emit_ringback_music_failed(owner=owner, task_id="", error=str(e))
        except Exception:
            pass
        return
    except Exception as e:
        logger.exception("kickoff_suno_generate_failed", assignment_id=assignment_id)
        cur = cc_db.get_ringback_schedule_assignment(assignment_id)
        if cur and (cur.get("suno_generation_status") == "pending"):
            cc_db.update_ringback_schedule_assignment(
                assignment_id,
                {"suno_generation_status": "failed", "suno_task_id": None},
            )
        try:
            from src.websocket.server import emit_ringback_music_failed

            await emit_ringback_music_failed(owner=owner, task_id="", error=str(e))
        except Exception:
            pass
        return

    task_id = str((result or {}).get("task_id") or "").strip()
    if not task_id:
        cc_db.update_ringback_schedule_assignment(
            assignment_id,
            {"suno_generation_status": "failed"},
        )
        return

    cur = cc_db.get_ringback_schedule_assignment(assignment_id)
    if not cur or cur.get("suno_generation_status") != "pending":
        logger.info(
            "kickoff_suno_skip_not_pending",
            assignment_id=assignment_id,
            status=cur.get("suno_generation_status") if cur else None,
        )
        return

    cc_db.update_ringback_schedule_assignment(
        assignment_id,
        {"suno_task_id": task_id, "suno_generation_status": "pending"},
    )
    asyncio.create_task(
        poll_and_notify(
            owner=owner,
            task_id=task_id,
            ringback_assignment_id=assignment_id,
        ),
        name=f"ringback_poll_{task_id[:8]}",
    )
