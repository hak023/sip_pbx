# Knowledge base: ChromaDB client and embedder for API.
# ContactKnowledgeExtractor / OrganizationInfoManager are used by pipeline
# and may live in this package or be provided by the caller.

from .contact_extractor import ContactKnowledgeExtractor

__all__ = ["ContactKnowledgeExtractor"]
