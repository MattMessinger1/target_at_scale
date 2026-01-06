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
import { useMutation } from '@tanstack/react-query'
import { 
  api, 
  FundingItem, 
  ComplianceItem, 
  ResearchResponse,
  GenerateEmailResponse 
} from '../lib/api'
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

export default function EmailGenerator() {
  // Step state
  const [currentStep, setCurrentStep] = useState<Step>('select')
  
  // Selection state - now arrays for multi-select
  const [selectedProducts, setSelectedProducts] = useState<string[]>([])
  const [selectedStates, setSelectedStates] = useState<SelectedState[]>([])
  const [selectedAudiences, setSelectedAudiences] = useState<string[]>([])
  
  // Research results
  const [researchResults, setResearchResults] = useState<ResearchResponse | null>(null)
  
  // Curation state
  const [selectedFunding, setSelectedFunding] = useState<FundingItem[]>([])
  const [selectedCompliance, setSelectedCompliance] = useState<ComplianceItem[]>([])
  
  // Generated email
  const [generatedEmail, setGeneratedEmail] = useState<GenerateEmailResponse | null>(null)
  const [copied, setCopied] = useState(false)

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
    }),
    onSuccess: (data) => {
      setGeneratedEmail(data)
      setCurrentStep('done')
    },
  })

  const canResearch = selectedProducts.length > 0 && selectedStates.length > 0 && selectedAudiences.length > 0
  const canGenerate = selectedFunding.length > 0 || selectedCompliance.length > 0

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
    setSelectedFunding([])
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

      {/* Main Content */}
      <div className="max-w-6xl mx-auto px-6 py-8">
        {/* Step 1: Selection */}
        {currentStep === 'select' && (
          <div className="space-y-6">
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
                  label="Researching funding opportunities (beyond Title I/III)" 
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
                  Searching for hidden gems: state-specific programs, foundation grants, new & upcoming opportunities...
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
              fundingItems={researchResults.funding_items}
              complianceItems={researchResults.compliance_items}
              selectedFunding={selectedFunding}
              selectedCompliance={selectedCompliance}
              onSelectFunding={setSelectedFunding}
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
