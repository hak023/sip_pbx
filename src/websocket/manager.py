"""WebSocket Manager - Singleton for accessing WebSocket functions"""
from .server import (
    emit_call_started,
    emit_call_ended,
    emit_stt_transcript,
    emit_tts_started,
    emit_tts_completed,
    emit_hitl_requested,
    emit_knowledge_updated,
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
    'emit_hitl_requested',
    'emit_knowledge_updated',
    'broadcast_to_call',
    'broadcast_to_operators',
    'broadcast_global'
]

