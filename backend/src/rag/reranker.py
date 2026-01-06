"""GPT-based re-ranking for RAG retrieval.

After initial retrieval from hybrid search, uses GPT to re-rank
candidates based on relevance to the specific query and context.
This improves precision by leveraging GPT's understanding.
"""
import json
import logging
from typing import List, Dict, Any, Optional

from openai import AsyncOpenAI

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


RERANK_PROMPT = """You are a relevance ranking assistant for an education technology company that sells products for English Learner (EL) programs.

Your task is to re-rank the following {num_items} knowledge base items by their relevance to the query and context.

**Query:** {query}
**Product:** {product}
**Audience:** {audience}
**State:** {state}

**Knowledge Base Items:**
{items_text}

**Instructions:**
1. Rank items by how well they match the specific product, audience, and state context
2. Prioritize items that contain:
   - Direct product information (features, benefits, use cases)
   - Information specific to the target audience
   - State-specific compliance or requirements if applicable
   - Concrete examples, statistics, or case studies
3. Deprioritize items that are:
   - Too generic or not specific to the product
   - About different products or audiences
   - Outdated or less relevant

**Output:**
Return a JSON object with:
- "ranked_indices": Array of item indices (0-based) in order of relevance, most relevant first
- "reasoning": Brief explanation of top 3 rankings

Only include the top {top_k} most relevant items in ranked_indices.

Example output:
{{"ranked_indices": [3, 0, 7, 2, 5], "reasoning": "Item 3 directly addresses product features for the target audience. Item 0 contains state-specific compliance info..."}}
"""


async def rerank_results(
    candidates: List[Dict[str, Any]],
    query: str,
    product: str,
    audience: str = "EL Coordinators",
    state: str = "",
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Use GPT to re-rank retrieved candidates by relevance.
    
    Args:
        candidates: List of candidate results from hybrid search
        query: Original search query
        product: Product name for context
        audience: Target audience
        state: State for context
        top_k: Number of top results to return
    
    Returns:
        Re-ranked list of top_k most relevant results
    """
    if not candidates:
        return []
    
    if len(candidates) <= top_k:
        # No need to re-rank if we have fewer than requested
        return candidates
    
    # Format candidates for the prompt
    items_text = format_candidates_for_prompt(candidates)
    
    prompt = RERANK_PROMPT.format(
        num_items=len(candidates),
        query=query,
        product=product,
        audience=audience,
        state=state or "Any",
        items_text=items_text,
        top_k=top_k,
    )
    
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        
        response = await client.chat.completions.create(
            model="gpt-5.2-thinking",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,  # Low temperature for consistent ranking
            max_tokens=500,
        )
        
        result_text = response.choices[0].message.content
        result = json.loads(result_text)
        
        ranked_indices = result.get("ranked_indices", [])
        reasoning = result.get("reasoning", "")
        
        logger.info(f"GPT re-ranking reasoning: {reasoning[:200]}...")
        
        # Build re-ranked list
        reranked = []
        for idx in ranked_indices[:top_k]:
            if 0 <= idx < len(candidates):
                candidate = candidates[idx].copy()
                candidate["rerank_position"] = len(reranked) + 1
                reranked.append(candidate)
        
        # If GPT didn't return enough, fill with top combined_score items
        if len(reranked) < top_k:
            used_ids = {r["id"] for r in reranked}
            remaining = [c for c in candidates if c["id"] not in used_ids]
            remaining.sort(key=lambda x: x.get("combined_score", 0), reverse=True)
            reranked.extend(remaining[:top_k - len(reranked)])
        
        return reranked
        
    except Exception as e:
        logger.error(f"GPT re-ranking failed: {e}")
        # Fall back to combined_score ranking
        sorted_candidates = sorted(
            candidates,
            key=lambda x: x.get("combined_score", 0),
            reverse=True
        )
        return sorted_candidates[:top_k]


def format_candidates_for_prompt(candidates: List[Dict[str, Any]], max_chars: int = 500) -> str:
    """Format candidates for the GPT prompt.
    
    Args:
        candidates: List of candidate results
        max_chars: Maximum chars per candidate
    
    Returns:
        Formatted string for prompt
    """
    lines = []
    
    for i, candidate in enumerate(candidates):
        metadata = candidate.get("metadata", {})
        document = candidate.get("document", "")
        
        # Truncate document
        if len(document) > max_chars:
            document = document[:max_chars] + "..."
        
        title = metadata.get("title", "Untitled")
        product_name = metadata.get("product_name", "Unknown")
        category = metadata.get("category", "")
        
        lines.append(f"""
**[{i}] {title}**
- Product: {product_name}
- Category: {category}
- Content: {document}
""")
    
    return "\n".join(lines)


async def rerank_with_scores(
    candidates: List[Dict[str, Any]],
    query: str,
    product: str,
    audience: str = "EL Coordinators",
    state: str = "",
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Re-rank and also get individual relevance scores from GPT.
    
    Similar to rerank_results but also asks GPT to score each item.
    More expensive but provides richer information.
    
    Args:
        candidates: List of candidate results
        query: Original search query
        product: Product name
        audience: Target audience
        state: State context
        top_k: Number of results
    
    Returns:
        Re-ranked results with GPT relevance scores
    """
    if not candidates:
        return []
    
    if len(candidates) <= 3:
        # For very small sets, just return as-is
        return candidates
    
    score_prompt = f"""Score these {len(candidates)} knowledge base items for relevance to:
Query: {query}
Product: {product}
Audience: {audience}
State: {state or "Any"}

Items:
{format_candidates_for_prompt(candidates)}

Return JSON with:
- "scores": Array of objects with "index" (0-based) and "score" (0-100)
- "top_indices": Top {top_k} indices in order of relevance

Score criteria:
- 90-100: Directly answers the query with product-specific information
- 70-89: Highly relevant, contains useful context
- 50-69: Somewhat relevant, tangentially related
- 30-49: Marginally relevant
- 0-29: Not relevant
"""

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        
        response = await client.chat.completions.create(
            model="gpt-5.2-thinking",
            messages=[{"role": "user", "content": score_prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=1000,
        )
        
        result = json.loads(response.choices[0].message.content)
        
        scores = {s["index"]: s["score"] for s in result.get("scores", [])}
        top_indices = result.get("top_indices", [])
        
        # Build result with scores
        reranked = []
        for idx in top_indices[:top_k]:
            if 0 <= idx < len(candidates):
                candidate = candidates[idx].copy()
                candidate["gpt_relevance_score"] = scores.get(idx, 50)
                candidate["rerank_position"] = len(reranked) + 1
                reranked.append(candidate)
        
        return reranked
        
    except Exception as e:
        logger.error(f"GPT scoring failed: {e}")
        # Fall back to simple rerank
        return await rerank_results(candidates, query, product, audience, state, top_k)
