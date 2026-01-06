"""Embeddings generation and storage using ChromaDB.

This module handles:
- Generating embeddings using OpenAI's text-embedding-3-small
- Storing and retrieving embeddings from ChromaDB
- Batch embedding of KB items
"""
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

import chromadb
from chromadb.config import Settings
from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import KnowledgeBaseItem
from ..config import get_settings

settings = get_settings()


# ChromaDB collection name
KB_COLLECTION_NAME = "knowledge_base"

# OpenAI embedding model
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536


def get_chroma_client() -> chromadb.Client:
    """Get ChromaDB client with persistent storage."""
    persist_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "chroma_db"
    )
    
    return chromadb.PersistentClient(path=persist_dir)


def get_or_create_collection(client: chromadb.Client, name: str = KB_COLLECTION_NAME):
    """Get or create a ChromaDB collection."""
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"}  # Use cosine similarity
    )


class EmbeddingService:
    """Service for generating and managing embeddings."""
    
    def __init__(self):
        self.openai_client = OpenAI(api_key=settings.openai_api_key)
        self.chroma_client = get_chroma_client()
        self.collection = get_or_create_collection(self.chroma_client)
    
    def embed_text(self, text: str) -> List[float]:
        """Generate embedding for a single text.
        
        Args:
            text: Text to embed
        
        Returns:
            Embedding vector (1536 dimensions)
        """
        # Truncate very long texts
        if len(text) > 8000:
            text = text[:8000]
        
        response = self.openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text,
        )
        
        return response.data[0].embedding
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts.
        
        Args:
            texts: List of texts to embed
        
        Returns:
            List of embedding vectors
        """
        # Truncate long texts
        texts = [t[:8000] if len(t) > 8000 else t for t in texts]
        
        response = self.openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
        )
        
        return [d.embedding for d in response.data]
    
    def add_to_collection(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict[str, Any]]
    ):
        """Add items to the ChromaDB collection.
        
        Args:
            ids: Unique identifiers
            embeddings: Pre-computed embeddings
            documents: Original text content
            metadatas: Metadata dicts for filtering
        """
        # Ensure all metadata values are valid types
        clean_metadatas = []
        for meta in metadatas:
            clean_meta = {}
            for k, v in meta.items():
                if v is None:
                    continue
                if isinstance(v, (str, int, float, bool)):
                    clean_meta[k] = v
                elif isinstance(v, list):
                    # Convert lists to comma-separated strings
                    clean_meta[k] = ",".join(str(x) for x in v)
                else:
                    clean_meta[k] = str(v)
            clean_metadatas.append(clean_meta)
        
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=clean_metadatas,
        )
    
    def get_collection_count(self) -> int:
        """Get number of items in the collection."""
        return self.collection.count()
    
    def clear_collection(self):
        """Clear all items from the collection."""
        # Delete and recreate
        self.chroma_client.delete_collection(KB_COLLECTION_NAME)
        self.collection = get_or_create_collection(self.chroma_client)


# Convenience functions

def embed_text(text: str) -> List[float]:
    """Generate embedding for text (convenience function)."""
    service = EmbeddingService()
    return service.embed_text(text)


async def embed_kb_items(db: AsyncSession, batch_size: int = 50) -> Dict[str, Any]:
    """Embed all KB items and store in ChromaDB.
    
    Args:
        db: Database session
        batch_size: Number of items to embed at once
    
    Returns:
        Summary of embedding results
    """
    service = EmbeddingService()
    
    # Get all KB items
    result = await db.execute(select(KnowledgeBaseItem))
    items = result.scalars().all()
    
    if not items:
        return {"error": "No KB items found", "embedded": 0}
    
    # Clear existing embeddings
    service.clear_collection()
    
    embedded_count = 0
    errors = []
    
    # Process in batches
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        
        try:
            # Prepare texts for embedding
            texts = []
            ids = []
            metadatas = []
            
            for item in batch:
                # Create searchable text from item
                text_parts = [item.title or ""]
                if item.summary:
                    text_parts.append(item.summary)
                if item.content:
                    # Use first 2000 chars of content
                    text_parts.append(item.content[:2000])
                
                text = "\n".join(text_parts)
                
                texts.append(text)
                ids.append(item.id)
                metadatas.append({
                    "category": item.category or "",
                    "subcategory": item.subcategory or "",
                    "product_name": item.product_name or "",
                    "document_type": item.document_type or "",
                    "applicable_states": ",".join(item.applicable_states) if item.applicable_states else "",
                    "title": item.title or "",
                })
            
            # Generate embeddings
            embeddings = service.embed_batch(texts)
            
            # Store in ChromaDB
            service.add_to_collection(ids, embeddings, texts, metadatas)
            
            embedded_count += len(batch)
            print(f"Embedded {embedded_count}/{len(items)} items...")
            
        except Exception as e:
            errors.append(f"Batch {i}: {str(e)}")
    
    return {
        "total_items": len(items),
        "embedded": embedded_count,
        "collection_count": service.get_collection_count(),
        "errors": errors if errors else None,
    }
