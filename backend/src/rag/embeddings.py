"""Embeddings generation and storage using ChromaDB.

This module handles:
- Generating embeddings using OpenAI's text-embedding-3-large (3072 dims)
- Smart chunking with overlap for better context capture
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

# OpenAI embedding model - using large for better retrieval accuracy
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSION = 3072


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


def chunk_text(
    text: str, 
    chunk_size: int = 1500, 
    overlap: int = 200,
    min_chunk_size: int = 100
) -> List[str]:
    """Split text into overlapping chunks for better context capture.
    
    Args:
        text: Text to chunk
        chunk_size: Target size for each chunk (chars)
        overlap: Number of chars to overlap between chunks
        min_chunk_size: Minimum chunk size (skip tiny chunks)
    
    Returns:
        List of text chunks
    """
    if not text or len(text) <= chunk_size:
        return [text] if text else []
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        
        # Try to break at paragraph boundary for cleaner chunks
        if end < len(text):
            # Look for paragraph break
            last_para = chunk.rfind('\n\n')
            if last_para > chunk_size // 2:
                end = start + last_para + 2
                chunk = text[start:end]
            else:
                # Fall back to sentence boundary
                last_period = chunk.rfind('. ')
                if last_period > chunk_size // 2:
                    end = start + last_period + 2
                    chunk = text[start:end]
        
        # Only add if chunk is substantial
        if len(chunk.strip()) >= min_chunk_size:
            chunks.append(chunk.strip())
        
        # Move start position with overlap
        start = end - overlap if end < len(text) else len(text)
    
    return chunks


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
            Embedding vector (3072 dimensions with text-embedding-3-large)
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
    """Embed all KB items and store in ChromaDB with smart chunking.
    
    Uses overlapping chunks for long documents to capture more context.
    Each chunk becomes a separate embedding with shared metadata.
    
    Args:
        db: Database session
        batch_size: Number of chunks to embed at once
    
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
    
    # Prepare all chunks from all items
    all_chunks = []  # List of (id, text, metadata)
    
    for item in items:
        # Build base metadata for this item
        base_metadata = {
            "category": item.category or "",
            "subcategory": item.subcategory or "",
            "product_name": item.product_name or "",
            "document_type": item.document_type or "",
            "applicable_states": ",".join(item.applicable_states) if item.applicable_states else "",
            "title": item.title or "",
            "source_id": item.id,  # Track original item
        }
        
        # Create full text for chunking
        text_parts = [item.title or ""]
        if item.summary:
            text_parts.append(item.summary)
        if item.content:
            text_parts.append(item.content)
        
        full_text = "\n\n".join(filter(None, text_parts))
        
        # Chunk the text (handles short texts automatically)
        chunks = chunk_text(full_text, chunk_size=1500, overlap=200)
        
        # Create entry for each chunk
        for chunk_idx, chunk in enumerate(chunks):
            chunk_id = f"{item.id}_chunk_{chunk_idx}" if len(chunks) > 1 else item.id
            chunk_metadata = {
                **base_metadata,
                "chunk_index": chunk_idx,
                "total_chunks": len(chunks),
            }
            all_chunks.append((chunk_id, chunk, chunk_metadata))
    
    print(f"Created {len(all_chunks)} chunks from {len(items)} KB items")
    
    embedded_count = 0
    errors = []
    
    # Process chunks in batches
    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i:i + batch_size]
        
        try:
            ids = [c[0] for c in batch]
            texts = [c[1] for c in batch]
            metadatas = [c[2] for c in batch]
            
            # Generate embeddings
            embeddings = service.embed_batch(texts)
            
            # Store in ChromaDB
            service.add_to_collection(ids, embeddings, texts, metadatas)
            
            embedded_count += len(batch)
            print(f"Embedded {embedded_count}/{len(all_chunks)} chunks...")
            
        except Exception as e:
            errors.append(f"Batch {i}: {str(e)}")
    
    return {
        "total_items": len(items),
        "total_chunks": len(all_chunks),
        "embedded": embedded_count,
        "collection_count": service.get_collection_count(),
        "avg_chunks_per_item": len(all_chunks) / len(items) if items else 0,
        "errors": errors if errors else None,
    }


async def embed_kb_item_by_id(db: AsyncSession, item_id: str) -> Dict[str, Any]:
    """Embed a single KB item and add it to ChromaDB without clearing the collection.

    Useful for incremental updates (e.g., newly uploaded KB items).
    """
    if not item_id:
        return {"error": "item_id is required", "embedded": 0}

    # Fetch the KB item
    result = await db.execute(select(KnowledgeBaseItem).where(KnowledgeBaseItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        return {"error": f"KB item not found: {item_id}", "embedded": 0}

    service = EmbeddingService()

    # Base metadata mirrors embed_kb_items()
    base_metadata = {
        "category": item.category or "",
        "subcategory": item.subcategory or "",
        "product_name": item.product_name or "",
        "document_type": item.document_type or "",
        "applicable_states": ",".join(item.applicable_states) if item.applicable_states else "",
        "title": item.title or "",
        "source_id": item.id,
    }

    # Build text for chunking
    text_parts = [item.title or ""]
    if item.summary:
        text_parts.append(item.summary)
    if item.content:
        text_parts.append(item.content)
    full_text = "\n\n".join(filter(None, text_parts))

    chunks = chunk_text(full_text, chunk_size=1500, overlap=200)
    if not chunks:
        return {"error": "No content to embed", "embedded": 0}

    ids: List[str] = []
    texts: List[str] = []
    metadatas: List[Dict[str, Any]] = []

    for chunk_idx, chunk in enumerate(chunks):
        chunk_id = f"{item.id}_chunk_{chunk_idx}" if len(chunks) > 1 else item.id
        ids.append(chunk_id)
        texts.append(chunk)
        metadatas.append(
            {
                **base_metadata,
                "chunk_index": chunk_idx,
                "total_chunks": len(chunks),
            }
        )

    embeddings = service.embed_batch(texts)
    service.add_to_collection(ids, embeddings, texts, metadatas)

    return {
        "item_id": item.id,
        "embedded": len(ids),
        "total_chunks": len(chunks),
        "collection_count": service.get_collection_count(),
    }
