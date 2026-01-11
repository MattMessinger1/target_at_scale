import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, SavedRunSummary, SavedRunFull, BatchJobSummary, BatchJobDetail, GroupedRunsResponse } from '@/lib/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/components/ui/use-toast'
import { 
  FolderOpen, 
  Search,
  Trash2,
  ChevronRight,
  ChevronDown,
  FileText,
  Mail,
  Clock,
  Loader2,
  AlertCircle,
  CheckCircle2,
  XCircle,
} from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'

type ViewMode = 'grouped' | 'list' | 'batch'

export default function SavedRuns() {
  const { toast } = useToast()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  
  const [viewMode, setViewMode] = useState<ViewMode>('grouped')
  const [expandedProducts, setExpandedProducts] = useState<Record<string, boolean>>({})
  const [expandedStates, setExpandedStates] = useState<Record<string, boolean>>({})
  const [selectedRun, setSelectedRun] = useState<SavedRunFull | null>(null)
  
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
      navigate('/generator')
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
  
  const renderRunCard = (run: SavedRunSummary) => (
    <div
      key={run.id}
      className="p-3 rounded-lg border border-slate-700 bg-slate-800/30 hover:bg-slate-800/60 transition-colors cursor-pointer group"
      onClick={() => loadAndNavigate(run)}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            {run.run_type === 'research' ? (
              <Search className="w-4 h-4 text-blue-400 shrink-0" />
            ) : (
              <Mail className="w-4 h-4 text-emerald-400 shrink-0" />
            )}
            <span className="font-medium text-slate-200 truncate">
              {run.name || `${run.product} - ${run.state_full || run.state_code}`}
            </span>
            <Badge variant="outline" className={run.run_type === 'research' ? 'border-blue-600 text-blue-300' : 'border-emerald-600 text-emerald-300'}>
              {run.run_type}
            </Badge>
          </div>
          <div className="text-xs text-slate-500 flex items-center gap-3">
            <span>{formatDate(run.created_at)}</span>
            {run.run_type === 'research' && run.hook_count !== undefined && (
              <span>{run.hook_count} hooks</span>
            )}
            {run.run_type === 'email' && run.subject_preview && (
              <span className="truncate max-w-[200px]">{run.subject_preview}</span>
            )}
            {run.district_name && (
              <span className="text-amber-400">{run.district_name}</span>
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
            Save research or email runs from the Generator to see them here.
          </p>
          <Link to="/generator">
            <Button variant="outline" className="mt-4">
              Go to Generator
            </Button>
          </Link>
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
                        <span className="text-xs text-slate-500">{runs.length} runs</span>
                      </button>
                      
                      {/* Runs */}
                      {expandedStates[key] && (
                        <div className="px-8 py-2 space-y-2 bg-slate-900/20">
                          {runs.map(renderRunCard)}
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
    
    return (
      <div className="space-y-2">
        {listRuns.map(renderRunCard)}
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
                    job.status === 'running' ? 'bg-blue-500' :
                    'bg-slate-500'
                  }`}
                  style={{ width: `${(job.completed_states / job.total_states) * 100}%` }}
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
                  // View batch results - filter saved runs by batch_job_id
                  // For now, switch to list view filtered by this batch
                  toast({
                    title: 'View batch results',
                    description: 'Feature coming soon - check Saved Runs list for results.',
                  })
                }}
              >
                View Results
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
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Saved Runs</h1>
          <p className="text-muted-foreground">
            View and manage your saved research and email runs (30-day retention)
          </p>
        </div>
        <Link to="/generator">
          <Button variant="outline">
            New Research
          </Button>
        </Link>
      </div>
      
      {/* View Mode Tabs */}
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
      
      {/* Content */}
      {viewMode === 'grouped' && renderGroupedView()}
      {viewMode === 'list' && renderListView()}
      {viewMode === 'batch' && renderBatchView()}
    </div>
  )
}
