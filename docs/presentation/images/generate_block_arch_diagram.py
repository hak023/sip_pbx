"""
블록형 아키텍처 PNG 생성기 — PROJECT_BRIEF §3.2 용 (Layered & Pillared Block Style)
실행: python docs/presentation/images/generate_block_arch_diagram.py
의존: pip install matplotlib
"""

from __future__ import annotations

from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.font_manager as fm

def pick_korean_font_family() -> str | None:
    candidates = [
        "Malgun Gothic",
        "NanumGothic",
        "Nanum Gothic",
        "AppleGothic",
        "Noto Sans CJK KR",
        "Source Han Sans KR",
    ]
    for name in candidates:
        path = fm.findfont(fm.FontProperties(family=name))
        if path and "dejavu" not in path.lower():
            return name
    return None

def draw_container(ax, x: float, y: float, w: float, h: float, title: str):
    """큰 컨테이너 (Layer) 박스를 그립니다."""
    # Outer box
    rect = mpatches.Rectangle((x, y), w, h, linewidth=1.5, edgecolor="#111827", facecolor="#f8fafc", zorder=1)
    ax.add_patch(rect)
    # Title
    ax.text(x + w / 2, y + h - 0.35, title, fontsize=12.5, fontweight='bold', color='black', ha='center', va='center', zorder=2)

def draw_subblock(ax, x: float, y: float, w: float, h: float, title: str, lines: list[str]):
    """작은 내부 블록 (Component) 박스를 그립니다."""
    rect = mpatches.Rectangle((x, y), w, h, linewidth=1.0, edgecolor="#334155", facecolor="white", zorder=2)
    ax.add_patch(rect)
    
    # Subblock title
    ax.text(x + w / 2, y + h - 0.28, title, fontsize=10.5, fontweight='bold', color='black', ha='center', va='center', zorder=3)
    
    # Details in blue
    ty = y + h - 0.65
    for line in lines:
        ax.text(x + w / 2, ty, line, fontsize=9.0, color="#1d4ed8", ha='center', va='center', zorder=3)
        ty -= 0.32

def draw_double_arrow_v(ax, x, y1, y2):
    ax.annotate("", xy=(x, y2), xytext=(x, y1), arrowprops=dict(arrowstyle="<->", color="#64748b", lw=2.0), zorder=0)

def draw_double_arrow_h(ax, x1, x2, y):
    ax.annotate("", xy=(x2, y), xytext=(x1, y), arrowprops=dict(arrowstyle="<->", color="#64748b", lw=2.0), zorder=0)

def main() -> None:
    root = Path(__file__).resolve().parent
    out_path = root / "diagram_block_architecture.png"
    
    ko = pick_korean_font_family()
    if ko:
        plt.rcParams["font.family"] = ko
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(15, 10.5), dpi=200)
    ax.set_xlim(0, 15)
    ax.set_ylim(0, 10.5)
    ax.axis("off")
    fig.patch.set_facecolor('white')

    # ========== Left Pillar (운영 정책 및 관리) ==========
    draw_container(ax, 0.5, 0.5, 3.4, 9.5, "운영 정책 및 공통 관리 Layer")
    draw_subblock(ax, 0.7, 5.3, 3.0, 4.0, "Call Control", ["착신 및 시간대 라우팅", "발신자 번호 필터링", "블랙리스트 관리"])
    draw_subblock(ax, 0.7, 0.8, 3.0, 4.0, "멀티테넌시 및 감사", ["조직·내선별 지식 격리", "운영자 권한 및 개입 제어", "HITL 및 구조화 로그"])

    # ========== Right Pillar (외부 지원 및 데이터) ==========
    draw_container(ax, 11.1, 0.5, 3.4, 9.5, "외부 지원 및 데이터 Layer")
    draw_subblock(ax, 11.3, 6.8, 3.0, 2.5, "외부 AI 모델", ["Google Cloud STT / TTS", "Gemini 2.5 Flash LLM"])
    draw_subblock(ax, 11.3, 3.8, 3.0, 2.5, "외부 연동 서비스", ["Google Calendar API", "Suno 연결음 생성기", "MCP 도구 인터페이스"])
    draw_subblock(ax, 11.3, 0.8, 3.0, 2.5, "데이터 저장소", ["SQLite (관계형 제어 정보)", "ChromaDB (벡터 DB RAG)", "WAV 녹음 및 시스템 파일"])

    # ========== Central Stack ==========
    cx = 4.3
    cw = 6.4
    
    # 1. 접속 및 클라이언트 (Top)
    draw_container(ax, cx, 8.0, cw, 2.0, "접속 및 클라이언트 Layer")
    draw_subblock(ax, cx + 0.2, 8.2, cw / 2 - 0.3, 1.2, "SIP 단말 / 네트워크", ["IP 전화기, SIP 트렁크", "통신망 방화벽/NAT"])
    draw_subblock(ax, cx + cw / 2 + 0.1, 8.2, cw / 2 - 0.3, 1.2, "웹 운영 콘솔", ["Next.js 실시간 대시보드", "Call Dock 모니터링"])

    # 2. 운영 및 API
    draw_container(ax, cx, 5.5, cw, 2.0, "운영 및 API Layer")
    draw_subblock(ax, cx + 0.2, 5.7, cw / 2 - 0.3, 1.2, "FastAPI (REST)", ["호 처리 및 상태 제어", "설정 정보 조회·수정"])
    draw_subblock(ax, cx + cw / 2 + 0.1, 5.7, cw / 2 - 0.3, 1.2, "WebSocket / Socket.IO", ["실시간 통화 이벤트 Push", "운영자-AI 양방향 통신"])

    # 3. 지식 및 에이전트 로직
    draw_container(ax, cx, 3.0, cw, 2.0, "지식 및 에이전트 로직 Layer")
    draw_subblock(ax, cx + 0.2, 3.2, cw * 0.55, 1.2, "LangGraph 에이전트", ["17개 의도 분류 · 도구 호출", "예약 · 전환 · HITL 상태 분기"])
    draw_subblock(ax, cx + cw * 0.55 + 0.4, 3.2, cw * 0.45 - 0.6, 1.2, "Active RAG", ["동적 지식 검색 및 주입", "대화 맥락 이해"])

    # 4. 실시간 통화 파이프라인 (Bottom)
    draw_container(ax, cx, 0.5, cw, 2.0, "실시간 통화 파이프라인 Layer")
    sw = (cw - 0.6) / 3
    draw_subblock(ax, cx + 0.2, 0.7, sw, 1.2, "실시간 음성 제어", ["Pipecat, VAD 바지인", "스트리밍 음성 합성(TTS)"])
    draw_subblock(ax, cx + 0.2 + sw + 0.1, 0.7, sw, 1.2, "RTP 미디어", ["RTP 오디오 브리지 전송", "음성 코덱 변환 (G.711)"])
    draw_subblock(ax, cx + 0.2 + sw * 2 + 0.2, 0.7, sw, 1.2, "SIP 통화 제어", ["B2BUA 세션(INVITE) 관리", "호 전환(Transfer), 보류"])

    # ========== Arrows ==========
    # Vertical arrows in the center stack
    draw_double_arrow_v(ax, cx + cw / 2, 7.5, 8.0)
    draw_double_arrow_v(ax, cx + cw / 2, 5.0, 5.5)
    draw_double_arrow_v(ax, cx + cw / 2, 2.5, 3.0)

    # Horizontal arrows connecting stack to pillars
    # Left pillar to stack
    draw_double_arrow_h(ax, 3.9, 4.3, 5.25)
    # Stack to right pillar
    draw_double_arrow_h(ax, 10.7, 11.1, 5.25)

    fig.savefig(out_path, bbox_inches='tight', pad_inches=0.1)
    plt.close(fig)
    print(f"Successfully generated: {out_path}")

if __name__ == "__main__":
    main()
