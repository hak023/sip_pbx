# WebSocket 서버 (Socket.IO)

대시보드 실시간 연결용 Socket.IO 서버입니다. **대시보드에서 "연결 안 됨"이 나오지 않으려면 이 서버를 켜 두어야 합니다.**

## 실행

```bash
cd ws-server
npm install
npm start
```

기본 포트: **8001**  
환경 변수: `WS_PORT`, `WS_CORS_ORIGIN` (기본 `http://localhost:3000`)

## 동작

- 프론트엔드(localhost:3000)에서 로그인 후 대시보드 접속 시 Socket.IO로 이 서버에 연결합니다.
- 연결 시 `connection_established` 이벤트를 보내 대시보드에 "연결됨" 상태가 표시됩니다.
- `subscribe_call`, `submit_hitl_response` 등 이벤트는 추후 통화/오케스트레이터 연동 시 구현할 수 있습니다.
