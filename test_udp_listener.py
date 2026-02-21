import socket
import sys

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", 10000))
print("UDP 10000 포트 리스닝 중...")
print("단말 A에서 telnet 또는 UDP 패킷을 보내보세요.")
print("Ctrl+C로 종료")

try:
    while True:
        data, addr = sock.recvfrom(1024)
        print(f"패킷 수신: {addr} -> {data[:50]}")
except KeyboardInterrupt:
    print("\n종료")
    sock.close()
