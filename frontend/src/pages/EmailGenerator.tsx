/**
 * EmailGenerator page - Main V1 email tool flow.
 * 
 * Flow:
 * 1. Select products, states, audiences (multi-select)
 * 2. Research (with RAG context) → returns scored items
 * 3. Curate (select funding + compliance items)
 * 4. Generate email
 * 5. Copy / Export
 */
import { useState } from 'react'
import { useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
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
  PipelineRequest,
  PipelineRunStreamRequest,
  PipelineRunResponse,
  PipelineStreamEvent,
  HookDecision,
  EmailReviewRequest
} from '../lib/api'
import { toast } from '@/components/ui/use-toast'
import { ThemeToggle } from '@/components/ThemeToggle'
import { ProductSelector } from '../components/ProductSelector'
import { StateSelector, SelectedState } from '../components/StateSelector'
import { AudienceSelector } from '../components/AudienceSelector'
import { CurationStep } from '../components/CurationStep'

type Step = 'select' | 'research' | 'curate' | 'generate' | 'done'

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
  audiences: string[]
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

const RESEARCH_RUNS_STORAGE_KEY = 'wceps_emailgen_research_runs_v1'
const MAX_SAVED_RUNS = 3

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

function EmailGeneratorV1() {
  // Step state
  const [currentStep, setCurrentStep] = useState<Step>('select')
  
  // Selection state - now arrays for multi-select
  const [selectedProducts, setSelectedProducts] = useState<string[]>([])
  const [selectedStates, setSelectedStates] = useState<SelectedState[]>([])
  const [selectedAudiences, setSelectedAudiences] = useState<string[]>([])
  
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

  // Research mutation - for multi-select, we use the first selection as primary
  // and include others in the context
  const researchMutation = useMutation({
    mutationFn: () => api.research.research({
      product: selectedProducts[0], // Primary product
      state: selectedStates[0]?.code || '', // Primary state
      audience: selectedAudiences[0], // Primary audience
      // Additional selections are passed as context
      additional_products: selectedProducts.slice(1),
      additional_states: selectedStates.slice(1).map(s => s.code),
      additional_audiences: selectedAudiences.slice(1),
    }),
    onSuccess: (data) => {
      setResearchResults(data)
      // Create a saved snapshot so results are stable to revisit later
      const snapshot: ResearchRunSnapshot = {
        id: makeId(),
        createdAt: getNowIso(),
        criteria: {
          products: selectedProducts,
          states: selectedStates,
          audiences: selectedAudiences,
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
      product: selectedProducts.join(', '),
      state: selectedStates.map(s => s.code).join(', '),
      state_full: selectedStates.map(s => s.name).join(', '),
      audience: selectedAudiences.join(', '),
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
    setModelProduct(selectedProducts[0] || '')
    setModelStatesInput(selectedStates.map((s) => s.code).join(', '))
    setModelAudience(selectedAudiences[0] || '')

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

  const canResearch = selectedProducts.length > 0 && selectedStates.length > 0 && selectedAudiences.length > 0
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
    setSelectedProducts([])
    setSelectedStates([])
    setSelectedAudiences([])
    setResearchResults(null)
    setActiveRunId(null)
    setSelectedFunding([])
    setSelectedComplianceFunding([])
    setSelectedCompliance([])
    setGeneratedEmail(null)
  }

  const handleExportCSV = () => {
    if (!generatedEmail) return
    
    const headers = ['Subject Line', 'Email Body', 'Products', 'States', 'Audiences', 'Word Count']
    const row = [
      `"${generatedEmail.subject_line.replace(/"/g, '""')}"`,
      `"${generatedEmail.email_body.replace(/"/g, '""')}"`,
      `"${selectedProducts.join(', ')}"`,
      `"${selectedStates.map(s => s.name).join(', ')}"`,
      `"${selectedAudiences.join(', ')}"`,
      generatedEmail.word_count.toString(),
    ]
    
    const csv = [headers.join(','), row.join(',')].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `email-${selectedProducts[0]?.toLowerCase().replace(/\s+/g, '-') || 'wceps'}-${selectedStates[0]?.code || 'multi'}.csv`
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

  const resumeRun = (run: ResearchRunSnapshot) => {
    setSelectedProducts(run.criteria.products || [])
    setSelectedStates(run.criteria.states || [])
    setSelectedAudiences(run.criteria.audiences || [])
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

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="lg:col-span-1">
                <ProductSelector
                  selectedProducts={selectedProducts}
                  onSelect={setSelectedProducts}
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
                  selectedAudiences={selectedAudiences}
                  onSelect={setSelectedAudiences}
                />
              </div>
            </div>

            {/* Selection Summary */}
            {(selectedProducts.length > 0 || selectedStates.length > 0 || selectedAudiences.length > 0) && (
              <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
                <h3 className="text-sm font-medium text-slate-300 mb-3">Selection Summary</h3>
                <div className="flex flex-wrap gap-2">
                  {selectedProducts.map(p => (
                    <span key={p} className="px-2 py-1 bg-emerald-900/50 text-emerald-400 rounded text-sm">
                      {p}
                    </span>
                  ))}
                  {selectedStates.map(s => (
                    <span key={s.code} className="px-2 py-1 bg-blue-900/50 text-blue-400 rounded text-sm">
                      {s.name}
                    </span>
                  ))}
                  {selectedAudiences.map(a => (
                    <span key={a} className="px-2 py-1 bg-purple-900/50 text-purple-400 rounded text-sm">
                      {a}
                    </span>
                  ))}
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
              <span className="text-emerald-400">{selectedProducts.join(', ')}</span> in{' '}
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
                {selectedProducts.join(', ')}
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
                {selectedAudiences.join(', ')}
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
              Crafting a personalized email for {selectedAudiences.join(', ')}
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
                {selectedProducts.join(', ')}
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
                title="Click to edit audiences"
              >
                {selectedAudiences.join(', ')}
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

type ReviewSectionKey = 'subject_line' | 'product_relevance' | 'tone' | 'flow' | 'cta'

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

function EmailGeneratorPipeline() {
  const [wizardStep, setWizardStep] = useState<WizardStep>(1)
  const [selectedProducts, setSelectedProducts] = useState<string[]>([])
  const [selectedStates, setSelectedStates] = useState<SelectedState[]>([])
  const [selectedAudiences, setSelectedAudiences] = useState<string[]>([])

  const [districtName, setDistrictName] = useState('')
  const [districtUrl, setDistrictUrl] = useState('')

  // Cache status for the current state+product selection
  const [cacheStatus, setCacheStatus] = useState<CacheStatus | null>(null)
  const [showReSearchConfirm, setShowReSearchConfirm] = useState(false)

  const [result, setResult] = useState<PipelineRunResponse | null>(null)
  const [activeAudience, setActiveAudience] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [traceEvents, setTraceEvents] = useState<PipelineStreamEvent[]>([])
  const [researchStartTime, setResearchStartTime] = useState<Date | null>(null)
  const [prep, setPrep] = useState<{ evidence_pack: EvidencePack; treasure_hooks: WebHook[]; filtered_requirements: FilteredRequirement[]; warnings: string[] } | null>(null)
  const [blockedFilteredRequirements, setBlockedFilteredRequirements] = useState<FilteredRequirement[]>([])
  const [selectedHookLinks, setSelectedHookLinks] = useState<string[]>([])
  const [primaryHookLink, setPrimaryHookLink] = useState<string | null>(null)
  const [hookReasonTags, setHookReasonTags] = useState<Record<string, string[]>>({})
  const [hookReasonNotes, setHookReasonNotes] = useState<Record<string, string>>({})
  const [reviewDrafts, setReviewDrafts] = useState<Record<string, ReviewDraft>>({})
  const [showFilteredSection, setShowFilteredSection] = useState(false)

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
    const product = selectedProducts[0]
    
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
  }, [selectedStates, selectedProducts, wizardStep])

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

  const prepMutation = useMutation<
    { evidence_pack: EvidencePack; treasure_hooks: WebHook[]; filtered_requirements: FilteredRequirement[]; warnings: string[] },
    Error & { filteredRequirements?: FilteredRequirement[] },
    void
  >({
    mutationFn: () => {
      const req: PipelineRequest = {
        product: selectedProducts[0] || '',
        state: selectedStates[0]?.code || '',
        state_full: selectedStates[0]?.name || undefined,
        audiences: selectedAudiences.length ? selectedAudiences : undefined,
        district_name: districtName.trim() || undefined,
        district_url: districtUrl.trim() || undefined,
      }
      return api.generate.pipelinePrepStream(req, (evt) => {
        setTraceEvents((prev) => [...prev, evt])
      })
    },
    onSuccess: (data) => {
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

  const pipelineMutation = useMutation<PipelineRunResponse, Error, void>({
    mutationFn: () => {
      const req: PipelineRunStreamRequest = {
        product: selectedProducts[0] || '',
        state: selectedStates[0]?.code || '',
        state_full: selectedStates[0]?.name || undefined,
        audiences: selectedAudiences.length ? selectedAudiences : undefined,
        district_name: districtName.trim() || undefined,
        district_url: districtUrl.trim() || undefined,
      }
      if (prep) {
        req.evidence_pack = prep.evidence_pack
        req.treasure_hooks = prep.treasure_hooks
      }
      if (selectedHookLinks.length > 0) {
        req.selected_hook_links = selectedHookLinks
        req.primary_hook_link = (primaryHookLink || selectedHookLinks[0] || '').trim() || undefined
      }
      return api.generate.pipelineRunStream(req, (evt) => {
        setTraceEvents((prev) => [...prev, evt])
      })
    },
    onSuccess: (data) => {
      setReviewDrafts({})
      setResult(data)
      const first = data.variants?.[0]?.audience
      setActiveAudience(first || null)
      setWizardStep(5) // Go to Review step

      // Training loop: log the explicit human-selected requirements (no implicit rejections).
      try {
        if (prep && selectedHookLinks.length > 0) {
          const map = new Map((prep.treasure_hooks || []).map((h) => [h.link, h]))
          const primary = (primaryHookLink || selectedHookLinks[0] || '').trim()
          const decisions: HookDecision[] = []
          for (const link of selectedHookLinks) {
            const hook = map.get(link)
            if (!hook) continue
            const rank = selectedHookLinks.length === 1 ? 1 : link === primary ? 1 : 2
            decisions.push({
              decision: 'selected',
              rank,
              reason_tags: hookReasonTags[link] || [],
              reason_note: (hookReasonNotes[link] || '').trim() || null,
              hook,
            })
          }

          if (decisions.length > 0) {
            api.feedback
              .submitHookFeedback({
                run_id: data.run_id,
                product: selectedProducts[0] || data.request.product,
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
      toast({
        title: 'Email generation failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      })
      setWizardStep(3) // Go back to Select step
    },
  })

  const canPrep = selectedProducts.length > 0 && selectedStates.length > 0
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
        title: 'Review saved',
        description: 'Saved for training/export.',
      })
    },
    onError: (error) => {
      toast({
        title: 'Review save failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })

  const handlePrep = () => {
    if (!canPrep) return
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
    setWizardStep(2) // Go to Research step
    prepMutation.mutate()
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
      await api.generate.clearDeepResearchCache(selectedStates[0]?.code || '', selectedProducts[0] || '')
    } catch (e) {
      console.warn('Failed to clear cache:', e)
      // Continue anyway - cache clear is best-effort
    }
    
    prepMutation.mutate()
  }

  // Show confirmation before re-searching if there are completed results
  const handleReSearch = () => {
    if (!canPrep) return
    if (cacheStatus?.status === 'completed' || prep) {
      setShowReSearchConfirm(true)
    } else {
      handleReSearchConfirmed()
    }
  }

  // Cancel an in-progress research task
  const handleCancelResearch = async () => {
    const state = selectedStates[0]?.code
    const product = selectedProducts[0]
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

  const handleRun = () => {
    if (!canGenerate) return
    setTraceEvents([])
    setWizardStep(4) // Go to Generate step
    pipelineMutation.mutate()
  }

  const handleReset = () => {
    setWizardStep(1)
    setResult(null)
    setPrep(null)
    setBlockedFilteredRequirements([])
    setSelectedHookLinks([])
    setPrimaryHookLink(null)
    setHookReasonTags({})
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
      `"${selectedProducts[0] || ''}"`,
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
    return (
      <div className="mt-4 p-4 rounded-lg border border-slate-700 bg-slate-800/50">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm font-medium text-slate-200">Validation</div>
          <div className={`text-xs px-2 py-1 rounded ${
            v.passed ? 'bg-emerald-900/50 text-emerald-300 border border-emerald-700/50' : 'bg-amber-900/40 text-amber-300 border border-amber-700/50'
          }`}>
            {v.passed ? 'PASS' : 'FAIL'}
          </div>
        </div>
        <div className="mt-2 text-xs text-slate-400">
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
    )
  }

  const renderReview = () => {
    if (!result || !activeVariant) return null
    const aud = activeVariant.audience
    const draft = reviewDrafts[aud]
    if (!draft) return null

    const sections: Array<{ key: ReviewSectionKey; label: string }> = [
      { key: 'subject_line', label: 'Subject line' },
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
          <div className="text-sm font-medium text-slate-200">Review (training loop)</div>
          {reviewMutation.isPending && <div className="text-xs text-slate-400">Saving…</div>}
        </div>

        <div className="mt-3 space-y-3">
          <div>
            <label className="block text-xs text-slate-500 uppercase tracking-wide">Edited subject</label>
            <input
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
          <div className="text-sm text-slate-400 mt-1">1 = Poor, 5 = Excellent. All fields are optional.</div>
          <div className="mt-3 grid grid-cols-1 lg:grid-cols-2 gap-4">
            {sections.map(({ key, label }) => (
              <div key={key} className="p-3 rounded border border-slate-700 bg-slate-900/20">
                <div className="text-base font-medium text-slate-200">{label}</div>
                <div className="mt-2 flex items-center gap-3">
                  <label className="text-xs text-slate-500">Score</label>
                  <input
                    type="number"
                    min={1}
                    max={5}
                    value={draft.rubric[key]?.score ?? ''}
                    onChange={(e) => {
                      const raw = e.target.value
                      const score = raw === '' ? null : Number(raw)
                      setReviewDrafts((prev) => ({
                        ...prev,
                        [aud]: {
                          ...draft,
                          rubric: {
                            ...draft.rubric,
                            [key]: { ...draft.rubric[key], score: Number.isFinite(score) ? score : null },
                          },
                        },
                      }))
                    }}
                    className="w-20 px-2 py-1 bg-slate-800 border border-slate-700 rounded text-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
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
                  placeholder="Comments"
                  className="mt-2 w-full min-h-[72px] px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>
            ))}
          </div>
        </div>

        <button
          onClick={() => {
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

            const payload: EmailReviewRequest = {
              run_id: result.run_id,
              product: result.request.product,
              state_code: result.request.state,
              audience: aud,
              district_name: result.request.district_name || null,
              district_url: result.request.district_url || null,
              primary_hook_link: activeVariant.selected_hook?.hook?.link || null,
              secondary_hook_link: activeVariant.secondary_hook?.hook?.link || null,
              original_subject_line: activeVariant.email_draft.subject_line,
              original_email_body: activeVariant.email_draft.email_body,
              edited_subject_line: draft.edited_subject_line,
              edited_email_body: draft.edited_email_body,
              rubric: {
                subject_line: getScore('subject_line'),
                product_relevance: getScore('product_relevance'),
                tone: getScore('tone'),
                flow: getScore('flow'),
                cta: getScore('cta'),
              },
            }

            reviewMutation.mutate(payload)
          }}
          disabled={!canSave}
          className={`mt-4 w-full px-6 py-3 rounded-lg font-medium transition-colors ${
            !canSave ? 'bg-slate-700 text-slate-400 cursor-not-allowed' : 'bg-emerald-600 hover:bg-emerald-500 text-white'
          }`}
        >
          Save review
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
                    <div className="text-xs text-slate-500">{h.confidence}</div>
                  </div>
                  <a className="mt-1 block text-sm text-emerald-300 hover:text-emerald-200 underline break-all" href={h.link} target="_blank" rel="noreferrer">
                    {h.link}
                  </a>
                  <div className="mt-2 text-sm text-slate-300">“{h.quote}”</div>
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
    const h = activeVariant.selected_hook?.hook
    const sh = activeVariant.secondary_hook?.hook
    if (!h) return null
    return (
      <div className="mt-4 p-4 rounded-lg border border-slate-700 bg-slate-800/50">
        <div className="flex items-center justify-between">
          <div className="text-sm font-medium text-slate-200">Selected Requirements</div>
          <div className="text-xs text-slate-500">{h.hook_type} · {h.confidence}</div>
        </div>
        <div className="mt-2 text-xs text-slate-500 uppercase tracking-wide">Primary Requirement (opener)</div>
        <div className="mt-2 text-sm text-slate-300">“{h.quote}”</div>
        <a className="mt-2 block text-sm text-emerald-300 hover:text-emerald-200 underline break-all" href={h.link} target="_blank" rel="noreferrer">
          {h.link}
        </a>
        <div className="mt-3 text-xs text-slate-500 uppercase tracking-wide">Trigger excerpt</div>
        <div className="mt-1 text-sm text-slate-300">{h.trigger_excerpt}</div>
        {h.eligibility_excerpt && (
          <>
            <div className="mt-3 text-xs text-slate-500 uppercase tracking-wide">Eligibility excerpt</div>
            <div className="mt-1 text-sm text-slate-300">{h.eligibility_excerpt}</div>
          </>
        )}

        {sh && (
          <>
            <div className="mt-4 pt-4 border-t border-slate-700">
              <div className="flex items-center justify-between">
                <div className="text-xs text-slate-500 uppercase tracking-wide">Secondary Requirement (supporting)</div>
                <div className="text-xs text-slate-500">{sh.hook_type} · {sh.confidence}</div>
              </div>
              <div className="mt-2 text-sm text-slate-300">“{sh.quote}”</div>
              <a className="mt-2 block text-sm text-emerald-300 hover:text-emerald-200 underline break-all" href={sh.link} target="_blank" rel="noreferrer">
                {sh.link}
              </a>
              <div className="mt-3 text-xs text-slate-500 uppercase tracking-wide">Trigger excerpt</div>
              <div className="mt-1 text-sm text-slate-300">{sh.trigger_excerpt}</div>
              {sh.eligibility_excerpt && (
                <>
                  <div className="mt-3 text-xs text-slate-500 uppercase tracking-wide">Eligibility excerpt</div>
                  <div className="mt-1 text-sm text-slate-300">{sh.eligibility_excerpt}</div>
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
    
    // Truncate long quotes
    const MAX_QUOTE_LENGTH = 250
    const quote = h.quote || ''
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
            </div>
            
            {/* Quote - truncated */}
            <div className="mt-3 text-sm text-slate-200 italic">"{truncatedQuote}"</div>
            
            {/* Divider */}
            <div className="my-3 border-t border-slate-700/50" />
            
            {/* Details grid */}
            <div className="space-y-2">
              <div>
                <div className="text-xs text-slate-500 uppercase tracking-wide font-medium">Trigger</div>
                <div className="mt-0.5 text-sm text-slate-300">{h.trigger_excerpt}</div>
              </div>
              {h.eligibility_excerpt && (
                <div>
                  <div className="text-xs text-slate-500 uppercase tracking-wide font-medium">Eligibility</div>
                  <div className="mt-0.5 text-sm text-slate-300">{h.eligibility_excerpt}</div>
                </div>
              )}
              <div>
                <div className="text-xs text-slate-500 uppercase tracking-wide font-medium">Why Relevant</div>
                <div className="mt-0.5 text-sm text-slate-400">{h.why_relevant}</div>
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

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      <div className="max-w-5xl mx-auto px-4 py-10">
        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl sm:text-3xl font-semibold text-slate-100">
              Email Generator
            </h1>
            <div className="mt-1 text-sm text-slate-400">
              Find funding/compliance requirements and generate targeted emails.
            </div>
          </div>
          <ThemeToggle />
        </div>

        {renderProgressBar()}

        {/* Step 1: Choose Product & Audience */}
        {wizardStep === 1 && (
          <div className="p-6 rounded-xl border border-slate-700 bg-slate-800/50">
            <h2 className="text-lg font-medium text-slate-200 mb-6">Choose Product & Audience</h2>
            <div className="space-y-6">
              <ProductSelector selectedProducts={selectedProducts} onSelect={setSelectedProducts} />
              <StateSelector selectedStates={selectedStates} onSelect={setSelectedStates} />

              <div className="space-y-2">
                <label className="block text-sm font-medium text-slate-300">District (optional)</label>
                <input
                  value={districtName}
                  onChange={(e) => setDistrictName(e.target.value)}
                  placeholder="District name (optional)"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-600 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
                <input
                  value={districtUrl}
                  onChange={(e) => setDistrictUrl(e.target.value)}
                  placeholder="District URL (optional)"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-600 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>

              <div>
                <AudienceSelector selectedAudiences={selectedAudiences} onSelect={setSelectedAudiences} />
                <div className="mt-2 text-xs text-slate-500">
                  Leave audiences empty to use the default 3 (Title III, ELL, Curriculum).
                </div>
              </div>

              {/* Cache status notification */}
              {cacheStatus && cacheStatus.status !== 'not_found' && cacheStatus.status !== 'loading' && (
                <div className={`p-4 rounded-lg border ${
                  cacheStatus.status === 'completed' 
                    ? 'border-emerald-700/50 bg-emerald-900/20'
                    : cacheStatus.status === 'in_progress'
                    ? 'border-amber-700/50 bg-amber-900/20'
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
                          Click "Find Requirements" to view them instantly, or "Re-search" to run fresh research (5-30 min).
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
                          Started {cacheStatus.elapsed_minutes} minutes ago. Click "Find Requirements" to resume viewing progress.
                        </div>
                        <div className="mt-2 flex gap-2">
                          <button
                            onClick={handleCancelResearch}
                            className="text-xs px-3 py-1 rounded bg-amber-800/50 text-amber-300 hover:bg-amber-800 transition-colors"
                          >
                            Cancel Research
                          </button>
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
                          {cacheStatus.error || 'Unknown error'}. Click "Find Requirements" to try again.
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="pt-4 flex justify-end gap-3">
                {cacheStatus?.status === 'completed' && (
                  <button
                    onClick={handleReSearch}
                    disabled={!canPrep}
                    className="px-4 py-2 rounded-lg font-medium text-slate-300 border border-slate-600 hover:bg-slate-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Re-search (Fresh)
                  </button>
                )}
                <button
                  onClick={handlePrep}
                  disabled={!canPrep}
                  className={`px-6 py-3 rounded-lg font-medium transition-colors ${
                    !canPrep
                      ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                      : 'bg-emerald-600 hover:bg-emerald-500 text-white'
                  }`}
                >
                  {cacheStatus?.status === 'completed' ? 'View Cached Results →' : 
                   cacheStatus?.status === 'in_progress' ? 'View Progress →' :
                   'Find Requirements →'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Step 2: Research (loading state) */}
        {wizardStep === 2 && (
          <div className="p-6 rounded-xl border border-slate-700 bg-slate-800/50">
            <h2 className="text-lg font-medium text-slate-200 mb-4">Researching Funding & Compliance Requirements...</h2>
            
            {/* Deep Research explanation */}
            <div className="mb-6 p-4 rounded-lg border border-emerald-700/50 bg-emerald-900/20">
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-full bg-emerald-600/30 flex items-center justify-center flex-shrink-0">
                  <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </div>
                <div>
                  <div className="text-sm font-medium text-emerald-300">
                    Deep Research is analyzing funding and compliance requirements for {selectedStates[0]?.name || 'your state'}.
                  </div>
                  <div className="mt-2 text-sm text-emerald-200/80">
                    This thorough research typically takes <span className="font-medium">5-30 minutes</span>. Feel free to leave this page and come back - we'll save your results.
                  </div>
                  <div className="mt-2 text-sm text-emerald-200/70">
                    Your results will be saved for <span className="font-medium">14 days</span>. Future searches for {selectedStates[0]?.name || 'this state'} + {selectedProducts[0] || 'this product'} will return instantly until the cache expires.
                  </div>
                </div>
              </div>
            </div>
            
            <div className="flex items-center gap-3 mb-6">
              <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
              <span className="text-slate-300">
                {getLatestTraceStatus(traceEvents) || 'Running Deep Research...'}
              </span>
            </div>
            
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
                  const isSelected = selectedHookLinks.includes(h.link)
                  const isPrimary = primaryHookLink === h.link
                  return (
                    <div key={h.link}>
                      {renderRequirementCard(h, {
                        isSelected,
                        isPrimary,
                        onToggle: () => toggleHook(h.link),
                        onSetPrimary: () => setPrimaryHookLink(h.link),
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
                                key={`${h.link}-${opt.tag}`}
                                className={`flex items-center gap-2 px-2 py-1 rounded border text-xs cursor-pointer ${
                                  (hookReasonTags[h.link] || []).includes(opt.tag)
                                    ? 'border-emerald-600 bg-emerald-900/10 text-emerald-200'
                                    : 'border-slate-700 bg-slate-900/10 text-slate-300 hover:bg-slate-900/20'
                                }`}
                              >
                                <input
                                  type="checkbox"
                                  checked={(hookReasonTags[h.link] || []).includes(opt.tag)}
                                  onChange={() => toggleReasonTag(h.link, opt.tag)}
                                  className="sr-only"
                                />
                                <span>{opt.label}</span>
                              </label>
                            ))}
                          </div>
                          <textarea
                            value={hookReasonNotes[h.link] || ''}
                            onChange={(e) => setHookReasonNotes((prev) => ({ ...prev, [h.link]: e.target.value }))}
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
                    {allFilteredRequirements.map((fr, idx) => (
                      <div key={`filtered-${idx}`}>
                        {renderRequirementCard(fr.hook, {
                          isFiltered: true,
                          filterReason: fr.reason,
                          filterReasonLabel: fr.reason_label,
                          isSelected: selectedHookLinks.includes(fr.hook.link),
                          isPrimary: primaryHookLink === fr.hook.link,
                          onToggle: () => toggleHook(fr.hook.link),
                          onSetPrimary: () => setPrimaryHookLink(fr.hook.link),
                        })}
                      </div>
                    ))}
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
                  onClick={handleReSearch}
                  disabled={prepMutation.isPending}
                  className="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 font-medium transition-colors"
                  title="Clear cache and run fresh Deep Research (5-30 minutes)"
                >
                  Re-search (Fresh)
                </button>
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

        {/* Step 4: Generate Email (loading state) */}
        {wizardStep === 4 && (
          <div className="p-6 rounded-xl border border-slate-700 bg-slate-800/50">
            <h2 className="text-lg font-medium text-slate-200 mb-6">Generating Email...</h2>
            <div className="flex items-center gap-3 mb-6">
              <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
              <span className="text-slate-300">
                {getLatestTraceStatus(traceEvents) || 'Creating audience variants...'}
              </span>
            </div>
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
                    <div className="px-4 py-3">
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
                  {prep && selectedHookLinks.length > 0 && (
                    <div className="mt-4 p-4 rounded-lg border border-slate-700 bg-slate-800/30">
                      <div className="text-sm font-medium text-slate-300 mb-2">
                        Targeting Context <span className="text-slate-500 font-normal">(for your reference - not in email)</span>
                      </div>
                      <div className="text-sm text-slate-400 space-y-2">
                        {prep.treasure_hooks
                          .filter(h => selectedHookLinks.includes(h.link))
                          .map((hook, idx) => (
                            <div key={idx}>
                              {hook.eligibility_excerpt && (
                                <div>
                                  <span className="text-slate-500">Eligibility info:</span>{' '}
                                  {hook.eligibility_excerpt}
                                </div>
                              )}
                            </div>
                          ))
                        }
                      </div>
                    </div>
                  )}

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


export default function EmailGenerator() {
  const mode = (() => {
    try {
      return new URLSearchParams(window.location.search).get('mode')
    } catch {
      return null
    }
  })()

  if (mode === 'v1') {
    return <EmailGeneratorV1 />
  }
  return <EmailGeneratorPipeline />
}
