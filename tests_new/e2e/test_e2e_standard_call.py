"""
End-to-End Tests - Standard SIP Call

표준 SIP 통화 전체 흐름 테스트
"""

import pytest
import asyncio
from datetime import datetime
from pathlib import Path

from tests.helpers.sip_client import SIPClient
from tests.helpers.test_utils import wait_for_condition


class TestE2EStandardCall:
    """표준 SIP 통화 E2E 테스트"""
    
    @pytest.fixture
    async def sip_clients(self):
        """SIP 클라이언트 A, B 생성"""
        client_a = SIPClient(username="1001", display_name="User A")
        client_b = SIPClient(username="1002", display_name="User B")
        
        await client_a.start()
        await client_b.start()
        
        yield client_a, client_b
        
        await client_a.stop()
        await client_b.stop()
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_standard_call_full_flow(self, sip_clients):
        """
        TC-SIP-001: 표준 통화 흐름
        
        Given: 사용자 A와 B가 등록됨
        When: A가 B에게 INVITE 전송
        Then: 
          - PBX가 100 Trying 응답
          - PBX가 B에게 INVITE 전달
          - B가 180 Ringing 응답
          - B가 200 OK 응답
          - A가 ACK 전송
          - 양방향 RTP 스트림 시작
          - A가 BYE 전송
          - CDR 생성 및 저장
        """
        # Given
        client_a, client_b = sip_clients
        
        # REGISTER
        assert await client_a.register(), "Client A registration failed"
        assert await client_b.register(), "Client B registration failed"
        
        # When - INVITE
        call_session_a = await client_a.invite(target="1002@localhost")
        
        # Then - 100 Trying
        assert call_session_a.state == "TRYING"
        
        # Then - B receives INVITE and auto-answers after 2 seconds
        await asyncio.sleep(2)
        await client_b.auto_answer()
        
        # Then - 180 Ringing
        await wait_for_condition(
            lambda: call_session_a.state == "RINGING",
            timeout=5,
            error_msg="Expected RINGING state"
        )
        
        # Then - 200 OK
        await wait_for_condition(
            lambda: call_session_a.state == "ESTABLISHED",
            timeout=5,
            error_msg="Expected ESTABLISHED state"
        )
        
        # Then - RTP 스트림 시작
        assert call_session_a.media_session is not None
        assert call_session_a.media_session.is_active
        
        # RTP 패킷 전송 (5초)
        await client_a.send_rtp_audio(duration=5)
        await asyncio.sleep(5)
        
        # Verify RTP received by B
        rtp_stats_b = await client_b.get_rtp_stats()
        assert rtp_stats_b["packets_received"] > 0
        assert rtp_stats_b["packets_lost"] < rtp_stats_b["packets_received"] * 0.01  # < 1% loss
        
        # When - BYE
        await client_a.bye()
        
        # Then - Call terminated
        await wait_for_condition(
            lambda: call_session_a.state == "TERMINATED",
            timeout=5,
            error_msg="Expected TERMINATED state"
        )
        
        # Then - CDR 생성 확인
        cdr_file = Path(f"./logs/cdr/{datetime.now().strftime('%Y%m%d')}.jsonl")
        assert cdr_file.exists(), "CDR file not created"
        
        with open(cdr_file, 'r') as f:
            last_line = f.readlines()[-1]
            cdr_data = eval(last_line)  # JSON parse
            assert cdr_data["caller_uri"] == "sip:1001@localhost"
            assert cdr_data["callee_uri"] == "sip:1002@localhost"
            assert cdr_data["duration_seconds"] >= 5
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_call_cancel_before_answer(self, sip_clients):
        """
        TC-SIP-002: CANCEL 처리
        
        Given: A→B INVITE 진행 중 (180 Ringing)
        When: A가 CANCEL 전송
        Then: 
          - PBX가 487 Request Terminated 응답
          - PBX가 B에게 CANCEL 전달
          - 통화 설정 취소됨
        """
        # Given
        client_a, client_b = sip_clients
        await client_a.register()
        await client_b.register()
        
        # INVITE
        call_session_a = await client_a.invite(target="1002@localhost")
        
        # Wait for RINGING
        await wait_for_condition(
            lambda: call_session_a.state == "RINGING",
            timeout=5
        )
        
        # When - CANCEL
        await client_a.cancel()
        
        # Then - 487 Request Terminated
        await wait_for_condition(
            lambda: call_session_a.state == "TERMINATED",
            timeout=5
        )
        assert call_session_a.termination_reason == "CANCELLED"
        
        # B should also receive CANCEL
        call_session_b = client_b.get_active_call()
        assert call_session_b.state == "TERMINATED"
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_rtp_relay_low_latency(self, sip_clients):
        """
        Performance Test: RTP Relay 지연 < 5ms
        
        Given: A↔B 통화 중
        When: RTP 패킷 전송
        Then: Relay 지연 < 5ms
        """
        # Given
        client_a, client_b = sip_clients
        await client_a.register()
        await client_b.register()
        
        call_session_a = await client_a.invite(target="1002@localhost")
        await client_b.auto_answer()
        await wait_for_condition(lambda: call_session_a.state == "ESTABLISHED", timeout=5)
        
        # When - Send timestamped RTP packets
        latencies = []
        for i in range(100):
            sent_time = datetime.now()
            await client_a.send_rtp_packet_with_timestamp(sent_time)
            await asyncio.sleep(0.02)  # 20ms 간격
            
            # Measure receive time at B
            received_packet = await client_b.get_last_received_packet()
            if received_packet:
                receive_time = datetime.now()
                latency = (receive_time - sent_time).total_seconds() * 1000  # ms
                latencies.append(latency)
        
        # Then - Average latency < 5ms
        avg_latency = sum(latencies) / len(latencies)
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]
        
        assert avg_latency < 5.0, f"Average latency {avg_latency}ms > 5ms"
        assert p95_latency < 10.0, f"P95 latency {p95_latency}ms > 10ms"
        
        print(f"RTP Relay Performance: Avg={avg_latency:.2f}ms, P95={p95_latency:.2f}ms")

