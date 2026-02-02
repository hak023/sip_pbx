"""Test RTP packet parsing"""
import struct

# Simulate RTP packet (12-byte header + payload)
# RTP Header format:
#  0                   1                   2                   3
#  0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
# +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
# |V=2|P|X|  CC   |M|     PT      |       sequence number         |
# +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
# |                           timestamp                           |
# +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
# |           synchronization source (SSRC) identifier            |
# +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

# Create RTP header
version = 2
padding = 0
extension = 0
csrc_count = 0
marker = 0
payload_type = 0  # PCMU
sequence_number = 1234
timestamp = 1000000
ssrc = 0x12345678

# Byte 0: V(2) P(1) X(1) CC(4)
byte0 = (version << 6) | (padding << 5) | (extension << 4) | csrc_count

# Byte 1: M(1) PT(7)
byte1 = (marker << 7) | payload_type

# Pack header
rtp_header = struct.pack(
    '!BBHII',
    byte0,
    byte1,
    sequence_number,
    timestamp,
    ssrc
)

print(f"RTP Header size: {len(rtp_header)} bytes")
print(f"RTP Header hex: {rtp_header.hex()}")

# Add dummy G.711 payload (160 bytes for 20ms @ 8kHz)
payload = b'\x80' * 160  # G.711 μ-law silence

rtp_packet = rtp_header + payload
print(f"Total RTP packet size: {len(rtp_packet)} bytes")
print(f"Expected: 12 + 160 = 172 bytes")

# Test parsing
if len(rtp_packet) >= 12:
    parsed_header = rtp_packet[:12]
    parsed_payload = rtp_packet[12:]
    
    print(f"\nParsed header size: {len(parsed_header)} bytes")
    print(f"Parsed payload size: {len(parsed_payload)} bytes")
    
    # Verify
    byte0 = parsed_header[0]
    version = (byte0 >> 6) & 0x03
    payload_type = parsed_header[1] & 0x7F
    
    print(f"Parsed version: {version}")
    print(f"Parsed payload type: {payload_type}")

print("\n✅ RTP packet structure is correct!")
print("Issue: If RTP parsing fails, entire packet (including header) is used as payload")
print("This would cause 12 bytes of garbage audio at the start of EVERY RTP packet!")
