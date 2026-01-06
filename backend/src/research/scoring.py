"""GPT-based relevance scoring for funding and compliance items.

This module scores research items by their relevance to a specific
product, audience, and use case.
"""
import json
from typing import List, Dict, Any, Optional

from openai import AsyncOpenAI

from ..config import get_settings

settings = get_settings()

# Scoring prompt template
SCORING_PROMPT = """Score this {item_type} for relevance to selling {product} to {audience} in {state}.

## Item to Score
{item}

## Product Context
{product_context}

## Scoring Criteria (each 0-20 points, total 0-100)
1. **Product Fit** (0-20): Does this directly support the product's use case?
   - 20: Perfect match (e.g., PD funding for PD product)
   - 10: Related (general EL funding)
   - 0: Unrelated
   
2. **Audience Match** (0-20): Is this relevant to the target audience?
   - 20: Directly affects their decisions/responsibilities
   - 10: Indirectly relevant
   - 0: Wrong audience
   
3. **Recency** (0-20): How current is this information?
   - 20: 2025-2026 active
   - 15: 2024-2025
   - 10: 2023-2024
   - 0: Older or unknown
   
4. **Specificity** (0-20): How concrete and actionable?
   - 20: Specific amounts, deadlines, requirements
   - 10: General information
   - 0: Vague or unclear
   
5. **Actionability** (0-20): Can they act on this now?
   - 20: Can apply/use immediately
   - 10: Requires planning
   - 0: FYI only

Return JSON:
{{
  "score": <total 0-100>,
  "breakdown": {{
    "product_fit": <0-20>,
    "audience_match": <0-20>,
    "recency": <0-20>,
    "specificity": <0-20>,
    "actionability": <0-20>
  }},
  "reason": "<1-2 sentence explanation>",
  "email_hook": "<1 sentence that could be used in an email>"
}}

JSON:"""


async def score_item(
    item: Dict[str, Any],
    item_type: str,  # "funding" or "compliance"
    product: str,
    audience: str,
    state: str,
    product_context: Optional[str] = None,
) -> Dict[str, Any]:
    """Score a single item for relevance.
    
    Args:
        item: The item to score (from Perplexity parsing)
        item_type: "funding" or "compliance"
        product: WCEPS product name
        audience: Target audience
        state: Target state
        product_context: RAG context about the product
    
    Returns:
        Original item with added score information
    """
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    # Format item for prompt
    item_text = json.dumps(item, indent=2)
    
    prompt = SCORING_PROMPT.format(
        item_type=item_type,
        product=product,
        audience=audience,
        state=state,
        item=item_text,
        product_context=product_context or f"No specific context. {product} is a WCEPS product for English Learner education.",
    )
    
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert at evaluating sales opportunities in K-12 education. Return only valid JSON."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=500,
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean JSON
        if content.startswith("```"):
            import re
            content = re.sub(r"```json?\n?", "", content)
            content = content.replace("```", "")
        
        score_data = json.loads(content)
        
        # Add score data to item
        return {
            **item,
            "score": score_data.get("score", 0),
            "score_breakdown": score_data.get("breakdown", {}),
            "score_reason": score_data.get("reason", ""),
            "email_hook": score_data.get("email_hook", ""),
        }
        
    except Exception as e:
        print(f"Error scoring item: {e}")
        # Return item with default low score
        return {
            **item,
            "score": 0,
            "score_reason": f"Scoring error: {str(e)}",
            "email_hook": "",
        }


async def score_items(
    items: List[Dict[str, Any]],
    item_type: str,
    product: str,
    audience: str,
    state: str,
    product_context: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Score multiple items and sort by score.
    
    Args:
        items: List of items to score
        item_type: "funding" or "compliance"
        product: WCEPS product name
        audience: Target audience
        state: Target state
        product_context: RAG context about the product
    
    Returns:
        Items with scores, sorted by score descending
    """
    import asyncio
    
    # Score all items concurrently
    tasks = [
        score_item(item, item_type, product, audience, state, product_context)
        for item in items
    ]
    
    scored_items = await asyncio.gather(*tasks)
    
    # Sort by score descending
    scored_items.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    return scored_items


async def get_top_items(
    items: List[Dict[str, Any]],
    item_type: str,
    product: str,
    audience: str,
    state: str,
    product_context: Optional[str] = None,
    top_n: int = 3,
    min_score: int = 50,
) -> List[Dict[str, Any]]:
    """Score items and return top N above minimum score.
    
    Args:
        items: List of items to score
        item_type: "funding" or "compliance"
        product: WCEPS product name
        audience: Target audience
        state: Target state
        product_context: RAG context about the product
        top_n: Number of top items to return (default 3)
        min_score: Minimum score threshold (default 50)
    
    Returns:
        Top N scored items above threshold
    """
    scored = await score_items(
        items, item_type, product, audience, state, product_context
    )
    
    # Filter by minimum score and take top N
    return [item for item in scored if item.get("score", 0) >= min_score][:top_n]
