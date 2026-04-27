## 메타

- **작성일(로컬)**: 2026-04-21 17:34
- **상태**: 수정 반영
- **관련 로그**: `chat_sip_message_send_error` — `'utf-8' codec can't encode character '\\udc9c' ... surrogates not allowed`

## 개요

SIP MESSAGE 송신 시 본문은 `utf-8` + `surrogatepass`로 바이트화하지만, **SIP 헤더 블록**은 `hdr.encode("utf-8")` 기본(strict)이라 헤더 조립 문자열에 **U+D800–U+DFFF**(잘못된 UTF-8·경계 처리로 생긴 surrogate)가 끼면 **UDP 전송 전에** `UnicodeEncodeError`가 나 `sip_message_relay_finished`의 `send_error`로 끝난다. `Content-Type` 등에 surrogate가 섞일 수 있어 치환·헤더 인코딩을 보강했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `send_chat_sip_message` / `send_sip_message`: `Content-Type`에 `_sanitize_sip_text_for_utf8_io`, `hdr.encode(..., errors="surrogatepass")` | 설계대로 |

## 주요 결정 사항

- 기존 `_sanitize_sip_text_for_utf8_io`(서로게이트 → U+FFFD)를 **송신 Content-Type**에 적용.
- 헤더 전체 `encode`에 `surrogatepass`를 추가해, 예상 밖 필드에 surrogate가 남아도 송신 단계에서 예외를 피함(SIP 표준상 헤더는 ASCII 권장이나, 장애 방지 우선).
