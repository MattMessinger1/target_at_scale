#!/usr/bin/env python3
"""Regenerate all product briefs using enhanced hybrid search.

This script rebuilds briefs for all known products using both SQL and semantic
search (ChromaDB embeddings) to maximize KB content discovery.

Usage:
    cd backend
    source venv/bin/activate
    python scripts/regenerate_briefs.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# Set up the Python path correctly for imports
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir / "src"))
os.chdir(backend_dir)

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.config import get_settings
from src.research.product_briefs import (
    regenerate_all_briefs,
    get_brief_quality_report,
    DISPLAY_TO_KEY,
)


async def main():
    """Main entry point for brief regeneration."""
    settings = get_settings()
    
    # Create async engine
    # Handle both SQLite and PostgreSQL connection strings
    db_url = settings.database_url
    if db_url.startswith("sqlite:///"):
        # Convert to async SQLite URL
        db_url = db_url.replace("sqlite:///", "sqlite+aiosqlite:///")
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
    
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as db:
        print("=" * 60)
        print("PRODUCT BRIEF REGENERATION")
        print("Using hybrid search (SQL + ChromaDB semantic search)")
        print("=" * 60)
        print()
        
        # First, show current state
        print("1. Current Brief Quality Report:")
        print("-" * 40)
        try:
            report = await get_brief_quality_report(db)
            for product_key, info in report.items():
                status = info.get("status", "unknown")
                if status == "missing":
                    print(f"  {product_key}: MISSING")
                else:
                    fields = info.get("fields", {})
                    diffs = fields.get("differentiators", {}).get("count", 0)
                    cases = fields.get("case_studies", {}).get("count", 0)
                    semantic = "✓" if info.get("semantic_search_used") else "✗"
                    print(f"  {product_key}: diff={diffs}, cases={cases}, semantic={semantic}")
        except Exception as e:
            print(f"  Could not generate report: {e}")
        
        print()
        print("2. Regenerating all briefs with hybrid search...")
        print("-" * 40)
        
        try:
            results = await regenerate_all_briefs(db, force_rebuild=True)
            
            # Show successes
            if results["success"]:
                print("\n  ✓ Successfully regenerated:")
                for item in results["success"]:
                    product = item["product"]
                    diffs = item.get("differentiators_count", 0)
                    cases = item.get("case_studies_count", 0)
                    semantic = "yes" if item.get("semantic_search_used") else "no"
                    print(f"    - {product}: {diffs} differentiators, {cases} case studies, semantic={semantic}")
            
            # Show errors
            if results["errors"]:
                print("\n  ✗ Errors:")
                for item in results["errors"]:
                    print(f"    - {item['product']}: {item['error']}")
            
            # Show skipped
            if results["skipped"]:
                print("\n  ○ Skipped:")
                for item in results["skipped"]:
                    print(f"    - {item['product']}: {item['reason']}")
                    
        except Exception as e:
            print(f"  ERROR during regeneration: {e}")
            import traceback
            traceback.print_exc()
        
        print()
        print("3. Post-Regeneration Quality Report:")
        print("-" * 40)
        try:
            report = await get_brief_quality_report(db)
            for product_key, info in report.items():
                status = info.get("status", "unknown")
                if status == "missing":
                    print(f"  {product_key}: MISSING")
                else:
                    fields = info.get("fields", {})
                    diffs = fields.get("differentiators", {}).get("count", 0)
                    cases = fields.get("case_studies", {}).get("count", 0)
                    offerings = fields.get("offerings", {}).get("count", 0)
                    problems = fields.get("problems_solved", {}).get("count", 0)
                    semantic = "✓" if info.get("semantic_search_used") else "✗"
                    print(f"  {product_key}:")
                    print(f"    offerings={offerings}, problems={problems}")
                    print(f"    differentiators={diffs}, case_studies={cases}")
                    print(f"    semantic_search={semantic}")
        except Exception as e:
            print(f"  Could not generate report: {e}")
        
        print()
        print("=" * 60)
        print("DONE")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
