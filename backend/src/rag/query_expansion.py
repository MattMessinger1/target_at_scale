"""Query expansion for improved RAG retrieval.

Expands user queries with related terms and synonyms to improve recall
when searching the knowledge base.
"""
from typing import List, Optional, Tuple


# Topic-based expansions for purpose-aware retrieval
# When a topic keyword is detected in purpose_prompt, expand with related document titles and terms
TOPIC_EXPANSIONS = {
    # CARE Coaching topics
    "newcomer": "newcomer Empowering Newcomers SLIFE Catching Moving Target academic success soft landing welcoming immigrant refugee",
    "slife": "SLIFE limited interrupted formal education newcomer refugee immigrant Empowering Newcomers",
    "family engagement": "family engagement community partnerships ABCs building community multilingual families",
    "translanguaging": "translanguaging biliteracy multilingual practices dynamic language Bridging Literacy",
    "ccna": "CARE Coaching Needs Assessment CCNA data school improvement survey action-based",
    "literacy": "literacy reading Bridging Literacy oracy writing language transfer",
    "oracy": "oracy literacy speaking Bridging Oracy discussion academic discourse",
    
    # CALL topics
    "leadership": "leadership distributed leadership principal school improvement CALL five domains",
    "school improvement": "school improvement CSI TSI ATSI turnaround evidence-based leadership CALL",
    "principal": "principal leadership evaluation growth planning distributed leadership CALL",
    
    # WebbAlign topics
    "dok": "DOK Depth of Knowledge Webb cognitive rigor alignment Unlocking Rigor",
    "depth of knowledge": "DOK Depth of Knowledge Webb cognitive rigor alignment Unlocking Rigor",
    "assessment alignment": "assessment alignment standards quality audit item analysis WebbAlign",
    "cognitive rigor": "cognitive rigor DOK Depth of Knowledge Webb alignment",
    
    # WIDA MODEL topics
    "progress monitoring": "progress monitoring interim assessment ACCESS prediction ELP MODEL",
    "reclassification": "reclassification exit criteria proficiency level monitoring ACCESS MODEL",
    "interim assessment": "interim assessment progress monitoring MODEL ACCESS prediction",
    "access prediction": "ACCESS prediction MODEL interim assessment progress monitoring",
    
    # WIDA Professional Learning topics
    "endorsement": "endorsement certification ESOL ESL professional development training",
    "certification": "certification endorsement ESOL ESL professional development",
    "standards framework": "ELD Standards Framework WIDA 2020 Can Do Descriptors",
    
    # WIDA SIS topics
    "compliance": "compliance monitoring Title III ESSA OCR corrective action reporting",
    "title iii": "Title III compliance reporting federal accountability EL programs",
    "data management": "data management SIS student information tracking compliance reporting",
    
    # Discussion Project topics
    "discussion": "discussion facilitation academic discourse SAC Structured Academic Controversy",
    "sac": "SAC Structured Academic Controversy discussion facilitation",
    
    # General cross-product topics
    "professional development": "professional development PD training workshop endorsement certification",
    "coaching": "coaching job-embedded coaching cycles implementation support",
    "implementation": "implementation planning support coaching cycles school improvement",
}

# Mapping of topic keywords to detect (lowercase) -> canonical topic key
# This helps catch variations like "newcomers" -> "newcomer"
TOPIC_ALIASES = {
    "newcomers": "newcomer",
    "newcomer students": "newcomer",
    "new arrivals": "newcomer",
    "immigrant": "newcomer",
    "refugee": "newcomer",
    "slife students": "slife",
    "limited formal education": "slife",
    "families": "family engagement",
    "parent engagement": "family engagement",
    "family partnerships": "family engagement",
    "biliteracy": "translanguaging",
    "needs assessment": "ccna",
    "reading": "literacy",
    "writing": "literacy",
    "speaking": "oracy",
    "leaders": "leadership",
    "school leader": "leadership",
    "assistant principal": "principal",
    "depth-of-knowledge": "dok",
    "webbs": "dok",
    "webb's": "dok",
    "interim": "interim assessment",
    "model online": "interim assessment",
    "exit criteria": "reclassification",
    "reclass": "reclassification",
    "esol endorsement": "endorsement",
    "esl certification": "certification",
    "title 3": "title iii",
    "federal reporting": "compliance",
    "monitoring review": "compliance",
    "structured academic controversy": "sac",
    "talk moves": "discussion",
    "pd": "professional development",
    "job-embedded": "coaching",
    "coaching cycles": "coaching",
}


def detect_topics_from_purpose(purpose_prompt: Optional[str]) -> List[str]:
    """Detect topic keywords from a purpose prompt.
    
    Args:
        purpose_prompt: The user's purpose/focus for the email
        
    Returns:
        List of detected topic keys that have expansions
    """
    if not purpose_prompt:
        return []
    
    purpose_lower = purpose_prompt.lower()
    detected: List[str] = []
    
    # Check for direct topic matches
    for topic_key in TOPIC_EXPANSIONS.keys():
        if topic_key in purpose_lower:
            if topic_key not in detected:
                detected.append(topic_key)
    
    # Check for aliases
    for alias, canonical in TOPIC_ALIASES.items():
        if alias in purpose_lower:
            if canonical not in detected:
                detected.append(canonical)
    
    return detected


def expand_purpose_for_retrieval(purpose_prompt: Optional[str]) -> Tuple[str, List[str]]:
    """Expand a purpose prompt with topic-specific terms for better KB retrieval.
    
    Args:
        purpose_prompt: The user's purpose/focus for the email
        
    Returns:
        Tuple of (expanded_text, detected_topics)
    """
    if not purpose_prompt:
        return "", []
    
    detected_topics = detect_topics_from_purpose(purpose_prompt)
    
    # Build expansion from detected topics
    expansions: List[str] = []
    for topic in detected_topics:
        if topic in TOPIC_EXPANSIONS:
            expansions.append(TOPIC_EXPANSIONS[topic])
    
    expanded_text = " ".join([purpose_prompt] + expansions)
    return expanded_text, detected_topics


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
