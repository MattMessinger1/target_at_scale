"""RAG query functions for semantic search.

This module provides functions to retrieve relevant KB content
based on product, audience, and state selections.
"""
from typing import List, Dict, Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .embeddings import EmbeddingService, get_chroma_client, get_or_create_collection
from ..db import KnowledgeBaseItem


# WCEPS Products (for validation)
WCEPS_PRODUCTS = [
    "CARE Coaching",
    "WIDA Professional Learning",
    "WebbAlign",
    "CALL",
    "The Discussion Project",
    "WIDA MODEL Online",
    "WIDA SIS",
]

# Target audiences
AUDIENCES = [
    "District Leadership",
    "Curriculum Directors",
    "ELL/Multilingual Directors",
    "Principals",
    "Teachers",
    "Title III Coordinators",
]


class RAGService:
    """Service for RAG-based semantic search."""
    
    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.chroma_client = get_chroma_client()
        self.collection = get_or_create_collection(self.chroma_client)
    
    def query(
        self,
        query_text: str,
        n_results: int = 10,
        filter_product: Optional[str] = None,
        filter_state: Optional[str] = None,
        filter_category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query the KB for relevant content.
        
        Args:
            query_text: Natural language query
            n_results: Number of results to return
            filter_product: Optional product name filter
            filter_state: Optional state filter
            filter_category: Optional category filter
        
        Returns:
            List of matching documents with metadata and scores
        """
        # Generate query embedding
        query_embedding = self.embedding_service.embed_text(query_text)
        
        # Build where clause for filters
        where_clause = None
        where_conditions = []
        
        if filter_product:
            where_conditions.append({"product_name": filter_product})
        if filter_category:
            where_conditions.append({"category": filter_category})
        
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
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                # Convert distance to similarity (cosine)
                distance = results["distances"][0][i] if results["distances"] else 0
                similarity = 1 - distance  # Cosine distance to similarity
                
                formatted.append({
                    "id": doc_id,
                    "content": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "similarity": round(similarity, 4),
                })
        
        # Filter by state if specified (done post-query due to ChromaDB limitations with contains)
        if filter_state and formatted:
            formatted = [
                r for r in formatted
                if filter_state.lower() in r["metadata"].get("applicable_states", "").lower()
            ]
        
        return formatted
    
    def get_product_context(
        self,
        product_name: str,
        audience: Optional[str] = None,
        state: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get comprehensive product context for email generation.
        
        This is the main RAG function - it retrieves all relevant
        information about a product to inform Perplexity searches
        and email generation.
        
        Args:
            product_name: WCEPS product name
            audience: Target audience
            state: Target state
        
        Returns:
            Dict with product context including value props, use cases, etc.
        """
        context = {
            "product_name": product_name,
            "audience": audience,
            "state": state,
            "value_propositions": [],
            "use_cases": [],
            "case_studies": [],
            "talking_points": [],
            "state_specific": [],
            "raw_content": [],
        }
        
        # Query 1: General product info
        product_query = f"What is {product_name}? What are its key features and benefits for English Learner programs?"
        product_results = self.query(
            product_query,
            n_results=5,
            filter_product=product_name,
        )
        
        for r in product_results:
            context["raw_content"].append(r["content"])
            if r["metadata"].get("subcategory") == "value_proposition":
                context["value_propositions"].append(r["content"])
            elif r["metadata"].get("category") == "case_study":
                context["case_studies"].append(r["content"])
        
        # Query 2: Audience-specific content
        if audience:
            audience_query = f"How does {product_name} help {audience} support English Learners?"
            audience_results = self.query(
                audience_query,
                n_results=3,
                filter_product=product_name,
            )
            for r in audience_results:
                if r["content"] not in context["raw_content"]:
                    context["raw_content"].append(r["content"])
                    context["talking_points"].append(r["content"])
        
        # Query 3: Use cases
        use_case_query = f"What problems does {product_name} solve? When should districts use it?"
        use_case_results = self.query(
            use_case_query,
            n_results=3,
            filter_product=product_name,
        )
        for r in use_case_results:
            if r["content"] not in context["raw_content"]:
                context["use_cases"].append(r["content"])
        
        # Query 4: State-specific content (filter by state)
        if state:
            state_query = f"{product_name} {state} English Learner programs requirements"
            state_results = self.query(
                state_query,
                n_results=3,
                filter_state=state,
            )
            for r in state_results:
                context["state_specific"].append(r["content"])
        
        # Query 5: State funding and compliance info (broader search for state documents)
        if state:
            # Search for any KB content about state funding, grants, CSI/TSI, compliance
            funding_query = f"{state} funding grants CSI TSI school improvement Title I Title III EL programs"
            funding_results = self.query(
                funding_query,
                n_results=5,
                filter_state=state,
            )
            for r in funding_results:
                if r["content"] not in context["state_specific"]:
                    context["state_specific"].append(r["content"])
            
            # Search for compliance/requirements
            compliance_query = f"{state} compliance requirements certification ESOL endorsement professional development EL"
            compliance_results = self.query(
                compliance_query,
                n_results=5,
                filter_state=state,
            )
            for r in compliance_results:
                if r["content"] not in context["state_specific"]:
                    context["state_specific"].append(r["content"])
            
            # Also search without state filter but with state name in query
            # This catches documents that mention the state but aren't tagged with it
            broader_query = f"{state} state funding grants school improvement CSI TSI"
            broader_results = self.query(
                broader_query,
                n_results=5,
            )
            for r in broader_results:
                content = r["content"]
                # Only include if it actually mentions the state
                if state.lower() in content.lower() and content not in context["state_specific"]:
                    context["state_specific"].append(content)
        
        # Build summary for Perplexity
        context["summary_for_research"] = self._build_research_summary(context)
        
        return context
    
    def _build_research_summary(self, context: Dict[str, Any]) -> str:
        """Build a concise summary for Perplexity research queries.
        
        This summary includes product info AND state-specific context from KB
        to inform Perplexity's research with our internal knowledge.
        """
        parts = [f"Product: {context['product_name']}"]
        
        if context["value_propositions"]:
            parts.append(f"Value: {context['value_propositions'][0][:200]}")
        
        if context["use_cases"]:
            parts.append(f"Use case: {context['use_cases'][0][:200]}")
        
        if context["audience"]:
            parts.append(f"Target audience: {context['audience']}")
        
        # Include state-specific KB content to inform research
        if context["state_specific"]:
            state_info = "\n\nKnown state information from our knowledge base:"
            for i, content in enumerate(context["state_specific"][:3]):
                # Truncate each piece but include key info
                truncated = content[:400] if len(content) > 400 else content
                state_info += f"\n- {truncated}"
            parts.append(state_info)
        
        return "\n".join(parts)


# Convenience functions

def query_relevant_content(
    query: str,
    n_results: int = 10,
    product: Optional[str] = None,
    state: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query KB for relevant content (convenience function)."""
    service = RAGService()
    return service.query(query, n_results, filter_product=product, filter_state=state)


def query_product_context(
    product_name: str,
    audience: Optional[str] = None,
    state: Optional[str] = None,
) -> Dict[str, Any]:
    """Get product context for research and generation (convenience function)."""
    service = RAGService()
    return service.get_product_context(product_name, audience, state)


async def get_full_product_context_with_db(
    product_name: str,
    audience: Optional[str],
    state: Optional[str],
    db: AsyncSession,
) -> Dict[str, Any]:
    """Get product context with additional DB lookups.
    
    This function combines RAG results with direct DB queries
    for the most comprehensive context.
    """
    # Get RAG context
    context = query_product_context(product_name, audience, state)
    
    # Add direct DB lookups for specific content types
    query = select(KnowledgeBaseItem).where(
        KnowledgeBaseItem.product_name == product_name
    )
    result = await db.execute(query)
    items = result.scalars().all()
    
    # Organize by subcategory
    by_subcategory = {}
    for item in items:
        subcat = item.subcategory or "general"
        if subcat not in by_subcategory:
            by_subcategory[subcat] = []
        by_subcategory[subcat].append({
            "title": item.title,
            "content": item.content[:500] if item.content else "",
            "summary": item.summary,
        })
    
    context["by_subcategory"] = by_subcategory
    context["total_kb_items"] = len(items)
    
    return context
