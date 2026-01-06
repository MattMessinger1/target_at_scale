"""Hybrid search combining semantic and keyword-based retrieval.

Merges results from:
1. ChromaDB semantic search (vector similarity)
2. SQLite keyword search (exact/fuzzy matching)

This improves both recall (keyword catches exact terms) and precision
(semantic captures meaning).
"""
from typing import List, Dict, Any, Optional
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from .embeddings import EmbeddingService, get_chroma_client, get_or_create_collection
from .query_expansion import expand_query, get_search_keywords
from ..db import KnowledgeBaseItem


# Weights for combining search results
SEMANTIC_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3


class HybridSearchService:
    """Service for hybrid semantic + keyword search."""
    
    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.chroma_client = get_chroma_client()
        self.collection = get_or_create_collection(self.chroma_client)
    
    def semantic_search(
        self,
        query: str,
        n_results: int = 20,
        filter_product: Optional[str] = None,
        filter_state: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Perform semantic search using ChromaDB.
        
        Args:
            query: Search query (will be embedded)
            n_results: Number of results to return
            filter_product: Optional product name filter
            filter_state: Optional state filter
        
        Returns:
            List of results with scores
        """
        # Generate query embedding
        query_embedding = self.embedding_service.embed_text(query)
        
        # Build where clause for filtering
        where_clause = None
        where_conditions = []
        
        if filter_product:
            where_conditions.append({"product_name": filter_product})
        if filter_state:
            # States stored as comma-separated string
            where_conditions.append({
                "applicable_states": {"$contains": filter_state}
            })
        
        if len(where_conditions) == 1:
            where_clause = where_conditions[0]
        elif len(where_conditions) > 1:
            where_clause = {"$and": where_conditions}
        
        # Query ChromaDB
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where_clause,
            include=["documents", "metadatas", "distances"],
        )
        
        # Format results
        formatted = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                # Convert distance to similarity score (cosine distance)
                distance = results["distances"][0][i] if results["distances"] else 0
                similarity = 1 - distance  # Convert distance to similarity
                
                formatted.append({
                    "id": doc_id,
                    "document": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "semantic_score": max(0, min(1, similarity)),  # Clamp to [0,1]
                    "source": "semantic",
                })
        
        return formatted
    
    async def keyword_search(
        self,
        db: AsyncSession,
        keywords: List[str],
        product: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Perform keyword-based search in SQLite.
        
        Args:
            db: Database session
            keywords: List of keywords to search for
            product: Optional product filter
            state: Optional state filter
            limit: Maximum results
        
        Returns:
            List of results with match scores
        """
        # Build OR conditions for keyword matching
        conditions = []
        for keyword in keywords:
            keyword_pattern = f"%{keyword}%"
            conditions.extend([
                KnowledgeBaseItem.title.ilike(keyword_pattern),
                KnowledgeBaseItem.content.ilike(keyword_pattern),
                KnowledgeBaseItem.summary.ilike(keyword_pattern),
            ])
        
        # Add product filter if specified
        if product:
            conditions.append(KnowledgeBaseItem.product_name.ilike(f"%{product}%"))
        
        # Build query
        query = select(KnowledgeBaseItem).where(or_(*conditions))
        
        # Add state filter if specified (states stored as JSON array)
        # Note: SQLite JSON handling
        if state:
            # This is a simplification - in production you'd want proper JSON querying
            query = query.where(
                KnowledgeBaseItem.applicable_states.cast(str).ilike(f"%{state}%")
            )
        
        query = query.limit(limit)
        
        result = await db.execute(query)
        items = result.scalars().all()
        
        # Calculate keyword match score based on how many keywords matched
        formatted = []
        for item in items:
            # Count keyword matches in title, content, summary
            match_count = 0
            searchable_text = f"{item.title or ''} {item.content or ''} {item.summary or ''}".lower()
            
            for keyword in keywords:
                if keyword.lower() in searchable_text:
                    match_count += 1
            
            # Normalize score
            keyword_score = match_count / len(keywords) if keywords else 0
            
            formatted.append({
                "id": item.id,
                "document": f"{item.title}\n{item.summary or ''}\n{item.content[:500] if item.content else ''}",
                "metadata": {
                    "category": item.category or "",
                    "subcategory": item.subcategory or "",
                    "product_name": item.product_name or "",
                    "title": item.title or "",
                    "source_id": item.id,
                },
                "keyword_score": keyword_score,
                "source": "keyword",
            })
        
        return formatted


async def hybrid_search(
    query: str,
    db: AsyncSession,
    product: Optional[str] = None,
    state: Optional[str] = None,
    n_results: int = 20,
    expand_query_terms: bool = True,
) -> List[Dict[str, Any]]:
    """Perform hybrid search combining semantic and keyword approaches.
    
    Args:
        query: Search query
        db: Database session
        product: Optional product filter
        state: Optional state filter
        n_results: Total results to return
        expand_query_terms: Whether to expand query with synonyms
    
    Returns:
        Merged and deduplicated results ranked by combined score
    """
    service = HybridSearchService()
    
    # Optionally expand query for semantic search
    search_query = query
    if expand_query_terms:
        search_query = expand_query(query, product, state)
    
    # Get keywords for keyword search
    keywords = get_search_keywords(product or "", state or "")
    # Add query terms as keywords too
    keywords.extend(query.split())
    keywords = list(set(keywords))
    
    # Perform both searches
    semantic_results = service.semantic_search(
        search_query,
        n_results=n_results * 2,  # Get more for merging
        filter_product=product,
        filter_state=state,
    )
    
    keyword_results = await service.keyword_search(
        db,
        keywords,
        product=product,
        state=state,
        limit=n_results * 2,
    )
    
    # Merge results
    merged = merge_search_results(
        semantic_results,
        keyword_results,
        semantic_weight=SEMANTIC_WEIGHT,
        keyword_weight=KEYWORD_WEIGHT,
    )
    
    # Return top n
    return merged[:n_results]


def merge_search_results(
    semantic_results: List[Dict[str, Any]],
    keyword_results: List[Dict[str, Any]],
    semantic_weight: float = 0.7,
    keyword_weight: float = 0.3,
) -> List[Dict[str, Any]]:
    """Merge and deduplicate results from different search sources.
    
    Uses source_id from metadata to deduplicate chunks from same document.
    
    Args:
        semantic_results: Results from semantic search
        keyword_results: Results from keyword search
        semantic_weight: Weight for semantic scores
        keyword_weight: Weight for keyword scores
    
    Returns:
        Merged results sorted by combined score
    """
    # Build lookup by source_id (original KB item)
    results_by_source = {}
    
    # Process semantic results
    for result in semantic_results:
        source_id = result.get("metadata", {}).get("source_id", result["id"])
        
        if source_id not in results_by_source:
            results_by_source[source_id] = {
                "id": source_id,
                "document": result["document"],
                "metadata": result["metadata"],
                "semantic_score": result.get("semantic_score", 0),
                "keyword_score": 0,
                "sources": ["semantic"],
            }
        else:
            # Keep highest semantic score for this source
            existing = results_by_source[source_id]
            if result.get("semantic_score", 0) > existing["semantic_score"]:
                existing["semantic_score"] = result["semantic_score"]
                existing["document"] = result["document"]
            if "semantic" not in existing["sources"]:
                existing["sources"].append("semantic")
    
    # Process keyword results
    for result in keyword_results:
        source_id = result.get("metadata", {}).get("source_id", result["id"])
        
        if source_id not in results_by_source:
            results_by_source[source_id] = {
                "id": source_id,
                "document": result["document"],
                "metadata": result["metadata"],
                "semantic_score": 0,
                "keyword_score": result.get("keyword_score", 0),
                "sources": ["keyword"],
            }
        else:
            existing = results_by_source[source_id]
            existing["keyword_score"] = max(
                existing["keyword_score"],
                result.get("keyword_score", 0)
            )
            if "keyword" not in existing["sources"]:
                existing["sources"].append("keyword")
    
    # Calculate combined scores
    results = list(results_by_source.values())
    for result in results:
        result["combined_score"] = (
            semantic_weight * result["semantic_score"] +
            keyword_weight * result["keyword_score"]
        )
        # Bonus for appearing in both searches
        if len(result["sources"]) > 1:
            result["combined_score"] *= 1.1  # 10% bonus
    
    # Sort by combined score
    results.sort(key=lambda x: x["combined_score"], reverse=True)
    
    return results
