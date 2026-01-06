"""Query expansion for improved RAG retrieval.

Expands user queries with related terms and synonyms to improve recall
when searching the knowledge base.
"""
from typing import Optional


# Education/EL domain abbreviation expansions
EXPANSION_MAP = {
    # Assessment & Testing
    "WIDA": "WIDA ACCESS English proficiency assessment testing ELP",
    "ACCESS": "ACCESS for ELLs English language proficiency assessment",
    "ELP": "English language proficiency assessment standards",
    "ELPA": "English Language Proficiency Assessment",
    
    # Student populations
    "EL": "English learner ELL multilingual emergent bilingual LEP",
    "ELL": "English language learner EL multilingual",
    "LEP": "limited English proficient EL ELL",
    "SLIFE": "students with limited interrupted formal education newcomer",
    "LTELL": "long-term English learner reclassification",
    
    # Professional development
    "PD": "professional development training certification workshop",
    "ESOL": "English speakers other languages ESL certification endorsement",
    "ESL": "English second language ESOL teaching certification",
    "SEI": "Structured English Immersion sheltered instruction",
    
    # School designations
    "CSI": "Comprehensive Support Improvement underperforming schools turnaround",
    "TSI": "Targeted Support Improvement subgroup performance",
    "ATSI": "Additional Targeted Support Improvement",
    
    # Funding
    "ESSER": "Elementary Secondary School Emergency Relief pandemic funding",
    "ARP": "American Rescue Plan funding COVID relief",
    "IDEA": "Individuals Disabilities Education Act special education",
    
    # Compliance & Legal
    "DOJ": "Department of Justice civil rights investigation consent decree",
    "OCR": "Office Civil Rights complaint discrimination investigation",
    "ESSA": "Every Student Succeeds Act accountability compliance",
    
    # Instruction
    "SIOP": "Sheltered Instruction Observation Protocol lesson planning",
    "GLAD": "Guided Language Acquisition Design instruction strategies",
    "DLI": "dual language immersion bilingual program",
    
    # Products (WCEPS-specific)
    "ELLEVATION": "Ellevation platform EL management tracking",
    "FLASHLIGHT": "Flashlight 360 instructional practice observation",
    "AVANT": "Avant assessment language proficiency testing",
}

# Product name expansions
PRODUCT_EXPANSIONS = {
    "ellevation": "Ellevation platform EL student management tracking progress monitoring",
    "flashlight": "Flashlight 360 instructional practice observation coaching feedback",
    "avant": "Avant assessment language proficiency testing placement STAMP",
    "wceps": "Wisconsin Center Education Products Services assessment professional development",
}


def expand_query(
    query: str,
    product: Optional[str] = None,
    state: Optional[str] = None,
    include_product_context: bool = True
) -> str:
    """Expand query with related terms for better RAG recall.
    
    Args:
        query: Original search query
        product: Product name to add context for
        state: State name to add context for
        include_product_context: Whether to append product/state context
    
    Returns:
        Expanded query string
    """
    expanded_parts = [query]
    query_upper = query.upper()
    
    # Add expansions for detected abbreviations
    for abbrev, expansion in EXPANSION_MAP.items():
        if abbrev in query_upper:
            # Don't duplicate if expansion terms already present
            if expansion.split()[0].lower() not in query.lower():
                expanded_parts.append(expansion)
    
    # Add product-specific expansions
    if product:
        product_lower = product.lower()
        for prod_key, prod_expansion in PRODUCT_EXPANSIONS.items():
            if prod_key in product_lower:
                expanded_parts.append(prod_expansion)
                break
    
    # Add context for product and state if requested
    if include_product_context:
        if product and product.lower() not in query.lower():
            expanded_parts.append(product)
        if state and state.lower() not in query.lower():
            expanded_parts.append(state)
    
    return " ".join(expanded_parts)


def get_search_keywords(product: str, state: str) -> list[str]:
    """Extract key search terms for keyword matching.
    
    Args:
        product: Product name
        state: State name
    
    Returns:
        List of keywords for exact/fuzzy matching
    """
    keywords = []
    
    # Add product variations
    if product:
        keywords.append(product)
        # Add without spaces/special chars
        keywords.append(product.replace(" ", "").lower())
        # Check for known products
        for prod_key in PRODUCT_EXPANSIONS:
            if prod_key in product.lower():
                keywords.append(prod_key)
    
    # Add state
    if state:
        keywords.append(state)
    
    # Add common EL terms that should always match
    keywords.extend(["English learner", "EL", "ELL", "multilingual"])
    
    return list(set(keywords))
