"""Document parser for ingesting .docx and .pdf files into the Knowledge Base.

This module handles parsing various document formats and extracting
structured content for the KB.
"""
import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from docx import Document as DocxDocument
from pypdf import PdfReader


# Document type patterns for auto-classification
DOC_TYPE_PATTERNS = {
    "buyers_guide": [r"buyer.*guide", r"state.*guide"],
    "statute": [r"statute", r"regulation", r"law", r"code"],
    "marketing": [r"marketing", r"content", r"email"],
    "funding_guide": [r"title.*[iI1]", r"title.*[iI]{2,3}", r"grant", r"funding"],
    "licensing": [r"licens", r"certif", r"endors", r"credential"],
}

# State name patterns for auto-tagging
STATE_PATTERNS = {
    "Alabama": ["alabama", "AL"],
    "Alaska": ["alaska", "AK"],
    "Arizona": ["arizona", "AZ"],
    "Arkansas": ["arkansas", "AR"],
    "California": ["california", "CA"],
    "Colorado": ["colorado", "CO"],
    "Connecticut": ["connecticut", "CT"],
    "Delaware": ["delaware", "DE"],
    "Florida": ["florida", "FL"],
    "Georgia": ["georgia", "GA"],
    "Hawaii": ["hawaii", "HI"],
    "Idaho": ["idaho", "ID"],
    "Illinois": ["illinois", "IL"],
    "Indiana": ["indiana", "IN"],
    "Iowa": ["iowa", "IA"],
    "Kansas": ["kansas", "KS"],
    "Kentucky": ["kentucky", "KY"],
    "Louisiana": ["louisiana", "LA"],
    "Maine": ["maine", "ME"],
    "Maryland": ["maryland", "MD"],
    "Massachusetts": ["massachusetts", "MA"],
    "Michigan": ["michigan", "MI"],
    "Minnesota": ["minnesota", "MN"],
    "Mississippi": ["mississippi", "MS"],
    "Missouri": ["missouri", "MO"],
    "Montana": ["montana", "MT"],
    "Nebraska": ["nebraska", "NE"],
    "Nevada": ["nevada", "NV"],
    "New Hampshire": ["new hampshire", "NH"],
    "New Jersey": ["new jersey", "NJ"],
    "New Mexico": ["new mexico", "NM"],
    "New York": ["new york", "NY"],
    "North Carolina": ["north carolina", "NC"],
    "North Dakota": ["north dakota", "ND"],
    "Ohio": ["ohio", "OH"],
    "Oklahoma": ["oklahoma", "OK"],
    "Oregon": ["oregon", "OR"],
    "Pennsylvania": ["pennsylvania", "PA"],
    "Rhode Island": ["rhode island", "RI"],
    "South Carolina": ["south carolina", "SC"],
    "South Dakota": ["south dakota", "SD"],
    "Tennessee": ["tennessee", "TN"],
    "Texas": ["texas", "TX"],
    "Utah": ["utah", "UT"],
    "Vermont": ["vermont", "VT"],
    "Virginia": ["virginia", "VA"],
    "Washington": ["washington", "WA"],
    "West Virginia": ["west virginia", "WV"],
    "Wisconsin": ["wisconsin", "WI"],
    "Wyoming": ["wyoming", "WY"],
}


def parse_docx(file_path: str) -> str:
    """Parse a .docx file and extract text content.
    
    Args:
        file_path: Path to the .docx file
    
    Returns:
        Extracted text content
    """
    doc = DocxDocument(file_path)
    paragraphs = []
    
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            paragraphs.append(text)
    
    # Also extract text from tables
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                paragraphs.append(row_text)
    
    return "\n\n".join(paragraphs)


def parse_pdf(file_path: str) -> str:
    """Parse a .pdf file and extract text content.
    
    Args:
        file_path: Path to the .pdf file
    
    Returns:
        Extracted text content
    """
    reader = PdfReader(file_path)
    pages = []
    
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text.strip())
    
    return "\n\n".join(pages)


def detect_state(file_path: str, content: str) -> Optional[str]:
    """Detect which state a document relates to.
    
    Args:
        file_path: Path to the file (may contain state in name)
        content: Document content
    
    Returns:
        State name if detected, None otherwise
    """
    # Check file path first (more reliable)
    path_lower = file_path.lower()
    
    for state, patterns in STATE_PATTERNS.items():
        for pattern in patterns:
            if pattern.lower() in path_lower:
                return state
    
    # Check content (first 500 chars for efficiency)
    content_start = content[:500].lower()
    for state, patterns in STATE_PATTERNS.items():
        for pattern in patterns:
            if pattern.lower() in content_start:
                return state
    
    return None


def detect_document_type(file_path: str, content: str) -> str:
    """Detect the type of document based on filename and content.
    
    Args:
        file_path: Path to the file
        content: Document content
    
    Returns:
        Document type string
    """
    combined = f"{file_path} {content[:500]}".lower()
    
    for doc_type, patterns in DOC_TYPE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, combined, re.IGNORECASE):
                return doc_type
    
    return "general"


def parse_document(file_path: str) -> Dict[str, Any]:
    """Parse a document and extract structured content.
    
    Args:
        file_path: Path to the document
    
    Returns:
        Dict with title, content, metadata
    """
    path = Path(file_path)
    extension = path.suffix.lower()
    
    # Parse based on file type
    if extension == ".docx":
        content = parse_docx(file_path)
    elif extension == ".pdf":
        content = parse_pdf(file_path)
    else:
        raise ValueError(f"Unsupported file type: {extension}")
    
    # Extract metadata
    filename = path.stem
    state = detect_state(file_path, content)
    doc_type = detect_document_type(file_path, content)
    
    # Clean up title from filename
    title = filename.replace("_", " ").replace("-", " ")
    title = re.sub(r"\s+", " ", title).strip()
    
    # Build tags
    tags = [doc_type]
    if state:
        tags.append(state.lower().replace(" ", "-"))
    
    return {
        "id": f"doc-{path.stem}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "title": title,
        "content": content,
        "document_type": doc_type,
        "applicable_states": [state] if state else None,
        "tags": tags,
        "source_file": str(path.name),
        "created_at": datetime.utcnow().isoformat(),
    }


def parse_folder(folder_path: str) -> List[Dict[str, Any]]:
    """Parse all documents in a folder (recursive).
    
    Args:
        folder_path: Path to the folder
    
    Returns:
        List of parsed document dicts
    """
    documents = []
    folder = Path(folder_path)
    
    # Find all .docx and .pdf files
    for file_path in folder.rglob("*"):
        if file_path.suffix.lower() in [".docx", ".pdf"]:
            try:
                print(f"Parsing: {file_path.name}")
                doc = parse_document(str(file_path))
                
                # Skip empty documents
                if len(doc["content"].strip()) < 50:
                    print(f"  Skipping (too short): {file_path.name}")
                    continue
                
                documents.append(doc)
                print(f"  ✓ Parsed: {len(doc['content'])} chars, type={doc['document_type']}, state={doc.get('applicable_states')}")
                
            except Exception as e:
                print(f"  ✗ Error parsing {file_path.name}: {e}")
    
    return documents


async def ingest_documents_to_kb(folder_path: str, db) -> Dict[str, Any]:
    """Parse all documents in a folder and add to the Knowledge Base.
    
    Args:
        folder_path: Path to the folder with documents
        db: Database session
    
    Returns:
        Summary of ingestion results
    """
    from ..db import KnowledgeBaseItem
    
    documents = parse_folder(folder_path)
    
    added = 0
    skipped = 0
    errors = []
    
    for doc in documents:
        try:
            # Create KB item
            kb_item = KnowledgeBaseItem(
                title=doc["title"],
                content=doc["content"],
                summary=doc["content"][:500] + "..." if len(doc["content"]) > 500 else doc["content"],
                category="state_research" if doc.get("applicable_states") else "product_info",
                document_type=doc["document_type"],
                tags=doc["tags"],
                applicable_states=doc.get("applicable_states"),
                file_name=doc.get("source_file"),
            )
            
            db.add(kb_item)
            added += 1
            
        except Exception as e:
            errors.append(f"{doc['title']}: {str(e)}")
            skipped += 1
    
    await db.commit()
    
    return {
        "total_files": len(documents),
        "added": added,
        "skipped": skipped,
        "errors": errors,
    }
