"""Knowledge Base deduplication using embedding similarity.

This module identifies and removes duplicate KB items by comparing
their embedding vectors. Items with cosine similarity > threshold
are considered duplicates.
"""
import asyncio
from typing import List, Tuple, Dict, Any, Optional
from datetime import datetime

import numpy as np
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import KnowledgeBaseItem


# Similarity threshold - items above this are considered duplicates
SIMILARITY_THRESHOLD = 0.95


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    a = np.array(vec1)
    b = np.array(vec2)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


async def find_duplicates(
    embeddings: Dict[str, List[float]],
    threshold: float = SIMILARITY_THRESHOLD
) -> List[Tuple[str, str, float]]:
    """Find duplicate pairs based on embedding similarity.
    
    Args:
        embeddings: Dict mapping item_id to embedding vector
        threshold: Similarity threshold (0.95 = 95% similar)
    
    Returns:
        List of (id1, id2, similarity) tuples for duplicates
    """
    duplicates = []
    item_ids = list(embeddings.keys())
    
    for i, id1 in enumerate(item_ids):
        for id2 in item_ids[i + 1:]:
            sim = cosine_similarity(embeddings[id1], embeddings[id2])
            if sim >= threshold:
                duplicates.append((id1, id2, sim))
    
    return duplicates


def choose_item_to_keep(item1: KnowledgeBaseItem, item2: KnowledgeBaseItem) -> str:
    """Decide which item to keep when duplicates are found.
    
    Keeps the item that is:
    1. Longer (more complete content)
    2. More recently created (if same length)
    
    Args:
        item1, item2: The two duplicate items
    
    Returns:
        ID of the item to keep
    """
    len1 = len(item1.content or "")
    len2 = len(item2.content or "")
    
    if len1 != len2:
        return item1.id if len1 > len2 else item2.id
    
    # Same length - keep newer
    time1 = item1.created_at or datetime.min
    time2 = item2.created_at or datetime.min
    
    return item1.id if time1 >= time2 else item2.id


async def deduplicate_kb(
    db: AsyncSession,
    embeddings: Dict[str, List[float]],
    threshold: float = SIMILARITY_THRESHOLD,
    dry_run: bool = True
) -> Dict[str, Any]:
    """Find and optionally remove duplicate KB items.
    
    Args:
        db: Database session
        embeddings: Dict mapping item_id to embedding vector
        threshold: Similarity threshold
        dry_run: If True, only report duplicates without removing
    
    Returns:
        Summary of deduplication results
    """
    # Find all duplicate pairs
    duplicate_pairs = await find_duplicates(embeddings, threshold)
    
    if not duplicate_pairs:
        return {
            "duplicates_found": 0,
            "items_removed": 0,
            "dry_run": dry_run,
        }
    
    # Group duplicates and decide which to keep
    items_to_remove = set()
    items_to_keep = set()
    duplicate_groups = []
    
    # Load all items involved in duplicates
    all_dup_ids = set()
    for id1, id2, _ in duplicate_pairs:
        all_dup_ids.add(id1)
        all_dup_ids.add(id2)
    
    result = await db.execute(
        select(KnowledgeBaseItem).where(KnowledgeBaseItem.id.in_(all_dup_ids))
    )
    items_by_id = {item.id: item for item in result.scalars().all()}
    
    # Process each duplicate pair
    for id1, id2, similarity in duplicate_pairs:
        item1 = items_by_id.get(id1)
        item2 = items_by_id.get(id2)
        
        if not item1 or not item2:
            continue
        
        keep_id = choose_item_to_keep(item1, item2)
        remove_id = id2 if keep_id == id1 else id1
        
        items_to_keep.add(keep_id)
        items_to_remove.add(remove_id)
        
        duplicate_groups.append({
            "keep": keep_id,
            "remove": remove_id,
            "similarity": round(similarity, 4),
            "keep_title": items_by_id[keep_id].title,
            "remove_title": items_by_id[remove_id].title,
        })
    
    # Remove items that are also in keep set (they're duplicates of something better)
    items_to_remove -= items_to_keep
    
    # Actually remove if not dry run
    if not dry_run and items_to_remove:
        await db.execute(
            delete(KnowledgeBaseItem).where(KnowledgeBaseItem.id.in_(items_to_remove))
        )
        await db.commit()
    
    return {
        "duplicates_found": len(duplicate_pairs),
        "items_to_remove": len(items_to_remove),
        "items_removed": len(items_to_remove) if not dry_run else 0,
        "dry_run": dry_run,
        "duplicate_groups": duplicate_groups[:20],  # Limit response size
    }
