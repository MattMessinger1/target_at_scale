"""RAG (Retrieval-Augmented Generation) module.

This module provides semantic search capabilities for the Knowledge Base
using ChromaDB for vector storage and OpenAI embeddings.
"""
from .embeddings import (
    get_chroma_client,
    get_or_create_collection,
    embed_text,
    embed_kb_items,
    EmbeddingService,
)
from .query import (
    query_product_context,
    query_relevant_content,
    RAGService,
)

__all__ = [
    "get_chroma_client",
    "get_or_create_collection",
    "embed_text",
    "embed_kb_items",
    "EmbeddingService",
    "query_product_context",
    "query_relevant_content",
    "RAGService",
]
