/**
 * EmailGenerator page - Main V1 email tool flow.
 * 
 * Flow:
 * 1. Select product, state, audience
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
import { StateSelector } from '../components/StateSelector'
import { AudienceSelector } from '../components/AudienceSelector'
import { CurationStep } from '../components/CurationStep'

type Step = 'select' | 'research' | 'curate' | 'generate' | 'done'

export default function EmailGenerator() {
  // Step state
  const [currentStep, setCurrentStep] = useState<Step>('select')
  
  // Selection state
  const [selectedProduct, setSelectedProduct] = useState('')
  const [selectedState, setSelectedState] = useState('')
  const [selectedStateFull, setSelectedStateFull] = useState('')
  const [selectedAudience, setSelectedAudience] = useState('')
  
  // Research results
  const [researchResults, setResearchResults] = useState<ResearchResponse | null>(null)
  
  // Curation state
  const [selectedFunding, setSelectedFunding] = useState<FundingItem[]>([])
  const [selectedCompliance, setSelectedCompliance] = useState<ComplianceItem[]>([])
  
  // Generated email
  const [generatedEmail, setGeneratedEmail] = useState<GenerateEmailResponse | null>(null)
  const [copied, setCopied] = useState(false)

  // Research mutation
  const researchMutation = useMutation({
    mutationFn: () => api.research.research({
      product: selectedProduct,
      state: selectedState,
      audience: selectedAudience,
    }),
    onSuccess: (data) => {
      setResearchResults(data)
      setCurrentStep('curate')
    },
  })

  // Generate mutation
  const generateMutation = useMutation({
    mutationFn: () => api.generate.email({
      product: selectedProduct,
      state: selectedState,
      state_full: selectedStateFull,
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
    }),
    onSuccess: (data) => {
      setGeneratedEmail(data)
      setCurrentStep('done')
    },
  })

  const canResearch = selectedProduct && selectedState && selectedAudience
  const canGenerate = selectedFunding.length > 0 || selectedCompliance.length > 0

  const handleStateSelect = (code: string, name: string) => {
    setSelectedState(code)
    setSelectedStateFull(name)
  }

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
    setSelectedProduct('')
    setSelectedState('')
    setSelectedStateFull('')
    setSelectedAudience('')
    setResearchResults(null)
    setSelectedFunding([])
    setSelectedCompliance([])
    setGeneratedEmail(null)
  }

  const handleExportCSV = () => {
    if (!generatedEmail) return
    
    const headers = ['Subject Line', 'Email Body', 'Product', 'State', 'Audience', 'Word Count']
    const row = [
      `"${generatedEmail.subject_line.replace(/"/g, '""')}"`,
      `"${generatedEmail.email_body.replace(/"/g, '""')}"`,
      generatedEmail.product,
      generatedEmail.state,
      generatedEmail.audience,
      generatedEmail.word_count.toString(),
    ]
    
    const csv = [headers.join(','), row.join(',')].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `email-${generatedEmail.product.toLowerCase().replace(/\s+/g, '-')}-${generatedEmail.state}.csv`
    a.click()
    URL.revokeObjectURL(url)
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
            
            {/* Progress Steps */}
            <div className="flex items-center gap-2">
              {['select', 'research', 'curate', 'generate', 'done'].map((step, i) => (
                <div
                  key={step}
                  className={`flex items-center ${i > 0 ? 'ml-2' : ''}`}
                >
                  {i > 0 && (
                    <div className={`w-8 h-0.5 mr-2 ${
                      ['select', 'research', 'curate', 'generate', 'done'].indexOf(currentStep) >= i
                        ? 'bg-emerald-500'
                        : 'bg-slate-700'
                    }`} />
                  )}
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium transition-colors ${
                      currentStep === step
                        ? 'bg-emerald-500 text-white'
                        : ['select', 'research', 'curate', 'generate', 'done'].indexOf(currentStep) > i
                          ? 'bg-emerald-600/50 text-emerald-300'
                          : 'bg-slate-700 text-slate-400'
                    }`}
                  >
                    {i + 1}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-6xl mx-auto px-6 py-8">
        {/* Step 1: Selection */}
        {currentStep === 'select' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-1">
              <ProductSelector
                selectedProduct={selectedProduct}
                onSelect={setSelectedProduct}
              />
            </div>
            
            <div className="lg:col-span-1">
              <StateSelector
                selectedState={selectedState}
                onSelect={handleStateSelect}
              />
            </div>
            
            <div className="lg:col-span-1">
              <AudienceSelector
                selectedAudience={selectedAudience}
                onSelect={setSelectedAudience}
              />
            </div>

            {/* Start Research Button */}
            <div className="lg:col-span-3 flex justify-center pt-6">
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

        {/* Step 2: Researching */}
        {currentStep === 'research' && (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-16 h-16 border-4 border-emerald-500 border-t-transparent rounded-full animate-spin mb-6" />
            <h2 className="text-xl font-semibold text-slate-200 mb-2">
              Researching...
            </h2>
            <p className="text-slate-400 text-center max-w-md">
              Finding funding opportunities and compliance requirements for{' '}
              <span className="text-emerald-400">{selectedProduct}</span> in{' '}
              <span className="text-emerald-400">{selectedStateFull}</span>
            </p>
            <div className="mt-4 text-sm text-slate-500">
              This may take 30-60 seconds...
            </div>
          </div>
        )}

        {/* Step 3: Curation */}
        {currentStep === 'curate' && researchResults && (
          <div className="space-y-6">
            {/* Selection Summary */}
            <div className="flex items-center gap-4 text-sm">
              <span className="px-3 py-1 bg-emerald-900/50 text-emerald-400 rounded-full">
                {selectedProduct}
              </span>
              <span className="px-3 py-1 bg-blue-900/50 text-blue-400 rounded-full">
                {selectedStateFull}
              </span>
              <span className="px-3 py-1 bg-purple-900/50 text-purple-400 rounded-full">
                {selectedAudience}
              </span>
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
                ← Back
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
            {/* Selection Summary */}
            <div className="flex items-center gap-4 text-sm">
              <span className="px-3 py-1 bg-emerald-900/50 text-emerald-400 rounded-full">
                {selectedProduct}
              </span>
              <span className="px-3 py-1 bg-blue-900/50 text-blue-400 rounded-full">
                {selectedStateFull}
              </span>
              <span className="px-3 py-1 bg-purple-900/50 text-purple-400 rounded-full">
                {selectedAudience}
              </span>
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
            <div className="flex justify-center gap-4 pt-4">
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
          </div>
        )}
      </div>
    </div>
  )
}
