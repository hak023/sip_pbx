# AI 응대 시 말소리가 안 들릴 때 (TTS synthesis error)

## 증상

- AI가 통화를 받아 인사말이나 응답을 하려 할 때 **전화에서 음성이 나오지 않음**
- `app.log`에 아래 에러가 찍힘:

```json
{"level": "error", "event": "TTS synthesis error", "error": "400 Requested language code 'ko' doesn't match the voice 'ko-KR-Chirp3-HD-Kore''s language code 'ko-kr'. Either pick a different voice, or change the requested language code to ko-kr."}
```

## 원인

Google Cloud TTS(Text-to-Speech) API에 **언어 코드 `ko`**로 요청하는데, 사용 중인 보이스 `ko-KR-Chirp3-HD-Kore`는 **`ko-kr`(또는 `ko-KR`)만** 허용합니다. API가 400을 반환하면서 음성 합성이 실패하고, 그래서 통화에 말소리가 나오지 않습니다.

## 조치

TTS를 초기화하거나 요청하는 쪽에서 **언어 코드를 `ko` → `ko-kr`(또는 `ko-KR`)로 변경**해야 합니다.

### 1. 설정 파일에서 수정하는 경우

- `config/config.yaml`(또는 사용 중인 설정 파일)에서 TTS/streaming_tts 관련 항목을 찾습니다.
- `language`, `language_code` 등이 `ko`로 되어 있으면 **`ko-kr`** 또는 **`ko-KR`**로 바꿉니다.

예시:

```yaml
# 변경 전
streaming_tts:
  language: "ko"
  voice: "ko-KR-Chirp3-HD-Kore"

# 변경 후
streaming_tts:
  language: "ko-kr"   # 또는 "ko-KR"
  voice: "ko-KR-Chirp3-HD-Kore"
```

### 2. 코드에서 TTSClient 초기화하는 경우

- `TTSClient`를 생성하는 부분(또는 Google TTS 클라이언트를 만드는 부분)을 찾습니다.
- `language="ko"` 또는 `language_code="ko"`를 **`language="ko-kr"`** / **`language_code="ko-kr"`**로 변경합니다.

로그에 `"TTSClient initialized", "language": "ko"` 가 보이므로, 해당 초기화 코드에서 `language` 인자나 설정 읽기 부분을 수정하면 됩니다.

### 3. 수정 후

- 서버를 재시작한 뒤 다시 통화해 보면 인사말·AI 응답 음성이 나와야 합니다.

## 참고

- 같은 로그에 **STT streaming error** (Audio Timeout)가 나와도, **말소리가 안 들리는 직접 원인**은 위 TTS 에러입니다. TTS를 고치면 음성은 나오고, STT 타임아웃은 별도로 조정할 수 있습니다.
