import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, SavedRunSummary, SavedRunFull, WebHook, FilteredDistrictHook, ConferenceOpportunity } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/use-toast'
import { ThemeToggle } from '@/components/ThemeToggle'
import { ChevronDown, ChevronUp, ExternalLink, FolderOpen, Search } from 'lucide-react'

const formatDateTime = (dateStr: string) => {
  const date = new Date(dateStr)
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

const hostFromUrl = (url: string) => {
  try {
    const parsed = new URL(url)
    return parsed.hostname.replace('www.', '')
  } catch {
    return url
  }
}

const getStateHooks = (full: SavedRunFull): WebHook[] => {
  const response = full.pipeline_response as unknown as { hooks?: WebHook[]; treasure_hooks?: WebHook[] }
  return response.hooks || response.treasure_hooks || []
}

const getDistrictResearch = (full: SavedRunFull) => {
  const response = full.pipeline_response as unknown as { district_research?: { passed_hooks?: WebHook[]; filtered_hooks?: FilteredDistrictHook[]; districts_surveyed?: string[]; research_summary?: string | null } | null }
  return response.district_research || null
}

const getConferenceOpportunities = (full: SavedRunFull): ConferenceOpportunity[] => {
  const response = full.pipeline_response as unknown as { conferences?: ConferenceOpportunity[] }
  return response.conferences || []
}

export default function ResearchLibrary() {
  const { toast } = useToast()
  const [productFilter, setProductFilter] = useState<string>('all')
  const [stateFilter, setStateFilter] = useState<string>('all')
  const [expandedRuns, setExpandedRuns] = useState<Record<number, boolean>>({})
  const [runDetails, setRunDetails] = useState<Record<number, SavedRunFull>>({})
  const [loadingRun, setLoadingRun] = useState<Record<number, boolean>>({})
  const [showFilteredDistrict, setShowFilteredDistrict] = useState(false)
  const [showConferences, setShowConferences] = useState(true)

  const { data: runs, isLoading, error } = useQuery({
    queryKey: ['research-library-runs'],
    queryFn: () => api.savedRuns.listFiltered({ run_type: 'research', limit: 200, offset: 0 }),
  })

  const products = useMemo(() => {
    const list = (runs || []).map(r => r.product).filter(Boolean)
    return Array.from(new Set(list)).sort()
  }, [runs])

  const filteredRuns = useMemo(() => {
    if (!runs) return []
    return runs.filter((run) => {
      if (productFilter !== 'all' && run.product !== productFilter) return false
      if (stateFilter !== 'all' && run.state_code !== stateFilter) return false
      return true
    })
  }, [runs, productFilter, stateFilter])

  const states = useMemo(() => {
    const list = filteredRuns.map(r => r.state_code).filter(Boolean)
    return Array.from(new Set(list)).sort()
  }, [filteredRuns])

  const groupedByState = useMemo(() => {
    const grouped = new Map<string, SavedRunSummary[]>()
    for (const run of filteredRuns) {
      const key = run.state_code
      if (!grouped.has(key)) grouped.set(key, [])
      grouped.get(key)?.push(run)
    }
    return Array.from(grouped.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [filteredRuns])

  const toggleRun = async (runId: number) => {
    setExpandedRuns(prev => ({ ...prev, [runId]: !prev[runId] }))
    if (runDetails[runId] || loadingRun[runId]) return
    setLoadingRun(prev => ({ ...prev, [runId]: true }))
    try {
      const full = await api.savedRuns.get(runId)
      setRunDetails(prev => ({ ...prev, [runId]: full }))
    } catch (err) {
      toast({
        title: 'Error loading research run',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    } finally {
      setLoadingRun(prev => ({ ...prev, [runId]: false }))
    }
  }

  const renderHookCard = (hook: WebHook, idx: number) => (
    <div key={`${hook.link}-${idx}`} className="rounded-lg border border-slate-700/70 bg-slate-900/40 p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <Badge variant="outline" className="border-slate-600 text-slate-300">{hook.hook_type}</Badge>
        <Badge variant="outline" className="border-emerald-700/60 text-emerald-300">{hook.confidence}</Badge>
        {hook.source_level && (
          <Badge variant="outline" className="border-amber-700/60 text-amber-300">{hook.source_level}</Badge>
        )}
        {hook.deadline_warning && (
          <span className="text-amber-300">{hook.deadline_warning}</span>
        )}
        {hook.timing_summary && (
          <span className="text-slate-500">{hook.timing_summary}</span>
        )}
        {typeof hook.propensity_score === 'number' && (
          <span className="text-emerald-300">Propensity: {hook.propensity_score}</span>
        )}
        {typeof hook.outcome_score === 'number' && (
          <span className="text-sky-300">Outcome: {hook.outcome_score}</span>
        )}
      </div>
      <div className="mt-2 text-sm text-slate-100">{hook.quote || hook.trigger_excerpt}</div>
      {hook.why_relevant && (
        <div className="mt-2 text-xs text-slate-400">Why relevant: {hook.why_relevant}</div>
      )}
      {hook.propensity_reasons && hook.propensity_reasons.length > 0 && (
        <div className="mt-1 text-xs text-slate-500">
          Signals: {hook.propensity_reasons.join(', ')}
        </div>
      )}
      {hook.outcome_summary && (
        <div className="mt-1 text-xs text-sky-300/80">{hook.outcome_summary}</div>
      )}
      <div className="mt-2 flex items-center gap-2 text-xs">
        <a
          href={hook.link}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-blue-400 hover:text-blue-300"
        >
          {hostFromUrl(hook.link)}
          <ExternalLink className="w-3 h-3" />
        </a>
        {hook.district_name && (
          <span className="text-amber-300">District: {hook.district_name}</span>
        )}
      </div>
    </div>
  )

  const renderDistrictSection = (full: SavedRunFull) => {
    const district = getDistrictResearch(full)
    if (!district) return null

    const passedHooks = district.passed_hooks || []
    const filteredHooks = district.filtered_hooks || []

    const byDistrict = passedHooks.reduce<Record<string, WebHook[]>>((acc, hook) => {
      const key = hook.district_name || 'Unknown district'
      if (!acc[key]) acc[key] = []
      acc[key].push(hook)
      return acc
    }, {})

    return (
      <div className="mt-5">
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-semibold text-slate-200">District Research</h4>
          <div className="text-xs text-slate-500">
            Surveyed: {district.districts_surveyed?.length || 0} districts
          </div>
        </div>
        {district.research_summary && (
          <div className="mt-2 text-xs text-slate-400">{district.research_summary}</div>
        )}

        <div className="mt-3 space-y-4">
          {Object.entries(byDistrict).map(([districtName, hooks]) => (
            <div key={districtName} className="rounded-lg border border-slate-700/60 bg-slate-900/20 p-3">
              <div className="text-xs uppercase tracking-wide text-amber-300">{districtName}</div>
              <div className="mt-2 grid gap-3">
                {hooks.map(renderHookCard)}
              </div>
            </div>
          ))}
          {passedHooks.length === 0 && (
            <div className="text-xs text-slate-500">No district-level hooks passed.</div>
          )}
        </div>

        {showFilteredDistrict && filteredHooks.length > 0 && (
          <div className="mt-4">
            <div className="text-xs uppercase tracking-wide text-slate-500">Filtered District Items</div>
            <div className="mt-2 grid gap-3">
              {filteredHooks.map((item, idx) => (
                <div key={`${item.hook.link}-${idx}`} className="rounded-lg border border-slate-800 bg-slate-900/30 p-3">
                  <div className="text-xs text-slate-500">Filtered: {item.filter_reason}</div>
                  {item.filter_detail && (
                    <div className="text-xs text-slate-600">{item.filter_detail}</div>
                  )}
                  <div className="mt-2 text-sm text-slate-300">{item.hook.quote}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }

  const renderConferences = (full: SavedRunFull) => {
    if (!showConferences) return null
    const conferences = getConferenceOpportunities(full)
    if (conferences.length === 0) return null

    return (
      <div className="mt-5">
        <h4 className="text-sm font-semibold text-slate-200">Conference Opportunities</h4>
        <div className="mt-3 grid gap-3">
          {conferences.map((conf, idx) => (
            <div key={`${conf.conference_name}-${idx}`} className="rounded-lg border border-slate-700/70 bg-slate-900/30 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-slate-100">{conf.conference_name}</span>
                <Badge variant="outline" className="border-emerald-700/60 text-emerald-300">{conf.confidence}</Badge>
              </div>
              <div className="mt-1 text-xs text-slate-400">{conf.organization} • {conf.location}</div>
              <div className="mt-1 text-xs text-slate-400">Dates: {conf.dates}</div>
              {conf.presentation_deadline && (
                <div className="mt-1 text-xs text-amber-300">Presentation deadline: {conf.presentation_deadline}</div>
              )}
              {conf.sponsorship_info && (
                <div className="mt-1 text-xs text-slate-400">Sponsorship: {conf.sponsorship_info}</div>
              )}
              <div className="mt-2 text-sm text-slate-200">{conf.relevance}</div>
              <a
                href={conf.website}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
              >
                {hostFromUrl(conf.website)}
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link to="/" className="text-sm text-slate-400 hover:text-slate-200">Home</Link>
            <Link to="/saved-runs" className="text-sm text-slate-400 hover:text-slate-200 inline-flex items-center gap-1">
              <FolderOpen className="w-4 h-4" />
              Saved Runs
            </Link>
          </div>
          <h1 className="text-xl font-semibold text-slate-100">Research Library</h1>
          <ThemeToggle />
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8">
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="text-sm text-slate-400">Filters</div>
            <select
              value={productFilter}
              onChange={(e) => {
                setProductFilter(e.target.value)
                setStateFilter('all')
              }}
              className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-sm text-slate-200"
            >
              <option value="all">All products</option>
              {products.map(product => (
                <option key={product} value={product}>{product}</option>
              ))}
            </select>
            <select
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-sm text-slate-200"
            >
              <option value="all">All states</option>
              {states.map(state => (
                <option key={state} value={state}>{state}</option>
              ))}
            </select>
            <div className="ml-auto flex flex-wrap items-center gap-2 text-xs text-slate-400">
              <label className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={showFilteredDistrict}
                  onChange={(e) => setShowFilteredDistrict(e.target.checked)}
                />
                Show filtered district items
              </label>
              <label className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={showConferences}
                  onChange={(e) => setShowConferences(e.target.checked)}
                />
                Show conferences
              </label>
            </div>
          </div>
        </div>

        {isLoading && (
          <div className="mt-6 text-sm text-slate-400">Loading saved research runs...</div>
        )}
        {error && (
          <div className="mt-6 text-sm text-red-400">Failed to load research runs.</div>
        )}
        {!isLoading && filteredRuns.length === 0 && (
          <div className="mt-6 rounded-lg border border-slate-800 bg-slate-900/30 p-6 text-center text-slate-400">
            <Search className="w-6 h-6 mx-auto mb-3" />
            No saved research runs match these filters.
          </div>
        )}

        <div className="mt-6 space-y-6">
          {groupedByState.map(([stateCode, runsForState]) => {
            const stateFull = runsForState[0]?.state_full || stateCode
            return (
              <section key={stateCode} className="rounded-xl border border-slate-800 bg-slate-900/30 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-lg font-semibold text-slate-100">{stateFull}</h2>
                    <p className="text-xs text-slate-500">{stateCode} • {runsForState.length} saved run(s)</p>
                  </div>
                </div>
                <div className="mt-4 space-y-3">
                  {runsForState.map(run => {
                    const isExpanded = expandedRuns[run.id]
                    const detail = runDetails[run.id]
                    const isLoadingDetail = loadingRun[run.id]
                    const hookCount = run.hook_count ?? 0
                    const districtComplete = run.district_research_complete

                    return (
                      <div key={run.id} className="rounded-lg border border-slate-700/70 bg-slate-900/40">
                        <div className="flex flex-wrap items-center justify-between gap-3 p-3">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-medium text-slate-100">{run.product}</span>
                              <Badge variant="outline" className="border-blue-700/60 text-blue-300">{run.state_code}</Badge>
                              {run.district_name && (
                                <Badge variant="outline" className="border-amber-700/60 text-amber-300">{run.district_name}</Badge>
                              )}
                              {districtComplete && (
                                <Badge variant="outline" className="border-emerald-700/60 text-emerald-300">District research</Badge>
                              )}
                            </div>
                            <div className="mt-1 text-xs text-slate-500">
                              {formatDateTime(run.created_at)} • {hookCount} state hooks
                            </div>
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => toggleRun(run.id)}
                            className="text-slate-300"
                          >
                            {isExpanded ? (
                              <><ChevronUp className="w-4 h-4 mr-1" />Hide</>
                            ) : (
                              <><ChevronDown className="w-4 h-4 mr-1" />View</>
                            )}
                          </Button>
                        </div>

                        {isExpanded && (
                          <div className="border-t border-slate-800 p-4 space-y-4">
                            {isLoadingDetail && (
                              <div className="text-xs text-slate-500">Loading details...</div>
                            )}
                            {detail && (
                              <>
                                <div>
                                  <h4 className="text-sm font-semibold text-slate-200">State Research Hooks</h4>
                                  <div className="mt-3 grid gap-3">
                                    {getStateHooks(detail).map(renderHookCard)}
                                    {getStateHooks(detail).length === 0 && (
                                      <div className="text-xs text-slate-500">No state-level hooks found.</div>
                                    )}
                                  </div>
                                </div>
                                {renderDistrictSection(detail)}
                                {renderConferences(detail)}
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </section>
            )
          })}
        </div>
      </main>
    </div>
  )
}
