"""
Organization Info Manager (Multi-tenant VectorDB 기반)

착신번호(owner) 기반으로 ChromaDB에서 테넌트 정보를 로드하여 관리한다.
기존 data/organization_info.json 의존성을 완전히 제거한다.

사용 흐름:
  1. SIP INVITE 수신 → callee 추출 (예: "1004")
  2. OrganizationInfoManager(owner="1004") 생성
  3. await manager.load() → VectorDB에서 tenant_config 로드
  4. manager.get_organization_name() → "기상청"
  5. manager.get_random_greeting_template() → "안녕하세요. 기상청 AI 비서입니다..."
"""

import json
import random
from typing import Dict, List, Optional, Any

import structlog

logger = structlog.get_logger(__name__)

# VectorDB에 tenant_config가 없을 때 사용할 기본값
DEFAULT_SYSTEM_PROMPT_TEMPLATE = (
    "당신은 {tenant_name}의 친절한 AI 통화 비서입니다.\n\n"
    "## 역할\n"
    "- 발신자의 질문에 정확하고 친절하게 답변\n"
    "- 간결하고 명확하게 1-2문장으로 답변\n"
    "- 모르는 것은 솔직히 인정하고 대안 제시\n\n"
    "## 제공 가능한 서비스\n{capabilities}\n"
)


class OrganizationInfoManager:
    """착신번호(owner) 기반 테넌트 정보 관리자
    
    VectorDB(ChromaDB)의 doc_type=tenant_config에서 테넌트 정보를 로드한다.
    """
    
    def __init__(self, owner: str, knowledge_service=None):
        """
        Args:
            owner: 착신번호 (예: "1004")
            knowledge_service: KnowledgeService 인스턴스 (VectorDB 접근용)
        """
        self.owner = owner
        self.knowledge_service = knowledge_service
        self.tenant_config: Dict[str, Any] = {}
        self._capabilities_cache: Optional[List[str]] = None
        self._loaded = False
    
    async def load(self) -> bool:
        """VectorDB에서 tenant_config 로드
        
        Returns:
            True if loaded successfully, False otherwise
        """
        if not self.knowledge_service or not self.owner:
            logger.warning("org_manager_no_service_or_owner",
                          owner=self.owner,
                          has_service=bool(self.knowledge_service))
            self._use_defaults()
            return False
        
        try:
            import asyncio
            vector_db = self.knowledge_service.vector_db
            
            # ChromaDB에서 tenant_config 조회
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: vector_db.collection.get(
                    where={"$and": [
                        {"doc_type": "tenant_config"},
                        {"owner": self.owner},
                    ]},
                    limit=1,
                    include=["documents", "metadatas"],
                ),
            )
            
            if results and results.get("ids") and len(results["ids"]) > 0:
                metadata = results["metadatas"][0] if results.get("metadatas") else {}
                self.tenant_config = metadata
                self._loaded = True
                
                logger.info("org_manager_loaded_from_vectordb",
                           owner=self.owner,
                           tenant_name=metadata.get("tenant_name", ""),
                           tenant_type=metadata.get("tenant_type", ""))
                return True
            else:
                logger.warning("org_manager_tenant_config_not_found",
                             owner=self.owner,
                             message="VectorDB에 tenant_config가 없습니다. 기본값 사용.")
                self._use_defaults()
                return False
                
        except Exception as e:
            logger.error("org_manager_load_failed",
                        owner=self.owner, error=str(e), exc_info=True)
            self._use_defaults()
            return False
    
    def _use_defaults(self):
        """기본값 설정"""
        self.tenant_config = {
            "tenant_name": "고객 센터",
            "tenant_type": "default",
            "description": "AI 통화 응대 시스템",
            "service_description": "일반 상담",
            "greeting_templates": json.dumps([
                "안녕하세요. AI 상담원입니다. 무엇을 도와드릴까요?"
            ], ensure_ascii=False),
        }
    
    def get_organization_name(self) -> str:
        """기관 이름 반환"""
        return self.tenant_config.get("tenant_name", "고객 센터")
    
    def get_organization_description(self) -> str:
        """기관 설명 반환"""
        return self.tenant_config.get("description", "")
    
    def get_service_description(self) -> str:
        """서비스 설명 반환"""
        return self.tenant_config.get("service_description", "")
    
    def get_greeting_templates(self) -> List[str]:
        """인사말 템플릿 목록 반환"""
        templates_raw = self.tenant_config.get("greeting_templates", "[]")
        try:
            if isinstance(templates_raw, str):
                return json.loads(templates_raw)
            elif isinstance(templates_raw, list):
                return templates_raw
        except (json.JSONDecodeError, TypeError):
            pass
        return ["안녕하세요. AI 상담원입니다. 무엇을 도와드릴까요?"]
    
    def get_random_greeting_template(self) -> str:
        """랜덤 인사말 템플릿 반환"""
        templates = self.get_greeting_templates()
        if not templates:
            return f"안녕하세요. {self.get_organization_name()} AI 비서입니다. 무엇을 도와드릴까요?"
        return random.choice(templates)
    
    def get_capabilities(self) -> List[str]:
        """제공 가능한 기능 목록 반환 (캐시된 값 사용)"""
        if self._capabilities_cache is not None:
            return self._capabilities_cache
        # 아직 로드되지 않았으면 빈 리스트 반환 (비동기 메서드 load_capabilities 필요)
        return []
    
    async def load_capabilities(self) -> List[str]:
        """VectorDB에서 owner의 활성 capabilities 조회 후 캐시"""
        if self._capabilities_cache is not None:
            return self._capabilities_cache
            
        if not self.knowledge_service:
            self._capabilities_cache = []
            return []
        
        try:
            caps = await self.knowledge_service.get_all_capabilities(
                owner=self.owner, active_only=True
            )
            self._capabilities_cache = [
                c.get("display_name", c.get("text", ""))
                for c in caps
                if c.get("display_name") or c.get("text")
            ]
            logger.info("org_manager_capabilities_loaded",
                       owner=self.owner,
                       count=len(self._capabilities_cache))
            return self._capabilities_cache
        except Exception as e:
            logger.warning("org_manager_capabilities_load_failed",
                          owner=self.owner, error=str(e))
            self._capabilities_cache = []
            return []
    
    def get_capabilities_text(self) -> str:
        """제공 가능한 기능을 텍스트로 반환"""
        capabilities = self.get_capabilities()
        if not capabilities:
            return "일반 상담"
        return ", ".join(capabilities)
    
    def get_system_prompt(self) -> str:
        """LLM 시스템 프롬프트 생성"""
        template = self.tenant_config.get(
            "system_prompt_template",
            DEFAULT_SYSTEM_PROMPT_TEMPLATE,
        )
        
        try:
            return template.format(
                tenant_name=self.get_organization_name(),
                capabilities=self.get_capabilities_text(),
            )
        except (KeyError, ValueError):
            # 템플릿에 예상치 못한 변수가 있을 경우 기본값
            return template
    
    def get_organization_context(self) -> str:
        """RAG용 기관 정보 컨텍스트 반환"""
        return f"""## 기관 정보
- 이름: {self.get_organization_name()}
- 설명: {self.tenant_config.get('description', 'N/A')}
- 서비스: {self.tenant_config.get('service_description', 'N/A')}
- 대표번호: {self.tenant_config.get('main_phone', 'N/A')}
- 웹사이트: {self.tenant_config.get('website', 'N/A')}
- 운영시간: {self.tenant_config.get('business_hours', 'N/A')}

## 제공 가능한 기능
{self.get_capabilities_text()}""".strip()
    
    def get_full_context_for_llm(self, user_query: Optional[str] = None) -> str:
        """LLM에 제공할 전체 컨텍스트 생성"""
        return self.get_organization_context()
    
    def to_dict(self) -> Dict[str, Any]:
        """기관 정보를 딕셔너리로 반환"""
        return self.tenant_config


# =============================================================================
# 팩토리 함수
# =============================================================================

async def create_org_manager(owner: str, knowledge_service=None) -> OrganizationInfoManager:
    """OrganizationInfoManager 생성 및 초기화 (비동기 팩토리)
    
    Args:
        owner: 착신번호 (예: "1004")
        knowledge_service: KnowledgeService 인스턴스
        
    Returns:
        초기화된 OrganizationInfoManager
    """
    manager = OrganizationInfoManager(owner=owner, knowledge_service=knowledge_service)
    await manager.load()
    await manager.load_capabilities()
    return manager


# 하위 호환용: 싱글톤은 더 이상 사용하지 않지만 import 에러 방지
def get_organization_manager(data_file: str = "data/organization_info.json") -> OrganizationInfoManager:
    """[Deprecated] 기존 호환용. 새 코드에서는 create_org_manager() 사용"""
    logger.warning("get_organization_manager_deprecated",
                  message="create_org_manager(owner, knowledge_service)를 사용하세요")
    manager = OrganizationInfoManager(owner="default")
    manager._use_defaults()
    return manager
