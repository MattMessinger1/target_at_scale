/**
 * API client for WCEPS Email Generator backend.
 */

const API_BASE = '/api'

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
export const api = {
  districts: {
    list: () => fetchApi<District[]>('/districts/'),
    get: (id: string) => fetchApi<District>(`/districts/${id}`),
    loadPilot: () => fetchApi<{ message: string; districts: string[] }>('/districts/load-pilot', { method: 'POST' }),
    scrape: (id: string) => fetchApi<{ message: string }>(`/districts/${id}/scrape`, { method: 'POST' }),
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
}
