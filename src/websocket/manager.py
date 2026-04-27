"""WebSocket Manager - Singleton for accessing WebSocket functions"""
from .server import (
    emit_call_started,
    emit_call_ended,
    emit_stt_transcript,
    emit_tts_started,
    emit_tts_completed,
    emit_ai_greeting,
    emit_hitl_requested,
    emit_hitl_fallback_available,
    emit_hitl_timeout,
    emit_knowledge_updated,
    emit_transfer_initiated,
    emit_transfer_ringing,
    emit_transfer_success,
    emit_transfer_failed,
    emit_ringback_music_ready,
    emit_ringback_music_failed,
    broadcast_to_call,
    broadcast_to_operators,
    broadcast_global
)

__all__ = [
    'emit_call_started',
    'emit_call_ended',
    'emit_stt_transcript',
    'emit_tts_started',
    'emit_tts_completed',
    'emit_ai_greeting',
    'emit_hitl_requested',
    'emit_hitl_fallback_available',
    'emit_hitl_timeout',
    'emit_knowledge_updated',
    'emit_transfer_initiated',
    'emit_transfer_ringing',
    'emit_transfer_success',
    'emit_transfer_failed',
    'emit_ringback_music_ready',
    'emit_ringback_music_failed',
    'broadcast_to_call',
    'broadcast_to_operators',
    'broadcast_global'
]
