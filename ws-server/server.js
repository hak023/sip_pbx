/**
 * Socket.IO 서버 - 대시보드 WebSocket 연결 (포트 8001)
 *
 * ⚠️ 개발용 스텁: connection_established / 일부 이벤트 응답만 제공.
 *    SIP 통화의 call_started·call_ended·HITL 등은 송신하지 않음.
 *    실시간 통화·HITL 연동은 `python -m src.main` 이 띄우는
 *    Python Socket.IO(src/websocket/server.py, 동일 8001)를 사용할 것.
 *
 * 실행: npm install && npm start
 */
const { createServer } = require('http');
const { Server } = require('socket.io');

const PORT = Number(process.env.WS_PORT || 8001);
const CORS_ORIGIN = process.env.WS_CORS_ORIGIN || 'http://localhost:3000';

const httpServer = createServer();
const io = new Server(httpServer, {
  cors: {
    origin: CORS_ORIGIN,
    credentials: true,
  },
});

io.on('connection', (socket) => {
  const token = socket.handshake.auth?.token;
  console.log('[WS] Client connected', socket.id, token ? '(with token)' : '(no token)');

  socket.emit('connection_established', {
    message: 'Connected',
    timestamp: new Date().toISOString(),
  });

  socket.on('subscribe_call', (data, cb) => {
    if (typeof cb === 'function') {
      cb({ success: true, call_id: data?.call_id });
    }
  });

  socket.on('unsubscribe_call', () => {});

  socket.on('submit_hitl_response', (data, cb) => {
    if (typeof cb === 'function') {
      cb({ success: true });
    }
  });

  socket.on('disconnect', (reason) => {
    console.log('[WS] Client disconnected', socket.id, reason);
  });
});

httpServer.listen(PORT, () => {
  console.log(`Socket.IO server listening on http://0.0.0.0:${PORT}`);
  console.log(`CORS allowed origin: ${CORS_ORIGIN}`);
});
