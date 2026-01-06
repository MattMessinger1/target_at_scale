"""RAG (Retrieval-Augmented Generation) module.

This module provides optimized semantic search capabilities for the Knowledge Base:
- text-embedding-3-large (3072 dimensions) for high-quality embeddings
- Smart chunking with overlap for better context capture
- Hybrid search (semantic + keyword)
- Query expansion for better recall
- GPT re-ranking for precision

Usage:
    from src.rag import query_optimized, get_product_context_optimized
    
    # Optimized search with full pipeline
    results = await query_optimized(query, db, product="WIDA PL", state="Florida")
    
    # Get comprehensive product context
    context = await get_product_context_optimized(product, audience, state, db)
"""
from .embeddings import (
    get_chroma_client,
    get_or_create_collection,
    embed_text,
    embed_kb_items,
    chunk_text,
    EmbeddingService,
    EMBEDDING_MODEL,
    EMBEDDING_DIMENSION,
)
from .query import (
    query_product_context,
    query_relevant_content,
    query_optimized,
    get_product_context_optimized,
    get_full_product_context_with_db,
    RAGService,
    WCEPS_PRODUCTS,
    AUDIENCES,
)
from .query_expansion import (
    expand_query,
    get_search_keywords,
    EXPANSION_MAP,
    PRODUCT_EXPANSIONS,
)
from .hybrid_search import (
    hybrid_search,
    merge_search_results,
    HybridSearchService,
)
from .reranker import (
    rerank_results,
    rerank_with_scores,
)

__all__ = [
    # Embeddings
    "get_chroma_client",
    "get_or_create_collection",
    "embed_text",
    "embed_kb_items",
    "chunk_text",
    "EmbeddingService",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSION",
    # Query (basic)
    "query_product_context",
    "query_relevant_content",
    "get_full_product_context_with_db",
    "RAGService",
    "WCEPS_PRODUCTS",
    "AUDIENCES",
    # Query (optimized) - RECOMMENDED
    "query_optimized",
    "get_product_context_optimized",
    # Query expansion
    "expand_query",
    "get_search_keywords",
    "EXPANSION_MAP",
    "PRODUCT_EXPANSIONS",
    # Hybrid search
    "hybrid_search",
    "merge_search_results",
    "HybridSearchService",
    # Re-ranking
    "rerank_results",
    "rerank_with_scores",
]
