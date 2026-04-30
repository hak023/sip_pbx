"""
블록형 아키텍처 PNG 생성기 — PROJECT_BRIEF §3.2 용 (Layered & Right Pillared Block Style with Colors)
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

def draw_container(ax, x: float, y: float, w: float, h: float, title: str, facecolor: str = "#f8fafc"):
    """큰 컨테이너 (Layer) 박스를 그립니다."""
    # Outer box
    rect = mpatches.Rectangle((x, y), w, h, linewidth=1.5, edgecolor="#334155", facecolor=facecolor, zorder=1)
    ax.add_patch(rect)
    # Title
    ax.text(x + w / 2, y + h - 0.35, title, fontsize=12.5, fontweight='bold', color='#0f172a', ha='center', va='center', zorder=2)

def draw_subblock(ax, x: float, y: float, w: float, h: float, title: str, lines: list[str], lines_y_start: float = 0.65, line_spacing: float = 0.32):
    """작은 내부 블록 (Component) 박스를 그립니다."""
    rect = mpatches.Rectangle((x, y), w, h, linewidth=1.0, edgecolor="#64748b", facecolor="white", zorder=2)
    ax.add_patch(rect)
    
    # Subblock title
    ax.text(x + w / 2, y + h - 0.28, title, fontsize=10.5, fontweight='bold', color='black', ha='center', va='center', zorder=3)
    
    # Details in blue
    ty = y + h - lines_y_start
    for line in lines:
        ax.text(x + w / 2, ty, line, fontsize=9.0, color="#1d4ed8", ha='center', va='center', zorder=3)
        ty -= line_spacing

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

    # 레이아웃 정의: 중앙 스택(Left)과 우측 기둥(Right)
    cx = 0.5
    cw = 9.5
    
    rx = 10.5
    rw = 4.0

    # ================= 중앙 스택 (핵심 레이어 적층) =================
    
    # 1. 접속 및 클라이언트 (Top) - Light Blue
    draw_container(ax, cx, 8.0, cw, 2.0, "접속 및 클라이언트 Layer", facecolor="#e0f2fe")
    sub_w1 = (cw - 0.6) / 2
    draw_subblock(ax, cx + 0.2, 8.2, sub_w1, 1.2, "SIP 단말 / 네트워크", ["IP 전화기, SIP 트렁크", "통신망 방화벽/NAT"])
    draw_subblock(ax, cx + 0.4 + sub_w1, 8.2, sub_w1, 1.2, "웹 운영 콘솔", ["Next.js 실시간 대시보드", "Call Dock 모니터링"])

    # 2. 운영 및 API - Light Teal
    draw_container(ax, cx, 5.5, cw, 2.0, "운영 및 API Layer", facecolor="#ccfbf1")
    draw_subblock(ax, cx + 0.2, 5.7, sub_w1, 1.2, "FastAPI (REST)", ["호 처리 및 상태 제어", "설정 정보 조회·수정"])
    draw_subblock(ax, cx + 0.4 + sub_w1, 5.7, sub_w1, 1.2, "WebSocket / Socket.IO", ["실시간 통화 이벤트 Push", "운영자-AI 양방향 통신"])

    # 3. 지식 및 에이전트 로직 - Light Indigo
    draw_container(ax, cx, 3.0, cw, 2.0, "지식 및 에이전트 로직 Layer", facecolor="#e0e7ff")
    draw_subblock(ax, cx + 0.2, 3.2, cw * 0.55, 1.2, "LangGraph 에이전트", ["17개 의도 분류 · 도구 호출", "예약 · 전환 · HITL 상태 분기"])
    draw_subblock(ax, cx + cw * 0.55 + 0.4, 3.2, cw * 0.45 - 0.6, 1.2, "Active RAG", ["동적 지식 검색 및 주입", "대화 맥락 이해"])

    # 4. 실시간 통화 파이프라인 (Bottom) - Light Amber
    draw_container(ax, cx, 0.5, cw, 2.0, "실시간 통화 파이프라인 Layer", facecolor="#fef3c7")
    sub_w4 = (cw - 0.6) / 3
    draw_subblock(ax, cx + 0.2, 0.7, sub_w4, 1.2, "실시간 음성 제어", ["Pipecat, VAD 바지인", "스트리밍 음성 합성(TTS)"])
    draw_subblock(ax, cx + 0.2 + sub_w4 + 0.1, 0.7, sub_w4, 1.2, "RTP 미디어", ["RTP 오디오 브리지 전송", "음성 코덱 변환 (G.711)"])
    draw_subblock(ax, cx + 0.2 + sub_w4 * 2 + 0.2, 0.7, sub_w4, 1.2, "SIP 통화 제어", ["B2BUA 세션(INVITE) 관리", "호 전환(Transfer), 보류"])

    # ================= 우측 기둥 (관리 및 외부 연동) =================

    # Top Right Pillar: 외부 지원 및 데이터 - Light Green / Yellow
    draw_container(ax, rx, 5.5, rw, 4.5, "외부 연동 및 데이터 Layer", facecolor="#ecfccb")
    rsub_w = rw - 0.4
    draw_subblock(ax, rx + 0.2, 8.5, rsub_w, 1.0, "외부 AI 모델", ["Google STT/TTS", "Gemini 2.5 Flash LLM"], lines_y_start=0.55, line_spacing=0.28)
    draw_subblock(ax, rx + 0.2, 7.1, rsub_w, 1.0, "외부 서비스 연동", ["Google Calendar API", "Suno 연결음 생성기"], lines_y_start=0.55, line_spacing=0.28)
    draw_subblock(ax, rx + 0.2, 5.7, rsub_w, 1.0, "데이터 저장소", ["SQLite (제어 정보 DB)", "ChromaDB (벡터 DB RAG)"], lines_y_start=0.55, line_spacing=0.28)

    # Bottom Right Pillar: 운영 정책 및 공통 관리 - Light Rose / Pink
    draw_container(ax, rx, 0.5, rw, 4.5, "운영 정책 및 관리 Layer", facecolor="#fce7f3")
    draw_subblock(ax, rx + 0.2, 3.1, rsub_w, 1.4, "Call Control", ["착신 및 시간대 라우팅", "발신자 번호 필터링", "블랙리스트 관리"])
    draw_subblock(ax, rx + 0.2, 0.9, rsub_w, 1.4, "멀티테넌시 및 감사", ["조직·내선별 지식 격리", "운영자 권한 및 개입 제어", "HITL 및 구조화 로그"])


    # ========== Arrows ==========
    # Vertical arrows in the center stack
    draw_double_arrow_v(ax, cx + cw / 2, 7.5, 8.0)
    draw_double_arrow_v(ax, cx + cw / 2, 5.0, 5.5)
    draw_double_arrow_v(ax, cx + cw / 2, 2.5, 3.0)

    # Horizontal arrows connecting stack to right pillars
    draw_double_arrow_h(ax, cx + cw + 0.05, rx - 0.05, 7.75) # Top right pillar link
    draw_double_arrow_h(ax, cx + cw + 0.05, rx - 0.05, 2.75) # Bottom right pillar link

    fig.savefig(out_path, bbox_inches='tight', pad_inches=0.1)
    plt.close(fig)
    print(f"Successfully generated: {out_path}")

if __name__ == "__main__":
    main()
