#!/usr/bin/env python3
"""간단한 SIP 테스트 클라이언트"""

import socket
import sys
import random

def send_sip_register(host='127.0.0.1', port=5060):
    """SIP REGISTER 메시지 전송"""
    
    branch = f"z9hG4bK{random.randint(100000, 999999)}"
    tag = f"tag{random.randint(1000, 9999)}"
    call_id = f"call-{random.randint(10000, 99999)}@{host}"
    
    # SIP REGISTER 메시지 생성
    message = (
        f"REGISTER sip:{host}:{port} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {host}:5080;branch={branch};rport\r\n"
        f"From: <sip:testuser@{host}>;tag={tag}\r\n"
        f"To: <sip:testuser@{host}>\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:testuser@{host}:5080>\r\n"
        f"Max-Forwards: 70\r\n"
        f"User-Agent: SIP-Test-Client/1.0\r\n"
        f"Expires: 3600\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )
    
    return message, "REGISTER"

def send_sip_options(host='127.0.0.1', port=5060):
    """SIP OPTIONS 메시지 전송"""
    
    branch = f"z9hG4bK{random.randint(100000, 999999)}"
    tag = f"tag{random.randint(1000, 9999)}"
    call_id = f"call-{random.randint(10000, 99999)}@{host}"
    
    # SIP OPTIONS 메시지 생성
    message = (
        f"OPTIONS sip:{host}:{port} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {host}:5080;branch={branch};rport\r\n"
        f"From: <sip:test@{host}>;tag={tag}\r\n"
        f"To: <sip:{host}>\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: 1 OPTIONS\r\n"
        f"Contact: <sip:test@{host}:5080>\r\n"
        f"Max-Forwards: 70\r\n"
        f"User-Agent: SIP-Test-Client/1.0\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )
    
    return message, "OPTIONS"

def send_sip_message(host='127.0.0.1', port=5060, message_type='OPTIONS'):
    """SIP 메시지 전송"""
    
    # 메시지 생성
    if message_type == 'REGISTER':
        message, method = send_sip_register(host, port)
    else:
        message, method = send_sip_options(host, port)
    
    # UDP 소켓 생성
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5.0)  # 5초 타임아웃
    
    try:
        print(f"📤 Sending SIP {method} to {host}:{port}")
        print("=" * 70)
        print(message)
        print("=" * 70)
        
        # 메시지 전송
        sock.sendto(message.encode('utf-8'), (host, port))
        print(f"✅ Message sent successfully ({len(message)} bytes)\n")
        
        # 응답 대기
        print("⏳ Waiting for response...")
        data, addr = sock.recvfrom(65535)
        
        print(f"📥 Response received from {addr[0]}:{addr[1]} ({len(data)} bytes)")
        print("=" * 70)
        print(data.decode('utf-8'))
        print("=" * 70)
        print("✅ Test successful!")
        
    except socket.timeout:
        print("❌ Timeout: No response received within 5 seconds")
        print("💡 Check if the server is running on the specified port")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    finally:
        sock.close()
    
    return True

if __name__ == '__main__':
    host = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5060
    msg_type = sys.argv[3] if len(sys.argv) > 3 else 'OPTIONS'
    
    print(f"🧪 SIP Test Client")
    print(f"Target: {host}:{port}")
    print(f"Message Type: {msg_type}\n")
    
    success = send_sip_message(host, port, msg_type)
    sys.exit(0 if success else 1)

