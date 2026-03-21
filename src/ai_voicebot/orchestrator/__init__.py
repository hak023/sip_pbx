"""
AI Orchestrator Module (Legacy)

AI 통화 응대의 레거시 경로입니다.
- 현재 기본 동작: config.pipeline_engine = "pipecat" → Pipecat 파이프라인 사용
  (factory.create_pipecat_pipeline_builder, pipeline_builder.build_and_run)
- pipeline_engine = "legacy" 일 때만 이 Orchestrator가 사용됩니다.
  (factory.create_ai_orchestrator → AIOrchestrator.handle_call)

수정·디버깅 시: 실제 AI 응대 로직은 대부분 sip-pbx/src/ai_voicebot/pipecat/ 에 있음.
"""

from .barge_in_controller import BargeInController
from .ai_orchestrator import AIOrchestrator

__all__ = ['AIOrchestrator', 'BargeInController']
