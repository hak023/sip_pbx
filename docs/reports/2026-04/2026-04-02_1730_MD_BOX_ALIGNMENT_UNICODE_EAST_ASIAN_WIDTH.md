# Markdown 박스 정렬 문제: Unicode East Asian Width & Ambiguous 문자 분석 리포트

- **작성일**: 2026-04-02 17:30
- **상태**: 완료 (분석 + 수정 가이드)
- **관련 파일**: `sip-pbx/docs/presentation/PROJECT_BRIEF.md`

---

## 1. 문제 요약

`PROJECT_BRIEF.md`의 ASCII/Unicode 박스 다이어그램에서 특정 줄들이 반복적으로 정렬이 맞지 않는 현상이 발생한다.
이전 수정 스크립트로 대부분 교정됐으나 아래 줄들은 여전히 뭉개짐:

| 줄 번호 | 증상 |
|---------|------|
| 679 | `╔═══╗` 박스 안 제목 줄, `│`가 오른쪽으로 밀림 |
| 719 | 같은 패턴 (아웃바운드 섹션 제목 줄) |
| 821 / 830 | 내부 중첩 박스의 위/아래 경계선 (`┌─────┐`, `└─────┘`), 끝 `│` 위치 어긋남 |

---

## 2. 근본 원인: `eaw=A` (Ambiguous Width)

### 2-1. Unicode East Asian Width 분류

Unicode UAX #11은 각 코드포인트에 **East Asian Width** 속성을 부여한다:

| 속성 | 의미 | 터미널/렌더러 처리 |
|------|------|-------------------|
| `W` (Wide) | 한글 완성형(AC00–D7A3), CJK | **항상 2칸** |
| `F` (Fullwidth) | 전각 ASCII 등 | **항상 2칸** |
| `Na` (Narrow) | ASCII 영문·숫자 | **항상 1칸** |
| `N` (Neutral) | 중립 | **보통 1칸** |
| **`A` (Ambiguous)** | **박스 드로잉 문자 포함** | **환경마다 다름 (1칸 or 2칸)** |

### 2-2. 박스 드로잉 문자는 전부 `eaw=A`

Python `unicodedata.east_asian_width()` 검증 결과:

```
U+2502  eaw=A   │  BOX DRAWINGS LIGHT VERTICAL
U+2500  eaw=A   ─  BOX DRAWINGS LIGHT HORIZONTAL
U+250C  eaw=A   ┌  BOX DRAWINGS LIGHT DOWN AND RIGHT
U+2510  eaw=A   ┐  BOX DRAWINGS LIGHT DOWN AND LEFT
U+2514  eaw=A   └  BOX DRAWINGS LIGHT UP AND RIGHT
U+2518  eaw=A   ┘  BOX DRAWINGS LIGHT UP AND LEFT
U+2550  eaw=A   ═  BOX DRAWINGS DOUBLE HORIZONTAL
U+2551  eaw=A   ║  BOX DRAWINGS DOUBLE VERTICAL
U+2554  eaw=A   ╔  BOX DRAWINGS DOUBLE DOWN AND RIGHT
U+255A  eaw=A   ╚  BOX DRAWINGS DOUBLE UP AND RIGHT
```

즉, **박스 드로잉 문자 전체가 Ambiguous**이며, 렌더러(폰트/에디터/터미널)에 따라 1칸 또는 2칸으로 표시된다.

### 2-3. 에디터·폰트별 처리 방식 차이

| 환경 | Ambiguous 처리 | 효과 |
|------|---------------|------|
| VS Code (D2Coding) | `A` → 1칸 | 박스선 = 1칸, 한글 = 2칸 |
| VS Code (기본 Consolas/Courier) | `A` → 1칸 | 박스선 = 1칸, 한글 = 2칸 |
| WezTerm `treat_east_asian_ambiguous_width_as_wide=true` | `A` → 2칸 | 박스선도 2칸 → tree 등 TUI 레이아웃 깨짐 |
| Cursor IDE (현재 환경) | **`A` → 2칸으로 렌더링**하는 것으로 보임 | 경계선 `─`×N이 2N칸 → 내용줄과 어긋남 |

> **참고**: WezTerm GitHub Issue #2424에서 `treat_east_asian_ambiguous_width_as_wide=true` 설정이 박스 드로잉 문자를 2칸으로 렌더링해 TUI 레이아웃을 깨뜨림을 공식 확인함. 이 환경에서의 권장 해결책은 해당 설정을 제거하는 것이었다.

---

## 3. 구체적 사례 분석

### Case A: 679번·719번 — `╔══╗` 박스 안 제목 줄

```
678: ╔════════════════════════════════════════════════════════════════════════════╗
679:                                              │         멀티 테넌트 격리 (내선번호 = 테넌트 owner)│
680: ╠═══════════════════════════════════╦════════════════════════════════════════╣
```

**계산 비교**:

| 계산 방식 | 678번(경계선) | 679번(제목 줄) |
|-----------|-------------|--------------|
| `ambig=1` (박스=1칸) | 78 | 98 |
| `ambig=2` (박스=2칸) | 156 | 100 |

- `ambig=2` 기준: 경계선=156, 제목=100 → **56칸 차이 → 경계선이 훨씬 넓어 보임** (제목 줄이 짧아 보임)
- 하지만 `ambig=1` 기준: 경계선=78, 제목=98 → **제목이 20칸 더 넓음** (오른쪽 `│`가 밖으로 삐져나옴)

이 패턴은 "경계선이 전부 `═`(ambig)로 구성된 더블 라인 박스"의 특성이다.
`═` 문자 76개 → `ambig=1`에서 78칸, `ambig=2`에서 78×2 = 156칸.

679번 줄은 한글 포함 내용 줄로 `│` 두 개(2칸)와 한글 문자들이 있다.
`ambig=1` 기준 98칸으로 **경계선 78칸을 초과**하는 것이 이미 문제.

→ **해결 전략**: 679, 719번 줄은 경계선 `╔═══╗` 안에 들어가는 "제목 오버레이" 스타일이다.
  `ambig=1` 기준으로 경계선 폭(78/77)에 맞춰 내용을 정렬해야 한다.
  현재 `│` 앞 공백이 43칸 → 내용 표시 너비를 줄여야 한다.

### Case B: 821번·830번 — 중첩 박스 경계선

```
821: │  │  ┌─────────────────────────────────────────────────────────┐   │     │
830: │  │  └─────────────────────────────────────────────────────────┘   │     │
```

**계산 비교**:

| 계산 방식 | 경계선 줄(821) | 내용 줄(822) |
|-----------|-------------|------------|
| `ambig=1` (박스=1칸) | 75 | 75 |
| `ambig=2` (박스=2칸) | 138 | 81 |

- `ambig=1` 기준: 둘 다 75 → **완벽히 일치** ✓
- `ambig=2` 기준: 경계선=138, 내용=81 → **57칸 차이** → 경계선이 훨씬 넓어 보임

**결론**: 821/830번 줄은 `ambig=1` 기준으로 이미 올바르게 정렬되어 있다.
`ambig=2`로 렌더링하는 환경(Cursor IDE 등)에서는 경계선이 내용보다 넓어 보이는데, 이는 `─` 문자가 61개 포함된 경계선이 `ambig=2` 시 122칸으로 늘어나기 때문이다.

---

## 4. 폰트 및 렌더링 환경 권장사항

### 4-1. 마크다운 박스 다이어그램을 정확히 렌더링하는 폰트

| 우선순위 | 폰트 | 특징 |
|---------|------|------|
| ✅ 1순위 | **D2Coding** (네이버) | 한글+ASCII 모노스페이스, 한글=2칸, 박스문자=1칸 |
| ✅ 2순위 | **Nanum Gothic Coding** | 마찬가지로 CJK-aware, 박스=1칸 |
| ✅ 3순위 | **Cascadia Code** (MS) | 한글 포함 시 일부 환경에서 정렬 우수 |
| ⚠️ 주의 | HackGenNerd, Noto Sans Mono CJK | Ambiguous → 2칸 처리 가능, 박스선 깨짐 우려 |
| ❌ 피함 | Consolas, Courier New | 한글=1칸 처리 → 한글 줄 정렬 불일치 |

### 4-2. Cursor/VS Code 설정 권장

```json
// settings.json
{
  "editor.fontFamily": "D2Coding, 'Cascadia Code', Consolas, monospace",
  "editor.fontLigatures": false
}
```

---

## 5. 바이트 계산 vs. Display Width 계산

| 방법 | 계산 | 문제점 |
|------|------|--------|
| `len(str)` | 글자 수 | 한글 1글자=1로 계산 → 폭 오류 |
| `len(str.encode('utf-8'))` | UTF-8 바이트 수 | 한글 1글자=3바이트 → 완전히 다른 기준 |
| `len(str.encode('utf-16-le'))` / 2 | UTF-16 코드 유닛 | 한글 = 1 단위 → 폭 오류 |
| **`display_width(str)`** | **EAW 기반 시각 폭** | **✅ 정확 (단, ambig 처리 방식 선택 필요)** |

### 올바른 display_width 함수

```python
import unicodedata

def display_width(s: str, ambig_as_wide: bool = False) -> int:
    """
    문자열의 터미널/모노스페이스 폰트 표시 폭 계산.
    
    ambig_as_wide=False (기본, D2Coding/VS Code 기준):
        박스 드로잉 문자(eaw=A) → 1칸
    ambig_as_wide=True (일부 CJK 터미널 기준):
        박스 드로잉 문자(eaw=A) → 2칸
    """
    total = 0
    for ch in s:
        eaw = unicodedata.east_asian_width(ch)
        if eaw in ('W', 'F'):
            total += 2
        elif eaw == 'A':
            total += 2 if ambig_as_wide else 1
        else:  # Na, N, H
            total += 1
    return total
```

---

## 6. 수정 전략 (679·719번 줄)

### 현재 상태 분석

679번 줄 (`ambig=1` 기준):
- 전체 폭: 98칸
- 경계선 폭: 78칸
- 초과: 20칸

원인: 오른쪽 `│` 뒤에 내용이 있거나, `│` 앞 공백 + 내용 폭이 경계선 폭을 초과함.

### 수정 방향

679, 719번 줄은 `╔═══╗` 상단 경계선 안에 들어가는 "헤더 배너" 형식:
- 경계선 폭(78/77칸)에 맞춰 전체 줄 폭을 조정해야 함
- `│` 위치: 경계선 폭 기준으로 중앙 또는 좌측 고정
- 오른쪽 닫는 `│`은 경계선 우측과 일치해야 함 (`ambig=1` 기준 77 또는 78번째 칸)

---

## 7. 참고 링크

- [Unicode UAX #11: East Asian Width](https://unicode.org/reports/tr11/)
- [WezTerm Issue #2424: treat_east_asian_ambiguous_width_as_wide causes box drawing issues](https://github.com/wez/wezterm/issues/2424)
- [markdownlint Issue #564: MD013 Unicode character width](https://github.com/DavidAnson/markdownlint/issues/564)
- [wcwidth Python library spec](https://wcwidth.readthedocs.io/en/stable/specs.html)
- [jquast/wcwidth: New ambiguous_width=1 argument PR #172](https://github.com/jquast/wcwidth/pull/172)
