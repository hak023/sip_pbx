"""
블록형 아키텍처 PNG 생성기 (Professional Corporate Style)
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

def draw_layer(ax, x: float, y: float, w: float, h: float, title: str):
    """메인 레이어 컨테이너"""
    rect = mpatches.FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=0.1",
        linewidth=1.5, edgecolor="#94a3b8", facecolor="#f8fafc", zorder=1
    )
    ax.add_patch(rect)
    
    # Layer Title Area (Top part of the box)
    title_h = 0.45
    title_rect = mpatches.FancyBboxPatch(
        (x, y + h - title_h), w, title_h, boxstyle="round,pad=0,rounding_size=0.1",
        linewidth=1.5, edgecolor="#94a3b8", facecolor="#e2e8f0", zorder=2
    )
    # To make bottom corners square for title area, we overlay a rectangle
    square_overlay = mpatches.Rectangle((x, y + h - title_h), w, title_h - 0.1, facecolor="#e2e8f0", edgecolor="none", zorder=2)
    ax.add_patch(title_rect)
    ax.add_patch(square_overlay)
    
    # Redraw outer border to keep it clean
    rect_outline = mpatches.FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=0.1",
        linewidth=1.5, edgecolor="#94a3b8", facecolor="none", zorder=3
    )
    ax.add_patch(rect_outline)

    # Layer Title Text
    ax.text(x + w / 2, y + h - (title_h / 2), title, fontsize=12, fontweight='bold', color="#0f172a", ha='center', va='center', zorder=4)

def draw_component(ax, x: float, y: float, w: float, h: float, title: str, lines: list[str]):
    """내부 컴포넌트 박스"""
    rect = mpatches.Rectangle((x, y), w, h, linewidth=1.2, edgecolor="#cbd5e1", facecolor="#ffffff", zorder=3)
    ax.add_patch(rect)
    
    # Title
    ax.text(x + w / 2, y + h - 0.25, title, fontsize=10.5, fontweight='bold', color="#1e293b", ha='center', va='center', zorder=4)
    
    # Content
    ty = y + h - 0.55
    for line in lines:
        ax.text(x + w / 2, ty, f"• {line}", fontsize=9, color="#475569", ha='center', va='center', zorder=4)
        ty -= 0.25

def main() -> None:
    root = Path(__file__).resolve().parent
    out_path = root / "diagram_block_architecture.png"
    
    ko = pick_korean_font_family()
    if ko:
        plt.rcParams["font.family"] = ko
    plt.rcParams["axes.unicode_minus"] = False

    # 캔버스 크기
    fig, ax = plt.subplots(figsize=(12, 10.5), dpi=200)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 10.5)
    ax.axis("off")
    fig.patch.set_facecolor('#ffffff')

    # 레이아웃 상수
    W = 11.0
    CX = 0.5
    
    # 4. 외부 접속 (Top)
    L4_Y = 8.3
    L4_H = 1.6
    draw_layer(ax, CX, L4_Y, W, L4_H, "Client & External Access")
    cw = (W - 0.6) / 2
    draw_component(ax, CX + 0.2, L4_Y + 0.2, cw, 0.9, "SIP 단말 / 트렁크", ["IP 전화기, SIP 클라이언트", "SIP MESSAGE / 문자 릴레이"])
    draw_component(ax, CX + 0.4 + cw, L4_Y + 0.2, cw, 0.9, "웹 운영 콘솔", ["Next.js 실시간 대시보드", "Call Dock 및 설정 화면"])

    # 3. App Tier
    L3_Y = 6.4
    L3_H = 1.6
    draw_layer(ax, CX, L3_Y, W, L3_H, "Application Tier")
    draw_component(ax, CX + 0.2, L3_Y + 0.2, cw, 0.9, "FastAPI (REST)", ["호 처리, 착신 라우팅 API", "멀티테넌시 설정 조회"])
    draw_component(ax, CX + 0.4 + cw, L3_Y + 0.2, cw, 0.9, "Socket.IO (WebSocket)", ["실시간 통화 이벤트 Push", "운영자 실시간 개입 (HITL)"])

    # 2. Core Logic (AI & SIP) - 분리된 2개의 서브 블록 포함 큰 영역
    L2_Y = 2.8
    L2_H = 3.3
    draw_layer(ax, CX, L2_Y, W, L2_H, "Core Processing Engine")
    
    # Left Core: AI Voice + Agent
    draw_component(ax, CX + 0.2, L2_Y + 0.2, cw, 2.5, "AI Voice + Agent", [])
    ax.text(CX + 0.2 + cw/2, L2_Y + 2.5 - 0.25, "AI Voice + Agent", fontsize=10.5, fontweight='bold', color="#1e293b", ha='center', va='center', zorder=4)
    
    aw = cw - 0.4
    draw_component(ax, CX + 0.4, L2_Y + 1.3, aw, 0.8, "LangGraph 에이전트", ["17개 의도 분류, 도구 호출", "Active RAG, HITL 분기"])
    draw_component(ax, CX + 0.4, L2_Y + 0.4, aw, 0.8, "Pipecat 파이프라인", ["VAD, 스마트 바지인 제어", "STT/TTS 양방향 스트리밍"])

    # Right Core: SIP / RTP
    draw_component(ax, CX + 0.4 + cw, L2_Y + 0.2, cw, 2.5, "SIP / RTP Core", [])
    ax.text(CX + 0.4 + cw + cw/2, L2_Y + 2.5 - 0.25, "SIP / RTP Core", fontsize=10.5, fontweight='bold', color="#1e293b", ha='center', va='center', zorder=4)
    
    sw = cw - 0.4
    sx = CX + 0.4 + cw + 0.2
    draw_component(ax, sx, L2_Y + 1.3, sw, 0.8, "B2BUA Call Control", ["SIP 세션(INVITE) 중계", "호 전환, 보류, 연결음 제어"])
    draw_component(ax, sx, L2_Y + 0.4, sw, 0.8, "RTP Relay Worker", ["RTP 미디어 브리지", "오디오 믹싱, 녹음 전송"])

    # 1. Data & External (Bottom)
    L1_Y = 0.6
    L1_H = 1.9
    draw_layer(ax, CX, L1_Y, W, L1_H, "Data Storage & External Services")
    dw = (W - 0.8) / 3
    draw_component(ax, CX + 0.2, L1_Y + 0.2, dw, 1.1, "데이터 저장소 (DB)", ["SQLite (관계형 설정 DB)", "ChromaDB (벡터 RAG)"])
    draw_component(ax, CX + 0.4 + dw, L1_Y + 0.2, dw, 1.1, "외부 AI 모델", ["Google Cloud STT / TTS", "Gemini LLM (Flash)"])
    draw_component(ax, CX + 0.6 + dw * 2, L1_Y + 0.2, dw, 1.1, "파일 및 기타 연동", ["구조화 로그, WAV 녹음", "Google Calendar API"])

    # 화살표들
    arrow_props = dict(arrowstyle="<->", color="#94a3b8", lw=2.0)
    ax.annotate("", xy=(CX + W/2, L4_Y), xytext=(CX + W/2, L3_Y + L3_H), arrowprops=arrow_props, zorder=0)
    ax.annotate("", xy=(CX + W/2, L3_Y), xytext=(CX + W/2, L2_Y + L2_H), arrowprops=arrow_props, zorder=0)
    ax.annotate("", xy=(CX + W/2, L2_Y), xytext=(CX + W/2, L1_Y + L1_H), arrowprops=arrow_props, zorder=0)

    fig.savefig(out_path, bbox_inches='tight', pad_inches=0.1)
    plt.close(fig)
    print(f"Successfully generated: {out_path}")

if __name__ == "__main__":
    main()
