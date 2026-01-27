import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, SavedRunSummary } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/components/ui/use-toast'
import { 
  FolderOpen, 
  Search,
  Trash2,
  ChevronRight,
  ChevronDown,
  Mail,
  Clock,
  Loader2,
  CheckCircle2,
  XCircle,
} from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'

type ViewMode = 'grouped' | 'list' | 'batch'
type RunTypeFilter = 'all' | 'research' | 'email'

export default function SavedRuns() {
  const { toast } = useToast()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  
  const [viewMode, setViewMode] = useState<ViewMode>('grouped')
  const [runTypeFilter, setRunTypeFilter] = useState<RunTypeFilter>('all')
  const [expandedProducts, setExpandedProducts] = useState<Record<string, boolean>>({})
  const [expandedStates, setExpandedStates] = useState<Record<string, boolean>>({})
  const [batchJobFilter, setBatchJobFilter] = useState<number | null>(null)
  const [expandedEdits, setExpandedEdits] = useState<Record<number, boolean>>({})
  
  // Fetch grouped runs
  const { data: groupedRuns, isLoading: groupedLoading } = useQuery({
    queryKey: ['saved-runs-grouped'],
    queryFn: () => api.savedRuns.listGrouped(30),
    enabled: viewMode === 'grouped',
  })
  
  // Fetch flat list
  const { data: listRuns, isLoading: listLoading } = useQuery({
    queryKey: ['saved-runs-list'],
    queryFn: () => api.savedRuns.list(100),
    enabled: viewMode === 'list',
  })
  
  // Fetch batch jobs
  const { data: batchJobs, isLoading: batchLoading } = useQuery({
    queryKey: ['batch-jobs'],
    queryFn: () => api.batch.list(20),
    enabled: viewMode === 'batch',
  })
  
  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.savedRuns.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saved-runs-grouped'] })
      queryClient.invalidateQueries({ queryKey: ['saved-runs-list'] })
      toast({ title: 'Run deleted', description: 'The saved run has been removed.' })
    },
    onError: (err) => {
      toast({ 
        title: 'Error deleting run', 
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })
  
  // Auto-expand first product
  useEffect(() => {
    if (groupedRuns && groupedRuns.length > 0 && Object.keys(expandedProducts).length === 0) {
      setExpandedProducts({ [groupedRuns[0].product]: true })
    }
  }, [groupedRuns])
  
  const toggleProduct = (product: string) => {
    setExpandedProducts(prev => ({ ...prev, [product]: !prev[product] }))
  }
  
  const toggleState = (productState: string) => {
    setExpandedStates(prev => ({ ...prev, [productState]: !prev[productState] }))
  }
  
  const loadAndNavigate = async (run: SavedRunSummary) => {
    try {
      // Load full run data and navigate to generator
      const full = await api.savedRuns.get(run.id)
      // Store in session storage for the generator to pick up
      sessionStorage.setItem('loadSavedRun', JSON.stringify(full))
      navigate('/email')
      toast({
        title: 'Loading run...',
        description: `Loading ${run.name || run.product + ' - ' + run.state_code}`,
      })
    } catch (err) {
      toast({
        title: 'Error loading run',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    }
  }
  
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleDateString('en-US', { 
      month: 'short', 
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    })
  }
  
  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 className="w-4 h-4 text-emerald-400" />
      case 'running':
        return <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
      case 'failed':
        return <XCircle className="w-4 h-4 text-red-400" />
      case 'cancelled':
        return <XCircle className="w-4 h-4 text-slate-400" />
      default:
        return <Clock className="w-4 h-4 text-amber-400" />
    }
  }
  
  const renderRunCard = (run: SavedRunSummary) => {
    const isEmail = run.run_type === 'email'
    
    return (
      <div
        key={run.id}
        className={`p-3 rounded-lg border transition-colors cursor-pointer group ${
          isEmail 
            ? 'border-emerald-700/50 bg-emerald-900/10 hover:bg-emerald-900/20' 
            : 'border-slate-700 bg-slate-800/30 hover:bg-slate-800/60'
        }`}
        onClick={() => loadAndNavigate(run)}
      >
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              {isEmail ? (
                <Mail className="w-4 h-4 text-emerald-400 shrink-0" />
              ) : (
                <Search className="w-4 h-4 text-blue-400 shrink-0" />
              )}
              <span className="font-medium text-slate-200 truncate">
                {run.name || `${run.product} - ${run.state_full || run.state_code}`}
              </span>
              <Badge 
                variant="outline" 
                className={isEmail 
                  ? 'border-emerald-500 bg-emerald-900/30 text-emerald-300' 
                  : 'border-blue-600 text-blue-300'
                }
              >
                {isEmail ? '✉️ Email' : 'Research'}
              </Badge>
              {run.parent_run_id && (
                <Badge variant="outline" className="border-amber-500/60 text-amber-300">
                  Edited
                </Badge>
              )}
            </div>
            
            {/* Email subject preview - prominent for email runs */}
            {isEmail && run.subject_preview && (
              <div className="mb-2 px-2 py-1.5 bg-slate-800/50 rounded border border-slate-700/50">
                <span className="text-sm text-emerald-200 italic">"{run.subject_preview}"</span>
              </div>
            )}
            
            <div className="text-xs text-slate-500 flex items-center gap-3 flex-wrap">
              <span>{formatDate(run.created_at)}</span>
              {run.created_by && (
                <span className="text-slate-400">by {run.created_by}</span>
              )}
              {/* State vs District indicator */}
              <Badge variant="outline" className={run.district_name ? 'border-amber-600 text-amber-300' : 'border-slate-600 text-slate-400'}>
                {run.district_name ? 'District' : 'State'}
              </Badge>
              {run.district_name && (
                <span className="text-amber-400 truncate max-w-[150px]">{run.district_name}</span>
              )}
              {!isEmail && run.hook_count !== undefined && (
                <span>{run.hook_count} hooks</span>
              )}
            </div>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation()
              if (confirm('Delete this saved run?')) {
                deleteMutation.mutate(run.id)
              }
            }}
            className="p-1.5 rounded hover:bg-red-900/30 text-slate-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>
    )
  }
  
  // Filter runs based on type filter
  const filterRuns = (runs: SavedRunSummary[]) => {
    if (runTypeFilter === 'all') return runs
    return runs.filter(r => r.run_type === runTypeFilter)
  }

  const buildRunTree = (runs: SavedRunSummary[]) => {
    const children: Record<number, SavedRunSummary[]> = {}
    const roots: SavedRunSummary[] = []
    for (const run of runs) {
      if (run.parent_run_id) {
        if (!children[run.parent_run_id]) children[run.parent_run_id] = []
        children[run.parent_run_id].push(run)
      } else {
        roots.push(run)
      }
    }
    return { roots, children }
  }
  
  const renderGroupedView = () => {
    if (groupedLoading) {
      return (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
        </div>
      )
    }
    
    if (!groupedRuns || groupedRuns.length === 0) {
      return (
        <div className="text-center py-12">
          <FolderOpen className="w-12 h-12 mx-auto text-slate-600 mb-3" />
          <h3 className="text-lg font-medium text-slate-400">No saved runs yet</h3>
          <p className="text-sm text-slate-500 mt-1">
            Save research or email runs to see them here.
          </p>
          <div className="flex items-center gap-2 mt-4">
            <Link to="/research">
              <Button variant="outline" className="flex items-center gap-2">
                <Search className="w-4 h-4" />
                Start Research
              </Button>
            </Link>
            <Link to="/email?reset=1">
              <Button className="flex items-center gap-2">
                <Mail className="w-4 h-4" />
                Create Email
              </Button>
            </Link>
          </div>
        </div>
      )
    }
    
    return (
      <div className="space-y-4">
        {groupedRuns.map((group) => (
          <div key={group.product} className="rounded-xl border border-slate-700 bg-slate-800/30 overflow-hidden">
            {/* Product Header */}
            <button
              onClick={() => toggleProduct(group.product)}
              className="w-full px-4 py-3 flex items-center justify-between hover:bg-slate-700/30 transition-colors"
            >
              <div className="flex items-center gap-3">
                {expandedProducts[group.product] ? (
                  <ChevronDown className="w-5 h-5 text-slate-400" />
                ) : (
                  <ChevronRight className="w-5 h-5 text-slate-400" />
                )}
                <span className="font-semibold text-slate-200">{group.product}</span>
                <Badge variant="secondary">
                  {Object.values(group.states).flat().length} runs
                </Badge>
              </div>
              <span className="text-sm text-slate-500">
                {Object.keys(group.states).length} states
              </span>
            </button>
            
            {/* States */}
            {expandedProducts[group.product] && (
              <div className="border-t border-slate-700">
                {Object.entries(group.states).map(([stateCode, runs]) => {
                  const key = `${group.product}-${stateCode}`
                  const stateName = runs[0]?.state_full || stateCode
                  const filteredRuns = filterRuns(runs)
                  
                  // Hide states with no runs after filtering
                  if (filteredRuns.length === 0) return null
                  
                  return (
                    <div key={key} className="border-b border-slate-700/50 last:border-b-0">
                      {/* State Header */}
                      <button
                        onClick={() => toggleState(key)}
                        className="w-full px-6 py-2 flex items-center justify-between hover:bg-slate-700/20 transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          {expandedStates[key] ? (
                            <ChevronDown className="w-4 h-4 text-slate-500" />
                          ) : (
                            <ChevronRight className="w-4 h-4 text-slate-500" />
                          )}
                          <span className="text-sm font-medium text-slate-300">{stateName}</span>
                          <span className="text-xs text-slate-500">({stateCode})</span>
                        </div>
                        <span className="text-xs text-slate-500">{filteredRuns.length} runs</span>
                      </button>
                      
                      {/* Runs */}
                      {expandedStates[key] && (
                        <div className="px-8 py-2 space-y-2 bg-slate-900/20">
                          {(() => {
                            const { roots, children } = buildRunTree(filteredRuns)
                            return roots.map((run) => {
                              const edits = children[run.id] || []
                              const isExpanded = expandedEdits[run.id] || false
                              return (
                                <div key={`run-${run.id}`} className="space-y-1">
                                  {renderRunCard(run)}
                                  {edits.length > 0 && (
                                    <div className="pl-4 border-l border-slate-700/50 space-y-2">
                                      <button
                                        onClick={() =>
                                          setExpandedEdits((prev) => ({ ...prev, [run.id]: !isExpanded }))
                                        }
                                        className="text-xs text-slate-400 hover:text-slate-200"
                                      >
                                        {isExpanded ? 'Hide edits' : `Show edits (${edits.length})`}
                                      </button>
                                      {isExpanded && edits.map(renderRunCard)}
                                    </div>
                                  )}
                                </div>
                              )
                            })
                          })()}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        ))}
      </div>
    )
  }
  
  const renderListView = () => {
    if (listLoading) {
      return (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
        </div>
      )
    }
    
    if (!listRuns || listRuns.length === 0) {
      return (
        <div className="text-center py-12">
          <FolderOpen className="w-12 h-12 mx-auto text-slate-600 mb-3" />
          <h3 className="text-lg font-medium text-slate-400">No saved runs yet</h3>
        </div>
      )
    }
    
    let filtered = filterRuns(listRuns)
    if (batchJobFilter !== null) {
      filtered = filtered.filter(run => run.batch_job_id === batchJobFilter)
    }
    
    if (filtered.length === 0) {
      return (
        <div className="text-center py-12">
          <FolderOpen className="w-12 h-12 mx-auto text-slate-600 mb-3" />
          <h3 className="text-lg font-medium text-slate-400">
            No {runTypeFilter === 'email' ? 'email' : 'research'} runs found
          </h3>
          <p className="text-sm text-slate-500 mt-1">
            Try changing the filter or create a new {runTypeFilter === 'email' ? 'email' : 'research'} run
          </p>
        </div>
      )
    }
    
    return (
      <div className="space-y-3">
        {batchJobFilter !== null && (
          <div className="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-800/40 px-3 py-2 text-sm">
            <span className="text-slate-300">Showing results for batch #{batchJobFilter}</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setBatchJobFilter(null)}
            >
              Clear filter
            </Button>
          </div>
        )}
        <div className="space-y-2">
          {filtered.map(renderRunCard)}
        </div>
      </div>
    )
  }
  
  const renderBatchView = () => {
    if (batchLoading) {
      return (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
        </div>
      )
    }
    
    if (!batchJobs || batchJobs.length === 0) {
      return (
        <div className="text-center py-12">
          <FolderOpen className="w-12 h-12 mx-auto text-slate-600 mb-3" />
          <h3 className="text-lg font-medium text-slate-400">No batch jobs yet</h3>
          <p className="text-sm text-slate-500 mt-1">
            Start a batch job from the Generator to research multiple states at once.
          </p>
        </div>
      )
    }
    
    return (
      <div className="space-y-4">
        {batchJobs.map((job) => (
          <div key={job.id} className="rounded-xl border border-slate-700 bg-slate-800/30 p-4">
            <div className="flex items-start justify-between mb-3">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  {getStatusIcon(job.status)}
                  <span className="font-medium text-slate-200">
                    {job.name || `Batch #${job.id}`}
                  </span>
                  <Badge variant="outline" className="capitalize">
                    {job.status}
                  </Badge>
                </div>
                <div className="text-sm text-slate-400">{job.product}</div>
              </div>
              <div className="text-sm text-slate-500">
                {formatDate(job.created_at)}
              </div>
            </div>
            
            {/* Progress */}
            <div className="mb-3">
              <div className="flex justify-between text-xs text-slate-500 mb-1">
                <span>Progress</span>
                <span>{job.completed_states} / {job.total_states} states</span>
              </div>
              <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                <div 
                  className={`h-full transition-all ${
                    job.status === 'completed' ? 'bg-emerald-500' :
                    job.status === 'failed' ? 'bg-red-500' :
                    job.status === 'running' ? 'bg-blue-500 animate-pulse' :
                    'bg-slate-500'
                  }`}
                  style={{
                    width: `${job.status === 'running' && job.completed_states === 0
                      ? 8
                      : (job.completed_states / job.total_states) * 100}%`,
                  }}
                />
              </div>
              {job.failed_states > 0 && (
                <div className="text-xs text-red-400 mt-1">
                  {job.failed_states} failed
                </div>
              )}
            </div>
            
            {/* Actions */}
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setViewMode('list')
                  setRunTypeFilter('research')
                  setBatchJobFilter(job.id)
                  toast({
                    title: 'Batch results loaded',
                    description: `Showing saved research runs for batch #${job.id}.`,
                  })
                }}
              >
                View Results
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={async () => {
                  const input = window.prompt('State code for district restart (e.g., CO)')
                  if (!input) return
                  const stateCodes = input
                    .split(',')
                    .map((code) => code.trim().toUpperCase())
                    .filter(Boolean)
                  if (stateCodes.length === 0 || stateCodes.some((code) => code.length !== 2)) {
                    toast({
                      title: 'Invalid state code',
                      description: 'Please enter 2-letter state codes separated by commas (e.g., CO or NH, WA, ID).',
                      variant: 'destructive',
                    })
                    return
                  }
                  try {
                    for (const stateCode of stateCodes) {
                      await api.batch.restartDistrictResearch(job.id, stateCode)
                    }
                    queryClient.invalidateQueries({ queryKey: ['saved-runs-grouped'] })
                    queryClient.invalidateQueries({ queryKey: ['saved-runs-list'] })
                    toast({
                      title: 'District research restarted',
                      description: `Restarted district research for ${stateCodes.join(', ')} in batch #${job.id}.`,
                    })
                  } catch (err) {
                    toast({
                      title: 'Error restarting district research',
                      description: err instanceof Error ? err.message : 'Unknown error',
                      variant: 'destructive',
                    })
                  }
                }}
              >
                Restart District
              </Button>
              {(job.status === 'pending' || job.status === 'running') && (
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={async () => {
                    try {
                      await api.batch.cancel(job.id)
                      queryClient.invalidateQueries({ queryKey: ['batch-jobs'] })
                      toast({ title: 'Batch job cancelled' })
                    } catch (err) {
                      toast({
                        title: 'Error cancelling job',
                        description: err instanceof Error ? err.message : 'Unknown error',
                        variant: 'destructive',
                      })
                    }
                  }}
                >
                  Cancel
                </Button>
              )}
            </div>
          </div>
        ))}
      </div>
    )
  }
  
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
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
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Saved Research</h1>
            <p className="text-muted-foreground">
              View and manage your saved research and email runs (30-day retention)
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/research">
            <Button variant="outline" className="flex items-center gap-2">
              <Search className="w-4 h-4" />
              New Research
            </Button>
          </Link>
          <Link to="/email?reset=1">
            <Button className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500">
              <Mail className="w-4 h-4" />
              New Email
            </Button>
          </Link>
        </div>
      </div>
      
      {/* View Mode Tabs */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex gap-2">
          <button
            onClick={() => setViewMode('grouped')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              viewMode === 'grouped'
                ? 'bg-emerald-600 text-white'
                : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
            }`}
          >
            By Product
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              viewMode === 'list'
                ? 'bg-emerald-600 text-white'
                : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
            }`}
          >
            All Runs
          </button>
          <button
            onClick={() => setViewMode('batch')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              viewMode === 'batch'
                ? 'bg-emerald-600 text-white'
                : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
            }`}
          >
            Batch Jobs
          </button>
        </div>
        
        {/* Run Type Filter */}
        {viewMode !== 'batch' && (
          <div className="flex gap-1 p-1 bg-slate-900 rounded-lg border border-slate-700">
            <button
              onClick={() => setRunTypeFilter('all')}
              className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                runTypeFilter === 'all'
                  ? 'bg-slate-700 text-white'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              All
            </button>
            <button
              onClick={() => setRunTypeFilter('research')}
              className={`px-3 py-1.5 rounded text-sm font-medium transition-colors flex items-center gap-1.5 ${
                runTypeFilter === 'research'
                  ? 'bg-blue-700 text-white'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Search className="w-3.5 h-3.5" />
              Research
            </button>
            <button
              onClick={() => setRunTypeFilter('email')}
              className={`px-3 py-1.5 rounded text-sm font-medium transition-colors flex items-center gap-1.5 ${
                runTypeFilter === 'email'
                  ? 'bg-emerald-700 text-white'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Mail className="w-3.5 h-3.5" />
              Emails
            </button>
          </div>
        )}
      </div>
      
      {/* Content */}
      {viewMode === 'grouped' && renderGroupedView()}
      {viewMode === 'list' && renderListView()}
      {viewMode === 'batch' && renderBatchView()}
    </div>
  )
}
