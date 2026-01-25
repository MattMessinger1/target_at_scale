/**
 * EmailGenerator page - V2 streaming research flow.
 * @version 2.1.0 - Added edited email content saving
 * 
 * Flow:
 * 1. Select products, states, audiences (multi-select)
 * 2. Research (with RAG context) → returns scored items
 * 3. Curate (select funding + compliance items)
 * 4. Generate email
 * 5. Copy / Export
 */
import React, { useState, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { 
  api, 
  FundingItem, 
  ComplianceItem,
  ComplianceFundingItem,
  ResearchResponse,
  GenerateEmailResponse,
  EvidenceChunkCitation,
  EvidencePack,
  WebHook,
  FilteredRequirement,
  DistrictResearchResult,
  ConferenceOpportunity,
  PipelineRequest,
  PipelineRunStreamRequest,
  PipelineRunResponse,
  PipelineStreamEvent,
  HookDecision,
  EmailReviewRequest,
  SavedRunSummary,
  SavedRunFull
} from '../lib/api'
import { toast } from '@/components/ui/use-toast'
import { ThemeToggle } from '@/components/ThemeToggle'
import { ProductSelector } from '../components/ProductSelector'
import { StateSelector, SelectedState } from '../components/StateSelector'
import { AudienceSelector } from '../components/AudienceSelector'
import { CurationStep } from '../components/CurationStep'
import { AlertCircle, ChevronDown, ChevronUp } from 'lucide-react'

type Step = 'select' | 'research' | 'curate' | 'generate' | 'done'

// Parse markdown links and render as clickable elements
// Handles: [text](url) and bare URLs
const renderWithLinks = (text: string | undefined | null): React.ReactNode => {
  if (!text) return null
  
  // Pattern to match markdown links: [text](url)
  const markdownLinkPattern = /\[([^\]]+)\]\(([^)]+)\)/g
  
  const parts: React.ReactNode[] = []
  let lastIndex = 0
  let match
  let keyIndex = 0
  
  while ((match = markdownLinkPattern.exec(text)) !== null) {
    // Add text before the match
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    
    // Add the link
    const [, linkText, url] = match
    parts.push(
      <a
        key={`link-${keyIndex++}`}
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-indigo-400 hover:text-indigo-300 underline"
      >
        {linkText}
      </a>
    )
    
    lastIndex = match.index + match[0].length
  }
  
  // Add remaining text
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  
  return parts.length > 0 ? <>{parts}</> : text
}

// Clean up markdown URLs and links from quote text for display
const cleanQuoteText = (text: string | undefined | null): string => {
  if (!text) return ''
  // Remove markdown links: [text](url) -> text
  let cleaned = text.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
  // Remove standalone URLs
  cleaned = cleaned.replace(/https?:\/\/[^\s]+/g, '')
  // Remove markdown URL artifacts like ([text]...)
  cleaned = cleaned.replace(/\(\[?[^\)]+\]?\)/g, '')
  // Clean up extra whitespace
  cleaned = cleaned.replace(/\s+/g, ' ').trim()
  return cleaned
}

const STEP_ORDER: Step[] = ['select', 'research', 'curate', 'generate', 'done']
const STEP_LABELS: Record<Step, string> = {
  select: 'Select',
  research: 'Research',
  curate: 'Curate',
  generate: 'Generate',
  done: 'Done',
}

// Research progress step component for the thinking trace
function ResearchProgressStep({ 
  step, 
  label, 
  isActive, 
  isComplete 
}: { 
  step: number
  label: string
  isActive: boolean
  isComplete: boolean
}) {
  return (
    <div className={`flex items-center gap-3 transition-all ${
      isComplete ? 'opacity-100' : isActive ? 'opacity-100' : 'opacity-50'
    }`}>
      <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
        isComplete 
          ? 'bg-emerald-500 text-white' 
          : isActive 
            ? 'bg-emerald-500/30 text-emerald-400 ring-2 ring-emerald-500/50 animate-pulse' 
            : 'bg-slate-700 text-slate-500'
      }`}>
        {isComplete ? (
          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
          </svg>
        ) : (
          step
        )}
      </div>
      <span className={`text-sm ${
        isComplete 
          ? 'text-emerald-400' 
          : isActive 
            ? 'text-slate-200' 
            : 'text-slate-500'
      }`}>
        {label}
        {isActive && (
          <span className="ml-2 inline-flex">
            <span className="animate-bounce" style={{ animationDelay: '0ms' }}>.</span>
            <span className="animate-bounce" style={{ animationDelay: '150ms' }}>.</span>
            <span className="animate-bounce" style={{ animationDelay: '300ms' }}>.</span>
          </span>
        )}
      </span>
    </div>
  )
}

type ResearchRunCriteria = {
  products: string[]
  states: SelectedState[]
  audience: string  // Single audience: 'Decision Makers' or 'Users'
  audiences?: string[]  // Legacy support for old saved runs
}

type ResearchRunSelections = {
  selectedFunding: FundingItem[]
  selectedComplianceFunding: ComplianceFundingItem[]
  selectedCompliance: ComplianceItem[]
}

type ResearchRunSnapshot = {
  id: string
  createdAt: string
  criteria: ResearchRunCriteria
  results: ResearchResponse
  selections: ResearchRunSelections
}

type CachedPrepResult = {
  evidence_pack: EvidencePack
  treasure_hooks: WebHook[]
  filtered_requirements: FilteredRequirement[]
  district_research?: DistrictResearchResult | null
  conferences?: ConferenceOpportunity[]
  warnings: string[]
}

type CachedHookCategory = 'state' | 'district' | 'conference'

type SelectedCachedHook = {
  key: string
  category: CachedHookCategory
  state_code?: string
  hook: WebHook | ConferenceOpportunity
}

const RESEARCH_RUNS_STORAGE_KEY = 'wceps_emailgen_research_runs_v1'
const PENDING_EMAIL_TASK_KEY_V1 = 'wceps_pending_email_task_v1'  // Legacy - for migration
const PENDING_EMAIL_TASKS_KEY = 'wceps_pending_email_tasks_v2'   // New: map of tasks by taskId
const MAX_SAVED_RUNS = 3

// Map of pending email tasks keyed by taskId
type PendingEmailTasksMap = Record<string, PendingEmailTask>

// Type for pending email task (auto-save when navigating away)
interface PendingEmailTaskPrep {
  evidence_pack: EvidencePack
  treasure_hooks: WebHook[]
  filtered_requirements: FilteredRequirement[]
  district_research?: DistrictResearchResult | null
  conferences?: ConferenceOpportunity[]
  warnings: string[]
}

interface PendingEmailTask {
  taskId: string
  product: string
  stateCode: string
  stateName: string
  audience: string
  purposePrompt?: string
  selectedHookLinks: string[]
  primaryHookLink?: string
  startedAt: string
  prep?: PendingEmailTaskPrep  // Cached prep data for restoration
  hookReasonTags?: Record<string, string[]>
  hookReasonNotes?: Record<string, string>
}

const safeJsonParse = <T,>(raw: string | null): T | null => {
  if (!raw) return null
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

const getNowIso = (): string => new Date().toISOString()

const makeId = (): string => {
  try {
    return crypto.randomUUID()
  } catch {
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`
  }
}

const loadSavedRuns = (): ResearchRunSnapshot[] => {
  try {
    const parsed = safeJsonParse<ResearchRunSnapshot[]>(
      window.localStorage.getItem(RESEARCH_RUNS_STORAGE_KEY)
    )
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

const saveRuns = (runs: ResearchRunSnapshot[]) => {
  try {
    window.localStorage.setItem(RESEARCH_RUNS_STORAGE_KEY, JSON.stringify(runs))
  } catch {
    // Ignore storage quota errors
  }
}

// Pending email task helpers (for auto-save on navigate away)
// Now supports multiple concurrent tasks stored as a map by taskId

const loadAllPendingEmailTasks = (): PendingEmailTasksMap => {
  try {
    // First, check for and migrate legacy v1 single-task format
    const legacyRaw = window.localStorage.getItem(PENDING_EMAIL_TASK_KEY_V1)
    if (legacyRaw) {
      const legacyTask = JSON.parse(legacyRaw) as PendingEmailTask
      window.localStorage.removeItem(PENDING_EMAIL_TASK_KEY_V1)
      // Migrate to v2 format
      const migrated: PendingEmailTasksMap = { [legacyTask.taskId]: legacyTask }
      window.localStorage.setItem(PENDING_EMAIL_TASKS_KEY, JSON.stringify(migrated))
      return migrated
    }
    
    // Load v2 format
    const raw = window.localStorage.getItem(PENDING_EMAIL_TASKS_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as PendingEmailTasksMap
    return typeof parsed === 'object' && parsed !== null ? parsed : {}
  } catch {
    return {}
  }
}

const savePendingEmailTask = (task: PendingEmailTask) => {
  try {
    const existing = loadAllPendingEmailTasks()
    existing[task.taskId] = task
    window.localStorage.setItem(PENDING_EMAIL_TASKS_KEY, JSON.stringify(existing))
  } catch {
    // Ignore storage quota errors
  }
}

const clearPendingEmailTask = (taskId: string) => {
  try {
    const existing = loadAllPendingEmailTasks()
    delete existing[taskId]
    window.localStorage.setItem(PENDING_EMAIL_TASKS_KEY, JSON.stringify(existing))
  } catch {
    // Ignore
  }
}

function EmailGeneratorV1() {
  // Step state
  const [currentStep, setCurrentStep] = useState<Step>('select')
  
  // User identification (persisted to localStorage so you can find your info later)
  const [createdBy, setCreatedBy] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('wceps_created_by') || ''
    }
    return ''
  })
  
  // Selection state - single product, multi-state, single audience
  const [selectedProduct, setSelectedProduct] = useState<string | null>(null)
  const [selectedStates, setSelectedStates] = useState<SelectedState[]>([])
  const [selectedAudience, setSelectedAudience] = useState<string>('Decision Makers')
  
  // Research results
  const [researchResults, setResearchResults] = useState<ResearchResponse | null>(null)
  const [savedRuns, setSavedRuns] = useState<ResearchRunSnapshot[]>([])
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  
  // Curation state
  const [selectedFunding, setSelectedFunding] = useState<FundingItem[]>([])
  const [selectedComplianceFunding, setSelectedComplianceFunding] = useState<ComplianceFundingItem[]>([])
  const [selectedCompliance, setSelectedCompliance] = useState<ComplianceItem[]>([])
  
  // Generated email
  const [generatedEmail, setGeneratedEmail] = useState<GenerateEmailResponse | null>(null)
  const [copied, setCopied] = useState(false)

  // Save/Upload model emails (good exemplars) into the KB
  const [showModelEmailUploader, setShowModelEmailUploader] = useState(false)
  const [modelSubjectLine, setModelSubjectLine] = useState('')
  const [modelEmailBody, setModelEmailBody] = useState('')
  const [modelProduct, setModelProduct] = useState('')
  const [modelStatesInput, setModelStatesInput] = useState('')
  const [modelAudience, setModelAudience] = useState('')
  const [modelMessage, setModelMessage] = useState('')
  const [modelTiming, setModelTiming] = useState('')
  const [modelTagsInput, setModelTagsInput] = useState('')
  const [modelNotes, setModelNotes] = useState('')

  // Research mutation - single product, can target multiple states
  const researchMutation = useMutation({
    mutationFn: () => api.research.research({
      product: selectedProduct || '', // Single product
      state: selectedStates[0]?.code || '', // Primary state
      audience: selectedAudience, // Single audience
      // Additional states passed as context
      additional_products: [],
      additional_states: selectedStates.slice(1).map(s => s.code),
      created_by: createdBy || undefined,
    }),
    onSuccess: (data) => {
      setResearchResults(data)
      // Create a saved snapshot so results are stable to revisit later
      const snapshot: ResearchRunSnapshot = {
        id: makeId(),
        createdAt: getNowIso(),
        criteria: {
          products: selectedProduct ? [selectedProduct] : [],
          states: selectedStates,
          audience: selectedAudience,
        },
        // Avoid persisting large raw debug fields in localStorage
        results: {
          ...data,
          raw_kb_content: undefined,
          raw_funding_content: undefined,
          raw_compliance_funding_content: undefined,
          raw_compliance_content: undefined,
        },
        selections: {
          selectedFunding: [],
          selectedComplianceFunding: [],
          selectedCompliance: [],
        },
      }

      setActiveRunId(snapshot.id)
      setSelectedFunding([])
      setSelectedComplianceFunding([])
      setSelectedCompliance([])

      setSavedRuns((prev) => {
        const next = [snapshot, ...(prev || [])].slice(0, MAX_SAVED_RUNS)
        saveRuns(next)
        return next
      })
      setCurrentStep('curate')
    },
  })

  // Generate mutation
  const generateMutation = useMutation({
    mutationFn: () => api.generate.email({
      product: selectedProduct || '',
      state: selectedStates.map(s => s.code).join(', '),
      state_full: selectedStates.map(s => s.name).join(', '),
      audience: selectedAudience,
      selected_funding: selectedFunding.map(f => ({
        title: f.title,
        description: f.description,
        amount: f.amount,
        email_hook: f.email_hook,
      })),
      selected_compliance: selectedCompliance.map(c => ({
        title: c.title,
        description: c.description,
        type: c.type,
        email_hook: c.email_hook,
      })),
      selected_compliance_funding: selectedComplianceFunding.map(cf => ({
        title: cf.title,
        description: cf.description,
        amount: cf.amount,
        compliance_trigger: cf.compliance_trigger,
        action_required: cf.action_required,
        email_hook: cf.email_hook,
      })),
    }),
    onSuccess: (data) => {
      setGeneratedEmail(data)
      setCurrentStep('done')
    },
  })

  const parseCommaList = (raw: string): string[] => {
    return raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
  }

  const openModelEmailUploader = (opts?: { prefillFromGenerated?: boolean }) => {
    const prefillFromGenerated = Boolean(opts?.prefillFromGenerated)

    // Prefill metadata from current selections
    setModelProduct(selectedProduct || '')
    setModelStatesInput(selectedStates.map((s) => s.code).join(', '))
    setModelAudience(selectedAudience)

    if (prefillFromGenerated && generatedEmail) {
      setModelSubjectLine(generatedEmail.subject_line || '')
      setModelEmailBody(generatedEmail.email_body || '')
    } else {
      setModelSubjectLine('')
      setModelEmailBody('')
    }

    setShowModelEmailUploader(true)
  }

  const saveModelEmailMutation = useMutation({
    mutationFn: () =>
      api.kb.createEmailExample({
        subject_line: modelSubjectLine,
        email_body: modelEmailBody,
        product: modelProduct.trim() || undefined,
        states: parseCommaList(modelStatesInput).map((s) => s.toUpperCase()),
        audience: modelAudience.trim() || undefined,
        message: modelMessage.trim() || undefined,
        timing: modelTiming.trim() || undefined,
        tags: parseCommaList(modelTagsInput),
        notes: modelNotes.trim() || undefined,
      }),
    onSuccess: (data) => {
      toast({ title: 'Saved model email', description: data.id })
      setShowModelEmailUploader(false)
    },
    onError: (error) => {
      toast({
        title: 'Save failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })

  const canResearch = selectedProduct !== null && selectedStates.length > 0 && selectedAudience !== ''
  const canGenerate = selectedFunding.length > 0 || selectedComplianceFunding.length > 0 || selectedCompliance.length > 0

  const handleStartResearch = () => {
    setCurrentStep('research')
    researchMutation.mutate()
  }

  const handleGenerate = () => {
    setCurrentStep('generate')
    generateMutation.mutate()
  }

  const handleCopyEmail = () => {
    if (!generatedEmail) return
    const fullEmail = `Subject: ${generatedEmail.subject_line}\n\n${generatedEmail.email_body}`
    navigator.clipboard.writeText(fullEmail)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleReset = () => {
    setCurrentStep('select')
    setSelectedProduct(null)
    setSelectedStates([])
    setSelectedAudience('Decision Makers')
    setResearchResults(null)
    setActiveRunId(null)
    setSelectedFunding([])
    setSelectedComplianceFunding([])
    setSelectedCompliance([])
    setGeneratedEmail(null)
  }

  const handleExportCSV = () => {
    if (!generatedEmail) return
    
    const headers = ['Subject Line', 'Email Body', 'Products', 'States', 'Audience', 'Word Count']
    const row = [
      `"${generatedEmail.subject_line.replace(/"/g, '""')}"`,
      `"${generatedEmail.email_body.replace(/"/g, '""')}"`,
      `"${selectedProduct || ''}"`,
      `"${selectedStates.map(s => s.name).join(', ')}"`,
      `"${selectedAudience}"`,
      generatedEmail.word_count.toString(),
    ]
    
    const csv = [headers.join(','), row.join(',')].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `email-${selectedProduct?.toLowerCase().replace(/\s+/g, '-') || 'wceps'}-${selectedStates[0]?.code || 'multi'}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  // Load saved runs once on mount
  useEffect(() => {
    const runs = loadSavedRuns()
    if (runs.length > 0) {
      setSavedRuns(runs)
    }
  }, [])

  // Persist curation selections into the active saved run snapshot
  useEffect(() => {
    if (!activeRunId) return
    setSavedRuns((prev) => {
      const next = (prev || []).map((run) => {
        if (run.id !== activeRunId) return run
        return {
          ...run,
          selections: {
            selectedFunding,
            selectedComplianceFunding,
            selectedCompliance,
          },
        }
      })
      saveRuns(next)
      return next
    })
  }, [activeRunId, selectedFunding, selectedComplianceFunding, selectedCompliance])

  // Map old audiences to new simplified format
  const mapOldAudience = (audience: string): string => {
    const mapping: Record<string, string> = {
      'District Leadership': 'Decision Makers',
      'Curriculum Directors': 'Decision Makers',
      'ELL/Multilingual Directors': 'Decision Makers',
      'Principals': 'Decision Makers',
      'Teachers': 'Users',
      'Title III Coordinators': 'Decision Makers',
    }
    return mapping[audience] || audience
  }

  const resumeRun = (run: ResearchRunSnapshot) => {
    setSelectedProduct(run.criteria.products?.[0] || null)
    setSelectedStates(run.criteria.states || [])
    // Handle both old array format and new single format
    const oldAudiences = (run.criteria as { audiences?: string[] }).audiences
    const newAudience = (run.criteria as { audience?: string }).audience
    if (newAudience) {
      setSelectedAudience(mapOldAudience(newAudience))
    } else if (oldAudiences && oldAudiences.length > 0) {
      setSelectedAudience(mapOldAudience(oldAudiences[0]))
    } else {
      setSelectedAudience('Decision Makers')
    }
    setResearchResults(run.results)
    setSelectedFunding(run.selections.selectedFunding || [])
    setSelectedComplianceFunding(run.selections.selectedComplianceFunding || [])
    setSelectedCompliance(run.selections.selectedCompliance || [])
    setActiveRunId(run.id)
    setCurrentStep('curate')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const clearSavedRuns = () => {
    setSavedRuns([])
    try {
      window.localStorage.removeItem(RESEARCH_RUNS_STORAGE_KEY)
    } catch {
      // ignore
    }
  }

  // Handle clicking on a step to navigate
  const handleStepClick = (step: Step) => {
    const currentIndex = STEP_ORDER.indexOf(currentStep)
    const targetIndex = STEP_ORDER.indexOf(step)
    
    // Can only go back to completed steps or current step
    if (targetIndex <= currentIndex) {
      // Don't go to research or generate steps directly (they're loading states)
      if (step === 'research' || step === 'generate') {
        return
      }
      setCurrentStep(step)
    }
  }

  // Get step status for styling
  const getStepStatus = (step: Step) => {
    const currentIndex = STEP_ORDER.indexOf(currentStep)
    const stepIndex = STEP_ORDER.indexOf(step)
    
    if (step === currentStep) return 'current'
    if (stepIndex < currentIndex) return 'completed'
    return 'upcoming'
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      {/* Model email upload modal */}
      {showModelEmailUploader && (
        <div
          className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
          onClick={() => setShowModelEmailUploader(false)}
        >
          <div
            className="w-full max-w-2xl rounded-xl border border-slate-700 bg-slate-900 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 border-b border-slate-700/60 flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-slate-100">Upload model email</h2>
                <p className="text-sm text-slate-400 mt-1">
                  Save a high-performing email so the generator can imitate its structure and voice.
                </p>
              </div>
              <button
                onClick={() => setShowModelEmailUploader(false)}
                className="text-slate-400 hover:text-slate-200 transition-colors"
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            <div className="p-6 space-y-4">
              <div>
                <label className="block text-xs text-slate-400 uppercase tracking-wide mb-2">
                  Subject line
                </label>
                <input
                  type="text"
                  value={modelSubjectLine}
                  onChange={(e) => setModelSubjectLine(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-slate-950 border border-slate-700 text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
                  placeholder="Subject line"
                />
              </div>

              <div>
                <label className="block text-xs text-slate-400 uppercase tracking-wide mb-2">
                  Email body
                </label>
                <textarea
                  value={modelEmailBody}
                  onChange={(e) => setModelEmailBody(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-slate-950 border border-slate-700 text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 min-h-[180px]"
                  placeholder="Paste the full email body here"
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-slate-400 uppercase tracking-wide mb-2">
                    Product (optional)
                  </label>
                  <input
                    type="text"
                    value={modelProduct}
                    onChange={(e) => setModelProduct(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-slate-950 border border-slate-700 text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
                    placeholder="e.g. CARE Coaching"
                  />
                </div>

                <div>
                  <label className="block text-xs text-slate-400 uppercase tracking-wide mb-2">
                    States (optional)
                  </label>
                  <input
                    type="text"
                    value={modelStatesInput}
                    onChange={(e) => setModelStatesInput(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-slate-950 border border-slate-700 text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
                    placeholder="Comma-separated codes, e.g. FL, CO"
                  />
                </div>

                <div>
                  <label className="block text-xs text-slate-400 uppercase tracking-wide mb-2">
                    Audience (optional)
                  </label>
                  <input
                    type="text"
                    value={modelAudience}
                    onChange={(e) => setModelAudience(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-slate-950 border border-slate-700 text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
                    placeholder="e.g. District Leadership"
                  />
                </div>

                <div>
                  <label className="block text-xs text-slate-400 uppercase tracking-wide mb-2">
                    Message + timing (optional)
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={modelMessage}
                      onChange={(e) => setModelMessage(e.target.value)}
                      className="w-1/2 px-3 py-2 rounded-md bg-slate-950 border border-slate-700 text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
                      placeholder="message"
                    />
                    <input
                      type="text"
                      value={modelTiming}
                      onChange={(e) => setModelTiming(e.target.value)}
                      className="w-1/2 px-3 py-2 rounded-md bg-slate-950 border border-slate-700 text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
                      placeholder="timing"
                    />
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-slate-400 uppercase tracking-wide mb-2">
                    Tags (optional)
                  </label>
                  <input
                    type="text"
                    value={modelTagsInput}
                    onChange={(e) => setModelTagsInput(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-slate-950 border border-slate-700 text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
                    placeholder="Comma-separated tags"
                  />
                </div>

                <div>
                  <label className="block text-xs text-slate-400 uppercase tracking-wide mb-2">
                    Notes (optional)
                  </label>
                  <input
                    type="text"
                    value={modelNotes}
                    onChange={(e) => setModelNotes(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-slate-950 border border-slate-700 text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
                    placeholder="Short internal note"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  onClick={() => setShowModelEmailUploader(false)}
                  className="px-4 py-2 rounded-md bg-slate-800 text-slate-200 hover:bg-slate-700 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => saveModelEmailMutation.mutate()}
                  disabled={saveModelEmailMutation.isPending}
                  className={`px-4 py-2 rounded-md font-medium transition-colors ${
                    saveModelEmailMutation.isPending
                      ? 'bg-emerald-700/40 text-emerald-200 cursor-not-allowed'
                      : 'bg-emerald-600 hover:bg-emerald-500 text-white'
                  }`}
                >
                  {saveModelEmailMutation.isPending ? 'Saving…' : 'Save to KB'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="border-b border-slate-700/50 bg-slate-900/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-slate-100">
                WCEPS Email Generator
              </h1>
              <p className="text-sm text-slate-400 mt-1">
                Create targeted sales emails with AI-powered research
              </p>
            </div>
            
            <div className="flex items-center gap-3">
              <Link
                to="/saved-runs"
                className="px-4 py-2 rounded-md bg-emerald-600 text-white font-medium hover:bg-emerald-500 transition-colors text-sm flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
                </svg>
                Saved Research
              </Link>
              <Link
                to="/coverage"
                className="px-4 py-2 rounded-md bg-indigo-600 text-white font-medium hover:bg-indigo-500 transition-colors text-sm flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
                Coverage Matrix
              </Link>
              <Link
                to="/training"
                className="px-3 py-2 rounded-md bg-slate-800/60 text-amber-300 border border-amber-700/50 hover:bg-amber-900/30 transition-colors text-sm"
                title="View golden emails and training feedback"
              >
                Training Data
              </Link>
              <button
                onClick={() => openModelEmailUploader()}
                className="px-3 py-2 rounded-md bg-slate-800/60 text-slate-200 border border-slate-700 hover:bg-slate-800 transition-colors text-sm"
                title="Upload a high-performing email so the generator can learn from it"
              >
                Upload model email
              </button>

              <ThemeToggle />

              {/* Progress Steps - Clickable */}
              <div className="flex items-center gap-2">
                {STEP_ORDER.map((step, i) => {
                  const status = getStepStatus(step)
                  const isClickable = status === 'completed' || status === 'current'
                  const isTransitional = step === 'research' || step === 'generate'
                  
                  return (
                    <div
                      key={step}
                      className={`flex items-center ${i > 0 ? 'ml-2' : ''}`}
                    >
                      {i > 0 && (
                        <div className={`w-8 h-0.5 mr-2 ${
                          STEP_ORDER.indexOf(currentStep) >= i
                            ? 'bg-emerald-500'
                            : 'bg-slate-700'
                        }`} />
                      )}
                      <button
                        onClick={() => handleStepClick(step)}
                        disabled={!isClickable || isTransitional}
                        className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium transition-all ${
                          status === 'current'
                            ? 'bg-emerald-500 text-white'
                            : status === 'completed'
                              ? 'bg-emerald-600/50 text-emerald-300 hover:bg-emerald-600/70 cursor-pointer'
                              : 'bg-slate-700 text-slate-400'
                        } ${isClickable && !isTransitional ? 'hover:ring-2 hover:ring-emerald-500/50' : ''}`}
                        title={`${STEP_LABELS[step]}${isClickable && !isTransitional ? ' (click to edit)' : ''}`}
                      >
                        {status === 'completed' ? (
                          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                        ) : (
                          i + 1
                        )}
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-6xl mx-auto px-6 py-8">
        {/* Step 1: Selection */}
        {currentStep === 'select' && (
          <div className="space-y-6">
            {/* Saved runs (stable snapshots) */}
            {savedRuns.length > 0 && (
              <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-medium text-slate-200">Recent research runs</h3>
                    <p className="text-xs text-slate-400 mt-1">
                      Resume an earlier run to see the exact same results you liked (no re-search).
                    </p>
                  </div>
                  <button
                    onClick={clearSavedRuns}
                    className="text-xs text-slate-400 hover:text-slate-200 transition-colors"
                  >
                    Clear
                  </button>
                </div>

                <div className="mt-3 space-y-2">
                  {savedRuns.map((run) => (
                    <div
                      key={run.id}
                      className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 bg-slate-900/40 rounded-lg p-3 border border-slate-700/60"
                    >
                      <div className="text-sm">
                        <div className="text-slate-200">
                          {run.criteria.products?.[0] || 'Product'} · {run.criteria.states?.[0]?.name || 'State'} · {run.criteria.audiences?.[0] || 'Audience'}
                        </div>
                        <div className="text-xs text-slate-500 mt-0.5">
                          Saved {new Date(run.createdAt).toLocaleString()}
                        </div>
                      </div>
                      <button
                        onClick={() => resumeRun(run)}
                        className="px-3 py-2 rounded-md bg-emerald-600/20 text-emerald-300 border border-emerald-600/40 hover:bg-emerald-600/30 transition-colors text-sm"
                      >
                        Resume results
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Your Name (so you can find your info later) */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Your Name <span className="text-slate-500">(so you can find your info later)</span>
              </label>
              <input
                type="text"
                value={createdBy}
                onChange={(e) => {
                  const name = e.target.value
                  setCreatedBy(name)
                  localStorage.setItem('wceps_created_by', name)
                }}
                placeholder="e.g., Sarah Martinez"
                className="w-full max-w-xs px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500"
              />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="lg:col-span-1">
                <ProductSelector
                  selectedProduct={selectedProduct}
                  onSelect={setSelectedProduct}
                />
              </div>
              
              <div className="lg:col-span-1">
                <StateSelector
                  selectedStates={selectedStates}
                  onSelect={setSelectedStates}
                />
              </div>
              
              <div className="lg:col-span-1">
                <AudienceSelector
                  selectedProduct={selectedProduct}
                  selectedAudience={selectedAudience}
                  onSelect={setSelectedAudience}
                />
              </div>
            </div>

            {/* Selection Summary */}
            {(selectedProduct !== null || selectedStates.length > 0 || selectedAudience) && (
              <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
                <h3 className="text-sm font-medium text-slate-300 mb-3">Selection Summary</h3>
                <div className="flex flex-wrap gap-2">
                  {selectedProduct && (
                    <span className="px-2 py-1 bg-emerald-900/50 text-emerald-400 rounded text-sm">
                      {selectedProduct}
                    </span>
                  )}
                  {selectedStates.map(s => (
                    <span key={s.code} className="px-2 py-1 bg-blue-900/50 text-blue-400 rounded text-sm">
                      {s.name}
                    </span>
                  ))}
                  {selectedAudience && (
                    <span className="px-2 py-1 bg-purple-900/50 text-purple-400 rounded text-sm">
                      {selectedAudience}
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* Start Research Button */}
            <div className="flex justify-center pt-6">
              <button
                onClick={handleStartResearch}
                disabled={!canResearch}
                className={`px-8 py-4 rounded-xl text-lg font-semibold transition-all ${
                  canResearch
                    ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-500/25'
                    : 'bg-slate-700 text-slate-400 cursor-not-allowed'
                }`}
              >
                🔍 Start Research
              </button>
            </div>

            {/* Quick return to active run (if user clicked edit from curation) */}
            {researchResults && activeRunId && (
              <div className="flex justify-center">
                <button
                  onClick={() => setCurrentStep('curate')}
                  className="text-sm text-slate-400 hover:text-slate-200 transition-colors"
                >
                  Back to last results (no re-search)
                </button>
              </div>
            )}
          </div>
        )}

        {/* Step 2: Researching - with progress sub-steps */}
        {currentStep === 'research' && (
          <div className="flex flex-col items-center justify-center py-12">
            <div className="w-16 h-16 border-4 border-emerald-500 border-t-transparent rounded-full animate-spin mb-6" />
            <h2 className="text-xl font-semibold text-slate-200 mb-2">
              Researching...
            </h2>
            <p className="text-slate-400 text-center max-w-md mb-6">
              Finding funding opportunities and compliance requirements for{' '}
              <span className="text-emerald-400">{selectedProduct || ''}</span> in{' '}
              <span className="text-emerald-400">{selectedStates.map(s => s.name).join(', ')}</span>
            </p>
            
            {/* Progress Sub-Steps */}
            <div className="w-full max-w-md bg-slate-800/50 rounded-lg border border-slate-700 p-4">
              <div className="space-y-3">
                <ResearchProgressStep 
                  step={1} 
                  label="Querying knowledge base for product context" 
                  isActive={true}
                  isComplete={false}
                />
                <ResearchProgressStep 
                  step={2} 
                  label="Researching government funding (federal, state, district)" 
                  isActive={false}
                  isComplete={false}
                />
                <ResearchProgressStep 
                  step={3} 
                  label="Researching compliance requirements" 
                  isActive={false}
                  isComplete={false}
                />
                <ResearchProgressStep 
                  step={4} 
                  label="Scoring and ranking by relevance" 
                  isActive={false}
                  isComplete={false}
                />
              </div>
              
              <div className="mt-4 pt-4 border-t border-slate-700">
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <svg className="w-4 h-4 animate-pulse text-emerald-500" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                  </svg>
                  Finding government funding "hidden gems" beyond Title I/III: federal, state, district sources...
                </div>
              </div>
            </div>
            
            <div className="mt-4 text-sm text-slate-500">
              This may take 30-60 seconds...
            </div>
          </div>
        )}

        {/* Step 3: Curation */}
        {currentStep === 'curate' && researchResults && (
          <div className="space-y-6">
            {/* Selection Summary - Clickable to edit */}
            <div className="flex items-center gap-4 text-sm flex-wrap">
              <button 
                onClick={() => setCurrentStep('select')}
                className="flex items-center gap-2 px-3 py-1 bg-emerald-900/50 text-emerald-400 rounded-full hover:bg-emerald-900/70 transition-colors"
              >
                {selectedProduct || ''}
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                </svg>
              </button>
              <button 
                onClick={() => setCurrentStep('select')}
                className="flex items-center gap-2 px-3 py-1 bg-blue-900/50 text-blue-400 rounded-full hover:bg-blue-900/70 transition-colors"
              >
                {selectedStates.map(s => s.name).join(', ')}
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                </svg>
              </button>
              <button 
                onClick={() => setCurrentStep('select')}
                className="flex items-center gap-2 px-3 py-1 bg-purple-900/50 text-purple-400 rounded-full hover:bg-purple-900/70 transition-colors"
              >
                {selectedAudience}
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                </svg>
              </button>
            </div>

            {/* Curation UI */}
            <CurationStep
              kbFunding={researchResults.kb_funding || []}
              kbComplianceFunding={researchResults.kb_compliance_funding || []}
              kbCompliance={researchResults.kb_compliance || []}
              webFunding={researchResults.web_funding || []}
              webComplianceFunding={researchResults.web_compliance_funding || []}
              webCompliance={researchResults.web_compliance || []}
              selectedFunding={selectedFunding}
              selectedComplianceFunding={selectedComplianceFunding}
              selectedCompliance={selectedCompliance}
              onSelectFunding={setSelectedFunding}
              onSelectComplianceFunding={setSelectedComplianceFunding}
              onSelectCompliance={setSelectedCompliance}
            />

            {/* Generate Button */}
            <div className="flex justify-center pt-6 gap-4">
              <button
                onClick={() => setCurrentStep('select')}
                className="px-6 py-3 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 transition-colors"
              >
                ← Back to Selection
              </button>
              <button
                onClick={handleGenerate}
                disabled={!canGenerate}
                className={`px-8 py-3 rounded-lg text-lg font-semibold transition-all ${
                  canGenerate
                    ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-500/25'
                    : 'bg-slate-700 text-slate-400 cursor-not-allowed'
                }`}
              >
                ✨ Generate Email
              </button>
            </div>
          </div>
        )}

        {/* Step 4: Generating */}
        {currentStep === 'generate' && (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-16 h-16 border-4 border-emerald-500 border-t-transparent rounded-full animate-spin mb-6" />
            <h2 className="text-xl font-semibold text-slate-200 mb-2">
              Generating Email...
            </h2>
            <p className="text-slate-400">
              Crafting a personalized email for {selectedAudience}
            </p>
          </div>
        )}

        {/* Step 5: Done - Show Email */}
        {currentStep === 'done' && generatedEmail && (
          <div className="space-y-6">
            {/* Selection Summary - Clickable to edit */}
            <div className="flex items-center gap-4 text-sm flex-wrap">
              <button 
                onClick={() => setCurrentStep('select')}
                className="flex items-center gap-2 px-3 py-1 bg-emerald-900/50 text-emerald-400 rounded-full hover:bg-emerald-900/70 transition-colors"
                title="Click to edit products"
              >
                {selectedProduct || ''}
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                </svg>
              </button>
              <button 
                onClick={() => setCurrentStep('select')}
                className="flex items-center gap-2 px-3 py-1 bg-blue-900/50 text-blue-400 rounded-full hover:bg-blue-900/70 transition-colors"
                title="Click to edit states"
              >
                {selectedStates.map(s => s.name).join(', ')}
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                </svg>
              </button>
              <button 
                onClick={() => setCurrentStep('select')}
                className="flex items-center gap-2 px-3 py-1 bg-purple-900/50 text-purple-400 rounded-full hover:bg-purple-900/70 transition-colors"
                title="Click to edit audience"
              >
                {selectedAudience}
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                </svg>
              </button>
              <button 
                onClick={() => setCurrentStep('curate')}
                className="flex items-center gap-2 px-3 py-1 bg-slate-700 text-slate-300 rounded-full hover:bg-slate-600 transition-colors"
                title="Click to edit curation"
              >
                Edit Curation
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                </svg>
              </button>
              <span className="px-3 py-1 bg-slate-700 text-slate-300 rounded-full">
                {generatedEmail.word_count} words
              </span>
            </div>

            {/* Email Preview */}
            <div className="bg-slate-800/50 rounded-xl border border-slate-700 overflow-hidden">
              {/* Subject Line */}
              <div className="px-6 py-4 border-b border-slate-700 bg-slate-800/80">
                <label className="text-xs text-slate-500 uppercase tracking-wide">Subject Line</label>
                <div className="mt-1 text-lg font-medium text-slate-200">
                  {generatedEmail.subject_line}
                </div>
              </div>
              
              {/* Email Body */}
              <div className="px-6 py-4">
                <label className="text-xs text-slate-500 uppercase tracking-wide">Email Body</label>
                <div className="mt-2 text-slate-300 whitespace-pre-wrap leading-relaxed">
                  {generatedEmail.email_body}
                </div>
              </div>
            </div>

            {/* Action Buttons */}
            <div className="flex justify-center gap-4 pt-4 flex-wrap">
              <button
                onClick={handleCopyEmail}
                className={`px-6 py-3 rounded-lg font-medium transition-all flex items-center gap-2 ${
                  copied
                    ? 'bg-emerald-600 text-white'
                    : 'bg-slate-700 hover:bg-slate-600 text-slate-200'
                }`}
              >
                {copied ? (
                  <>
                    <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                    Copied!
                  </>
                ) : (
                  <>
                    📋 Copy Email
                  </>
                )}
              </button>
              
              <button
                onClick={handleExportCSV}
                className="px-6 py-3 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 font-medium transition-colors flex items-center gap-2"
              >
                📥 Export CSV
              </button>

              <button
                onClick={() => openModelEmailUploader({ prefillFromGenerated: true })}
                className="px-6 py-3 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 font-medium transition-colors flex items-center gap-2"
              >
                💾 Save as Model Email
              </button>
              
              <button
                onClick={() => {
                  // Re-run generation with same selections
                  setCurrentStep('generate')
                  generateMutation.mutate()
                }}
                className="px-6 py-3 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 font-medium transition-colors flex items-center gap-2"
              >
                🔄 Regenerate
              </button>
              
              <button
                onClick={handleReset}
                className="px-6 py-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium transition-colors"
              >
                + New Email
              </button>
            </div>
          </div>
        )}

        {/* Error Display */}
        {(researchMutation.isError || generateMutation.isError) && (
          <div className="mt-6 p-4 bg-red-900/30 border border-red-800 rounded-lg text-red-400">
            <strong>Error:</strong>{' '}
            {researchMutation.error?.message || generateMutation.error?.message || 'Something went wrong'}
            <button
              onClick={() => setCurrentStep('select')}
              className="ml-4 text-sm underline hover:text-red-300"
            >
              Go back and try again
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// Wizard steps for V3 pipeline
type WizardStep = 1 | 2 | 3 | 4 | 5
const WIZARD_STEP_LABELS: Record<WizardStep, string> = {
  1: 'Choose Product & Audience',
  2: 'Research',
  3: 'Select',
  4: 'Generate Email',
  5: 'Review and Improve Email',
}

// Human-readable stage labels for thinking trace
const STAGE_LABELS: Record<string, string> = {
  'evidence_pack': 'Gathering evidence from knowledge base',
  'treasure_hunter': 'Running Deep Research',
  'hook_gate': 'Filtering requirements',
  'district_research': 'Surveying districts for opportunities',
  'hook_selector': 'Selecting best hooks',
  'email_writer': 'Writing email',
  'validator': 'Validating email',
  'repair': 'Improving email',
}

// Get latest meaningful trace message
const getLatestTraceStatus = (events: PipelineStreamEvent[]): string | null => {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i]
    if (e.message && typeof e.message === 'string') return e.message
    if (e.stage && STAGE_LABELS[e.stage as string]) return STAGE_LABELS[e.stage as string]
  }
  return null
}

// Filter events for activity log: collapse heartbeats to just the most recent one
const filterTraceEventsForLog = (events: PipelineStreamEvent[]): PipelineStreamEvent[] => {
  const recent = events.slice(-20) // Take recent events
  const result: PipelineStreamEvent[] = []
  let lastHeartbeatIdx = -1
  
  // Find the last heartbeat index
  for (let i = recent.length - 1; i >= 0; i--) {
    if (recent[i].type === 'heartbeat') {
      lastHeartbeatIdx = i
      break
    }
  }
  
  // Include all non-heartbeat events, plus only the last heartbeat
  for (let i = 0; i < recent.length; i++) {
    if (recent[i].type !== 'heartbeat' || i === lastHeartbeatIdx) {
      result.push(recent[i])
    }
  }
  
  return result.slice(-10) // Return last 10
}

// Get display text for a trace event
const getEventDisplayText = (
  e: PipelineStreamEvent, 
  researchStartTime: Date | null
): string => {
  if (e.type === 'heartbeat') {
    const elapsed = researchStartTime 
      ? Math.floor((Date.now() - researchStartTime.getTime()) / 1000)
      : 0
    const mins = Math.floor(elapsed / 60)
    const secs = elapsed % 60
    return `Still researching... (${mins}m ${secs}s)`
  }
  
  const stageLabel = e.stage ? STAGE_LABELS[e.stage as string] : null
  return (typeof e.message === 'string' && e.message) || stageLabel || String(e.type)
}

type ReviewSectionKey = 'subject_line' | 'hook_usage' | 'product_relevance' | 'tone' | 'flow' | 'cta'

type ReviewRubricItemDraft = {
  score: number | null
  comment: string
}

type ReviewDraft = {
  edited_subject_line: string
  edited_email_body: string
  rubric: Record<ReviewSectionKey, ReviewRubricItemDraft>
}

// Cache status type
type CacheStatus = {
  status: 'completed' | 'in_progress' | 'pending' | 'failed' | 'cancelled' | 'not_found' | 'expired' | 'loading'
  cache_age_days?: number
  cached_at?: string
  expires_in_days?: number
  hook_count?: number
  elapsed_minutes?: number
  started_at?: string
  error?: string
}

interface EmailGeneratorPipelineProps {
  flowMode: FlowMode
}

function EmailGeneratorPipeline({ flowMode }: EmailGeneratorPipelineProps) {
  const [wizardStep, setWizardStep] = useState<WizardStep>(1)
  const [selectedProduct, setSelectedProduct] = useState<string | null>(null)
  const [selectedStates, setSelectedStates] = useState<SelectedState[]>([])
  const [selectedAudience, setSelectedAudience] = useState<string>('Decision Makers')

  // User identification (persisted to localStorage so you can find your info later)
  const [createdBy, setCreatedBy] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('wceps_created_by') || ''
    }
    return ''
  })

  // District name/URL removed - district research now handled automatically by checkbox
  
  // District research option
  const [includeDistrictResearch, setIncludeDistrictResearch] = useState(false)
  const [districtResearchStatus, setDistrictResearchStatus] = useState<'idle' | 'running' | 'complete'>('idle')
  const [districtResearchProgress, setDistrictResearchProgress] = useState(0)
  const [districtResearchMessage, setDistrictResearchMessage] = useState('')
  
  // Conference research option  
  const [includeConferenceResearch, setIncludeConferenceResearch] = useState(false)
  
  // Polling-based research state (robust against browser sleep/network issues)
  const [researchPhase, setResearchPhase] = useState<'idle' | 'state' | 'district' | 'conferences'>('idle')
  const [, setResearchTaskId] = useState<string | null>(null)
  const [researchProgress, setResearchProgress] = useState(0)
  const [researchMessage, setResearchMessage] = useState('')

  // Custom purpose + cached hooks flow
  const [purposePrompt, setPurposePrompt] = useState('')
  const [cachedPrepByState, setCachedPrepByState] = useState<Record<string, CachedPrepResult | null>>({})
  const [cachedPrepLoading, setCachedPrepLoading] = useState(false)
  const [selectedCachedHooks, setSelectedCachedHooks] = useState<SelectedCachedHook[]>([])
  const [stateHooksExpanded, setStateHooksExpanded] = useState(true)
  const [districtHooksExpanded, setDistrictHooksExpanded] = useState(false)
  const [conferenceHooksExpanded, setConferenceHooksExpanded] = useState(false)

  // Cache status for the current state+product selection
  const [cacheStatus, setCacheStatus] = useState<CacheStatus | null>(null)
  const [showReSearchConfirm, setShowReSearchConfirm] = useState(false)

  const selectedProductKey = selectedProduct || ''
  const selectedStateKey = selectedStates.map((st) => st.code).join(',')
  const hasCachedPrep = selectedStates.some((st) => Boolean(cachedPrepByState[st.code]))
  const showCachedSections = cachedPrepLoading || hasCachedPrep
  const canReSearch = cacheStatus?.status === 'completed' || cacheStatus?.status === 'expired'

  const [result, setResult] = useState<PipelineRunResponse | null>(null)
  const [activeAudience, setActiveAudience] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [traceEvents, setTraceEvents] = useState<PipelineStreamEvent[]>([])
  const [researchStartTime, setResearchStartTime] = useState<Date | null>(null)
  const [emailProgress, setEmailProgress] = useState<{ progress: number; message: string } | null>(null)
  const [currentEmailTaskId, setCurrentEmailTaskId] = useState<string | null>(null)  // Track current task for clearing
  const [backgroundEmailTasks, setBackgroundEmailTasks] = useState<PendingEmailTasksMap>({})  // Track all pending tasks
  const [prep, setPrep] = useState<{ evidence_pack: EvidencePack; treasure_hooks: WebHook[]; filtered_requirements: FilteredRequirement[]; district_research?: DistrictResearchResult | null; conferences?: ConferenceOpportunity[]; warnings: string[] } | null>(null)
  const [blockedFilteredRequirements, setBlockedFilteredRequirements] = useState<FilteredRequirement[]>([])
  // Use hook_id for reliable selection (handles multiple hooks with same URL)
  const [selectedHookKeys, setSelectedHookKeys] = useState<string[]>([])  // hook_id or link fallback
  const [primaryHookKey, setPrimaryHookKey] = useState<string | null>(null)  // hook_id or link fallback
  // Legacy aliases for backwards compatibility
  const selectedHookLinks = selectedHookKeys  
  const setSelectedHookLinks = setSelectedHookKeys
  const primaryHookLink = primaryHookKey
  const setPrimaryHookLink = setPrimaryHookKey
  const [hookReasonTags, setHookReasonTags] = useState<Record<string, string[]>>({})
  const [hookReasonNotes, setHookReasonNotes] = useState<Record<string, string>>({})
  const [reviewDrafts, setReviewDrafts] = useState<Record<string, ReviewDraft>>({})
  const [showFilteredSection, setShowFilteredSection] = useState(false)
  
  // Helper: get unique key for a hook (prefer hook_id, fallback to link)
  const getHookKey = (h: WebHook): string => h.hook_id || h.link

  useEffect(() => {
    setSelectedCachedHooks([])
    setCachedPrepByState({})
  }, [selectedProductKey, selectedStateKey])
  
  // Helper: sanitize evidence_pack to match backend EvidencePack schema
  // Handles legacy saved runs that may have state_code instead of state, or extra fields
  const sanitizeEvidencePack = (ep: EvidencePack): EvidencePack => {
    const raw = ep as unknown as Record<string, unknown>
    return {
      product: ep.product || (raw.product_name as string) || '',
      product_key: ep.product_key,
      state: ep.state || (raw.state_code as string) || '',
      retrieved_chunks: ep.retrieved_chunks || [],
      micro_offer_candidates: ep.micro_offer_candidates || [],
      supplemental_brief: ep.supplemental_brief,
    }
  }
  
  // Saved runs state
  const [showSavedRuns, setShowSavedRuns] = useState(false)
  const [savedRuns, setSavedRuns] = useState<SavedRunSummary[]>([])
  const [loadingSavedRuns, setLoadingSavedRuns] = useState(false)
  const [savingRun, setSavingRun] = useState(false)
  const [currentSavedRunId, setCurrentSavedRunId] = useState<number | null>(null)
  
  // Batch processing state
  const [showBatchModal, setShowBatchModal] = useState(false)
  const [batchStates, setBatchStates] = useState<Array<{ code: string; name: string }>>([])
  const [startingBatch, setStartingBatch] = useState(false)
  const [batchForceFresh, setBatchForceFresh] = useState(false)
  const [batchIncludeDistrictResearch, setBatchIncludeDistrictResearch] = useState(true)
  const [batchIncludeConferenceResearch, setBatchIncludeConferenceResearch] = useState(false)
  const [batchStateInput, setBatchStateInput] = useState('')

  // All 50 US states lookup
  const ALL_US_STATES: Record<string, string> = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California',
    'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware', 'DC': 'District of Columbia', 'FL': 'Florida',
    'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana',
    'IA': 'Iowa', 'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine',
    'MD': 'Maryland', 'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
    'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire',
    'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina', 'ND': 'North Dakota',
    'OH': 'Ohio', 'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island',
    'SC': 'South Carolina', 'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
    'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming',
  }

  // Parse state codes from text input
  const parseAndAddStates = (input: string) => {
    if (!input.trim()) return
    
    // Split by comma, space, or newline and normalize to uppercase
    const codes = input.toUpperCase().split(/[\s,]+/).filter(Boolean)
    const newStates: Array<{ code: string; name: string }> = []
    const invalidCodes: string[] = []
    const existingCodes = new Set(batchStates.map(s => s.code))
    
    for (const code of codes) {
      const name = ALL_US_STATES[code]
      if (name && !existingCodes.has(code)) {
        newStates.push({ code, name })
        existingCodes.add(code)
      } else if (!name) {
        invalidCodes.push(code)
      }
    }
    
    if (newStates.length > 0) {
      setBatchStates(prev => [...prev, ...newStates])
    }
    
    if (invalidCodes.length > 0) {
      toast({
        title: 'Invalid state codes',
        description: `Unknown codes: ${invalidCodes.join(', ')}`,
        variant: 'destructive',
      })
    }
    
    setBatchStateInput('')
  }

  // Handle URL params for batch prefill (from Coverage Matrix page)
  const [searchParams, setSearchParams] = useSearchParams()

  const resetEntryState = () => {
    setWizardStep(1)
    setSelectedProduct(null)
    setSelectedStates([])
    setSelectedAudience('Decision Makers')
    setPurposePrompt('')
    setCachedPrepByState({})
    setCachedPrepLoading(false)
    setSelectedCachedHooks([])
    setStateHooksExpanded(true)
    setDistrictHooksExpanded(false)
    setConferenceHooksExpanded(false)
    setCacheStatus(null)
    setShowReSearchConfirm(false)
    setResult(null)
    setActiveAudience(null)
    setCopied(false)
    setTraceEvents([])
    setResearchStartTime(null)
    setEmailProgress(null)
    setPrep(null)
    setBlockedFilteredRequirements([])
    setSelectedHookLinks([])
    setPrimaryHookLink(null)
    setHookReasonTags({})
    setHookReasonNotes({})
    setReviewDrafts({})
    setShowFilteredSection(false)
    setIncludeDistrictResearch(false)
    setIncludeConferenceResearch(false)
    setResearchPhase('idle')
    setResearchProgress(0)
    setResearchMessage('')
    setShowBatchModal(false)
    setBatchStates([])
    setStartingBatch(false)
    setBatchForceFresh(false)
    setBatchIncludeDistrictResearch(true)
    setBatchIncludeConferenceResearch(false)
    setBatchStateInput('')
    setValidationExpanded(false)
  }
  
  useEffect(() => {
    const shouldReset = searchParams.get('reset') === '1'
    if (!shouldReset) return
    resetEntryState()
    const next = new URLSearchParams(searchParams)
    next.delete('reset')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])
  
  useEffect(() => {
    const batchParam = searchParams.get('batch')
    if (batchParam === 'true') {
      // Get prefill values from URL
      const productParam = searchParams.get('product')
      const statesParam = searchParams.get('states')
      const districtParam = searchParams.get('district')
      const conferenceParam = searchParams.get('conference')
      
      // Set product if specified
      if (productParam) {
        setSelectedProduct(productParam)
      }
      
      // Parse and set states
      if (statesParam) {
        const stateCodes = statesParam.split(',')
        const states = stateCodes
          .map(code => ({ code, name: ALL_US_STATES[code] }))
          .filter(s => s.name)
        setBatchStates(states)
      }
      
      // Set research options
      if (districtParam === 'true') {
        setBatchIncludeDistrictResearch(true)
      }
      if (conferenceParam === 'true') {
        setBatchIncludeConferenceResearch(true)
      }
      
      // Open the batch modal
      setShowBatchModal(true)
      
      // Clear the URL params (without triggering navigation)
      setSearchParams({}, { replace: true })
    }
  }, []) // Only run on mount

  // Validation section collapsed by default
  const [validationExpanded, setValidationExpanded] = useState(false)

  // Load saved run from sessionStorage (when navigating from SavedRuns page)
  useEffect(() => {
    const storedRun = sessionStorage.getItem('loadSavedRun')
    if (!storedRun) return
    
    try {
      const full: SavedRunFull = JSON.parse(storedRun)
      sessionStorage.removeItem('loadSavedRun')
      
      // Restore all state from the saved run
      setSelectedProduct(full.product)
      setSelectedStates([{ code: full.state_code, name: full.state_full || full.state_code }])
      // Handle both old array format and new single format with mapping
      const oldAudienceMap: Record<string, string> = {
        'District Leadership': 'Decision Makers',
        'Curriculum Directors': 'Decision Makers',
        'ELL/Multilingual Directors': 'Decision Makers',
        'Principals': 'Decision Makers',
        'Teachers': 'Users',
        'Title III Coordinators': 'Decision Makers',
      }
      const savedAudience = full.audiences?.[0] || 'Decision Makers'
      setSelectedAudience(oldAudienceMap[savedAudience] || savedAudience)
      
      // Restore pipeline result
      setResult(full.pipeline_response)
      setActiveAudience(full.pipeline_response.variants?.[0]?.audience || null)
      
      // Restore hook selection
      setSelectedHookLinks(full.selected_hook_links)
      setPrimaryHookLink(full.primary_hook_link || null)
      setHookReasonTags(full.hook_reason_tags)
      setHookReasonNotes(full.hook_reason_notes)
      
      // Restore research options (so Re-research remembers original settings)
      setIncludeDistrictResearch(full.include_district_research ?? false)
      setIncludeConferenceResearch(full.include_conference_research ?? false)
      
      // Extract prep data from pipeline response
      // Handle both field names: treasure_hooks (email runs) and hooks (research runs)
      const hooks = full.pipeline_response.treasure_hooks || full.pipeline_response.hooks || []
      if (full.pipeline_response.evidence_pack && hooks.length > 0) {
        setPrep({
          evidence_pack: full.pipeline_response.evidence_pack,
          treasure_hooks: hooks,
          filtered_requirements: full.pipeline_response.filtered_requirements || [],
          district_research: full.pipeline_response.district_research || null,
          conferences: full.pipeline_response.conferences || [],
          warnings: full.pipeline_response.warnings || [],
        })
        setDistrictResearchStatus(full.pipeline_response.district_research ? 'complete' : 'idle')
      }
      
      // Navigate to appropriate step based on run type
      setWizardStep(full.run_type === 'research' ? 3 : 5)
      setCurrentSavedRunId(full.id)
      
      toast({
        title: 'Run loaded',
        description: full.name || `Loaded ${full.product} / ${full.state_code}`,
      })
    } catch (err) {
      console.error('Failed to load saved run from sessionStorage:', err)
      sessionStorage.removeItem('loadSavedRun')
    }
  }, [])

  useEffect(() => {
    if (selectedHookLinks.length === 1) {
      setPrimaryHookLink(selectedHookLinks[0])
      return
    }
    if (selectedHookLinks.length === 2) {
      setPrimaryHookLink((prev) => (prev && selectedHookLinks.includes(prev) ? prev : selectedHookLinks[0]))
      return
    }
    setPrimaryHookLink(null)
  }, [selectedHookLinks])

  useEffect(() => {
    // Keep reason/tag state in sync with current selection
    setHookReasonTags((prev) => {
      const next: Record<string, string[]> = {}
      for (const link of selectedHookLinks) next[link] = prev[link] || []
      return next
    })
    setHookReasonNotes((prev) => {
      const next: Record<string, string> = {}
      for (const link of selectedHookLinks) next[link] = prev[link] || ''
      return next
    })
  }, [selectedHookLinks])

  // Check cache status when state+product changes
  useEffect(() => {
    const state = selectedStates[0]?.code
    const product = selectedProduct
    
    if (!state || !product) {
      setCacheStatus(null)
      return
    }

    // Don't check while researching
    if (wizardStep === 2) return

    setCacheStatus({ status: 'loading' })
    
    api.generate.checkCacheStatus(state, product)
      .then((status) => {
        setCacheStatus(status)
      })
      .catch((err) => {
        console.warn('Failed to check cache status:', err)
        setCacheStatus(null)
      })
  }, [selectedStates, selectedProduct, wizardStep])

  const loadCachedPrepForStates = async () => {
    if (!selectedProduct || selectedStates.length === 0) {
      setCachedPrepByState({})
      return
    }
    setCachedPrepLoading(true)
    try {
      const entries = await Promise.all(selectedStates.map(async (st) => {
        try {
          const cached = await api.generate.getCachedPrep(st.code, selectedProduct)
          return [st.code, cached.result || null] as const
        } catch {
          return [st.code, null] as const
        }
      }))
      const next: Record<string, CachedPrepResult | null> = {}
      for (const [code, result] of entries) {
        next[code] = result
      }
      setCachedPrepByState(next)
    } finally {
      setCachedPrepLoading(false)
    }
  }

  // On page load: check for any active research and resume if found
  useEffect(() => {
    let cancelled = false
    
    const checkActiveResearch = async () => {
      // Skip if we're loading a saved run from sessionStorage
      // (the saved run loading effect should take priority)
      if (sessionStorage.getItem('loadSavedRun')) {
        return
      }
      
      try {
        const active = await api.generate.pipelinePrepActive()
        if (cancelled) return

        if (!active.task_id) return
        
        // Found active research - resume polling
        setResearchTaskId(active.task_id)
        setResearchPhase(active.phase || 'state')
        setResearchProgress(active.progress || 0)
        setResearchMessage(active.message || 'Resuming research...')
        setWizardStep(2)
        
        // Set selection to match active research
        if (active.product_display_name) {
          setSelectedProduct(active.product_display_name)
        }
        if (active.state_code) {
          setSelectedStates([{ code: active.state_code, name: active.state_code }])
        }
        if (active.include_district_research) {
          setIncludeDistrictResearch(true)
        }
        if (active.include_conference_research) {
          setIncludeConferenceResearch(true)
        }
        
        toast({
          title: 'Research in progress',
          description: `Reconnected to active research for ${active.product_display_name || 'your product'} / ${active.state_code || 'your state'}`,
        })
        
        // Resume polling
        const pollForCompletion = async () => {
          while (!cancelled) {
            await new Promise(resolve => setTimeout(resolve, 3000))
            if (cancelled) break
            
            try {
              const status = await api.generate.pipelinePrepStatus(active.task_id!)
              if (cancelled) break
              
              setResearchPhase(status.phase || 'state')
              setResearchProgress(status.progress)
              setResearchMessage(status.message)
              
              if (status.phase === 'district') {
                setDistrictResearchStatus('running')
                setDistrictResearchProgress(status.progress)
                setDistrictResearchMessage(status.message)
              }
              
              if (status.status === 'completed' && status.result) {
                setResearchPhase('idle')
                setResearchTaskId(null)
                setDistrictResearchStatus(status.result.district_research ? 'complete' : 'idle')
                setPrep(status.result)
                setWizardStep(3)
                toast({ title: 'Research complete!' })
                break
              }
              
              if (status.status === 'failed') {
                setResearchPhase('idle')
                setResearchTaskId(null)
                setWizardStep(1)
                toast({ 
                  title: 'Research failed', 
                  description: status.error,
                  variant: 'destructive' 
                })
                break
              }
              
              if (status.status === 'cancelled') {
                setResearchPhase('idle')
                setResearchTaskId(null)
                setWizardStep(1)
                toast({ title: 'Research was cancelled' })
                break
              }
            } catch (e) {
              console.warn('Failed to poll research status:', e)
            }
          }
        }
        
        pollForCompletion()
      } catch (e) {
        console.warn('Failed to check for active research:', e)
      }
    }
    
    checkActiveResearch()
    
    return () => { cancelled = true }
  }, []) // Only run once on mount

  // On page load: check for ALL pending email generations and handle them
  // Supports multiple concurrent tasks - auto-saves completed ones, clears failed ones
  useEffect(() => {
    let cancelled = false
    
    const checkAllPendingEmails = async () => {
      const allPending = loadAllPendingEmailTasks()
      const taskIds = Object.keys(allPending)
      if (taskIds.length === 0) return
      
      // Initialize background tasks state
      setBackgroundEmailTasks(allPending)
      
      let completedCount = 0
      let failedCount = 0
      let inProgressCount = 0
      
      // Check status of each pending task
      for (const taskId of taskIds) {
        if (cancelled) break
        const pending = allPending[taskId]
        
        try {
          const status = await api.generate.pipelineRunStatus(taskId)
          if (cancelled) break
          
          if (status.status === 'completed' && status.result) {
            // Task completed - auto-save!
            clearPendingEmailTask(taskId)
            setBackgroundEmailTasks(prev => {
              const next = { ...prev }
              delete next[taskId]
              return next
            })
            completedCount++
            
            // Auto-save to backend
            try {
              if (!status.saved_run_id) {
                await api.savedRuns.save({
                  name: `Auto-saved: ${pending.product} - ${pending.stateName}`,
                  product: pending.product,
                  state_code: pending.stateCode,
                  state_full: pending.stateName,
                  audiences: [pending.audience],
                  pipeline_response: status.result,
                  selected_hook_links: pending.selectedHookLinks || [],
                  primary_hook_link: pending.primaryHookLink || null,
                  hook_reason_tags: pending.hookReasonTags || {},
                  hook_reason_notes: pending.hookReasonNotes || {},
                })
              }
            } catch {
              // Silent fail - still saved locally
            }
          } else if (status.status === 'failed') {
            clearPendingEmailTask(taskId)
            setBackgroundEmailTasks(prev => {
              const next = { ...prev }
              delete next[taskId]
              return next
            })
            failedCount++
          } else if (status.status === 'in_progress' || status.status === 'queued') {
            inProgressCount++
            // Start background polling for this task
            pollBackgroundTask(taskId, pending)
          }
        } catch (e) {
          console.warn(`Failed to check pending email task ${taskId}:`, e)
          // Clear stale/invalid tasks
          clearPendingEmailTask(taskId)
          setBackgroundEmailTasks(prev => {
            const next = { ...prev }
            delete next[taskId]
            return next
          })
        }
      }
      
      // Show summary notification
      if (completedCount > 0 || failedCount > 0 || inProgressCount > 0) {
        const parts = []
        if (completedCount > 0) parts.push(`${completedCount} completed & saved`)
        if (failedCount > 0) parts.push(`${failedCount} failed`)
        if (inProgressCount > 0) parts.push(`${inProgressCount} still running`)
        
        toast({
          title: 'Background emails',
          description: parts.join(', '),
          variant: failedCount > 0 && completedCount === 0 ? 'destructive' : 'default',
        })
      }
    }
    
    // Poll a single background task until completion
    const pollBackgroundTask = async (taskId: string, pending: PendingEmailTask) => {
      while (!cancelled) {
        await new Promise(resolve => setTimeout(resolve, 5000)) // Poll every 5s for background
        if (cancelled) break
        
        try {
          const status = await api.generate.pipelineRunStatus(taskId)
          if (cancelled) break
          
          if (status.status === 'completed' && status.result) {
            clearPendingEmailTask(taskId)
            setBackgroundEmailTasks(prev => {
              const next = { ...prev }
              delete next[taskId]
              return next
            })
            
            // Auto-save
            try {
              if (!status.saved_run_id) {
                await api.savedRuns.save({
                  name: `Auto-saved: ${pending.product} - ${pending.stateName}`,
                  product: pending.product,
                  state_code: pending.stateCode,
                  state_full: pending.stateName,
                  audiences: [pending.audience],
                  pipeline_response: status.result,
                  selected_hook_links: pending.selectedHookLinks || [],
                  primary_hook_link: pending.primaryHookLink || null,
                  hook_reason_tags: pending.hookReasonTags || {},
                  hook_reason_notes: pending.hookReasonNotes || {},
                })
              }
              toast({
                title: 'Background email complete!',
                description: status.saved_run_id
                  ? `${pending.product} - ${pending.stateName} saved.`
                  : `${pending.product} - ${pending.stateName} has been auto-saved.`,
              })
            } catch {
              toast({
                title: 'Background email complete!',
                description: `${pending.product} - ${pending.stateName} finished.`,
              })
            }
            break
          }
          
          if (status.status === 'failed') {
            clearPendingEmailTask(taskId)
            setBackgroundEmailTasks(prev => {
              const next = { ...prev }
              delete next[taskId]
              return next
            })
            toast({
              title: 'Background email failed',
              description: `${pending.product} - ${pending.stateName}: ${status.error || 'Unknown error'}`,
              variant: 'destructive',
            })
            break
          }
        } catch (e) {
          console.warn(`Failed to poll background task ${taskId}:`, e)
        }
      }
    }
    
    checkAllPendingEmails()
    
    return () => { cancelled = true }
  }, []) // Only run once on mount

  useEffect(() => {
    if (wizardStep !== 2) return
    loadCachedPrepForStates()
  }, [wizardStep, selectedProduct, selectedStates])

  const toggleReasonTag = (link: string, tag: string) => {
    setHookReasonTags((prev) => {
      const existing = prev[link] || []
      const next = existing.includes(tag) ? existing.filter((t) => t !== tag) : [...existing, tag]
      return { ...prev, [link]: next }
    })
  }

  const toggleHook = (link: string) => {
    setSelectedHookLinks((prev) => {
      if (prev.includes(link)) return prev.filter((x) => x !== link)
      if (prev.length >= 2) {
        toast({
          title: 'Max 2 requirements',
          description: 'Select at most two funding/compliance requirements.',
          variant: 'destructive',
        })
        return prev
      }
      return [...prev, link]
    })
  }

  // Saved runs functions
  const loadSavedRuns = async () => {
    setLoadingSavedRuns(true)
    try {
      const runs = await api.savedRuns.list()
      setSavedRuns(runs)
    } catch (err) {
      toast({
        title: 'Error loading saved runs',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    } finally {
      setLoadingSavedRuns(false)
    }
  }

  const saveCurrentRun = async (name?: string, editedContent?: { audience: string; subject_line: string; email_body: string }) => {
    if (!result) return
    setSavingRun(true)
    try {
      // If edited content is provided, create a modified copy of the result with the edits
      let pipelineResponse = result
      if (editedContent) {
        pipelineResponse = {
          ...result,
          variants: result.variants.map((variant) => {
            if (variant.audience === editedContent.audience) {
              return {
                ...variant,
                email_draft: {
                  ...variant.email_draft,
                  subject_line: editedContent.subject_line,
                  email_body: editedContent.email_body,
                  // Recalculate word count for the edited content
                  word_count: editedContent.email_body.split(/\s+/).filter(Boolean).length,
                },
              }
            }
            return variant
          }),
        }
      }

      const saved = await api.savedRuns.save({
        name: name || undefined,
        product: selectedProduct || '',
        state_code: selectedStates[0]?.code || '',
        state_full: selectedStates[0]?.name || undefined,
        audiences: [selectedAudience],
        pipeline_response: pipelineResponse,
        selected_hook_links: selectedHookLinks,
        primary_hook_link: primaryHookLink || undefined,
        hook_reason_tags: hookReasonTags,
        hook_reason_notes: hookReasonNotes,
      })
      setCurrentSavedRunId(saved.id)
      toast({
        title: 'Run saved',
        description: name ? `Saved as "${name}"` : 'Run saved successfully',
      })
      // Refresh the saved runs list
      loadSavedRuns()
    } catch (err) {
      toast({
        title: 'Error saving run',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    } finally {
      setSavingRun(false)
    }
  }

  // Save research results BEFORE email generation (allows revisiting later)
  const saveResearchRun = async (name?: string) => {
    if (!prep) return
    setSavingRun(true)
    try {
      const product = selectedProduct || ''
      const state = selectedStates[0]
      const defaultName = `${product} - ${state?.name || state?.code || 'Research'}`
      
      const saved = await api.savedRuns.saveResearch({
        name: name || defaultName,
        product,
        state_code: state?.code || '',
        state_full: state?.name || undefined,
        audiences: [selectedAudience],
        evidence_pack: prep.evidence_pack,
        hooks: prep.treasure_hooks || [],
        filtered_requirements: prep.filtered_requirements || [],
        district_research: prep.district_research || null,
        conferences: prep.conferences || [],
      })
      toast({
        title: 'Research saved',
        description: `Saved as "${saved.name || defaultName}". View it in Saved Research.`,
      })
      // Refresh the saved runs list
      loadSavedRuns()
    } catch (err) {
      toast({
        title: 'Error saving research',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    } finally {
      setSavingRun(false)
    }
  }

  const loadSavedRun = async (run: SavedRunSummary) => {
    try {
      const full = await api.savedRuns.get(run.id)
      
      // Restore all state
      setSelectedProduct(full.product)
      setSelectedStates([{ code: full.state_code, name: full.state_full || full.state_code }])
      // Handle both old array format and new single format with mapping
      const oldAudienceMap: Record<string, string> = {
        'District Leadership': 'Decision Makers',
        'Curriculum Directors': 'Decision Makers',
        'ELL/Multilingual Directors': 'Decision Makers',
        'Principals': 'Decision Makers',
        'Teachers': 'Users',
        'Title III Coordinators': 'Decision Makers',
      }
      const savedAudience = full.audiences?.[0] || 'Decision Makers'
      setSelectedAudience(oldAudienceMap[savedAudience] || savedAudience)
      
      // Restore pipeline result
      setResult(full.pipeline_response)
      setActiveAudience(full.pipeline_response.variants?.[0]?.audience || null)
      
      // Restore hook selection
      setSelectedHookLinks(full.selected_hook_links)
      setPrimaryHookLink(full.primary_hook_link || null)
      setHookReasonTags(full.hook_reason_tags)
      setHookReasonNotes(full.hook_reason_notes)
      
      // Extract prep data from pipeline response
      // Handle both field names: treasure_hooks (email runs) and hooks (research runs)
      const hooks = full.pipeline_response.treasure_hooks || full.pipeline_response.hooks || []
      if (full.pipeline_response.evidence_pack && hooks.length > 0) {
        setPrep({
          evidence_pack: full.pipeline_response.evidence_pack,
          treasure_hooks: hooks,
          filtered_requirements: full.pipeline_response.filtered_requirements || [],
          district_research: full.pipeline_response.district_research || null,
          conferences: full.pipeline_response.conferences || [],
          warnings: full.pipeline_response.warnings || [],
        })
        // Set district research status if data exists
        setDistrictResearchStatus(full.pipeline_response.district_research ? 'complete' : 'idle')
      }
      
      // Navigate to appropriate step based on run type
      setWizardStep(full.run_type === 'research' ? 3 : 5)
      setCurrentSavedRunId(full.id)
      setShowSavedRuns(false)
      
      toast({
        title: 'Run loaded',
        description: run.name || `Loaded ${run.product} / ${run.state_code}`,
      })
    } catch (err) {
      toast({
        title: 'Error loading run',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    }
  }

  const deleteSavedRun = async (id: number) => {
    try {
      await api.savedRuns.delete(id)
      setSavedRuns((prev) => prev.filter((r) => r.id !== id))
      if (currentSavedRunId === id) {
        setCurrentSavedRunId(null)
      }
      toast({
        title: 'Run deleted',
      })
    } catch (err) {
      toast({
        title: 'Error deleting run',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    }
  }

  const prepMutation = useMutation<
    { evidence_pack: EvidencePack; treasure_hooks: WebHook[]; filtered_requirements: FilteredRequirement[]; district_research?: DistrictResearchResult | null; warnings: string[] },
    Error & { filteredRequirements?: FilteredRequirement[] },
    void
  >({
    mutationFn: async () => {
      const req: PipelineRequest & { include_district_research?: boolean } = {
        product: selectedProduct || '',
        state: selectedStates[0]?.code || '',
        state_full: selectedStates[0]?.name || undefined,
        audiences: [selectedAudience],
        include_district_research: includeDistrictResearch,
        include_conference_research: includeConferenceResearch,
        created_by: createdBy.trim() || undefined,
      }
      
      // Use polling-based research (more robust than streaming)
      return api.generate.pipelinePrepPolling(req, (phase, progress, message) => {
        setResearchPhase(phase)
        setResearchProgress(progress)
        setResearchMessage(message)
        
        // Also update legacy district research state for UI compatibility
        if (phase === 'district') {
          setDistrictResearchStatus('running')
          setDistrictResearchProgress(progress)
          setDistrictResearchMessage(message)
        }
        
        // Add trace event for activity log
        setTraceEvents((prev) => [...prev, { 
          type: 'progress', 
          stage: phase === 'district' ? 'district_research' : 'treasure_hunter',
          message, 
          percent: progress 
        } as PipelineStreamEvent])
      })
    },
    onSuccess: (data) => {
      setResearchPhase('idle')
      setResearchTaskId(null)
      setResearchProgress(0)
      setResearchMessage('')
      setDistrictResearchStatus(data.district_research ? 'complete' : 'idle')
      
      setPrep(data)
      setBlockedFilteredRequirements([])
      setSelectedHookLinks([])
      setPrimaryHookLink(null)
      setResult(null)
      setReviewDrafts({})
      setActiveAudience(null)
      // Auto-expand filtered section if nothing passed but requirements were found
      if ((data.treasure_hooks?.length || 0) === 0 && (data.filtered_requirements?.length || 0) > 0) {
        setShowFilteredSection(true)
      }
      setWizardStep(3) // Go to Select step
    },
    onError: (error) => {
      setResearchPhase('idle')
      setResearchTaskId(null)
      setResearchProgress(0)
      setResearchMessage('')
      setDistrictResearchStatus('idle')
      
      // Capture filtered requirements even on blocked/error
      if (error && 'filteredRequirements' in error && error.filteredRequirements) {
        setBlockedFilteredRequirements(error.filteredRequirements)
        setShowFilteredSection(true)
      }
      toast({
        title: 'Research failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      })
      setWizardStep(3) // Still go to Select step to show filtered requirements
    },
  })

  const pipelineMutation = useMutation<PipelineRunResponse, Error, { selectedCachedHooks?: SelectedCachedHook[] } | void>({
    mutationFn: (overrides) => {
      const req: PipelineRunStreamRequest = {
        product: selectedProduct || '',
        state: selectedStates[0]?.code || '',
        state_full: selectedStates[0]?.name || undefined,
        audiences: [selectedAudience],
      }
      const cachedHooksOverride = overrides && 'selectedCachedHooks' in overrides ? overrides.selectedCachedHooks : undefined
      const cachedHooksToUse = cachedHooksOverride ?? selectedCachedHooks
      if (purposePrompt.trim()) {
        req.purpose_prompt = purposePrompt.trim()
      }
      // IMPORTANT: cached hooks can be used without a purpose prompt (hook-only flow).
      if (cachedHooksToUse.length > 0) {
        req.selected_cached_hooks = cachedHooksToUse.map((item) => ({
          category: item.category,
          state_code: item.state_code || null,
          hook: item.hook,
        }))
      }
      if (cachedHooksOverride && cachedHooksOverride.length > 0) {
        const overrideIds = cachedHooksOverride
          .map((item) => ('hook_id' in item.hook ? item.hook.hook_id : undefined))
          .filter((id): id is string => Boolean(id))
        const overrideLinks = cachedHooksOverride
          .map((item) => ('link' in item.hook ? item.hook.link : undefined))
          .filter((link): link is string => Boolean(link))
        if (overrideIds.length > 0) {
          req.selected_hook_ids = overrideIds
          req.primary_hook_id = overrideIds[0]
        } else if (overrideLinks.length > 0) {
          req.selected_hook_links = overrideLinks
          req.primary_hook_link = overrideLinks[0]
        }
      } else if (selectedHookLinks.length === 0 && cachedHooksToUse.length > 0) {
        const cachedStateHooks = cachedHooksToUse.filter(
          (item) => item.category === 'state' && item.hook && ('hook_id' in item.hook || 'link' in item.hook)
        )
        const cachedIds = cachedStateHooks
          .map((item) => ('hook_id' in item.hook ? item.hook.hook_id : undefined))
          .filter((id): id is string => Boolean(id))
        const cachedLinks = cachedStateHooks
          .map((item) => ('link' in item.hook ? item.hook.link : undefined))
          .filter((link): link is string => Boolean(link))
        if (cachedIds.length > 0) {
          req.selected_hook_ids = cachedIds
          req.primary_hook_id = cachedIds[0]
        } else if (cachedLinks.length > 0) {
          req.selected_hook_links = cachedLinks
          req.primary_hook_link = cachedLinks[0]
        }
      }
      // Reuse existing prep outputs if we have them.
      // If we're in the cached-hooks flow (Step 2), `prep` may be null even though we have cached
      // evidence_pack + treasure_hooks available; sending them avoids re-running deep research.
      const stateCode = selectedStates[0]?.code
      const cachedPrep = stateCode ? cachedPrepByState[stateCode] : null
      const prepLike = prep || cachedPrep
      if (prepLike) {
        req.evidence_pack = sanitizeEvidencePack(prepLike.evidence_pack)
        req.treasure_hooks = prepLike.treasure_hooks
        if (prepLike.district_research) req.district_research = prepLike.district_research
        if (prepLike.conferences) req.conferences = prepLike.conferences
      }
      if (!cachedHooksOverride && prep && selectedHookLinks.length > 0) {
        // Send hook IDs (preferred) for reliable selection
        req.selected_hook_ids = selectedHookLinks  // selectedHookLinks now contains hook_id or link
        req.primary_hook_id = (primaryHookLink || selectedHookLinks[0] || '').trim() || undefined
        // Also send legacy links for backwards compatibility (convert keys back to links if needed)
        const selectedLinks = prep?.treasure_hooks
          .filter(h => selectedHookLinks.includes(getHookKey(h)))
          .map(h => h.link) || selectedHookLinks
        req.selected_hook_links = selectedLinks
        req.primary_hook_link = prep?.treasure_hooks.find(h => getHookKey(h) === primaryHookLink)?.link || primaryHookLink || undefined
      }
      // Use polling-based approach to avoid browser connection timeouts
      return api.generate.pipelineRunPolling(
        req,
        (progress, message) => {
          setEmailProgress({ progress, message })
          // Also add to trace events for activity log
          setTraceEvents((prev) => [...prev, { type: 'progress', progress, message } as PipelineStreamEvent])
        },
        3000, // pollInterval
        600,  // maxPolls
        (taskId) => {
          // Save pending task for auto-resume if user navigates away
          const pendingTask: PendingEmailTask = {
            taskId,
            product: selectedProduct || '',
            stateCode: selectedStates[0]?.code || '',
            stateName: selectedStates[0]?.name || '',
            audience: selectedAudience,
            purposePrompt: purposePrompt.trim() || undefined,
            selectedHookLinks,
            primaryHookLink: primaryHookLink || undefined,
            startedAt: new Date().toISOString(),
            prep: prep || undefined,
            hookReasonTags,
            hookReasonNotes,
          }
          savePendingEmailTask(pendingTask)
          setCurrentEmailTaskId(taskId)  // Track for clearing on success/error
          // Update background tasks state
          setBackgroundEmailTasks(prev => ({ ...prev, [taskId]: pendingTask }))
        }
      )
    },
    onSuccess: (data) => {
      // Clear pending task - email completed successfully
      if (currentEmailTaskId) {
        clearPendingEmailTask(currentEmailTaskId)
        setBackgroundEmailTasks(prev => {
          const next = { ...prev }
          delete next[currentEmailTaskId]
          return next
        })
      }
      setCurrentEmailTaskId(null)
      setReviewDrafts({})
      setResult(data)
      const first = data.variants?.[0]?.audience
      setActiveAudience(first || null)
      setWizardStep(5) // Go to Review step

      // Training loop: log the explicit human-selected requirements (no implicit rejections).
      try {
        if (prep && selectedHookLinks.length > 0) {
          const map = new Map((prep.treasure_hooks || []).map((h) => [getHookKey(h), h]))
          const primary = (primaryHookLink || selectedHookLinks[0] || '').trim()
          const decisions: HookDecision[] = []
          for (const hookKey of selectedHookLinks) {
            const hook = map.get(hookKey)
            if (!hook) continue
            const rank = selectedHookLinks.length === 1 ? 1 : hookKey === primary ? 1 : 2
            decisions.push({
              decision: 'selected',
              rank,
              reason_tags: hookReasonTags[hookKey] || [],
              reason_note: (hookReasonNotes[hookKey] || '').trim() || null,
              hook,
            })
          }

          if (decisions.length > 0) {
            api.feedback
              .submitHookFeedback({
                run_id: data.run_id,
                product: selectedProduct || data.request.product,
                state_code: selectedStates[0]?.code || data.request.state,
                audiences: data.request.audiences || null,
                district_name: data.request.district_name || null,
                district_url: data.request.district_url || null,
                decisions,
              })
              .catch(() => {
                // non-blocking
              })
          }
        }
      } catch {
        // non-blocking
      }
    },
    onError: (error) => {
      // Clear pending task - email failed
      if (currentEmailTaskId) {
        clearPendingEmailTask(currentEmailTaskId)
        setBackgroundEmailTasks(prev => {
          const next = { ...prev }
          delete next[currentEmailTaskId]
          return next
        })
      }
      setCurrentEmailTaskId(null)
      toast({
        title: 'Email generation failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      })
      setWizardStep(3) // Go back to Select step
    },
  })

  const canPrep = selectedProduct !== null && selectedStates.length > 0
  const tagsOk = selectedHookLinks.every((link) => (hookReasonTags[link]?.length || 0) > 0)
  const canGenerate = canPrep && !!prep && selectedHookLinks.length > 0 && tagsOk
  const variants = result?.variants || []
  const activeVariant = variants.find((v) => v.audience === activeAudience) || variants[0]

  useEffect(() => {
    if (!activeVariant) return
    const aud = activeVariant.audience
    setReviewDrafts((prev) => {
      if (prev[aud]) return prev
      const blank = { score: null, comment: '' }
      return {
        ...prev,
        [aud]: {
          edited_subject_line: activeVariant.email_draft.subject_line,
          edited_email_body: activeVariant.email_draft.email_body,
          rubric: {
            subject_line: { ...blank },
            hook_usage: { ...blank },
            product_relevance: { ...blank },
            tone: { ...blank },
            flow: { ...blank },
            cta: { ...blank },
          },
        },
      }
    })
  }, [activeVariant?.audience, result?.run_id])

  const reviewMutation = useMutation({
    mutationFn: (payload: EmailReviewRequest) => api.feedback.submitEmailReview(payload),
    onSuccess: () => {
      toast({
        title: 'Email saved',
        description: 'Saved to Saved Research and submitted for training.',
      })
    },
    onError: (error) => {
      toast({
        title: 'Save failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })

  const handlePrep = async () => {
    if (!canPrep) return
    
    // Reset state
    setTraceEvents([])
    setResearchStartTime(new Date())
    setPrep(null)
    setBlockedFilteredRequirements([])
    setSelectedHookLinks([])
    setPrimaryHookLink(null)
    setHookReasonTags({})
    setHookReasonNotes({})
    setReviewDrafts({})
    setResult(null)
    setActiveAudience(null)
    
    if (isResearchMode) {
      setWizardStep(2)
      prepMutation.mutate()
      return
    }

    // Custom purpose flow (cached research only)
    setWizardStep(2)
  }

  // Re-search clears the cache first to force fresh Deep Research
  const handleReSearchConfirmed = async () => {
    if (!canPrep) return
    setShowReSearchConfirm(false)
    setTraceEvents([])
    setResearchStartTime(new Date())
    setPrep(null)
    setBlockedFilteredRequirements([])
    setSelectedHookLinks([])
    setPrimaryHookLink(null)
    setHookReasonTags({})
    setHookReasonNotes({})
    setReviewDrafts({})
    setResult(null)
    setActiveAudience(null)
    setCacheStatus(null)
    setWizardStep(2) // Go to Research step
    
    // Clear cache for this state/product before re-searching
    try {
      await api.generate.clearDeepResearchCache(selectedStates[0]?.code || '', selectedProduct || '')
    } catch (e) {
      console.warn('Failed to clear cache:', e)
      // Continue anyway - cache clear is best-effort
    }
    
    prepMutation.mutate()
  }

  // Show confirmation before re-searching if there are completed results
  const handleReSearch = () => {
    if (!canPrep || !canReSearch) return
    if (cacheStatus?.status === 'completed' || cacheStatus?.status === 'expired' || prep) {
      setShowReSearchConfirm(true)
    } else {
      handleReSearchConfirmed()
    }
  }

  const isCachedHookSelected = (key: string) => selectedCachedHooks.some((h) => h.key === key)

  const toggleCachedHook = (hook: SelectedCachedHook) => {
    setSelectedCachedHooks((prev) => {
      const exists = prev.some((h) => h.key === hook.key)
      if (exists) {
        return prev.filter((h) => h.key !== hook.key)
      }
      if (prev.length >= 2) {
        toast({
          title: 'Selection limit reached',
          description: 'You can include up to 2 cached items total.',
        })
        return prev
      }
      return [...prev, hook]
    })
  }

  // Cancel an in-progress research task (kept for potential future use)
  const _handleCancelResearch = async () => {
    const state = selectedStates[0]?.code
    const product = selectedProduct
    if (!state || !product) return

    try {
      await api.generate.cancelResearch(state, product)
      setCacheStatus({ status: 'cancelled' })
      toast({
        title: 'Research cancelled',
        description: 'The research task has been cancelled.',
      })
    } catch (e) {
      console.warn('Failed to cancel research:', e)
      toast({
        title: 'Failed to cancel',
        description: 'Could not cancel the research task.',
        variant: 'destructive',
      })
    }
  }
  void _handleCancelResearch // Suppress unused warning

  const handleRun = () => {
    if (!canGenerate) return
    setTraceEvents([])
    setEmailProgress(null) // Reset progress
    setWizardStep(4) // Go to Generate step
    pipelineMutation.mutate()
  }

  const handleDistrictGenerate = (hook: WebHook, stateCode: string) => {
    const selected = [{
      key: `district:${stateCode}:${getHookKey(hook)}`,
      category: 'district' as const,
      state_code: stateCode,
      hook,
    }]
    setSelectedCachedHooks(selected)
    setSelectedHookLinks([])
    setPrimaryHookLink(null)
    setTraceEvents([])
    setEmailProgress(null)
    setWizardStep(4)
    pipelineMutation.mutate({ selectedCachedHooks: selected })
  }

  const handleReset = () => {
    setWizardStep(1)
    setResult(null)
    setPrep(null)
    setBlockedFilteredRequirements([])
    setSelectedHookLinks([])
    setPrimaryHookLink(null)
    setHookReasonTags({})
    setEmailProgress(null)
    setHookReasonNotes({})
    setReviewDrafts({})
    setActiveAudience(null)
    setCopied(false)
    setTraceEvents([])
    setShowFilteredSection(false)
  }

  const handleBackToStep = (step: WizardStep) => {
    if (step < wizardStep) {
      setWizardStep(step)
    }
  }

  const handleCopy = () => {
    if (!activeVariant) return
    const full = `Subject: ${activeVariant.email_draft.subject_line}\n\n${activeVariant.email_draft.email_body}`
    navigator.clipboard.writeText(full)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleExportCsv = () => {
    if (!activeVariant) return
    const headers = ['Audience', 'Subject Line', 'Email Body', 'Product', 'State', 'Word Count']
    const row = [
      `"${activeVariant.audience.replace(/"/g, '""')}"`,
      `"${activeVariant.email_draft.subject_line.replace(/"/g, '""')}"`,
      `"${activeVariant.email_draft.email_body.replace(/"/g, '""')}"`,
      `"${selectedProduct || ''}"`,
      `"${selectedStates[0]?.name || ''}"`,
      String(activeVariant.email_draft.word_count),
    ]
    const csv = [headers.join(','), row.join(',')].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `email-pipeline-${(activeVariant.audience || 'audience').toLowerCase().replace(/\s+/g, '-')}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const renderValidation = () => {
    if (!activeVariant) return null
    const v = activeVariant.validation
    const failureCount = v.failures?.length || 0
    
    return (
      <div className="mt-4 rounded-lg border border-slate-700 bg-slate-800/50">
        {/* Collapsible header - always visible */}
        <button
          onClick={() => setValidationExpanded(!validationExpanded)}
          className="w-full p-3 flex items-center justify-between gap-3 hover:bg-slate-700/30 transition-colors rounded-lg"
        >
          <div className="flex items-center gap-3">
            <div className="text-sm font-medium text-slate-400">Validation</div>
            <div className={`text-xs px-2 py-0.5 rounded ${
            v.passed ? 'bg-emerald-900/50 text-emerald-300 border border-emerald-700/50' : 'bg-amber-900/40 text-amber-300 border border-amber-700/50'
          }`}>
              {v.passed ? 'PASS' : `FAIL${failureCount > 0 ? ` (${failureCount} issue${failureCount > 1 ? 's' : ''})` : ''}`}
          </div>
        </div>
          {validationExpanded ? (
            <ChevronUp className="h-4 w-4 text-slate-500" />
          ) : (
            <ChevronDown className="h-4 w-4 text-slate-500" />
          )}
        </button>
        
        {/* Expanded content */}
        {validationExpanded && (
          <div className="px-4 pb-4 border-t border-slate-700/50">
            <div className="mt-3 text-xs text-slate-400">
          Words: {v.word_count} · Bullets: {v.bullet_count} · Bullet words: {v.bullet_word_counts.join(', ') || 'n/a'}
        </div>
        {!v.passed && v.failures?.length > 0 && (
          <ul className="mt-3 space-y-1 text-sm text-slate-300">
            {v.failures.map((f, i) => (
              <li key={`${f.code}-${i}`}>
                <span className="text-amber-300 font-mono text-xs">{f.code}</span>
                <span className="ml-2">{f.message}</span>
              </li>
            ))}
          </ul>
        )}
        {activeVariant.trace?.attempts?.length > 0 && (
          <div className="mt-4">
            <div className="text-xs text-slate-500 uppercase tracking-wide">Repair trace</div>
            <div className="mt-2 space-y-2">
              {activeVariant.trace.attempts.map((a) => (
                <div key={a.iteration} className="p-3 rounded border border-slate-700 bg-slate-900/30">
                  <div className="flex items-center justify-between">
                    <div className="text-sm text-slate-200">Attempt {a.iteration}</div>
                    <div className={`text-xs px-2 py-1 rounded ${
                      a.validation.passed ? 'bg-emerald-900/50 text-emerald-300' : 'bg-slate-700/50 text-slate-300'
                    }`}>
                      {a.validation.passed ? 'PASS' : 'FAIL'}
                    </div>
                  </div>
                  {a.stopped && (
                    <div className="mt-1 text-xs text-slate-400">
                      stopped: <span className="font-mono">{a.stop_reason || 'unknown'}</span>
                    </div>
                  )}
                  {!a.validation.passed && a.validation.failures?.length > 0 && (
                    <div className="mt-2 text-xs text-slate-400">
                      failures: {a.validation.failures.map((f) => f.code).join(', ')}
                    </div>
                  )}
                </div>
              ))}
            </div>
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  const renderReview = () => {
    if (!result || !activeVariant) return null
    const aud = activeVariant.audience
    const draft = reviewDrafts[aud]
    if (!draft) return null

    const sections: Array<{ key: ReviewSectionKey; label: string }> = [
      { key: 'subject_line', label: 'Subject line' },
      { key: 'hook_usage', label: 'Hook usage (funding/compliance integration)' },
      { key: 'product_relevance', label: 'Product relevance' },
      { key: 'tone', label: 'Tone' },
      { key: 'flow', label: 'Flow' },
      { key: 'cta', label: 'CTA' },
    ]

    const textOk = draft.edited_subject_line.trim().length > 0 && draft.edited_email_body.trim().length > 0
    const canSave = textOk && !reviewMutation.isPending  // Scores are optional

    return (
      <div className="mt-4 p-4 rounded-lg border border-slate-700 bg-slate-800/50">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm font-medium text-slate-200">Review and Save</div>
          {(reviewMutation.isPending || savingRun) && <div className="text-xs text-slate-400">Saving…</div>}
        </div>

        <div className="mt-3 space-y-3">
          <div>
            <label className="block text-xs text-slate-500 uppercase tracking-wide">Edited subject</label>
            <input
              data-testid="edited-subject"
              value={draft.edited_subject_line}
              onChange={(e) =>
                setReviewDrafts((prev) => ({
                  ...prev,
                  [aud]: { ...draft, edited_subject_line: e.target.value },
                }))
              }
              className="mt-2 w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          <div>
            <label className="block text-xs text-slate-500 uppercase tracking-wide">Edited email</label>
            <textarea
              data-testid="edited-email"
              value={draft.edited_email_body}
              onChange={(e) =>
                setReviewDrafts((prev) => ({
                  ...prev,
                  [aud]: { ...draft, edited_email_body: e.target.value },
                }))
              }
              className="mt-2 w-full min-h-[160px] px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>
        </div>

        <div className="mt-4">
          <div className="text-base font-medium text-slate-200">Rubric (optional)</div>
          <div className="text-sm text-slate-400 mt-1">Rate each category as Good or Bad. All fields are optional.</div>
          <div className="mt-3 grid grid-cols-1 lg:grid-cols-2 gap-4">
            {sections.map(({ key, label }) => {
              const currentScore = draft.rubric[key]?.score
              return (
                <div key={key} className="p-3 rounded border border-slate-700 bg-slate-900/20">
                  <div className="text-base font-medium text-slate-200">{label}</div>
                  <div className="mt-2 flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setReviewDrafts((prev) => ({
                          ...prev,
                          [aud]: {
                            ...draft,
                            rubric: {
                              ...draft.rubric,
                              [key]: { ...draft.rubric[key], score: currentScore === 1 ? null : 1 },
                            },
                          },
                        }))
                      }}
                      className={`px-3 py-1.5 rounded-l text-sm font-medium transition-colors ${
                        currentScore === 1
                          ? 'bg-red-600 text-white'
                          : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                      }`}
                    >
                      Bad
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setReviewDrafts((prev) => ({
                          ...prev,
                          [aud]: {
                            ...draft,
                            rubric: {
                              ...draft.rubric,
                              [key]: { ...draft.rubric[key], score: currentScore === 5 ? null : 5 },
                            },
                          },
                        }))
                      }}
                      className={`px-3 py-1.5 rounded-r text-sm font-medium transition-colors ${
                        currentScore === 5
                          ? 'bg-emerald-600 text-white'
                          : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                      }`}
                    >
                      Good
                    </button>
                    {currentScore !== null && currentScore !== undefined && (
                      <button
                        type="button"
                        onClick={() => {
                          setReviewDrafts((prev) => ({
                            ...prev,
                            [aud]: {
                              ...draft,
                              rubric: {
                                ...draft.rubric,
                                [key]: { ...draft.rubric[key], score: null },
                              },
                            },
                          }))
                        }}
                        className="ml-2 text-xs text-slate-500 hover:text-slate-300"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                  <textarea
                    value={draft.rubric[key]?.comment || ''}
                    onChange={(e) =>
                      setReviewDrafts((prev) => ({
                        ...prev,
                        [aud]: {
                          ...draft,
                          rubric: { ...draft.rubric, [key]: { ...draft.rubric[key], comment: e.target.value } },
                        },
                      }))
                    }
                    placeholder="Comments (optional)"
                    className="mt-2 w-full min-h-[60px] px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </div>
              )
            })}
          </div>
        </div>

        <button
          data-testid="save-email"
          onClick={async () => {
            const rubric = draft.rubric
            const getScore = (key: ReviewSectionKey) => {
              const item = rubric[key]
              const score = item?.score
              // Return score object if valid, otherwise use defaults for optional fields
              if (typeof score === 'number' && score >= 1 && score <= 5) {
                return { score, comment: (item.comment || '').trim() || null }
              }
              // Return null score with any comment that was provided
              return { score: null, comment: (item?.comment || '').trim() || null }
            }

            // Extract hook types for flywheel learning
            const hookTypesUsed: string[] = []
            if (activeVariant.selected_hook?.hook?.hook_type) {
              hookTypesUsed.push(activeVariant.selected_hook.hook.hook_type)
            }
            if (activeVariant.secondary_hook?.hook?.hook_type) {
              hookTypesUsed.push(activeVariant.secondary_hook.hook.hook_type)
            }

            const payload: EmailReviewRequest = {
              run_id: result.run_id,
              product: result.request?.product || selectedProduct || '',
              state_code: result.request?.state || selectedStates[0]?.code || '',
              audience: aud,
              district_name: result.request?.district_name || null,
              district_url: result.request?.district_url || null,
              primary_hook_link: activeVariant.selected_hook?.hook?.link || null,
              secondary_hook_link: activeVariant.secondary_hook?.hook?.link || null,
              original_subject_line: activeVariant.email_draft.subject_line,
              original_email_body: activeVariant.email_draft.email_body,
              edited_subject_line: draft.edited_subject_line,
              edited_email_body: draft.edited_email_body,
              rubric: {
                subject_line: getScore('subject_line'),
                hook_usage: getScore('hook_usage'),
                product_relevance: getScore('product_relevance'),
                tone: getScore('tone'),
                flow: getScore('flow'),
                cta: getScore('cta'),
              },
              // Include evidence chunk IDs for tracking which chunks led to good/bad emails
              evidence_chunks_used: result.evidence_pack?.retrieved_chunks?.map((c: EvidenceChunkCitation) => c.chunk_id) || null,
              // Flywheel learning: capture context for better example matching
              purpose_prompt: purposePrompt.trim() || null,
              hook_types_used: hookTypesUsed.length > 0 ? hookTypesUsed : null,
            }

            // Unified save: saves both the run AND the review
            // 1. Save to Saved Research for retrieval (with edited content)
            await saveCurrentRun(undefined, {
              audience: aud,
              subject_line: draft.edited_subject_line,
              email_body: draft.edited_email_body,
            })
            // 2. Save review feedback for training
            reviewMutation.mutate(payload)
          }}
          disabled={!canSave || savingRun}
          className={`mt-4 w-full px-6 py-3 rounded-lg font-medium transition-colors ${
            (!canSave || savingRun) ? 'bg-slate-700 text-slate-400 cursor-not-allowed' : 'bg-emerald-600 hover:bg-emerald-500 text-white'
          }`}
        >
          {savingRun ? 'Saving...' : 'Save Email'}
        </button>
      </div>
    )
  }

  const renderEvidence = () => {
    if (!result) return null
    return (
      <div className="mt-4 p-4 rounded-lg border border-slate-700 bg-slate-800/50">
        <div className="text-sm font-medium text-slate-200">Evidence</div>
        <div className="mt-3 grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-slate-500 uppercase tracking-wide">Product chunks (KB)</div>
            <div className="mt-2 space-y-2 max-h-72 overflow-y-auto pr-1">
              {(result.evidence_pack?.retrieved_chunks || []).slice(0, 20).map((c: EvidenceChunkCitation) => (
                <div key={c.chunk_id} className="p-3 rounded border border-slate-700 bg-slate-900/30">
                  <div className="text-xs text-slate-400 font-mono">{c.chunk_id}</div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
                    {c.source_kb_id && <span className="font-mono">kb:{c.source_kb_id}</span>}
                    {c.file_name && <span className="truncate">file: {c.file_name}</span>}
                    {typeof c.adjusted_score === 'number' && (
                      <span className="font-mono">
                        score:{c.adjusted_score.toFixed(3)}
                        {typeof c.boost === 'number' && c.boost !== 0 ? ` (boost ${c.boost > 0 ? '+' : ''}${c.boost.toFixed(2)})` : ''}
                      </span>
                    )}
                  </div>
                  {c.title && <div className="text-sm text-slate-200 mt-1">{c.title}</div>}
                  <div className="text-sm text-slate-300 mt-1">{c.excerpt}</div>
                </div>
              ))}
              {(result.evidence_pack?.retrieved_chunks || []).length === 0 && (
                <div className="text-sm text-slate-400">No KB chunks returned.</div>
              )}
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500 uppercase tracking-wide">Web sources</div>
            <div className="mt-2 space-y-2 max-h-72 overflow-y-auto pr-1">
              {(result.treasure_hooks || []).slice(0, 20).map((h: WebHook, i: number) => (
                <div key={`${h.link}-${i}`} className="p-3 rounded border border-slate-700 bg-slate-900/30">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-xs text-slate-400 font-mono">{h.hook_type}</div>
                    <div className="flex items-center gap-2">
                      {h.deadline_warning && (
                        <span className={`px-1.5 py-0.5 rounded text-xs ${
                          h.deadline_warning.includes('passed') ? 'bg-red-900/50 text-red-300' : 'bg-amber-900/50 text-amber-300'
                        }`}>
                          {h.deadline_warning}
                        </span>
                      )}
                      <span className="text-xs text-slate-500">{h.confidence}</span>
                    </div>
                  </div>
                  <a className="mt-1 block text-sm text-emerald-300 hover:text-emerald-200 underline break-all" href={h.link} target="_blank" rel="noreferrer">
                    {h.link}
                  </a>
                  <div className="mt-2 text-sm text-slate-300">"{cleanQuoteText(h.quote)}"</div>
                  {(h.timing_summary || h.signal_summary || h.stale_reason) && (
                    <div className="mt-2 space-y-1 text-xs text-slate-400">
                      {h.timing_summary && <div>Timing: {cleanQuoteText(h.timing_summary)}</div>}
                      {h.signal_summary && <div>Signal: {cleanQuoteText(h.signal_summary)}</div>}
                      {h.stale_reason && <div>Stale: {h.stale_reason}</div>}
                    </div>
                  )}
                </div>
              ))}
              {(result.treasure_hooks || []).length === 0 && (
                <div className="text-sm text-slate-400">No web hooks returned.</div>
              )}
            </div>
          </div>
        </div>
        {result.warnings?.length > 0 && (
          <div className="mt-4 text-xs text-amber-300">
            warnings: {result.warnings.join(' · ')}
          </div>
        )}
      </div>
    )
  }

  const renderHook = () => {
    if (!activeVariant) return null

    const hasSelection = Boolean(prep && selectedHookLinks.length > 0)
    let h: WebHook | undefined
    let sh: WebHook | undefined

    if (hasSelection && prep) {
      const hookMap = new Map((prep.treasure_hooks || []).map((hook) => [getHookKey(hook), hook]))
      const primaryKey = (primaryHookLink || selectedHookLinks[0] || '').trim()
      const secondaryKey = selectedHookLinks.find((key) => key !== primaryKey)

      h = (primaryKey && hookMap.get(primaryKey)) || hookMap.get(selectedHookLinks[0])
      sh = secondaryKey ? hookMap.get(secondaryKey) : undefined
    } else {
      h = activeVariant.selected_hook?.hook
      sh = activeVariant.secondary_hook?.hook
    }

    if (!h) return null
    return (
      <div className="mt-4 p-4 rounded-lg border border-slate-700 bg-slate-800/50">
        <div className="flex items-center justify-between">
          <div className="text-sm font-medium text-slate-200">Selected Requirements</div>
          <div className="text-xs text-slate-500">{h.hook_type} · {h.confidence}</div>
        </div>
        <div className="mt-2 text-xs text-slate-500 uppercase tracking-wide">Primary Requirement (opener)</div>
        <div className="mt-2 text-sm text-slate-300">"{cleanQuoteText(h.quote)}"</div>
        <a className="mt-2 block text-sm text-emerald-300 hover:text-emerald-200 underline break-all" href={h.link} target="_blank" rel="noreferrer">
          {h.link}
        </a>
        <div className="mt-3 text-xs text-slate-500 uppercase tracking-wide">Trigger excerpt</div>
        <div className="mt-1 text-sm text-slate-300">{cleanQuoteText(h.trigger_excerpt)}</div>
        {h.eligibility_excerpt && (
          <>
            <div className="mt-3 text-xs text-slate-500 uppercase tracking-wide">Eligibility excerpt</div>
            <div className="mt-1 text-sm text-slate-300">{cleanQuoteText(h.eligibility_excerpt)}</div>
          </>
        )}

        {sh && (
          <>
            <div className="mt-4 pt-4 border-t border-slate-700">
              <div className="flex items-center justify-between">
                <div className="text-xs text-slate-500 uppercase tracking-wide">Secondary Requirement (supporting)</div>
                <div className="text-xs text-slate-500">{sh.hook_type} · {sh.confidence}</div>
              </div>
              <div className="mt-2 text-sm text-slate-300">"{cleanQuoteText(sh.quote)}"</div>
              <a className="mt-2 block text-sm text-emerald-300 hover:text-emerald-200 underline break-all" href={sh.link} target="_blank" rel="noreferrer">
                {sh.link}
              </a>
              <div className="mt-3 text-xs text-slate-500 uppercase tracking-wide">Trigger excerpt</div>
              <div className="mt-1 text-sm text-slate-300">{cleanQuoteText(sh.trigger_excerpt)}</div>
              {sh.eligibility_excerpt && (
                <>
                  <div className="mt-3 text-xs text-slate-500 uppercase tracking-wide">Eligibility excerpt</div>
                  <div className="mt-1 text-sm text-slate-300">{cleanQuoteText(sh.eligibility_excerpt)}</div>
                </>
              )}
            </div>
          </>
        )}
      </div>
    )
  }

  // Helper: get all filtered requirements (from prep or from blocked state)
  const allFilteredRequirements = prep?.filtered_requirements || blockedFilteredRequirements || []
  const passedRequirements = prep?.treasure_hooks || []

  // Auto-expand filtered section when nothing passed but requirements were found
  useEffect(() => {
    if (passedRequirements.length === 0 && allFilteredRequirements.length > 0) {
      setShowFilteredSection(true)
    }
  }, [passedRequirements.length, allFilteredRequirements.length])

  // Render the wizard progress bar
  const renderProgressBar = () => {
    const steps: WizardStep[] = [1, 2, 3, 4, 5]
    return (
      <div className="mb-8">
        {/* Top row: circles and lines */}
        <div className="flex items-center">
          {steps.map((step, idx) => {
            const isActive = step === wizardStep
            const isCompleted = step < wizardStep
            const isClickable = step < wizardStep
            return (
              <div key={step} className="flex items-center flex-1 last:flex-none">
                <button
                  onClick={() => isClickable && handleBackToStep(step)}
                  disabled={!isClickable}
                  className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-medium border-2 transition-all flex-shrink-0 ${
                    isCompleted
                      ? 'bg-emerald-600 border-emerald-600 text-white'
                      : isActive
                      ? 'bg-emerald-600/20 border-emerald-500 text-emerald-300'
                      : 'bg-slate-800 border-slate-600 text-slate-500'
                  } ${isClickable ? 'cursor-pointer hover:scale-105' : 'cursor-default'}`}
                >
                  {isCompleted ? (
                    <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  ) : step}
                </button>
                {/* Connector line */}
                {idx < steps.length - 1 && (
                  <div className={`flex-1 h-0.5 mx-2 ${
                    step < wizardStep ? 'bg-emerald-600' : 'bg-slate-700'
                  }`} />
                )}
              </div>
            )
          })}
        </div>
        {/* Bottom row: labels */}
        <div className="flex mt-2">
          {steps.map((step) => {
            const isActive = step === wizardStep
            const isCompleted = step < wizardStep
            return (
              <div key={`label-${step}`} className="flex-1 last:flex-none">
                <div className={`text-xs text-center ${
                  isActive ? 'text-emerald-300 font-medium' : isCompleted ? 'text-slate-300' : 'text-slate-500'
                }`} style={{ width: step === 5 ? '80px' : 'auto' }}>
                  {WIZARD_STEP_LABELS[step]}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  // Render a single requirement card (for both passed and filtered)
  const renderRequirementCard = (h: WebHook, opts: { 
    isFiltered?: boolean
    filterReason?: string
    filterReasonLabel?: string
    isSelected?: boolean
    isPrimary?: boolean
    onToggle?: () => void
    onSetPrimary?: () => void
  }) => {
    const hookTypeLabels: Record<string, string> = {
      deadline: 'Deadline',
      funding_guidance: 'Funding Guidance',
      budget_coding: 'Budget Coding',
      monitoring: 'Monitoring',
      allowable_use: 'Allowable Use',
      district_specific: 'District Specific',
    }
    
    // Truncate long quotes (use global cleanQuoteText helper)
    const MAX_QUOTE_LENGTH = 250
    const quote = cleanQuoteText(h.quote)
    const truncatedQuote = quote.length > MAX_QUOTE_LENGTH 
      ? quote.slice(0, MAX_QUOTE_LENGTH) + '...' 
      : quote
    
    // Extract domain from URL for cleaner display
    let displayDomain = h.link
    try {
      displayDomain = new URL(h.link).hostname.replace('www.', '')
    } catch {
      // Keep original if URL parsing fails
    }
    
    // Check if this is an elevated (filtered but selected) item
    const isElevated = opts.isFiltered && opts.isSelected
    
    return (
      <div className={`p-4 rounded-lg border ${
        isElevated
          ? 'border-amber-600 bg-amber-900/20 opacity-100'
          : opts.isFiltered 
          ? 'border-slate-700 bg-slate-900/30 opacity-75' 
          : opts.isSelected 
          ? 'border-emerald-600 bg-emerald-900/20' 
          : 'border-slate-700 bg-slate-800/50'
      }`}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            {/* Header badges */}
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                opts.isFiltered && !isElevated ? 'bg-slate-700 text-slate-400' : 'bg-emerald-900/50 text-emerald-300'
              }`}>
                {hookTypeLabels[h.hook_type] || h.hook_type}
              </span>
              <span className={`text-xs ${
                h.confidence === 'high' ? 'text-emerald-400' : h.confidence === 'medium' ? 'text-amber-400' : 'text-red-400'
              }`}>
                {h.confidence} confidence
              </span>
              {opts.isFiltered && opts.filterReasonLabel && (
                <span className="px-2 py-0.5 rounded bg-red-900/30 text-red-300 text-xs">
                  {opts.filterReasonLabel}
                </span>
              )}
              {isElevated && (
                <span className="px-2 py-0.5 rounded bg-amber-900/50 text-amber-300 text-xs font-medium">
                  Elevated
                </span>
              )}
              {typeof h.signal_strength === 'number' && (
                <span className="px-2 py-0.5 rounded bg-indigo-900/50 text-indigo-300 text-xs font-medium">
                  Intent {h.signal_strength}
                </span>
              )}
              {h.timing_bucket && (
                <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-300 text-xs font-medium">
                  {h.timing_bucket}
                </span>
              )}
              {h.stale_reason && (
                <span className="px-2 py-0.5 rounded bg-red-900/50 text-red-300 text-xs font-medium">
                  Stale
                </span>
              )}
              {h.deadline_warning && (
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                  h.deadline_warning.includes('passed') || h.deadline_warning.includes('TODAY')
                    ? 'bg-red-900/50 text-red-300'
                    : h.deadline_warning.includes('too late') || h.deadline_warning.includes('quickly')
                    ? 'bg-amber-900/50 text-amber-300'
                    : 'bg-blue-900/50 text-blue-300'
                }`}>
                  {h.deadline_warning}
                </span>
              )}
            </div>
            
            {/* Quote - truncated */}
            <div className="mt-3 text-sm text-slate-200 italic">"{truncatedQuote}"</div>
            
            {/* Divider */}
            <div className="my-3 border-t border-slate-700/50" />
            
            {/* Details grid */}
            <div className="space-y-2">
              <div>
                <div className="text-xs text-slate-500 uppercase tracking-wide font-medium">Trigger</div>
                <div className="mt-0.5 text-sm text-slate-300">{cleanQuoteText(h.trigger_excerpt)}</div>
              </div>
              {h.eligibility_excerpt && (
                <div>
                  <div className="text-xs text-slate-500 uppercase tracking-wide font-medium">Eligibility</div>
                  <div className="mt-0.5 text-sm text-slate-300">{cleanQuoteText(h.eligibility_excerpt)}</div>
                </div>
              )}
              {h.timing_summary && (
                <div>
                  <div className="text-xs text-slate-500 uppercase tracking-wide font-medium">Timing</div>
                  <div className="mt-0.5 text-sm text-slate-300">{cleanQuoteText(h.timing_summary)}</div>
                </div>
              )}
              {h.signal_summary && (
                <div>
                  <div className="text-xs text-slate-500 uppercase tracking-wide font-medium">Buying Intent</div>
                  <div className="mt-0.5 text-sm text-slate-300">{cleanQuoteText(h.signal_summary)}</div>
                </div>
              )}
              {h.stale_reason && (
                <div>
                  <div className="text-xs text-slate-500 uppercase tracking-wide font-medium">Stale Reason</div>
                  <div className="mt-0.5 text-sm text-slate-300">{h.stale_reason}</div>
                </div>
              )}
              <div>
                <div className="text-xs text-slate-500 uppercase tracking-wide font-medium">Why Relevant</div>
                <div className="mt-0.5 text-sm text-slate-400">{cleanQuoteText(h.why_relevant)}</div>
              </div>
            </div>
            
            {/* Source link - clean domain display */}
            <a 
              href={h.link} 
              target="_blank" 
              rel="noreferrer"
              className="mt-3 inline-flex items-center gap-1.5 text-sm text-emerald-400 hover:text-emerald-300"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
              {displayDomain}
            </a>
          </div>
          
          {/* Selection controls - now available for filtered items too */}
          {opts.onToggle && (
            <div className="flex flex-col items-end gap-2 flex-shrink-0">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={opts.isSelected}
                  onChange={opts.onToggle}
                  className="w-5 h-5 rounded border-slate-600 bg-slate-800 text-emerald-500 focus:ring-emerald-500"
                />
                <span className="text-sm text-slate-300">{opts.isFiltered ? 'Elevate' : 'Select'}</span>
              </label>
              {opts.isSelected && selectedHookLinks.length === 2 && opts.onSetPrimary && (
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="primaryHook"
                    checked={opts.isPrimary}
                    onChange={opts.onSetPrimary}
                    className="w-4 h-4 border-slate-600 bg-slate-800 text-emerald-500 focus:ring-emerald-500"
                  />
                  <span className="text-xs text-slate-400">Primary</span>
                </label>
              )}
            </div>
          )}
        </div>
      </div>
    )
  }

  // Determine header content based on flow mode
  const isResearchMode = flowMode === 'research'
  const headerTitle = isResearchMode ? 'Research Discovery' : 'Email Generator'
  const headerSubtitle = isResearchMode 
    ? 'Discover funding opportunities and compliance hooks for any product and state.'
    : 'Find funding/compliance requirements and generate targeted emails.'

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      <div className="max-w-5xl mx-auto px-4 py-10">
        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <Link 
                to="/" 
                className="flex items-center gap-2 text-slate-400 hover:text-slate-200 transition-colors"
                title="Home"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
                </svg>
                <span className="text-sm">Home</span>
              </Link>
              <h1 className="text-2xl sm:text-3xl font-semibold text-slate-100">
                {headerTitle}
              </h1>
              {isResearchMode && (
                <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-blue-600/30 text-blue-300 border border-blue-600/50">
                  Research Mode
                </span>
              )}
            </div>
            <div className="mt-1 text-sm text-slate-400">
              {headerSubtitle}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Background email tasks indicator */}
            {Object.keys(backgroundEmailTasks).length > 0 && (
              <div className="px-3 py-2 rounded-lg bg-amber-900/50 border border-amber-700/50 flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                <span className="text-sm text-amber-200">
                  {Object.keys(backgroundEmailTasks).length} email{Object.keys(backgroundEmailTasks).length > 1 ? 's' : ''} generating
                </span>
              </div>
            )}
            <Link
              to="/saved-runs"
              className="px-4 py-2 rounded-lg bg-emerald-600 text-white font-medium hover:bg-emerald-500 transition-colors flex items-center gap-2"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
              </svg>
              Saved Research
            </Link>
            {isResearchMode && (
              <Link
                to="/coverage"
                className="px-4 py-2 rounded-lg bg-indigo-600 text-white font-medium hover:bg-indigo-500 transition-colors flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
                Coverage
              </Link>
            )}
            {!isResearchMode && (
              <Link
                to="/training"
                className="px-3 py-2 rounded-lg border border-amber-700/50 text-amber-300 hover:bg-amber-900/30 transition-colors flex items-center gap-2"
                title="View golden emails and training feedback"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                </svg>
                Training Data
              </Link>
            )}
            <ThemeToggle />
          </div>
        </div>

        {/* Saved Research Modal */}
        {showSavedRuns && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
            <div className="bg-slate-800 rounded-xl border border-slate-700 w-full max-w-2xl max-h-[80vh] overflow-hidden">
              <div className="p-4 border-b border-slate-700 flex items-center justify-between">
                <h2 className="text-lg font-medium text-slate-200">Saved Email Runs</h2>
                <button
                  onClick={() => setShowSavedRuns(false)}
                  className="p-1 text-slate-400 hover:text-slate-200"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="p-4 overflow-y-auto max-h-[60vh]">
                {loadingSavedRuns ? (
                  <div className="flex items-center justify-center py-8">
                    <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
                    <span className="ml-3 text-slate-400">Loading saved runs...</span>
                  </div>
                ) : savedRuns.length === 0 ? (
                  <div className="text-center py-8 text-slate-400">
                    No saved runs yet. Generate an email and click "Save Run" to save it.
                  </div>
                ) : (
                  <div className="space-y-3">
                    {savedRuns.map((run) => (
                      <div 
                        key={run.id} 
                        className={`p-4 rounded-lg border transition-colors ${
                          currentSavedRunId === run.id 
                            ? 'border-emerald-600 bg-emerald-900/20' 
                            : 'border-slate-700 bg-slate-900/30 hover:border-slate-600'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1 min-w-0">
                            <div className="font-medium text-slate-200">
                              {run.name || `${run.product} / ${run.state_code}`}
                            </div>
                            {run.subject_preview && (
                              <div className="text-sm text-slate-400 mt-1 truncate">
                                "{run.subject_preview}"
                              </div>
                            )}
                            <div className="flex items-center gap-2 mt-2 text-xs text-slate-500">
                              <span>{run.product}</span>
                              <span>•</span>
                              <span>{run.state_full || run.state_code}</span>
                              <span>•</span>
                              <span>{run.audiences.length} audience{run.audiences.length !== 1 ? 's' : ''}</span>
                              <span>•</span>
                              <span>{new Date(run.created_at).toLocaleDateString()}</span>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => loadSavedRun(run)}
                              className="px-3 py-1.5 text-sm rounded bg-emerald-600 text-white hover:bg-emerald-700 transition-colors"
                            >
                              Load
                            </button>
                            <button
                              onClick={() => {
                                if (confirm('Delete this saved run?')) {
                                  deleteSavedRun(run.id)
                                }
                              }}
                              className="p-1.5 text-slate-400 hover:text-red-400 transition-colors"
                            >
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                              </svg>
                            </button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Batch Research Modal */}
        {showBatchModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
            <div className="bg-slate-800 rounded-xl border border-slate-700 w-full max-w-2xl max-h-[80vh] overflow-hidden">
              <div className="p-4 border-b border-slate-700 flex items-center justify-between">
                <h2 className="text-lg font-medium text-slate-200">Batch Research</h2>
                <button
                  onClick={() => setShowBatchModal(false)}
                  className="p-1 text-slate-400 hover:text-slate-200"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="p-4 overflow-y-auto max-h-[60vh]">
                <p className="text-sm text-slate-400 mb-2">
                  Run research across multiple states simultaneously. Results will be saved to your Saved Research.
                </p>
                <p className="text-xs text-slate-500 mb-4">
                  💡 Want to fill gaps efficiently? Use the{' '}
                  <Link 
                    to="/coverage" 
                    className="text-indigo-400 hover:text-indigo-300 underline"
                    onClick={() => setShowBatchModal(false)}
                  >
                    Coverage Matrix
                  </Link>{' '}
                  to see exactly what research is missing.
                </p>
                
                {/* Product Summary */}
                <div className="mb-4 p-3 bg-slate-900/50 rounded-lg border border-slate-700">
                  <div className="text-xs text-slate-500 mb-1">Product</div>
                  <div className="text-sm text-slate-200">{selectedProduct || 'No product selected'}</div>
                </div>
                
                {/* State Selection */}
                <div className="mb-4">
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-sm font-medium text-slate-300">States to research</label>
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          // Add all WIDA states (38 states - matches backend WIDA_STATES)
                          const widaStates = [
                            { code: 'AK', name: 'Alaska' }, { code: 'AL', name: 'Alabama' },
                            { code: 'CO', name: 'Colorado' }, { code: 'DC', name: 'District of Columbia' },
                            { code: 'DE', name: 'Delaware' }, { code: 'FL', name: 'Florida' },
                            { code: 'GA', name: 'Georgia' }, { code: 'HI', name: 'Hawaii' },
                            { code: 'ID', name: 'Idaho' }, { code: 'IL', name: 'Illinois' },
                            { code: 'IN', name: 'Indiana' }, { code: 'KY', name: 'Kentucky' },
                            { code: 'MA', name: 'Massachusetts' }, { code: 'MD', name: 'Maryland' },
                            { code: 'ME', name: 'Maine' }, { code: 'MI', name: 'Michigan' },
                            { code: 'MN', name: 'Minnesota' }, { code: 'MO', name: 'Missouri' },
                            { code: 'MT', name: 'Montana' }, { code: 'NC', name: 'North Carolina' },
                            { code: 'ND', name: 'North Dakota' }, { code: 'NH', name: 'New Hampshire' },
                            { code: 'NJ', name: 'New Jersey' }, { code: 'NM', name: 'New Mexico' },
                            { code: 'NY', name: 'New York' }, { code: 'NV', name: 'Nevada' },
                            { code: 'OK', name: 'Oklahoma' }, { code: 'PA', name: 'Pennsylvania' },
                            { code: 'RI', name: 'Rhode Island' }, { code: 'SC', name: 'South Carolina' },
                            { code: 'SD', name: 'South Dakota' }, { code: 'TN', name: 'Tennessee' },
                            { code: 'UT', name: 'Utah' }, { code: 'VA', name: 'Virginia' },
                            { code: 'VT', name: 'Vermont' }, { code: 'WA', name: 'Washington' },
                            { code: 'WI', name: 'Wisconsin' }, { code: 'WY', name: 'Wyoming' },
                          ]
                          setBatchStates(widaStates)
                        }}
                        className="text-xs px-2 py-1 rounded bg-emerald-800/50 text-emerald-300 hover:bg-emerald-700/50"
                      >
                        All WIDA
                      </button>
                      <button
                        onClick={() => {
                          // Add all 50 US states + DC
                          const allStates = Object.entries(ALL_US_STATES).map(([code, name]) => ({ code, name }))
                          setBatchStates(allStates)
                        }}
                        className="text-xs px-2 py-1 rounded bg-blue-800/50 text-blue-300 hover:bg-blue-700/50"
                      >
                        All 50 States
                      </button>
                      <button
                        onClick={() => setBatchStates([])}
                        className="text-xs px-2 py-1 rounded bg-slate-700 text-slate-300 hover:bg-slate-600"
                      >
                        Clear
                      </button>
                    </div>
                  </div>
                  
                  {/* Text input for typing state codes */}
                  <div className="flex gap-2 mb-3">
                    <input
                      type="text"
                      value={batchStateInput}
                      onChange={(e) => setBatchStateInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault()
                          parseAndAddStates(batchStateInput)
                        }
                      }}
                      placeholder="Type state codes: IL, TX, CA..."
                      className="flex-1 px-3 py-2 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                    />
                    <button
                      onClick={() => parseAndAddStates(batchStateInput)}
                      disabled={!batchStateInput.trim()}
                      className="px-3 py-2 rounded-lg bg-emerald-700 text-white text-sm hover:bg-emerald-600 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Add
                    </button>
                  </div>
                  
                  <div className="flex flex-wrap gap-2 p-3 bg-slate-900/30 rounded-lg border border-slate-700 min-h-[60px]">
                    {batchStates.length === 0 ? (
                      <span className="text-sm text-slate-500">Type state codes above or use quick-select buttons</span>
                    ) : (
                      batchStates.map(s => (
                        <span
                          key={s.code}
                          className="inline-flex items-center gap-1 px-2 py-1 bg-slate-700 rounded text-xs text-slate-200"
                        >
                          {s.code}
                          <button
                            onClick={() => setBatchStates(prev => prev.filter(x => x.code !== s.code))}
                            className="text-slate-400 hover:text-red-400"
                          >
                            ×
                          </button>
                        </span>
                      ))
                    )}
                  </div>
                  <div className="mt-2 text-xs text-slate-500">
                    {batchStates.length} states selected
                  </div>
                </div>
                
                {/* Force fresh research option */}
                <div className="mb-4">
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={batchForceFresh}
                      onChange={(e) => setBatchForceFresh(e.target.checked)}
                      className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-emerald-500 focus:ring-emerald-500/50"
                    />
                    <div>
                      <span className="text-sm text-slate-200">Force fresh research</span>
                      <span className="text-xs text-slate-500 ml-2">(clear cached results)</span>
                    </div>
                  </label>
                  <p className="text-xs text-slate-500 mt-1 ml-7">
                    Check this to get new research results instead of using cached data from previous runs.
                  </p>
                </div>
                
                {/* Include district research option */}
                <div className="mb-4">
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={batchIncludeDistrictResearch}
                      onChange={(e) => setBatchIncludeDistrictResearch(e.target.checked)}
                      className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-amber-500 focus:ring-amber-500/50"
                    />
                    <div>
                      <span className="text-sm text-slate-200">Include district research</span>
                      <span className="text-xs text-slate-500 ml-2">(find district-specific opportunities)</span>
                    </div>
                  </label>
                  <p className="text-xs text-slate-500 mt-1 ml-7">
                    Adds ~10-20 min per state to find levy failures, budget crises, and district-specific initiatives.
                  </p>
                </div>

                {/* Include conference research option */}
                <div className="mb-4">
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={batchIncludeConferenceResearch}
                      onChange={(e) => setBatchIncludeConferenceResearch(e.target.checked)}
                      className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-indigo-500 focus:ring-indigo-500/50"
                    />
                    <div>
                      <span className="text-sm text-slate-200">Include conference research</span>
                      <span className="text-xs text-slate-500 ml-2">(find marketing opportunities)</span>
                    </div>
                  </label>
                  <p className="text-xs text-slate-500 mt-1 ml-7">
                    Adds ~5-15 min per state to find relevant conferences (TESOL affiliates, EL summits, etc.)
                  </p>
                </div>
                
                {/* Estimated time/cost */}
                <div className="mb-4 p-3 bg-amber-900/20 rounded-lg border border-amber-700/30">
                  <div className="text-sm text-amber-300 font-medium mb-1">Estimated Time & Cost</div>
                  <div className="text-xs text-amber-200/70">
                    ~{Math.ceil(batchStates.length / 3) * 15} - {Math.ceil(batchStates.length / 3) * 30} minutes
                    (3 states in parallel, 5-10 min each)
                  </div>
                  <div className="text-xs text-amber-200/70 mt-1">
                    ~${(batchStates.length * 1.5).toFixed(2)} in API costs ({batchStates.length} states × ~$1.50/state)
                  </div>
                </div>
              </div>
              
              <div className="p-4 border-t border-slate-700 flex justify-end gap-3">
                <button
                  onClick={() => setShowBatchModal(false)}
                  className="px-4 py-2 rounded-lg text-slate-300 hover:bg-slate-700"
                >
                  Cancel
                </button>
                <button
                  onClick={async () => {
                    if (!selectedProduct || batchStates.length === 0) return
                    setStartingBatch(true)
                    try {
                      await api.batch.create({
                        name: `${selectedProduct} - ${batchStates.length} states`,
                        product: selectedProduct,
                        states: batchStates,
                        audiences: [selectedAudience],
                        include_district_research: batchIncludeDistrictResearch,
                        include_conference_research: batchIncludeConferenceResearch,
                        force_fresh: batchForceFresh,
                      })
                      toast({
                        title: 'Batch job started!',
                        description: `Processing ${batchStates.length} states. View progress in Saved Research.`,
                      })
                      setShowBatchModal(false)
                      setBatchStates([])
                      setBatchForceFresh(false)
                    } catch (err) {
                      toast({
                        title: 'Failed to start batch job',
                        description: err instanceof Error ? err.message : 'Unknown error',
                        variant: 'destructive',
                      })
                    } finally {
                      setStartingBatch(false)
                    }
                  }}
                  disabled={!selectedProduct || batchStates.length === 0 || startingBatch}
                  className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {startingBatch ? 'Starting...' : `Start Batch (${batchStates.length} states)`}
                </button>
              </div>
            </div>
          </div>
        )}

        {renderProgressBar()}

        {/* Step 1: Choose Product & Audience */}
        {wizardStep === 1 && (
          <div className="p-6 rounded-xl border border-slate-700 bg-slate-800/50">
            <h2 className="text-lg font-medium text-slate-200 mb-6">Choose Product & Audience</h2>
            <div className="space-y-6">
              {/* Your Name (so you can find your info later) */}
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  Your Name <span className="text-slate-500">(so you can find your info later)</span>
                </label>
                <input
                  type="text"
                  value={createdBy}
                  onChange={(e) => {
                    const name = e.target.value
                    setCreatedBy(name)
                    localStorage.setItem('wceps_created_by', name)
                  }}
                  placeholder="e.g., Sarah Martinez"
                  className="w-full max-w-xs px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500"
                />
              </div>
              
              <ProductSelector selectedProduct={selectedProduct} onSelect={setSelectedProduct} />
              <StateSelector selectedStates={selectedStates} onSelect={setSelectedStates} />

              <div>
                <AudienceSelector selectedProduct={selectedProduct} selectedAudience={selectedAudience} onSelect={setSelectedAudience} />
              </div>

              {/* District/Conference research toggles removed from UI (keeping backend capability) */}

              {/* Cache status notification */}
              {cacheStatus && cacheStatus.status !== 'not_found' && cacheStatus.status !== 'loading' && (
                <div className={`p-4 rounded-lg border ${
                  cacheStatus.status === 'completed' 
                    ? 'border-emerald-700/50 bg-emerald-900/20'
                    : cacheStatus.status === 'in_progress'
                    ? 'border-amber-700/50 bg-amber-900/20'
                    : cacheStatus.status === 'expired'
                    ? 'border-amber-700/50 bg-amber-900/10'
                    : 'border-slate-700 bg-slate-800/50'
                }`}>
                  {cacheStatus.status === 'completed' && (
                    <div className="flex items-start gap-3">
                      <div className="w-8 h-8 rounded-full bg-emerald-600/30 flex items-center justify-center flex-shrink-0">
                        <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                        </svg>
                      </div>
                      <div className="flex-1">
                        <div className="text-sm font-medium text-emerald-300">
                          Cached results available!
                        </div>
                        <div className="mt-1 text-sm text-emerald-200/80">
                          Found {cacheStatus.hook_count} requirements {cacheStatus.cache_age_days === 0 ? 'today' : `${cacheStatus.cache_age_days} days ago`}.
                          Expires in {cacheStatus.expires_in_days} days.
                        </div>
                        <div className="mt-2 text-xs text-emerald-200/60">
                          Cached research is ready. Click Continue to add purpose and optionally include cached items.
                        </div>
                      </div>
                    </div>
                  )}
                  {cacheStatus.status === 'expired' && (
                    <div className="flex items-start gap-3">
                      <div className="w-8 h-8 rounded-full bg-amber-600/20 flex items-center justify-center flex-shrink-0">
                        <AlertCircle className="w-4 h-4 text-amber-400" />
                      </div>
                      <div className="flex-1">
                        <div className="text-sm font-medium text-amber-300">
                          Stale cached results available
                        </div>
                        <div className="mt-1 text-sm text-amber-200/80">
                          Found {typeof cacheStatus.hook_count === 'number' ? cacheStatus.hook_count : 'cached'} requirements {cacheStatus.cache_age_days === 0 ? 'today' : `${cacheStatus.cache_age_days} days ago`}.
                          These results are older than 30 days, but you can still reuse them to avoid new research costs.
                        </div>
                        <div className="mt-2 text-xs text-amber-200/60">
                          Click Continue to select optional cached items, or Re-search if you need fresh results.
                        </div>
                      </div>
                    </div>
                  )}
                  {cacheStatus.status === 'in_progress' && (
                    <div className="flex items-start gap-3">
                      <div className="w-8 h-8 rounded-full bg-amber-600/30 flex items-center justify-center flex-shrink-0">
                        <div className="w-4 h-4 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
                      </div>
                      <div className="flex-1">
                        <div className="text-sm font-medium text-amber-300">
                          Research in progress!
                        </div>
                        <div className="mt-1 text-sm text-amber-200/80">
                          Research is in progress. Cached items will appear once it completes.
                        </div>
                      </div>
                    </div>
                  )}
                  {cacheStatus.status === 'failed' && (
                    <div className="flex items-start gap-3">
                      <div className="w-8 h-8 rounded-full bg-red-600/30 flex items-center justify-center flex-shrink-0">
                        <svg className="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </div>
                      <div>
                        <div className="text-sm font-medium text-red-300">Previous research failed</div>
                        <div className="mt-1 text-sm text-red-200/80">
                          {cacheStatus.error || 'Unknown error'}. You can still proceed with a purpose-only email.
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="pt-4 flex justify-between items-center">
                {/* Batch research: subtle link in research mode, button in email mode */}
                {isResearchMode ? (
                  <button
                    onClick={() => setShowBatchModal(true)}
                    disabled={!selectedProduct}
                    className="text-sm text-slate-400 hover:text-slate-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    title="Run research across multiple states at once"
                  >
                    Need to research multiple states? →
                  </button>
                ) : (
                  <button
                    onClick={() => setShowBatchModal(true)}
                    disabled={!selectedProduct}
                    className="px-4 py-2 rounded-lg font-medium text-amber-300 border border-amber-600 hover:bg-amber-900/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    title="Run research across multiple states at once"
                  >
                    🚀 Batch Research
                  </button>
                )}
                <div className="flex gap-3">
                  <button
                    onClick={handlePrep}
                    disabled={!canPrep}
                    className={`px-6 py-3 rounded-lg font-medium transition-colors flex items-center gap-2 ${
                      !canPrep
                        ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                        : isResearchMode
                          ? 'bg-blue-600 hover:bg-blue-500 text-white'
                          : 'bg-emerald-600 hover:bg-emerald-500 text-white'
                    }`}
                  >
                    {isResearchMode ? 'Start Research →' : 'Continue →'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Step 2: Purpose + Optional Cached Hooks */}
        {wizardStep === 2 && (
          <div className="p-6 rounded-xl border border-slate-700 bg-slate-800/50">
            {isResearchMode ? (
              <div className="flex flex-col items-center justify-center py-8">
                <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4" />
                <h2 className="text-lg font-medium text-slate-200 mb-2">Researching...</h2>
                <p className="text-sm text-slate-400 text-center max-w-md">
                  {researchMessage || 'Running research for the selected product and state.'}
                </p>
                <div className="mt-4 w-full max-w-md">
                  <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                    <span>{researchPhase === 'idle' ? 'Starting' : `Phase: ${researchPhase}`}</span>
                    <span>{Math.round(researchProgress)}%</span>
                  </div>
                  <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-500 transition-all"
                      style={{ width: `${Math.min(100, Math.max(0, researchProgress))}%` }}
                    />
                  </div>
                </div>
                <div className="mt-3 text-xs text-slate-500">
                  This can take a few minutes.
                </div>
              </div>
            ) : (
              <>
                <h2 className="text-lg font-medium text-slate-200 mb-2">Purpose of the Email</h2>
                <p className="text-sm text-slate-400 mb-4">
                  Enter a purpose OR select cached research below. You can also provide both for more targeted emails.
                </p>

                <div className="mb-6">
                  <label className="block text-sm font-medium text-slate-300 mb-2">
                    Purpose (optional)
                  </label>
                  <textarea
                    value={purposePrompt}
                    onChange={(e) => setPurposePrompt(e.target.value)}
                    placeholder="e.g., Let Hawaii districts know CARE Coaching is now available after we won the RFP."
                    rows={4}
                    className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500"
                  />
                  <div className="mt-2 text-xs text-slate-500">
                    Keep it specific: audience, context, and desired outcome.
                  </div>
                </div>

            <div className="mb-2 flex items-center justify-between">
              <div className="text-sm font-medium text-slate-200">Optional cached research</div>
              {showCachedSections && (
                <div className="text-xs text-slate-400">{selectedCachedHooks.length}/2 selected</div>
              )}
                    </div>
            {showCachedSections ? (
              <>
                <div className="text-xs text-slate-500 mb-4">
                  Uses cached research (may be stale). If no cache exists for a state, hooks will be unavailable.
                </div>

                <div className="space-y-3">
              <div className="rounded-lg border border-slate-700 bg-slate-900/30">
                <button
                  onClick={() => setStateHooksExpanded((v) => !v)}
                  className="w-full flex items-center justify-between px-4 py-3 text-sm text-slate-200"
                >
                  <span>State-level hooks</span>
                  {stateHooksExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </button>
                {stateHooksExpanded && (
                  <div className="px-4 pb-4 space-y-3">
                    {cachedPrepLoading && (
                      <div className="text-xs text-slate-500">Loading cached research…</div>
                    )}
                    {!cachedPrepLoading && selectedStates.map((st) => {
                      const cached = cachedPrepByState[st.code]
                      const hooks = cached?.treasure_hooks || []
                      return (
                        <div key={`state-${st.code}`}>
                          <div className="text-xs text-slate-500 mb-1">{st.name}</div>
                          {hooks.length === 0 ? (
                            <div className="text-xs text-slate-600">No cached state hooks.</div>
                          ) : (
                            <div className="space-y-3">
                              {hooks.map((h) => {
                                const key = `state:${st.code}:${getHookKey(h)}`
                                const selected = isCachedHookSelected(key)
                                return (
                                  <div key={key} data-testid="cached-state-hook">
                                    {renderRequirementCard(h, {
                                      isSelected: selected,
                                      onToggle: () => toggleCachedHook({ key, category: 'state', state_code: st.code, hook: h }),
                                    })}
                                  </div>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
            </div>
            
              <div className="rounded-lg border border-slate-700 bg-slate-900/30">
                <button
                  onClick={() => setDistrictHooksExpanded((v) => !v)}
                  className="w-full flex items-center justify-between px-4 py-3 text-sm text-slate-200"
                >
                  <span>District-level hooks</span>
                  {districtHooksExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </button>
                {districtHooksExpanded && (
                  <div className="px-4 pb-4 space-y-3">
                    {!cachedPrepLoading && selectedStates.map((st) => {
                      const cached = cachedPrepByState[st.code]
                      const hooks = cached?.district_research?.passed_hooks || []
                      return (
                        <div key={`district-${st.code}`}>
                          <div className="text-xs text-slate-500 mb-1">{st.name}</div>
                          {hooks.length === 0 ? (
                            <div className="text-xs text-slate-600">No cached district hooks.</div>
                          ) : (
                            <div className="space-y-3">
                              {hooks.map((h) => {
                                const key = `district:${st.code}:${getHookKey(h)}`
                                const selected = isCachedHookSelected(key)
                                return (
                                  <div key={key} data-testid="cached-district-hook">
                                    {renderRequirementCard(h, {
                                      isSelected: selected,
                                      onToggle: () => toggleCachedHook({ key, category: 'district', state_code: st.code, hook: h }),
                                    })}
                                  </div>
                                )
                              })}
                            </div>
                )}
              </div>
                      )
                    })}
                  </div>
                )}
            </div>
            
              <div className="rounded-lg border border-slate-700 bg-slate-900/30">
                <button
                  onClick={() => setConferenceHooksExpanded((v) => !v)}
                  className="w-full flex items-center justify-between px-4 py-3 text-sm text-slate-200"
                >
                  <span>Conference info</span>
                  {conferenceHooksExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </button>
                {conferenceHooksExpanded && (
                  <div className="px-4 pb-4 space-y-3">
                    {!cachedPrepLoading && selectedStates.map((st) => {
                      const cached = cachedPrepByState[st.code]
                      const conferences = cached?.conferences || []
                    return (
                        <div key={`conference-${st.code}`}>
                          <div className="text-xs text-slate-500 mb-1">{st.name}</div>
                          {conferences.length === 0 ? (
                            <div className="text-xs text-slate-600">No cached conference info.</div>
                          ) : (
                            <div className="space-y-2">
                              {conferences.map((c) => {
                                const key = `conference:${st.code}:${c.website}`
                                const selected = isCachedHookSelected(key)
                                return (
                                  <div key={key} className="p-3 rounded border border-slate-700 bg-slate-900/40">
                                    <div className="flex items-start justify-between gap-3">
                                      <div>
                                        <div className="text-xs text-slate-500 uppercase">{c.conference_name}</div>
                                        <div className="text-sm text-slate-200 mt-1">{c.relevance || 'Conference opportunity'}</div>
                                      </div>
                                      <button
                                        onClick={() => toggleCachedHook({ key, category: 'conference', state_code: st.code, hook: c })}
                                        className={`px-2 py-1 text-xs rounded border ${
                                          selected ? 'bg-emerald-900/40 text-emerald-300 border-emerald-700/50' : 'border-slate-600 text-slate-300'
                                        }`}
                                      >
                                        {selected ? 'Selected' : 'Select'}
                                      </button>
                                    </div>
                      </div>
                    )
                  })}
                </div>
                          )}
                        </div>
                      )
                    })}
              </div>
            )}
              </div>
            </div>
              </>
            ) : (
              <div className="text-xs text-slate-500 mb-4">
                No cached research for {selectedProduct || 'this product'} yet. Run research to generate cached hooks.
              </div>
            )}

                <div className="mt-6">
                  {!purposePrompt.trim() && selectedCachedHooks.length === 0 && (
                    <div className="mb-3 text-xs text-amber-400/80">
                      {showCachedSections
                        ? 'Enter a purpose OR select at least one cached hook above to generate an email.'
                        : 'Enter a purpose to generate an email.'}
                    </div>
                  )}
                  <div className="flex justify-end gap-3">
                    <button
                      onClick={() => setWizardStep(1)}
                      className="px-4 py-2 rounded-lg text-slate-300 border border-slate-600 hover:bg-slate-700"
                    >
                      Back
                    </button>
                    <button
                      onClick={() => {
                        if (!purposePrompt.trim() && selectedCachedHooks.length === 0) return
                        setWizardStep(4)
                        pipelineMutation.mutate()
                      }}
                      disabled={!purposePrompt.trim() && selectedCachedHooks.length === 0}
                      className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Generate Email →
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* Step 3: Select Requirements */}
        {wizardStep === 3 && (
          <div className="p-6 rounded-xl border border-slate-700 bg-slate-800/50">
            <h2 className="text-lg font-medium text-slate-200 mb-2">Select Funding & Compliance Requirements</h2>
            <p className="text-sm text-slate-400 mb-6">
              Select 1-2 requirements to include in your email. Each selected requirement needs at least one reason tag.
            </p>

            {/* Passed requirements */}
            {passedRequirements.length > 0 ? (
              <div className="space-y-4 mb-6">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium text-emerald-300">
                    Requirements that passed ({passedRequirements.length})
                  </h3>
                  <span className="text-xs text-slate-500">Selected: {selectedHookLinks.length}/2</span>
                </div>
                {passedRequirements.map((h) => {
                  const hookKey = getHookKey(h)
                  const isSelected = selectedHookLinks.includes(hookKey)
                  const isPrimary = primaryHookLink === hookKey
                  return (
                    <div key={hookKey}>
                      {renderRequirementCard(h, {
                        isSelected,
                        isPrimary,
                        onToggle: () => toggleHook(hookKey),
                        onSetPrimary: () => setPrimaryHookLink(hookKey),
                      })}
                      {/* Reason tags for selected requirements */}
                      {isSelected && (
                        <div className="mt-3 ml-4 p-3 rounded-lg border border-slate-700 bg-slate-900/30">
                          <div className="text-xs text-slate-400 mb-2">Why did you select this requirement?</div>
                          <div className="flex flex-wrap gap-2">
                            {[
                              { tag: 'timely', label: 'Timely/Urgent' },
                              { tag: 'relevant', label: 'Relevant to offering' },
                              { tag: 'actionable', label: 'Actionable' },
                              { tag: 'credible', label: 'Credible source' },
                            ].map((opt) => (
                              <label
                                key={`${hookKey}-${opt.tag}`}
                                className={`flex items-center gap-2 px-2 py-1 rounded border text-xs cursor-pointer ${
                                  (hookReasonTags[hookKey] || []).includes(opt.tag)
                                    ? 'border-emerald-600 bg-emerald-900/10 text-emerald-200'
                                    : 'border-slate-700 bg-slate-900/10 text-slate-300 hover:bg-slate-900/20'
                                }`}
                              >
                                <input
                                  type="checkbox"
                                  checked={(hookReasonTags[hookKey] || []).includes(opt.tag)}
                                  onChange={() => toggleReasonTag(hookKey, opt.tag)}
                                  className="sr-only"
                                />
                                <span>{opt.label}</span>
                              </label>
                            ))}
                          </div>
                          <textarea
                            value={hookReasonNotes[hookKey] || ''}
                            onChange={(e) => setHookReasonNotes((prev) => ({ ...prev, [hookKey]: e.target.value }))}
                            placeholder="Optional notes..."
                            className="mt-2 w-full min-h-[60px] px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500 text-sm"
                          />
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="p-4 rounded-lg border border-amber-800 bg-amber-900/20 text-amber-300 mb-6">
                <div className="font-medium text-lg">
                  Deep Research found {allFilteredRequirements.length} potential requirement{allFilteredRequirements.length !== 1 ? 's' : ''}
                </div>
                <div className="text-sm mt-2 text-amber-200">
                  Our relevance filter flagged all of them, but you can review and select them below.
                  Click any requirement to see why it was filtered - you can override the filter.
                </div>
              </div>
            )}

            {/* Filtered requirements (collapsible) */}
            {allFilteredRequirements.length > 0 && (
              <div className="mt-4">
                <div className="p-4 rounded-lg bg-slate-700/50 border border-slate-600">
                  <button
                    onClick={() => setShowFilteredSection(!showFilteredSection)}
                    className="w-full text-left"
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="font-medium text-slate-200">
                          {showFilteredSection ? 'Hide' : 'Review'} {allFilteredRequirements.length} Research Result{allFilteredRequirements.length !== 1 ? 's' : ''}
                        </div>
                        <div className="text-sm text-slate-400 mt-1">
                          {passedRequirements.length === 0 
                            ? 'These were flagged by our filter but may still be relevant - you can select them'
                            : 'Additional results that were flagged by our filter'}
                        </div>
                      </div>
                      <svg className={`w-5 h-5 text-slate-400 transition-transform ${showFilteredSection ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </div>
                  </button>
                </div>
                {showFilteredSection && (
                  <div className="mt-4 space-y-4">
                    {allFilteredRequirements.map((fr, idx) => {
                      const hookKey = getHookKey(fr.hook)
                      return (
                        <div key={`filtered-${idx}`}>
                          {renderRequirementCard(fr.hook, {
                            isFiltered: true,
                            filterReason: fr.reason,
                            filterReasonLabel: fr.reason_label,
                            isSelected: selectedHookLinks.includes(hookKey),
                            isPrimary: primaryHookLink === hookKey,
                            onToggle: () => toggleHook(hookKey),
                            onSetPrimary: () => setPrimaryHookLink(hookKey),
                          })}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )}

            {/* Validation message */}
            {!tagsOk && selectedHookLinks.length > 0 && (
              <div className="mt-4 p-3 rounded border border-amber-800 bg-amber-900/20 text-amber-300 text-sm">
                Add at least one reason tag for each selected requirement to continue.
              </div>
            )}

            {/* District Research Section */}
            {prep && (
              <div className="mt-8 pt-6 border-t border-slate-700">
                {/* District Research Progress */}
                {districtResearchStatus === 'running' && (
                  <div className="mb-6 p-4 bg-slate-800/50 rounded-lg border border-amber-700/50">
                    <div className="flex items-center gap-3 mb-3">
                      <div className="animate-spin h-5 w-5 border-2 border-amber-500 border-t-transparent rounded-full" />
                      <span className="text-sm font-medium text-amber-400">District Research in Progress</span>
                    </div>
                    
                    {/* Progress bar */}
                    <div className="w-full h-2 bg-slate-700 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-amber-500 transition-all duration-500"
                        style={{ width: `${districtResearchProgress}%` }}
                      />
                    </div>
                    
                    {/* Status text */}
                    <div className="mt-2 flex justify-between text-xs text-slate-400">
                      <span>{districtResearchMessage || 'Researching districts...'}</span>
                      <span>{Math.round(districtResearchProgress)}%</span>
                    </div>
                  </div>
                )}
                
                {/* District Results Section */}
                {prep.district_research && (
                  <div className="mb-6">
                    <h3 className="text-lg font-semibold text-amber-400 mb-2 flex items-center gap-2">
                      🏫 District-Level Opportunities
                      <span className="text-sm font-normal text-slate-500">
                        ({prep.district_research.districts_surveyed?.length || 0} districts surveyed)
                      </span>
                    </h3>
                    
                    {/* Passed Hooks - Grouped by District */}
                    {prep.district_research.passed_hooks && prep.district_research.passed_hooks.length > 0 ? (
                      <div className="space-y-4">
                        {(() => {
                          // Group hooks by district
                          const byDistrict: Record<string, typeof prep.district_research.passed_hooks> = {}
                          for (const hook of prep.district_research.passed_hooks || []) {
                            const district = hook.district_name || 'Unknown District'
                            if (!byDistrict[district]) byDistrict[district] = []
                            byDistrict[district].push(hook)
                          }
                          return Object.entries(byDistrict).map(([district, hooks]) => (
                            <div key={district} className="p-4 bg-slate-800/50 rounded-lg border border-amber-700/30">
                              <div className="flex items-center justify-between mb-3">
                                <h4 className="font-medium text-amber-400">{district}</h4>
                                <button
                                  onClick={() => {
                                    handleDistrictGenerate(hooks[0], selectedStates[0]?.code || '')
                                  }}
                                  className="px-3 py-1.5 text-sm bg-amber-600 hover:bg-amber-500 text-white rounded transition-colors"
                                >
                                  Generate Email →
                                </button>
                              </div>
                              <div className="space-y-2">
                                {hooks.map((hook, i) => (
                                  <div key={i} className="text-sm">
                                    <span className="text-slate-300">{cleanQuoteText(hook.quote)}</span>
                                    {hook.why_district_specific && (
                                      <p className="text-xs text-slate-500 mt-1">
                                        Why district-specific: {cleanQuoteText(hook.why_district_specific)}
                                      </p>
                                    )}
                                  </div>
                                ))}
                              </div>
                            </div>
                          ))
                        })()}
                      </div>
                    ) : (
                      <div className="p-4 bg-slate-800/30 rounded-lg border border-slate-700">
                        <p className="text-sm text-slate-400">
                          ✓ District research completed. No incremental opportunities found beyond state-level findings.
                        </p>
                        {prep.district_research.districts_surveyed && prep.district_research.districts_surveyed.length > 0 && (
                          <p className="text-xs text-slate-500 mt-1">
                            Surveyed: {prep.district_research.districts_surveyed.slice(0, 10).join(', ')}
                            {prep.district_research.districts_surveyed.length > 10 && ` +${prep.district_research.districts_surveyed.length - 10} more`}
                          </p>
                        )}
                      </div>
                    )}
                    
                    {/* Filtered Items - Expandable for Transparency */}
                    {prep.district_research.filtered_hooks && prep.district_research.filtered_hooks.length > 0 && (
                      <details className="mt-4">
                        <summary className="text-sm text-slate-500 cursor-pointer hover:text-slate-400">
                          View {prep.district_research.filtered_hooks.length} filtered district items
                        </summary>
                        <div className="mt-2 space-y-2 pl-4 border-l-2 border-slate-700">
                          {prep.district_research.filtered_hooks.map((item, i) => (
                            <div key={i} className="text-xs text-slate-500">
                              <span className="font-medium">{cleanQuoteText(item.hook.quote)?.slice(0, 80)}...</span>
                              <span className="text-slate-600 ml-2">— {item.filter_detail}</span>
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                  </div>
                )}
                
                {/* Run District Research Button (on-demand) */}
                {!prep.district_research && !includeDistrictResearch && districtResearchStatus === 'idle' && (
                  <div className="p-4 bg-amber-900/20 rounded-lg border border-amber-700/50">
                    <div className="flex items-center justify-between">
                      <div>
                        <h4 className="text-sm font-medium text-amber-400">Want more opportunities?</h4>
                        <p className="text-xs text-slate-400 mt-1">
                          Survey top 30 districts for additional funding & compliance hooks
                        </p>
                      </div>
                      <button
                        onClick={async () => {
                          setDistrictResearchStatus('running')
                          setDistrictResearchProgress(0)
                          setDistrictResearchMessage('Starting district research...')
                          try {
                            const result: DistrictResearchResult = await api.generate.districtResearchStream(
                              {
                                product: selectedProduct || '',
                                state: selectedStates[0]?.code || '',
                                state_full: selectedStates[0]?.name,
                                state_hooks: (prep.treasure_hooks || []).map(h => ({
                                  hook_id: h.hook_id || undefined,
                                  link: h.link,
                                  quote: h.quote,
                                  title: h.quote?.slice(0, 100),
                                })),
                              },
                              (evt) => {
                                if (evt.stage === 'district_research' && evt.type === 'progress') {
                                  setDistrictResearchProgress((evt.percent as number) || 0)
                                  setDistrictResearchMessage((evt.message as string) || 'Researching...')
                                }
                              }
                            )
                            setPrep(prev => prev ? { ...prev, district_research: result } : null)
                            setDistrictResearchStatus('complete')
                            toast({
                              title: 'District research complete',
                              description: `Found ${result.passed_hooks?.length || 0} district-level opportunities.`,
                            })
                          } catch (err) {
                            toast({
                              title: 'District research failed',
                              description: err instanceof Error ? err.message : 'Unknown error',
                              variant: 'destructive',
                            })
                            setDistrictResearchStatus('idle')
                          }
                        }}
                        className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium rounded-lg transition-colors"
                      >
                        Run District Research
                      </button>
                    </div>
                  </div>
                )}
                
                {/* Conference Opportunities Section */}
                <div className="p-4 bg-indigo-900/20 rounded-lg border border-indigo-700/50">
                  <h4 className="text-sm font-medium text-indigo-400 flex items-center gap-2 mb-3">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                    Conference Opportunities
                    <span className="text-xs text-slate-500 font-normal ml-2">
                      (for in-person relationship building)
                    </span>
                  </h4>
                  
                  {prep.conferences && prep.conferences.length > 0 ? (
                    <>
                      <div className="space-y-3">
                        {prep.conferences.map((conf, idx) => (
                          <div 
                            key={idx} 
                            className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50 hover:border-indigo-600/50 transition-colors"
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 mb-1">
                                  <h5 className="text-sm font-medium text-slate-200 truncate">
                                    {conf.conference_name}
                                  </h5>
                                  {conf.confidence === 'high' && (
                                    <span className="shrink-0 px-1.5 py-0.5 text-[10px] font-medium bg-emerald-900/50 text-emerald-400 rounded">
                                      HIGH QUALITY
                                    </span>
                                  )}
                                </div>
                                <p className="text-xs text-slate-400 mb-2">
                                  {conf.organization} • {conf.location}
                                </p>
                                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                                  <span className="text-indigo-400">
                                    📅 {renderWithLinks(conf.dates)}
                                  </span>
                                  {conf.presentation_deadline && (
                                    <span className="text-amber-400">
                                      ✍️ Proposals due: {renderWithLinks(conf.presentation_deadline)}
                                    </span>
                                  )}
                                  {conf.sponsorship_info && (
                                    <span className="text-emerald-400">
                                      💼 {renderWithLinks(conf.sponsorship_info)}
                                    </span>
                                  )}
                                </div>
                                {conf.relevance && (
                                  <p className="text-xs text-slate-500 mt-2 italic">
                                    {renderWithLinks(conf.relevance)}
                                  </p>
                                )}
                              </div>
                              <a
                                href={conf.website}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="shrink-0 px-3 py-1.5 text-xs font-medium bg-indigo-600/20 text-indigo-400 hover:bg-indigo-600/30 rounded-lg transition-colors"
                              >
                                Visit →
                              </a>
                            </div>
                          </div>
                        ))}
                      </div>
                      
                      <p className="text-[11px] text-slate-500 mt-3">
                        💡 Tip: Presenting or sponsoring at these conferences is a great way to build relationships with {selectedAudience === 'Users' ? 'educators' : 'decision makers'} in {selectedStates[0]?.name || 'this state'}.
                      </p>
                    </>
                  ) : (
                    <div className="text-center py-4">
                      <p className="text-sm text-slate-400">
                        No conference opportunities found for {selectedStates[0]?.name || 'this state'}.
                      </p>
                      <p className="text-xs text-slate-500 mt-1">
                        The conference search may have timed out. Try searching manually for state TESOL chapters or regional education conferences.
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Navigation */}
            <div className="mt-6 pt-4 border-t border-slate-700 flex justify-between">
              <button
                onClick={() => setWizardStep(1)}
                className="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 font-medium transition-colors"
              >
                ← Back
              </button>
              <div className="flex gap-3">
                <button
                  onClick={() => saveResearchRun()}
                  disabled={savingRun || !prep}
                  className="px-4 py-2 rounded-lg bg-blue-700 hover:bg-blue-600 text-white font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  title="Save research for later email generation"
                >
                  {savingRun ? 'Saving...' : '💾 Save Research'}
                </button>
                {canReSearch && (
                  <button
                    onClick={handleReSearch}
                    disabled={prepMutation.isPending}
                    className="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 font-medium transition-colors"
                    title="Clear cache and run fresh Deep Research (5-30 minutes)"
                  >
                    Re-search (Fresh)
                  </button>
                )}
                <button
                  onClick={handleRun}
                  disabled={!canGenerate}
                  className={`px-6 py-3 rounded-lg font-medium transition-colors ${
                    !canGenerate
                      ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                      : 'bg-emerald-600 hover:bg-emerald-500 text-white'
                  }`}
                >
                  Generate Email →
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Step 4: Generate Email (loading state with polling progress) */}
        {wizardStep === 4 && (
          <div className="p-6 rounded-xl border border-slate-700 bg-slate-800/50">
            <h2 className="text-lg font-medium text-slate-200 mb-6">Generating Email...</h2>
            
            {/* Show selected hook being used */}
            {prep && selectedHookLinks.length > 0 && (
              <div className="mb-4 p-3 rounded-lg border border-slate-600 bg-slate-800/50">
                <div className="text-xs text-slate-500 uppercase tracking-wide mb-1">Using Hook</div>
                <div className="text-sm text-slate-300">
                  {(() => {
                    const selectedHook = prep.treasure_hooks.find(h => getHookKey(h) === primaryHookLink)
                    if (selectedHook) {
                      return (
                        <div>
                          <span className="text-emerald-400">[{selectedHook.hook_type}]</span>{' '}
                          {selectedHook.trigger_excerpt?.slice(0, 100)}
                          {(selectedHook.trigger_excerpt?.length || 0) > 100 ? '...' : ''}
                        </div>
                      )
                    }
                    return <span className="text-slate-500">Hook not found</span>
                  })()}
                </div>
              </div>
            )}
            
            {/* Progress bar */}
            <div className="mb-4">
              <div className="flex justify-between text-sm text-slate-400 mb-2">
                <span>{emailProgress?.message || 'Starting...'}</span>
                <span>{emailProgress?.progress || 0}%</span>
              </div>
              <div className="w-full bg-slate-700 rounded-full h-2">
                <div 
                  className="bg-emerald-500 h-2 rounded-full transition-all duration-500"
                  style={{ width: `${emailProgress?.progress || 0}%` }}
                />
              </div>
            </div>
            
            <div className="flex items-center gap-3 mb-6">
              <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
              <span className="text-slate-300">
                {emailProgress?.message || getLatestTraceStatus(traceEvents) || 'Creating audience variants...'}
              </span>
            </div>
            
            <p className="text-sm text-slate-500 mb-4">
              This typically takes 2-4 minutes. The page will automatically update when complete.
            </p>
            
            {traceEvents.length > 0 && (
              <div className="p-4 rounded-lg border border-slate-700 bg-slate-900/30 max-h-48 overflow-y-auto">
                <div className="text-xs text-slate-500 uppercase tracking-wide mb-2">Activity Log</div>
                <div className="space-y-1">
                  {filterTraceEventsForLog(traceEvents).map((e, i) => {
                    const displayText = getEventDisplayText(e, researchStartTime)
                    return (
                      <div key={`${e.type}-${i}`} className="text-xs text-slate-400 flex items-start gap-2">
                        <span className="text-slate-600">•</span>
                        <span>{displayText}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Step 5: Review and Improve Email */}
        {wizardStep === 5 && result && (
          <div className="space-y-6">
            <div className="p-6 rounded-xl border border-slate-700 bg-slate-800/50">
              <h2 className="text-lg font-medium text-slate-200 mb-4">Review and Improve Email</h2>
              
              {/* Audience tabs */}
              <div className="flex flex-wrap gap-2 mb-6">
                {variants.map((v) => (
                  <button
                    key={v.audience}
                    onClick={() => setActiveAudience(v.audience)}
                    className={`px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
                      (activeVariant?.audience || variants[0]?.audience) === v.audience
                        ? 'bg-emerald-600/20 border-emerald-500 text-emerald-200'
                        : 'bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700/50'
                    }`}
                  >
                    {v.audience}
                  </button>
                ))}
              </div>

              {activeVariant && (
                <>
                  {/* Email display */}
                  <div className="rounded-lg border border-slate-700 bg-slate-900/30 overflow-hidden">
                    <div className="px-4 py-3 border-b border-slate-700">
                      <div className="text-xs text-slate-500 uppercase tracking-wide">Subject</div>
                      <div className="mt-1 text-lg font-medium text-slate-200">
                        {activeVariant.email_draft.subject_line}
                      </div>
                    </div>
                    <div className="px-4 py-3" data-testid="email-body">
                      <div className="text-xs text-slate-500 uppercase tracking-wide">Email Body</div>
                      <div className="mt-2 text-slate-300 whitespace-pre-wrap leading-relaxed">
                        {activeVariant.email_draft.email_body}
                      </div>
                    </div>
                  </div>

                  {/* Action buttons */}
                  <div className="mt-4 flex flex-wrap gap-3">
                    <button
                      onClick={handleCopy}
                      className={`px-4 py-2 rounded-lg font-medium transition-all ${
                        copied ? 'bg-emerald-600 text-white' : 'bg-slate-700 hover:bg-slate-600 text-slate-200'
                      }`}
                    >
                      {copied ? 'Copied!' : 'Copy'}
                    </button>
                    <button
                      onClick={handleExportCsv}
                      className="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 font-medium transition-colors"
                    >
                      Export CSV
                    </button>
                    <button
                      onClick={() => {
                        setWizardStep(4)
                        setTraceEvents([])
                        pipelineMutation.mutate()
                      }}
                      className="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 font-medium transition-colors"
                    >
                      Regenerate
                    </button>
                    <button
                      onClick={handleReset}
                      className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium transition-colors"
                    >
                      New Run
                    </button>
                  </div>

                  {/* Targeting Context - for sender's reference */}
                  <div className="mt-4 p-4 rounded-lg border border-slate-700 bg-slate-800/30">
                    <div className="text-sm font-medium text-slate-300 mb-2">
                      Targeting Context <span className="text-slate-500 font-normal">(for your reference - not in email)</span>
                    </div>
                    <div className="text-sm text-slate-400 space-y-2">
                      {(() => {
                        // Case 1: Selected hooks from research (treasure_hooks)
                        if (prep && selectedHookLinks.length > 0) {
                          const selectedHooks = prep.treasure_hooks.filter(h => selectedHookLinks.includes(getHookKey(h)))
                          if (selectedHooks.length > 0) {
                            return selectedHooks.map((hook, idx) => (
                              <div key={idx}>
                                <div>
                                  <span className="text-slate-500">Hook type:</span>{' '}
                                  <span className="text-emerald-400">[{hook.hook_type}]</span>
                                </div>
                                {hook.trigger_excerpt && (
                                  <div className="mt-1">
                                    <span className="text-slate-500">Trigger:</span>{' '}
                                    <span data-testid="selected-trigger-excerpt">{hook.trigger_excerpt}</span>
                                  </div>
                                )}
                                {hook.eligibility_excerpt && (
                                  <div className="mt-1">
                                    <span className="text-slate-500">Eligibility info:</span>{' '}
                                    {hook.eligibility_excerpt}
                                  </div>
                                )}
                              </div>
                            ))
                          }
                        }
                        
                        // Case 2: Selected cached hooks (state/district/conference)
                        if (selectedCachedHooks.length > 0) {
                          return selectedCachedHooks.map((cached, idx) => {
                            const hook = cached.hook as WebHook
                            return (
                              <div key={idx}>
                                <div>
                                  <span className="text-slate-500">Source:</span>{' '}
                                  <span className="text-emerald-400">[{cached.category}]</span>
                                  {cached.state_code && <span className="text-slate-500 ml-1">({cached.state_code})</span>}
                                </div>
                                {hook.trigger_excerpt && (
                                  <div className="mt-1">
                                    <span className="text-slate-500">Trigger:</span>{' '}
                                    <span data-testid="selected-trigger-excerpt">{hook.trigger_excerpt}</span>
                                  </div>
                                )}
                                {hook.eligibility_excerpt && (
                                  <div className="mt-1">
                                    <span className="text-slate-500">Eligibility info:</span>{' '}
                                    {hook.eligibility_excerpt}
                                  </div>
                                )}
                              </div>
                            )
                          })
                        }
                        
                        // Case 3: Variant has selected_hook (e.g., from saved run or backend selection)
                        if (activeVariant.selected_hook?.hook) {
                          const hook = activeVariant.selected_hook.hook
                          return (
                            <div>
                              <div>
                                <span className="text-slate-500">Hook type:</span>{' '}
                                <span className="text-emerald-400">[{hook.hook_type}]</span>
                              </div>
                              {hook.trigger_excerpt && (
                                <div className="mt-1">
                                    <span className="text-slate-500">Trigger:</span>{' '}
                                    <span data-testid="selected-trigger-excerpt">{hook.trigger_excerpt}</span>
                                  </div>
                                )}
                              {hook.eligibility_excerpt && (
                                <div className="mt-1">
                                  <span className="text-slate-500">Eligibility info:</span>{' '}
                                  {hook.eligibility_excerpt}
                                </div>
                              )}
                            </div>
                          )
                        }
                        
                        // Case 4: Purpose-only mode (no hook selected)
                        return (
                          <div className="text-slate-500">
                            N/A — Purpose-only mode
                            {purposePrompt && (
                              <div className="mt-2">
                                <span className="text-slate-500">Purpose:</span>{' '}
                                <span className="text-slate-400">{purposePrompt}</span>
                              </div>
                            )}
                          </div>
                        )
                      })()}
                    </div>
                  </div>

                  {/* Selected requirements display */}
                  {renderHook()}
                  
                  {/* Validation */}
                  {renderValidation()}
                  
                  {/* Review form */}
                  {renderReview()}
                </>
              )}
            </div>

            {/* Evidence panel (collapsible at bottom) */}
            {renderEvidence()}
          </div>
        )}
      </div>

      {/* Re-search confirmation dialog */}
      {showReSearchConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 max-w-md mx-4 shadow-xl">
            <h3 className="text-lg font-medium text-slate-200 mb-3">
              Run Fresh Research?
            </h3>
            <p className="text-sm text-slate-400 mb-6">
              {prep 
                ? 'This will discard your current research results and start fresh. The new research will take 5-30 minutes.'
                : cacheStatus?.status === 'completed'
                ? `You have cached results from ${cacheStatus.cache_age_days === 0 ? 'today' : `${cacheStatus.cache_age_days} days ago`}. Re-searching will delete them and start fresh (5-30 minutes).`
                : 'This will start a fresh research task, which takes 5-30 minutes.'}
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowReSearchConfirm(false)}
                className="px-4 py-2 rounded-lg text-slate-300 hover:bg-slate-700 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleReSearchConfirmed}
                className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-medium transition-colors"
              >
                Re-search (Fresh)
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


export type FlowMode = 'research' | 'email'

interface EmailGeneratorProps {
  mode?: FlowMode
}

export default function EmailGenerator({ mode: propMode }: EmailGeneratorProps) {
  const urlMode = (() => {
    try {
      return new URLSearchParams(window.location.search).get('mode')
    } catch {
      return null
    }
  })()

  if (urlMode === 'v1') {
    return <EmailGeneratorV1 />
  }
  
  // Use prop mode, or default to 'email' for backwards compatibility
  const flowMode: FlowMode = propMode || 'email'
  
  return <EmailGeneratorPipeline flowMode={flowMode} />
}
