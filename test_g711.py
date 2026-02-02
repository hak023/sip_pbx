"""Test G.711 codec encoding/decoding"""
import audioop
import wave
import struct

# Test G.711 μ-law codec
print("Testing G.711 μ-law codec...")

# Generate test PCM data (sine wave)
sample_rate = 8000
duration = 0.1  # 100ms
num_samples = int(sample_rate * duration)

# Generate sine wave (1000 Hz)
import math
samples = []
for i in range(num_samples):
    value = int(16000 * math.sin(2 * math.pi * 1000 * i / sample_rate))
    samples.append(value)

# Pack to PCM bytes (16-bit)
pcm_data = struct.pack(f'{len(samples)}h', *samples)
print(f"Original PCM: {len(pcm_data)} bytes, first 10 samples: {samples[:10]}")

# Encode to G.711 μ-law
ulaw_data = audioop.lin2ulaw(pcm_data, 2)
print(f"G.711 μ-law: {len(ulaw_data)} bytes")

# Decode back to PCM
decoded_pcm = audioop.ulaw2lin(ulaw_data, 2)
decoded_samples = struct.unpack(f'{len(decoded_pcm)//2}h', decoded_pcm)
print(f"Decoded PCM: {len(decoded_pcm)} bytes, first 10 samples: {decoded_samples[:10]}")

# Check if decoded is similar to original
print(f"\nOriginal first sample: {samples[0]}")
print(f"Decoded first sample: {decoded_samples[0]}")
print(f"Difference: {abs(samples[0] - decoded_samples[0])}")

# Save to WAV file for listening
wav_path = r'C:\work\workspace_sippbx\test_g711.wav'
with wave.open(wav_path, 'wb') as wav_file:
    wav_file.setnchannels(1)
    wav_file.setsampwidth(2)
    wav_file.setframerate(sample_rate)
    wav_file.writeframes(decoded_pcm)

print(f"\nTest WAV saved to: {wav_path}")
print("Play this file to verify G.711 codec is working correctly.")
