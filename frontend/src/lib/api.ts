/**
 * API client for WCEPS Email Generator backend.
 */

// Vite environment type augmentation
declare global {
  interface ImportMetaEnv {
    VITE_API_URL?: string
  }
}

// Use environment variable for API URL in production, fallback to /api for dev with proxy
const API_BASE = (import.meta as { env: ImportMetaEnv }).env.VITE_API_URL 
  ? `${(import.meta as { env: ImportMetaEnv }).env.VITE_API_URL}/api`
  : '/api'

// Types
export interface District {
  id: string
  name: string
  state: string
  state_full: string
  website_url: string
  student_count: number | null
  el_student_count: number | null
  el_percentage: number | null
  scrape_status: string
  scrape_phase: string | null
  last_scraped_at: string | null
  identified_needs: Record<string, unknown> | null
}

export interface Contact {
  id: number
  district_id: string
  full_name: string
  first_name: string | null
  last_name: string | null
  email: string | null
  title: string | null
  department: string | null
  phone: string | null
  confidence_score: number
  is_el_relevant: boolean
}

export interface ScrapedContent {
  id: number
  district_id: string
  content_type: string
  title: string
  content: string
  summary: string | null
  source: string
  source_url: string | null
  included_in_email: boolean
  human_weight_override: number | null
  human_notes: string | null
  scores: ContentScore[]
}

export interface ContentScore {
  product_match_score: number
  state_match_score: number
  recency_score: number
  urgency_score: number
  specificity_score: number
  final_score: number
  matched_product: string | null
  match_reason: string | null
}

export interface Email {
  id: number
  district_id: string
  contact_id: number | null
  subject_line: string
  email_body: string
  content_used: Record<string, unknown> | null
  status: string
  approved_by: string | null
  approved_at: string | null
  created_at: string
}

export interface KBItem {
  id: string
  category: string
  subcategory: string | null
  title: string
  content: string
  summary: string | null
  document_type: string | null
  tags: string[] | null
  applicable_states: string[] | null
  product_name: string | null
}

export interface Snippet {
  id: number
  district_id: string
  source_content_id: number | null
  category: string  // contact, statistic, priority, funding, compliance, program
  snippet_text: string
  relevance_note: string | null
  confidence: number
  included_in_email: boolean
  matched_product: string | null
  extracted_at: string
}

export interface SnippetSummary {
  district_id: string
  total_snippets: number
  selected_snippets: number
  by_category: Array<{
    category: string
    count: number
    selected_count: number
  }>
}

// V1 Email Tool Types
export interface StateInfo {
  code: string
  name: string
  is_wida: boolean
}

export interface FundingItem {
  title: string
  description?: string
  amount?: string
  deadline?: string
  source?: string
  score: number
  score_reason: string
  email_hook: string
  score_breakdown?: {
    product_fit: number
    audience_match: number
    recency: number
    specificity: number
    actionability: number
  }
}

export interface ComplianceItem {
  title: string
  description?: string
  type?: string
  deadline_or_frequency?: string
  hours_required?: string
  score: number
  score_reason: string
  email_hook: string
  score_breakdown?: {
    product_fit: number
    audience_match: number
    recency: number
    specificity: number
    actionability: number
  }
}

export interface ResearchRequest {
  product: string
  state: string
  audience: string
  top_n?: number
  min_score?: number
}

export interface ResearchResponse {
  product: string
  state: string
  state_full: string
  audience: string
  product_context_summary: string
  funding_items: FundingItem[]
  compliance_items: ComplianceItem[]
  raw_funding_content?: string
  raw_compliance_content?: string
}

export interface GenerateEmailRequest {
  product: string
  state: string
  state_full: string
  audience: string
  selected_funding: Array<{
    title: string
    description?: string
    amount?: string
    email_hook?: string
  }>
  selected_compliance: Array<{
    title: string
    description?: string
    type?: string
    email_hook?: string
  }>
  recipient_name?: string
  recipient_title?: string
  custom_instructions?: string
}

export interface GenerateEmailResponse {
  subject_line: string
  email_body: string
  product: string
  state: string
  audience: string
  word_count: number
}

// API functions
async function fetchApi<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  return response.json()
}

// Districts
export interface ScrapeResult {
  message: string
  result?: {
    district_id: string
    phases_completed: string[]
    errors: string[]
    urls_found?: number
    pages_scraped?: number
    products_matched?: number
    identified_needs?: Record<string, unknown>
  }
}

export const api = {
  districts: {
    list: () => fetchApi<District[]>('/districts/'),
    get: (id: string) => fetchApi<District>(`/districts/${id}`),
    loadPilot: () => fetchApi<{ message: string; districts: string[] }>('/districts/load-pilot', { method: 'POST' }),
    scrape: (id: string) => fetchApi<ScrapeResult>(`/districts/${id}/scrape`, { method: 'POST' }),
    reset: (id: string) => fetchApi<{ message: string }>(`/districts/${id}/reset`, { method: 'POST' }),
    resetAllPilot: () => fetchApi<{ message: string }>('/districts/reset-all-pilot', { method: 'POST' }),
  },

  content: {
    listByDistrict: (districtId: string, contentType?: string) => {
      const params = contentType ? `?content_type=${contentType}` : ''
      return fetchApi<ScrapedContent[]>(`/content/district/${districtId}${params}`)
    },
    get: (id: number) => fetchApi<ScrapedContent>(`/content/${id}`),
    update: (id: number, data: Partial<ScrapedContent>) =>
      fetchApi<ScrapedContent>(`/content/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    getCurated: (districtId: string) =>
      fetchApi<Record<string, ScrapedContent[]>>(`/content/district/${districtId}/curated`),
    scoreAll: (districtId: string) =>
      fetchApi<{ message: string }>(`/content/district/${districtId}/score-all`, { method: 'POST' }),
  },

  kb: {
    list: (params?: { category?: string; state?: string; product?: string }) => {
      const searchParams = new URLSearchParams()
      if (params?.category) searchParams.set('category', params.category)
      if (params?.state) searchParams.set('state', params.state)
      if (params?.product) searchParams.set('product', params.product)
      const query = searchParams.toString()
      return fetchApi<KBItem[]>(`/kb/${query ? `?${query}` : ''}`)
    },
    search: (q: string, category?: string) => {
      const params = new URLSearchParams({ q })
      if (category) params.set('category', category)
      return fetchApi<KBItem[]>(`/kb/search?${params.toString()}`)
    },
    products: () => fetchApi<{ products: string[] }>('/kb/products'),
    states: () => fetchApi<{ states: string[] }>('/kb/states'),
    caseStudies: (state?: string, product?: string) => {
      const params = new URLSearchParams()
      if (state) params.set('state', state)
      if (product) params.set('product', product)
      const query = params.toString()
      return fetchApi<KBItem[]>(`/kb/case-studies${query ? `?${query}` : ''}`)
    },
    index: () => fetchApi<{ message: string }>('/kb/index', { method: 'POST' }),
    stats: () => fetchApi<{ total_items: number; by_category: Record<string, number> }>('/kb/stats'),
  },

  snippets: {
    listByDistrict: (districtId: string, category?: string, includedOnly?: boolean) => {
      const params = new URLSearchParams()
      if (category) params.set('category', category)
      if (includedOnly) params.set('included_only', 'true')
      const query = params.toString()
      return fetchApi<Snippet[]>(`/snippets/district/${districtId}${query ? `?${query}` : ''}`)
    },
    getSummary: (districtId: string) =>
      fetchApi<SnippetSummary>(`/snippets/district/${districtId}/summary`),
    update: (id: number, data: { included_in_email: boolean }) =>
      fetchApi<Snippet>(`/snippets/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    bulkUpdate: (snippetIds: number[], includedInEmail: boolean) =>
      fetchApi<{ message: string; updated_count: number }>('/snippets/bulk-update', {
        method: 'POST',
        body: JSON.stringify({ snippet_ids: snippetIds, included_in_email: includedInEmail }),
      }),
    selectAll: (districtId: string, category?: string) => {
      const params = category ? `?category=${category}` : ''
      return fetchApi<{ message: string }>(`/snippets/district/${districtId}/select-all${params}`, { method: 'POST' })
    },
    deselectAll: (districtId: string, category?: string) => {
      const params = category ? `?category=${category}` : ''
      return fetchApi<{ message: string }>(`/snippets/district/${districtId}/deselect-all${params}`, { method: 'POST' })
    },
    extract: (districtId: string) =>
      fetchApi<{ snippets_extracted: number; by_category: Record<string, number> }>(`/snippets/district/${districtId}/extract`, { method: 'POST' }),
    getSelected: (districtId: string) =>
      fetchApi<Snippet[]>(`/snippets/district/${districtId}/selected`),
  },

  emails: {
    list: (districtId?: string, status?: string) => {
      const params = new URLSearchParams()
      if (districtId) params.set('district_id', districtId)
      if (status) params.set('status', status)
      const query = params.toString()
      return fetchApi<Email[]>(`/emails/${query ? `?${query}` : ''}`)
    },
    get: (id: number) => fetchApi<Email>(`/emails/${id}`),
    generate: (data: { district_id: string; contact_id?: number; custom_instructions?: string }) =>
      fetchApi<Email>('/emails/generate', { method: 'POST', body: JSON.stringify(data) }),
    approve: (id: number, data: { approved_by: string; review_notes?: string }) =>
      fetchApi<Email>(`/emails/${id}/approve`, { method: 'POST', body: JSON.stringify(data) }),
    update: (id: number, data: { subject_line?: string; email_body?: string }) =>
      fetchApi<Email>(`/emails/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    export: (status?: string, districtIds?: string[]) =>
      fetch(`${API_BASE}/emails/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, district_ids: districtIds }),
      }),
    previewExport: (status?: string) => {
      const params = status ? `?status=${status}` : ''
      return fetchApi<{ count: number; emails: unknown[] }>(`/emails/export/preview${params}`)
    },
  },

  // V1 Email Tool APIs
  research: {
    getProducts: () => fetchApi<{ products: string[] }>('/research/products'),
    getStates: () => fetchApi<{
      states: StateInfo[]
      wida_states: string[]
      non_wida_states: string[]
    }>('/research/states'),
    getAudiences: () => fetchApi<{ audiences: string[] }>('/research/audiences'),
    research: (data: ResearchRequest) =>
      fetchApi<ResearchResponse>('/research/', { method: 'POST', body: JSON.stringify(data) }),
    clearCache: (state?: string) => {
      const params = state ? `?state=${state}` : ''
      return fetchApi<{ message: string }>(`/research/cache/clear${params}`)
    },
  },

  generate: {
    email: (data: GenerateEmailRequest) =>
      fetchApi<GenerateEmailResponse>('/generate/', { method: 'POST', body: JSON.stringify(data) }),
    batch: (requests: GenerateEmailRequest[]) =>
      fetchApi<{ emails: GenerateEmailResponse[]; count: number }>('/generate/batch', {
        method: 'POST',
        body: JSON.stringify(requests),
      }),
    exportTemplate: () => fetchApi<{ headers: string[]; format: string; notes: string }>('/generate/export-csv'),
  },
}
