"""WebSocket 서버 진입점. 실행: python -m src.websocket"""
import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 path에 넣어서 src.api 등 import 가능하게
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

if __name__ == "__main__":
    print("WebSocket 서버 기동 중... (모듈 로드에 20초 정도 걸릴 수 있음)", flush=True)
    try:
        from src.websocket.server import start_server
        asyncio.run(start_server())
    except Exception as e:
        print(f"WebSocket 서버 시작 실패: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
