"""
Knowledge Base Components

Vector DB, Embedder, Knowledge Extractor, Extraction Pipeline v2
"""

from .embedder import TextEmbedder
from .vector_db import VectorDB, Document
from .chromadb_client import ChromaDBClient, get_chromadb_client, DEFAULT_PERSIST_DIRECTORY
from .knowledge_extractor import KnowledgeExtractor
from .extraction_pipeline import ExtractionPipeline

__all__ = [
    "TextEmbedder",
    "VectorDB",
    "Document",
    "ChromaDBClient",
    "get_chromadb_client",
    "DEFAULT_PERSIST_DIRECTORY",
    "KnowledgeExtractor",
    "ExtractionPipeline",
]

