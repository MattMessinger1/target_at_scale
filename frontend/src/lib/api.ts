/**
 * API client for WCEPS Email Generator backend.
 */

// Use environment variable for API URL in production, fallback to /api for dev with proxy
const getApiBase = (): string => {
  try {
    // @ts-expect-error - Vite injects env at build time
    const viteUrl = import.meta.env?.VITE_API_URL
    return viteUrl ? `${viteUrl}/api` : '/api'
  } catch {
    return '/api'
  }
}
const API_BASE = getApiBase()

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

// Research coverage matrix types
export interface ResearchStatus {
  status: 'completed'
  age_days: number
  hook_count?: number
  districts_surveyed?: number
  conference_count?: number
}

export interface StateCoverage {
  code: string
  name: string
  overall_status: 'complete' | 'partial' | 'missing'
  state_research: ResearchStatus | null
  district_research: ResearchStatus | null
  conference_research: ResearchStatus | null
}

export interface CoverageResponse {
  product: string
  product_key: string
  wida_only: boolean
  states: StateCoverage[]
  summary: {
    total_states: number
    complete: number
    partial: number
    missing: number
  }
}

export interface SourceLink {
  url: string
  title?: string
}

export interface FundingItem {
  title: string
  description?: string
  amount?: string
  deadline?: string
  funding_type?: string  // state, federal_supplemental, foundation, regional, university, private
  source?: string  // legacy field
  source_url?: string  // simplified web research output
  score?: number
  score_reason?: string
  email_hook?: string
  sources?: SourceLink[]  // Verifiable source links
  source_type?: 'knowledge_base' | 'perplexity' | 'web_research'  // Where the item came from
  status?: string  // active, verified, unverified, upcoming, closed_until_next_cycle
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
  type?: string  // consent_decree, doj_inquiry, certification, professional_development, reporting, assessment, csi_tsi, legal
  deadline_or_frequency?: string
  deadline?: string  // simplified web research output
  hours_required?: string
  urgency?: 'high' | 'medium' | 'low'
  source_url?: string  // simplified web research output
  score?: number
  score_reason?: string
  email_hook?: string
  sources?: SourceLink[]  // Verifiable source links
  source_type?: 'knowledge_base' | 'perplexity' | 'web_research'  // Where the item came from
  status?: string  // active, verified, unverified, upcoming
  score_breakdown?: {
    product_fit: number
    audience_match: number
    recency: number
    specificity: number
    actionability: number
  }
}

/**
 * Compliance-Linked Funding Item
 * 
 * These are funding sources that REQUIRE a compliance trigger to access,
 * like CSI/TSI school improvement grants or consent decree funding.
 * Different from general "hidden gem" funding - these funds are tied to compliance status.
 */
export interface ComplianceFundingItem {
  title: string
  description?: string
  amount?: string
  compliance_trigger: string  // e.g., "CSI/TSI designation", "DOJ consent decree"
  deadline?: string
  action_required?: string    // e.g., "Amend CSG application to include EL PD"
  districts_affected?: string[]
  source_url?: string
  source_type?: 'knowledge_base' | 'perplexity' | 'web_research'
  score?: number
  score_reason?: string
  email_hook?: string
  sources?: SourceLink[]
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
  audience: string  // 'Decision Makers' or 'Users'
  top_n?: number
  min_score?: number
  // Multi-select support for products/states only
  additional_products?: string[]
  additional_states?: string[]
  created_by?: string | null
}

export interface ResearchResponse {
  product: string
  state: string
  state_full: string
  audience: string
  product_context: {
    product_name: string
    description: string
    use_cases: string[]
    value_propositions: string[]
  }
  // KB items (from our knowledge base - direct SQL lookup)
  kb_funding: FundingItem[]
  kb_compliance_funding: ComplianceFundingItem[]
  kb_compliance: ComplianceItem[]
  // Web items (from Perplexity research)
  web_funding: FundingItem[]
  web_compliance_funding: ComplianceFundingItem[]
  web_compliance: ComplianceItem[]
  // Raw content for debugging
  raw_kb_content?: string
  raw_funding_content?: string
  raw_compliance_funding_content?: string
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
  selected_compliance_funding: Array<{
    title: string
    description?: string
    amount?: string
    compliance_trigger?: string
    action_required?: string
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

// ----------------------------------------------------------------------------
// V2 Pipeline Types (POST /api/generate/pipeline) — keep V1 types intact
// ----------------------------------------------------------------------------

export type PipelineMode = 'state_only' | 'district'

export type HookType =
  | 'deadline'
  | 'funding_guidance'
  | 'budget_coding'
  | 'monitoring'
  | 'allowable_use'
  | 'district_specific'

export type HookConfidence = 'high' | 'medium' | 'low'

export type ClaimKind =
  | 'hook'
  | 'deliverable_bullet'
  | 'funding'
  | 'compliance'
  | 'outcome'
  | 'other'

export interface PipelineRequest {
  product: string
  state: string
  state_full?: string | null
  audiences?: string[] | null
  district_name?: string | null
  district_url?: string | null
  include_district_research?: boolean
  include_conference_research?: boolean
  created_by?: string | null
}

export interface PipelineRunStreamRequest extends PipelineRequest {
  evidence_pack?: EvidencePack | null
  treasure_hooks?: WebHook[] | null
  district_research?: DistrictResearchResult | null
  conferences?: ConferenceOpportunity[] | null
  selected_hook_links?: string[] | null   // Deprecated: use selected_hook_ids
  primary_hook_link?: string | null       // Deprecated: use primary_hook_id
  selected_hook_ids?: string[] | null     // Preferred: unique hook IDs for reliable selection
  primary_hook_id?: string | null         // Preferred: unique ID of primary hook
  purpose_prompt?: string | null
  selected_cached_hooks?: SelectedCachedHookRequest[] | null
}

export type CachedHookCategory = 'state' | 'district' | 'conference'

export interface SelectedCachedHookRequest {
  category: CachedHookCategory
  state_code?: string | null
  hook: WebHook | ConferenceOpportunity
}

export interface EvidenceChunkCitation {
  chunk_id: string
  source_kb_id?: string | null
  title?: string | null
  excerpt: string
  category?: string | null
  subcategory?: string | null
  product_name?: string | null
  applicable_states?: string[] | null
  chunk_index?: number | null
  total_chunks?: number | null
}

export interface MicroOfferCandidate {
  offer: string
  rationale?: string | null
  citations: EvidenceChunkCitation[]
}

export interface EvidencePack {
  product: string
  product_key?: string | null
  state: string
  retrieved_chunks: EvidenceChunkCitation[]
  micro_offer_candidates: MicroOfferCandidate[]
  supplemental_brief?: Record<string, unknown> | null
}

export type SourceLevel = 'state' | 'district'

export interface WebHook {
  hook_id?: string | null  // Unique identifier for reliable selection (hash of content)
  hook_type: HookType
  quote: string
  link: string
  trigger_excerpt: string
  eligibility_excerpt?: string | null
  why_relevant: string
  confidence: HookConfidence
  source_quality_reason?: string | null
  // District-level fields
  source_level?: SourceLevel
  district_name?: string | null
  why_district_specific?: string | null
  // Deadline warning (added by hook gate if deadline is approaching)
  deadline_warning?: string | null
}

export interface SelectedHook {
  hook: WebHook
  rank: number
  reasons: string[]
}

export interface FilteredRequirement {
  hook: WebHook
  reason: string
  reason_label: string
}

export interface FilteredDistrictHook {
  hook: WebHook
  filter_reason: string
  filter_detail: string
}

export interface DistrictResearchResult {
  districts_surveyed: string[]
  passed_hooks: WebHook[]
  filtered_hooks: FilteredDistrictHook[]
  status: string
  research_summary?: string | null
}

// Conference opportunity for in-person relationship building
export type ConferenceConfidence = 'high' | 'medium'

export interface ConferenceOpportunity {
  conference_name: string          // "WAESOL 2026 Annual Conference"
  organization: string             // "Washington Association for ESL"
  location: string                 // "Seattle, WA"
  dates: string                    // "October 15-17, 2026"
  relevance: string                // Why this conference is relevant
  presentation_deadline?: string | null  // "June 30, 2026"
  sponsorship_info?: string | null       // "Exhibitor booths available, $500-$2000"
  website: string                  // Conference website link
  confidence: ConferenceConfidence
}

export interface EmailDraft {
  subject_line: string
  email_body: string
  word_count: number
  bullets: string[]
  micro_offer?: string | null
}

export interface ClaimsMapEntry {
  claim_kind: ClaimKind
  claim_text: string
  kb_chunk_ids: string[]
  urls: string[]
  notes?: string | null
}

export interface ValidationFailure {
  code: string
  message: string
  details?: Record<string, unknown> | null
}

export interface ValidationResult {
  passed: boolean
  failures: ValidationFailure[]
  word_count: number
  bullet_count: number
  bullet_word_counts: number[]
}

export interface IterationTrace {
  iteration: number
  validation: ValidationResult
  stopped: boolean
  stop_reason?: string | null
}

export interface AudienceVariantTrace {
  audience: string
  attempts: IterationTrace[]
  stage_ms: Record<string, number>
}

export interface AudienceVariantResult {
  audience: string
  selected_hook: SelectedHook
  secondary_hook?: SelectedHook | null
  email_draft: EmailDraft
  claims_map: ClaimsMapEntry[]
  validation: ValidationResult
  trace: AudienceVariantTrace
}

export interface PipelineTrace {
  run_id: string
  started_at: string
  finished_at?: string | null
  stage_ms: Record<string, number>
  variant_traces: AudienceVariantTrace[]
}

export interface PipelineRunResponse {
  run_id: string
  mode: PipelineMode
  request: PipelineRequest
  evidence_pack: EvidencePack
  treasure_hooks: WebHook[]
  hooks?: WebHook[]  // Alias used in saved research runs
  filtered_requirements?: FilteredRequirement[]  // Stored for research runs
  district_research?: DistrictResearchResult | null
  conferences?: ConferenceOpportunity[]  // Conference opportunities for in-person relationship building
  variants: AudienceVariantResult[]
  trace: PipelineTrace
  warnings: string[]
}

// ----------------------------------------------------------------------------
// Feedback (training loop)
// ----------------------------------------------------------------------------

export type HookDecisionKind = 'selected' | 'rejected'

export interface HookDecision {
  decision: HookDecisionKind
  rank?: number | null
  reason_tags: string[]
  reason_note?: string | null
  hook: WebHook
}

export interface HookFeedbackRequest {
  run_id?: string | null
  product: string
  state_code: string
  audiences?: string[] | null
  district_name?: string | null
  district_url?: string | null
  decisions: HookDecision[]
}

export interface HookFeedbackResponse {
  inserted: number
}

export interface RubricItem {
  score: number | null  // Optional: 1-5, or null if not provided
  comment?: string | null
}

export interface EmailRubric {
  subject_line: RubricItem
  product_relevance: RubricItem
  tone: RubricItem
  flow: RubricItem
  cta: RubricItem
}

export interface EmailReviewRequest {
  run_id?: string | null
  product: string
  state_code: string
  audience: string
  district_name?: string | null
  district_url?: string | null
  primary_hook_link?: string | null
  secondary_hook_link?: string | null
  original_subject_line: string
  original_email_body: string
  edited_subject_line: string
  edited_email_body: string
  rubric: EmailRubric
}

export interface EmailReviewResponse {
  id: number
}

// ----------------------------------------------------------------------------
// Training Feedback Types (for Training Feedback page)
// ----------------------------------------------------------------------------

export interface EmailReviewListItem {
  id: number
  created_at?: string | null
  run_id?: string | null
  product: string
  product_key?: string | null
  state_code: string
  audience: string
  district_name?: string | null
  subject_preview: string
  rubric: Record<string, { score?: number | null; comment?: string | null }>
  was_edited: boolean
}

export interface EmailReviewListResponse {
  total: number
  items: EmailReviewListItem[]
}

export interface GoldenEmailListItem {
  id: number
  created_at?: string | null
  product: string
  product_key?: string | null
  state_code: string
  audience: string
  district_name?: string | null
  subject_line: string
  source: 'edited' | 'rubric_qualified'
  rubric_scores?: Record<string, number> | null
  review_id?: number | null
}

export interface GoldenEmailListResponse {
  total: number
  items: GoldenEmailListItem[]
}

export interface GoldenEmailDetail {
  id: number
  created_at?: string | null
  product: string
  product_key?: string | null
  state_code: string
  audience: string
  district_name?: string | null
  subject_line: string
  email_body: string
  source: 'edited' | 'rubric_qualified'
  rubric_scores?: Record<string, number> | null
  hook_types_used?: string[] | null
  review_id?: number | null
}

// ----------------------------------------------------------------------------
// Saved Research Types
// ----------------------------------------------------------------------------

export interface SaveRunRequest {
  name?: string | null
  product: string
  state_code: string
  state_full?: string | null
  audiences: string[]
  district_name?: string | null
  pipeline_response: PipelineRunResponse
  selected_hook_links: string[]
  primary_hook_link?: string | null
  hook_reason_tags: Record<string, string[]>
  hook_reason_notes: Record<string, string>
}

export interface SavedRunSummary {
  id: number
  run_type: 'research' | 'email'
  name?: string | null
  created_by?: string | null
  product: string
  state_code: string
  state_full?: string | null
  audiences: string[]
  district_name?: string | null
  created_at: string
  batch_job_id?: number | null
  subject_preview?: string | null
  hook_count?: number | null
}

export interface SavedRunFull {
  id: number
  run_type: 'research' | 'email'
  name?: string | null
  created_by?: string | null
  product: string
  state_code: string
  state_full?: string | null
  audiences: string[]
  district_name?: string | null
  include_district_research?: boolean
  include_conference_research?: boolean
  purpose_prompt?: string | null
  selected_cached_hook_ids?: string[] | null
  pipeline_response: PipelineRunResponse
  selected_hook_links: string[]
  primary_hook_link?: string | null
  hook_reason_tags: Record<string, string[]>
  hook_reason_notes: Record<string, string>
  created_at: string
  batch_job_id?: number | null
}

export interface SaveResearchRequest {
  name?: string
  created_by?: string | null
  product: string
  state_code: string
  state_full?: string
  audiences?: string[]
  district_name?: string
  evidence_pack: EvidencePack
  hooks: WebHook[]
  filtered_requirements?: FilteredRequirement[]
  district_research?: DistrictResearchResult | null
  conferences?: ConferenceOpportunity[]
  batch_job_id?: number
}

export interface GroupedRunsResponse {
  product: string
  states: Record<string, SavedRunSummary[]>
}

export interface BatchJobSummary {
  id: number
  name?: string | null
  product: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  total_states: number
  completed_states: number
  failed_states: number
  created_at: string
  started_at?: string | null
  completed_at?: string | null
}

export interface BatchJobDetail {
  id: number
  name?: string | null
  product: string
  states: Array<{ code: string; name: string }>
  audiences: string[]
  include_district_research?: boolean
  include_conference_research?: boolean
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  total_states: number
  completed_states: number
  failed_states: number
  error_message?: string | null
  created_at: string
  started_at?: string | null
  completed_at?: string | null
}

export interface CreateBatchJobRequest {
  name?: string
  product: string
  states: Array<{ code: string; name: string }>
  audiences?: string[]
  include_district_research?: boolean
  include_conference_research?: boolean
  force_fresh?: boolean  // Clear cache before starting for fresh results
}

export interface BatchRunSummary {
  id: number
  state_code: string
  state_full?: string | null
  status: 'completed' | 'failed' | 'pending' | 'queued'
  hook_count?: number | null
  created_at: string
}

// ----------------------------------------------------------------------------
// NDJSON streaming helpers (V3 trace UI groundwork)
// ----------------------------------------------------------------------------

export type PipelineStreamEvent = Record<string, unknown> & {
  type: string
  ts?: string
  stage?: string
  ms?: number
  message?: string
  reason?: string
  payload?: unknown
}

async function fetchNdjson(
  endpoint: string,
  body: unknown,
  onEvent: (evt: PipelineStreamEvent) => void
): Promise<void> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const errorData = await response
      .json()
      .catch(() => ({ detail: 'Unknown error' as const }))

    const detail = (errorData as { detail?: unknown })?.detail
    const message = typeof detail === 'string' ? detail : JSON.stringify(detail ?? errorData)
    throw new Error(message || `HTTP ${response.status}`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('Streaming response not supported')

  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      const s = line.trim()
      if (!s) continue
      try {
        onEvent(JSON.parse(s) as PipelineStreamEvent)
      } catch {
        // ignore malformed lines
      }
    }
  }

  const tail = buffer.trim()
  if (tail) {
    try {
      onEvent(JSON.parse(tail) as PipelineStreamEvent)
    } catch {
      // ignore
    }
  }
}

export interface KbUploadResponse {
  message: string
  id: string
  title: string
  category: string
  product_name?: string | null
  applicable_states?: string[] | null
  document_type?: string | null
  embedding?: unknown
}

export interface CreateEmailExampleRequest {
  subject_line: string
  email_body: string
  product?: string
  states?: string[]
  audience?: string
  message?: string
  timing?: string
  tags?: string[]
  notes?: string
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
    const errorData = await response
      .json()
      .catch(() => ({ detail: 'Unknown error' as const }))

    const detail = (errorData as { detail?: unknown })?.detail

    const formatValidationErrors = (errors: unknown[]): string => {
      return errors
        .map((e) => {
          if (!e || typeof e !== 'object') return String(e)
          const obj = e as { loc?: unknown; msg?: unknown }
          const loc = Array.isArray(obj.loc) ? obj.loc.join('.') : obj.loc ? String(obj.loc) : ''
          const msg = obj.msg ? String(obj.msg) : JSON.stringify(e)
          return loc ? `${loc}: ${msg}` : msg
        })
        .join('; ')
    }

    let message: string
    if (typeof detail === 'string') {
      message = detail
    } else if (Array.isArray(detail)) {
      message = formatValidationErrors(detail)
    } else if (detail != null) {
      message = JSON.stringify(detail)
    } else if (typeof (errorData as { message?: unknown })?.message === 'string') {
      message = String((errorData as { message?: unknown }).message)
    } else {
      message = `HTTP ${response.status}`
    }

    throw new Error(message || `HTTP ${response.status}`)
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

    upload: async (formData: FormData) => {
      const response = await fetch(`${API_BASE}/kb/upload`, {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        let message = `HTTP ${response.status}`
        try {
          const errorData = (await response.json()) as { detail?: unknown; message?: unknown }
          const detail = errorData?.detail
          if (typeof detail === 'string') message = detail
          else if (detail != null) message = JSON.stringify(detail)
          else if (typeof errorData?.message === 'string') message = errorData.message
        } catch {
          // ignore
        }
        throw new Error(message)
      }

      return (await response.json()) as KbUploadResponse
    },

    exportEmailExamples: async (params?: { product?: string; audience?: string; state?: string }) => {
      const sp = new URLSearchParams()
      if (params?.product) sp.set('product', params.product)
      if (params?.audience) sp.set('audience', params.audience)
      if (params?.state) sp.set('state', params.state)
      const query = sp.toString()

      const response = await fetch(`${API_BASE}/kb/email-examples/export${query ? `?${query}` : ''}`)
      if (!response.ok) {
        let message = `HTTP ${response.status}`
        try {
          const errorData = (await response.json()) as { detail?: unknown; message?: unknown }
          const detail = errorData?.detail
          if (typeof detail === 'string') message = detail
          else if (detail != null) message = JSON.stringify(detail)
          else if (typeof errorData?.message === 'string') message = errorData.message
        } catch {
          // ignore
        }
        throw new Error(message)
      }

      return response.blob()
    },

    createEmailExample: (data: CreateEmailExampleRequest) =>
      fetchApi<KbUploadResponse>('/kb/email-examples', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
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
    getCoverage: (product: string, widaOnly: boolean = true) => {
      const params = new URLSearchParams()
      params.set('product', product)
      params.set('wida_only', String(widaOnly))
      return fetchApi<CoverageResponse>(`/research/coverage?${params.toString()}`)
    },
    archiveAllCache: () => {
      return fetchApi<{ deep_research_archived: number; district_research_archived: number }>(
        '/research/cache/archive',
        { method: 'POST' }
      )
    },
  },

  generate: {
    email: (data: GenerateEmailRequest) =>
      fetchApi<GenerateEmailResponse>('/generate/v1', { method: 'POST', body: JSON.stringify(data) }),
    pipeline: (data: PipelineRequest) =>
      fetchApi<PipelineRunResponse>('/generate/', { method: 'POST', body: JSON.stringify(data) }),
    clearDeepResearchCache: (state?: string, product?: string) => {
      const params = new URLSearchParams()
      if (state) params.set('state', state)
      if (product) params.set('product', product)
      const query = params.toString()
      return fetchApi<{ message: string; state?: string; product?: string }>(
        `/generate/pipeline/cache${query ? `?${query}` : ''}`,
        { method: 'DELETE' }
      )
    },
    checkCacheStatus: (state: string, product: string) => {
      const params = new URLSearchParams()
      params.set('state', state)
      params.set('product', product)
      return fetchApi<{
        status: 'completed' | 'in_progress' | 'pending' | 'failed' | 'cancelled' | 'not_found' | 'expired'
        cache_age_days?: number
        cached_at?: string
        expires_in_days?: number
        hook_count?: number
        elapsed_minutes?: number
        started_at?: string
        error?: string
      }>(`/generate/pipeline/cache/status?${params.toString()}`)
    },
    getCachedPrep: (state: string, product: string) => {
      const params = new URLSearchParams()
      params.set('state', state)
      params.set('product', product)
      return fetchApi<{
        cached: boolean
        result: {
          evidence_pack: EvidencePack
          treasure_hooks: WebHook[]
          filtered_requirements: FilteredRequirement[]
          district_research?: DistrictResearchResult | null
          warnings: string[]
        }
        cache_age_days: number
        cached_at: string
      }>(`/generate/pipeline/prep/cached?${params.toString()}`)
    },
    cancelResearch: (state: string, product: string) => {
      const params = new URLSearchParams()
      params.set('state', state)
      params.set('product', product)
      return fetchApi<{
        cancelled: boolean
        reason?: string
        status?: string
      }>(`/generate/pipeline/cancel?${params.toString()}`, { method: 'POST' })
    },
    pipelinePrepStream: async (data: PipelineRequest, onEvent: (evt: PipelineStreamEvent) => void) => {
      let payload: { evidence_pack: EvidencePack; treasure_hooks: WebHook[]; filtered_requirements: FilteredRequirement[]; district_research?: DistrictResearchResult | null; warnings: string[] } | null = null
      let blockedMsg: string | null = null
      let blockedFiltered: FilteredRequirement[] = []
      await fetchNdjson('/generate/pipeline/prep/stream', data, (evt) => {
        onEvent(evt)
        if (evt.type === 'blocked') {
          blockedMsg = typeof evt.message === 'string' ? evt.message : 'Blocked'
          // Capture filtered requirements even when blocked
          if (evt.filtered_requirements) {
            blockedFiltered = evt.filtered_requirements as FilteredRequirement[]
          }
        }
        if (evt.type === 'prep_ready') payload = evt.payload as typeof payload
      })
      if (blockedMsg) {
        // Return partial data with filtered requirements so UI can show what was found
        const err = new Error(blockedMsg) as Error & { filteredRequirements?: FilteredRequirement[] }
        err.filteredRequirements = blockedFiltered
        throw err
      }
      if (!payload) throw new Error('No prep payload returned')
      return payload
    },
    // On-demand district research (after state research)
    districtResearchStream: async (
      data: { product: string; state: string; state_full?: string; state_hooks: Array<{ hook_id?: string; link: string; quote: string; title?: string }> },
      onEvent: (evt: PipelineStreamEvent) => void
    ) => {
      let payload: DistrictResearchResult | null = null
      let errorMsg: string | null = null
      await fetchNdjson('/generate/pipeline/district-research/stream', data, (evt) => {
        onEvent(evt)
        if (evt.type === 'error') {
          errorMsg = typeof evt.error === 'string' ? evt.error : 'District research failed'
        }
        if (evt.type === 'district_research_ready') {
          payload = evt.payload as DistrictResearchResult
        }
      })
      if (errorMsg) throw new Error(errorMsg)
      if (!payload) throw new Error('No district research payload returned')
      return payload
    },
    pipelineRunStream: async (data: PipelineRunStreamRequest, onEvent: (evt: PipelineStreamEvent) => void) => {
      let payload: PipelineRunResponse | null = null
      let blockedMsg: string | null = null
      await fetchNdjson('/generate/pipeline/run/stream', data, (evt) => {
        onEvent(evt)
        if (evt.type === 'blocked') {
          blockedMsg = typeof evt.message === 'string' ? evt.message : 'Blocked'
        }
        if (evt.type === 'run_ready') payload = evt.payload as PipelineRunResponse
      })
      if (blockedMsg) throw new Error(blockedMsg)
      if (!payload) throw new Error('No run payload returned')
      return payload
    },
    // Polling-based email generation (avoids connection timeouts)
    pipelineRunStart: (data: PipelineRunStreamRequest) =>
      fetchApi<{ task_id: string; status: string; message: string }>('/generate/pipeline/run/start', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    pipelineRunStatus: (taskId: string) =>
      fetchApi<{
        task_id: string
        status: 'queued' | 'in_progress' | 'completed' | 'failed'
        progress: number
        message: string
        started_at?: string
        result?: PipelineRunResponse
        error?: string
      }>(`/generate/pipeline/run/status?task_id=${encodeURIComponent(taskId)}`),
    // Polling wrapper that handles the full flow
    pipelineRunPolling: async (
      data: PipelineRunStreamRequest,
      onProgress: (progress: number, message: string) => void,
      pollInterval = 3000,
      maxPolls = 600, // ~30 minutes max (3 audiences × 2 repair attempts × ~5 min each)
    ): Promise<PipelineRunResponse> => {
      // Start the task
      const startResult = await fetchApi<{ task_id: string; status: string; message: string }>(
        '/generate/pipeline/run/start',
        { method: 'POST', body: JSON.stringify(data) }
      )
      const taskId = startResult.task_id
      onProgress(0, 'Email generation started...')

      // Poll for completion
      for (let i = 0; i < maxPolls; i++) {
        await new Promise((resolve) => setTimeout(resolve, pollInterval))
        
        const status = await fetchApi<{
          task_id: string
          status: 'queued' | 'in_progress' | 'completed' | 'failed'
          progress: number
          message: string
          result?: PipelineRunResponse
          error?: string
        }>(`/generate/pipeline/run/status?task_id=${encodeURIComponent(taskId)}`)

        onProgress(status.progress, status.message)

        if (status.status === 'completed' && status.result) {
          return status.result
        }

        if (status.status === 'failed') {
          throw new Error(status.error || 'Email generation failed')
        }
      }

      throw new Error('Email generation timed out after 30 minutes. Please try again with fewer audiences.')
    },
    // Polling-based research prep (more robust than streaming)
    pipelinePrepStart: (data: PipelineRequest) =>
      fetchApi<{
        task_id: string
        status: string
        phase: 'state' | 'district' | 'conferences'
        message: string
        existing: boolean
      }>('/generate/pipeline/prep/start', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    pipelinePrepStatus: (taskId: string) =>
      fetchApi<{
        task_id: string
        status: 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled'
        phase: 'state' | 'district' | 'conferences'
        progress: number
        message: string
        started_at?: string
        completed_at?: string
        state_code?: string
        product_key?: string
        product_display_name?: string
        include_district_research?: boolean
        include_conference_research?: boolean
        saved_run_id?: number  // Auto-saved run ID (when completed)
        result?: {
          evidence_pack: EvidencePack
          treasure_hooks: WebHook[]
          filtered_requirements: FilteredRequirement[]
          district_research?: DistrictResearchResult | null
          conferences?: ConferenceOpportunity[]
          warnings: string[]
        }
        error?: string
      }>(`/generate/pipeline/prep/status?task_id=${encodeURIComponent(taskId)}`),
    pipelinePrepCancel: (taskId: string) =>
      fetchApi<{ task_id: string; cancelled: boolean; reason?: string }>(
        `/generate/pipeline/prep/cancel?task_id=${encodeURIComponent(taskId)}`,
        { method: 'POST' }
      ),
    pipelinePrepActive: () =>
      fetchApi<{
        task_id: string | null
        status?: string
        phase?: 'state' | 'district' | 'conferences'
        progress?: number
        message?: string
        state_code?: string
        product_key?: string
        product_display_name?: string
        include_district_research?: boolean
        include_conference_research?: boolean
        tasks?: Array<{
          task_id: string
          status: string
          phase: 'state' | 'district' | 'conferences'
          progress: number
          message: string
          state_code?: string
          product_key?: string
          product_display_name?: string
          include_district_research?: boolean
          include_conference_research?: boolean
        }>
      }>('/generate/pipeline/prep/active'),
    // Polling wrapper that handles the full research prep flow
    pipelinePrepPolling: async (
      data: PipelineRequest,
      onProgress: (phase: 'state' | 'district' | 'conferences', progress: number, message: string) => void,
      pollInterval = 3000,
      maxPolls = 1200, // ~60 minutes max (state + district research)
    ): Promise<{
      evidence_pack: EvidencePack
      treasure_hooks: WebHook[]
      filtered_requirements: FilteredRequirement[]
      district_research?: DistrictResearchResult | null
      conferences?: ConferenceOpportunity[]
      warnings: string[]
    }> => {
      // Start the task
      const startResult = await fetchApi<{
        task_id: string
        status: string
        phase: 'state' | 'district' | 'conferences'
        message: string
        existing: boolean
      }>('/generate/pipeline/prep/start', {
        method: 'POST',
        body: JSON.stringify(data),
      })
      const taskId = startResult.task_id
      
      // Poll immediately first (for cache hits that complete instantly)
      // Only show progress UI if not immediately complete
      let firstPoll = true
      
      for (let i = 0; i < maxPolls; i++) {
        // Skip initial wait on first poll to check for cache hits
        if (!firstPoll) {
          await new Promise((resolve) => setTimeout(resolve, pollInterval))
        }
        firstPoll = false
        
        const status = await fetchApi<{
          task_id: string
          status: 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled'
          phase: 'state' | 'district' | 'conferences'
          progress: number
          message: string
          result?: {
            evidence_pack: EvidencePack
            treasure_hooks: WebHook[]
            filtered_requirements: FilteredRequirement[]
            district_research?: DistrictResearchResult | null
            conferences?: ConferenceOpportunity[]
            warnings: string[]
          }
          error?: string
          from_cache?: boolean
        }>(`/generate/pipeline/prep/status?task_id=${encodeURIComponent(taskId)}`)

        // For immediate cache hits, return without showing progress UI
        if (status.status === 'completed' && status.result) {
          // Only show a brief message for cache hits
          if (status.from_cache) {
            onProgress(status.phase || 'state', 100, 'Loaded from cache')
          } else {
            onProgress(status.phase || 'state', status.progress, status.message)
          }
          return status.result
        }

        // Show progress for actual research (not cache hits)
        onProgress(status.phase || 'state', status.progress, status.message)

        if (status.status === 'failed') {
          throw new Error(status.error || 'Research failed')
        }

        if (status.status === 'cancelled') {
          throw new Error('Research was cancelled')
        }
      }

      throw new Error('Research timed out after 60 minutes. Please try again.')
    },
    batch: (requests: GenerateEmailRequest[]) =>
      fetchApi<{ emails: GenerateEmailResponse[]; count: number }>('/generate/batch', {
        method: 'POST',
        body: JSON.stringify(requests),
      }),
    exportTemplate: () => fetchApi<{ headers: string[]; format: string; notes: string }>('/generate/export-csv'),
  },

  feedback: {
    submitHookFeedback: (data: HookFeedbackRequest) =>
      fetchApi<HookFeedbackResponse>('/feedback/hooks', { method: 'POST', body: JSON.stringify(data) }),
    exportHookFeedback: () => fetch(`${API_BASE}/feedback/hooks/export`),
    submitEmailReview: (data: EmailReviewRequest) =>
      fetchApi<EmailReviewResponse>('/feedback/email-reviews', { method: 'POST', body: JSON.stringify(data) }),
    exportEmailReviews: () => fetch(`${API_BASE}/feedback/email-reviews/export`),
    
    // Training Feedback UI endpoints
    listEmailReviews: (params?: { product?: string; state_code?: string; audience?: string; limit?: number; offset?: number }) => {
      const searchParams = new URLSearchParams()
      if (params?.product) searchParams.set('product', params.product)
      if (params?.state_code) searchParams.set('state_code', params.state_code)
      if (params?.audience) searchParams.set('audience', params.audience)
      if (params?.limit) searchParams.set('limit', String(params.limit))
      if (params?.offset) searchParams.set('offset', String(params.offset))
      const query = searchParams.toString()
      return fetchApi<EmailReviewListResponse>(`/feedback/email-reviews${query ? `?${query}` : ''}`)
    },
    listGoldenEmails: (params?: { product?: string; state_code?: string; audience?: string; source?: string; limit?: number; offset?: number }) => {
      const searchParams = new URLSearchParams()
      if (params?.product) searchParams.set('product', params.product)
      if (params?.state_code) searchParams.set('state_code', params.state_code)
      if (params?.audience) searchParams.set('audience', params.audience)
      if (params?.source) searchParams.set('source', params.source)
      if (params?.limit) searchParams.set('limit', String(params.limit))
      if (params?.offset) searchParams.set('offset', String(params.offset))
      const query = searchParams.toString()
      return fetchApi<GoldenEmailListResponse>(`/feedback/golden-emails${query ? `?${query}` : ''}`)
    },
    getGoldenEmail: (id: number) => fetchApi<GoldenEmailDetail>(`/feedback/golden-emails/${id}`),
  },

  savedRuns: {
    list: (limit = 50, offset = 0) =>
      fetchApi<SavedRunSummary[]>(`/saved-runs?limit=${limit}&offset=${offset}`),
    listFiltered: (params: { run_type?: string; product?: string; state_code?: string; limit?: number; offset?: number }) => {
      const searchParams = new URLSearchParams()
      if (params.run_type) searchParams.set('run_type', params.run_type)
      if (params.product) searchParams.set('product', params.product)
      if (params.state_code) searchParams.set('state_code', params.state_code)
      if (params.limit) searchParams.set('limit', String(params.limit))
      if (params.offset) searchParams.set('offset', String(params.offset))
      return fetchApi<SavedRunSummary[]>(`/saved-runs?${searchParams.toString()}`)
    },
    listGrouped: (days = 30) =>
      fetchApi<GroupedRunsResponse[]>(`/saved-runs/grouped?days=${days}`),
    get: (id: number) => fetchApi<SavedRunFull>(`/saved-runs/${id}`),
    save: (data: SaveRunRequest) =>
      fetchApi<SavedRunFull>('/saved-runs', { method: 'POST', body: JSON.stringify(data) }),
    saveResearch: (data: SaveResearchRequest) =>
      fetchApi<SavedRunFull>('/saved-runs/research', { method: 'POST', body: JSON.stringify(data) }),
    rename: (id: number, name: string) =>
      fetchApi<SavedRunSummary>(`/saved-runs/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
    delete: (id: number) =>
      fetchApi<{ ok: boolean; deleted_id: number }>(`/saved-runs/${id}`, { method: 'DELETE' }),
    cleanup: (days = 30) =>
      fetchApi<{ deleted_count: number; cutoff_date: string }>(`/saved-runs/cleanup?days=${days}`, { method: 'DELETE' }),
  },

  // Batch processing
  batch: {
    list: (limit = 20, offset = 0) =>
      fetchApi<BatchJobSummary[]>(`/batch?limit=${limit}&offset=${offset}`),
    get: (jobId: number) =>
      fetchApi<BatchJobDetail>(`/batch/${jobId}`),
    getRuns: (jobId: number) =>
      fetchApi<BatchRunSummary[]>(`/batch/${jobId}/runs`),
    create: (data: CreateBatchJobRequest) =>
      fetchApi<BatchJobDetail>('/batch', { method: 'POST', body: JSON.stringify(data) }),
    cancel: (jobId: number) =>
      fetchApi<{ ok: boolean; job_id: number; status: string }>(`/batch/${jobId}/cancel`, { method: 'POST' }),
  },
}
