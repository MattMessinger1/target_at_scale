/**
 * Research Coverage Matrix - Shows research completion status across states
 * 
 * Helps identify gaps in research coverage and create targeted batch jobs
 * to fill only the missing research efficiently.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Link } from 'react-router-dom'
import { 
  CheckCircle2, 
  XCircle, 
  AlertCircle,
  Loader2,
  ChevronLeft,
  Play,
  RefreshCw,
  Archive,
} from 'lucide-react'

// Products to show in dropdown
const PRODUCTS = [
  'WIDA MODEL Online',
  'CARE Coaching',
  'WIDA Professional Learning',
  'WebbAlign',
  'CALL',
  'The Discussion Project',
  'WIDA SIS',
]

export default function ResearchCoverage() {
  const [selectedProduct, setSelectedProduct] = useState(PRODUCTS[0])
  const [selectedStates, setSelectedStates] = useState<Set<string>>(new Set())
  const [widaOnly, setWidaOnly] = useState(true)
  const [showArchiveConfirm, setShowArchiveConfirm] = useState(false)
  const queryClient = useQueryClient()

  // Fetch coverage data
  const { data: coverage, isLoading, refetch } = useQuery({
    queryKey: ['research-coverage', selectedProduct, widaOnly],
    queryFn: () => api.research.getCoverage(selectedProduct, widaOnly),
  })

  // Archive mutation
  const archiveMutation = useMutation({
    mutationFn: () => api.research.archiveAllCache(),
    onSuccess: (data) => {
      // Refetch coverage to show clean slate
      queryClient.invalidateQueries({ queryKey: ['research-coverage'] })
      setShowArchiveConfirm(false)
      alert(`Archived ${data.deep_research_archived} state research + ${data.district_research_archived} district research entries`)
    },
    onError: (error) => {
      alert(`Failed to archive: ${error}`)
    }
  })

  // Toggle state selection
  const toggleState = (code: string) => {
    setSelectedStates(prev => {
      const next = new Set(prev)
      if (next.has(code)) {
        next.delete(code)
      } else {
        next.add(code)
      }
      return next
    })
  }

  // Select all states with gaps
  const selectAllWithGaps = () => {
    if (!coverage) return
    const gaps = coverage.states
      .filter(s => s.overall_status !== 'complete')
      .map(s => s.code)
    setSelectedStates(new Set(gaps))
  }

  // Select all missing (no research at all)
  const selectAllMissing = () => {
    if (!coverage) return
    const missing = coverage.states
      .filter(s => s.overall_status === 'missing')
      .map(s => s.code)
    setSelectedStates(new Set(missing))
  }

  // Clear selection
  const clearSelection = () => {
    setSelectedStates(new Set())
  }

  // Determine what research is needed for selected states
  const getNeededResearch = () => {
    if (!coverage || selectedStates.size === 0) return { needsDistrict: false, needsConference: false }
    
    let needsDistrict = false
    let needsConference = false
    
    for (const code of selectedStates) {
      const state = coverage.states.find(s => s.code === code)
      if (state) {
        if (!state.district_research) needsDistrict = true
        if (!state.conference_research) needsConference = true
      }
    }
    
    return { needsDistrict, needsConference }
  }

  // Create batch job URL with pre-filled states
  const createBatchUrl = () => {
    const states = Array.from(selectedStates)
    // Navigate to email generator with batch modal pre-filled
    // We'll use URL params to pass the state
    const params = new URLSearchParams()
    params.set('batch', 'true')
    params.set('product', selectedProduct)
    params.set('states', states.join(','))
    const { needsDistrict, needsConference } = getNeededResearch()
    if (needsDistrict) params.set('district', 'true')
    if (needsConference) params.set('conference', 'true')
    return `/email?${params.toString()}`
  }

  // Status indicator component
  const StatusCell = ({ status, ageLabel }: { status: 'completed' | 'missing' | null, ageLabel?: string }) => {
    if (!status || status === 'missing') {
      return (
        <div className="flex items-center justify-center gap-1">
          <XCircle className="w-4 h-4 text-red-400" />
          <span className="text-xs text-red-400">Missing</span>
        </div>
      )
    }
    
    return (
      <div className="flex items-center justify-center gap-1">
        <CheckCircle2 className="w-4 h-4 text-emerald-400" />
        {ageLabel && (
          <span className="text-xs text-slate-400">{ageLabel}</span>
        )}
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Link 
                to="/email" 
                className="flex items-center gap-2 text-slate-400 hover:text-slate-200 transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
                Back to Email Generator
              </Link>
            </div>
            <h1 className="text-xl font-semibold text-slate-100">Research Coverage Matrix</h1>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowArchiveConfirm(true)}
                className="flex items-center gap-2 px-3 py-1.5 text-sm text-amber-400 hover:text-amber-300 hover:bg-amber-900/30 rounded-lg transition-colors"
              >
                <Archive className="w-4 h-4" />
                Archive All Cache
              </button>
              <button
                onClick={() => refetch()}
                className="flex items-center gap-2 px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition-colors"
              >
                <RefreshCw className="w-4 h-4" />
                Refresh
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        {/* Controls */}
        <div className="flex flex-wrap items-center gap-4 mb-6">
          {/* Product selector */}
          <div className="flex items-center gap-2">
            <label className="text-sm text-slate-400">Product:</label>
            <select
              value={selectedProduct}
              onChange={(e) => {
                setSelectedProduct(e.target.value)
                setSelectedStates(new Set())
              }}
              className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
            >
              {PRODUCTS.map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          {/* WIDA filter */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={widaOnly}
              onChange={(e) => setWidaOnly(e.target.checked)}
              className="w-4 h-4 rounded border-slate-600 text-emerald-500 focus:ring-emerald-500/50"
            />
            <span className="text-sm text-slate-300">WIDA States Only</span>
          </label>

          {/* Selection actions */}
          <div className="flex items-center gap-2 ml-auto">
            <button
              onClick={selectAllWithGaps}
              className="px-3 py-1.5 text-sm text-amber-400 hover:bg-amber-900/30 rounded-lg transition-colors"
            >
              Select All Gaps
            </button>
            <button
              onClick={selectAllMissing}
              className="px-3 py-1.5 text-sm text-red-400 hover:bg-red-900/30 rounded-lg transition-colors"
            >
              Select Missing
            </button>
            {selectedStates.size > 0 && (
              <button
                onClick={clearSelection}
                className="px-3 py-1.5 text-sm text-slate-400 hover:bg-slate-800 rounded-lg transition-colors"
              >
                Clear ({selectedStates.size})
              </button>
            )}
          </div>
        </div>

        {/* Summary cards */}
        {coverage && (
          <div className="grid grid-cols-4 gap-4 mb-6">
            <div className="p-4 bg-slate-800/50 rounded-lg border border-slate-700">
              <div className="text-2xl font-bold text-slate-100">{coverage.summary.total_states}</div>
              <div className="text-sm text-slate-400">Total States</div>
            </div>
            <div className="p-4 bg-emerald-900/20 rounded-lg border border-emerald-700/50">
              <div className="text-2xl font-bold text-emerald-400">{coverage.summary.complete}</div>
              <div className="text-sm text-emerald-300/70">Complete (all 3)</div>
            </div>
            <div className="p-4 bg-amber-900/20 rounded-lg border border-amber-700/50">
              <div className="text-2xl font-bold text-amber-400">{coverage.summary.partial}</div>
              <div className="text-sm text-amber-300/70">Partial (some done)</div>
            </div>
            <div className="p-4 bg-red-900/20 rounded-lg border border-red-700/50">
              <div className="text-2xl font-bold text-red-400">{coverage.summary.missing}</div>
              <div className="text-sm text-red-300/70">Missing (none done)</div>
            </div>
          </div>
        )}

        {/* Action bar when states are selected */}
        {selectedStates.size > 0 && (
          <div className="mb-6 p-4 bg-indigo-900/30 rounded-lg border border-indigo-600/50">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium text-indigo-300">
                  {selectedStates.size} state{selectedStates.size > 1 ? 's' : ''} selected
                </div>
                <div className="text-xs text-indigo-300/70 mt-1">
                  {getNeededResearch().needsDistrict && 'District research needed. '}
                  {getNeededResearch().needsConference && 'Conference research needed.'}
                </div>
              </div>
              <Link
                to={createBatchUrl()}
                className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors"
              >
                <Play className="w-4 h-4" />
                Create Batch Job
              </Link>
            </div>
          </div>
        )}

        {/* Coverage grid */}
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-8 h-8 text-slate-400 animate-spin" />
            <span className="ml-3 text-slate-400">Loading coverage data...</span>
          </div>
        ) : coverage ? (
          <div className="bg-slate-800/30 rounded-lg border border-slate-700 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700 bg-slate-800/50">
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-8">
                    <input
                      type="checkbox"
                      checked={selectedStates.size === coverage.states.length && coverage.states.length > 0}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedStates(new Set(coverage.states.map(s => s.code)))
                        } else {
                          setSelectedStates(new Set())
                        }
                      }}
                      className="w-4 h-4 rounded border-slate-600 text-emerald-500 focus:ring-emerald-500/50"
                    />
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                    State
                  </th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-slate-400 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-emerald-400 uppercase tracking-wider">
                    State Research
                  </th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-amber-400 uppercase tracking-wider">
                    District Research
                  </th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-indigo-400 uppercase tracking-wider">
                    Conference Research
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/50">
                {coverage.states.map((state) => (
                  <tr 
                    key={state.code}
                    className={`hover:bg-slate-800/30 transition-colors ${
                      selectedStates.has(state.code) ? 'bg-indigo-900/20' : ''
                    }`}
                  >
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selectedStates.has(state.code)}
                        onChange={() => toggleState(state.code)}
                        className="w-4 h-4 rounded border-slate-600 text-indigo-500 focus:ring-indigo-500/50"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-slate-200">{state.name}</span>
                        <span className="text-xs text-slate-500">({state.code})</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-center">
                      {state.overall_status === 'complete' ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-emerald-900/50 text-emerald-400 rounded-full">
                          <CheckCircle2 className="w-3 h-3" />
                          Complete
                        </span>
                      ) : state.overall_status === 'partial' ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-amber-900/50 text-amber-400 rounded-full">
                          <AlertCircle className="w-3 h-3" />
                          Partial
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-red-900/50 text-red-400 rounded-full">
                          <XCircle className="w-3 h-3" />
                          Missing
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <StatusCell 
                        status={state.state_research ? 'completed' : 'missing'}
                        ageLabel={state.state_research ? `${state.state_research.age_days}d ago` : undefined}
                      />
                    </td>
                    <td className="px-4 py-3">
                      <StatusCell 
                        status={state.district_research ? 'completed' : 'missing'}
                        ageLabel={state.district_research ? `${state.district_research.age_days}d ago` : undefined}
                      />
                    </td>
                    <td className="px-4 py-3">
                      <StatusCell 
                        status={state.conference_research ? 'completed' : 'missing'}
                        ageLabel={state.conference_research ? `${state.conference_research.age_days}d ago` : undefined}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-20 text-slate-400">
            No coverage data available
          </div>
        )}

        {/* Legend */}
        <div className="mt-6 flex items-center justify-center gap-6 text-sm text-slate-400">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <span>Completed (cached for 30 days)</span>
          </div>
          <div className="flex items-center gap-2">
            <XCircle className="w-4 h-4 text-red-400" />
            <span>Missing or expired</span>
          </div>
        </div>
      </main>

      {/* Archive Confirmation Modal */}
      {showArchiveConfirm && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 max-w-md mx-4 shadow-2xl">
            <h3 className="text-lg font-semibold text-slate-100 mb-2">Archive All Research Cache?</h3>
            <p className="text-slate-400 text-sm mb-4">
              This will mark all existing research cache entries as archived. They won't appear in the coverage matrix 
              or be used for cache lookups. New research runs will create fresh entries.
            </p>
            <p className="text-amber-400 text-sm mb-6">
              The data is preserved and can be restored later if needed.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowArchiveConfirm(false)}
                className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 hover:bg-slate-700 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => archiveMutation.mutate()}
                disabled={archiveMutation.isPending}
                className="px-4 py-2 text-sm bg-amber-600 hover:bg-amber-500 text-white rounded-lg transition-colors disabled:opacity-50"
              >
                {archiveMutation.isPending ? 'Archiving...' : 'Archive All'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
