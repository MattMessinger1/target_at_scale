import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, GoldenEmailListItem, EmailReviewListItem, GoldenEmailDetail, NegativeEmailListItem, NegativeEmailDetail, ChunkFeedbackListItem } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/components/ui/use-toast'
import { 
  Star,
  Edit3,
  CheckCircle2,
  ChevronRight,
  Loader2,
  Mail,
  Clock,
  Filter,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  FileWarning,
  ThumbsDown,
} from 'lucide-react'
import { Link } from 'react-router-dom'

type ViewMode = 'overview' | 'golden' | 'negative' | 'reviews' | 'flagged'

export default function TrainingFeedback() {
  const { toast } = useToast()
  
  const [viewMode, setViewMode] = useState<ViewMode>('overview')
  const [selectedEmail, setSelectedEmail] = useState<GoldenEmailDetail | null>(null)
  const [selectedNegative, setSelectedNegative] = useState<NegativeEmailDetail | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  
  // Filters
  const [productFilter, setProductFilter] = useState<string>('')
  const [stateFilter, setStateFilter] = useState<string>('')
  const [sourceFilter, setSourceFilter] = useState<string>('')
  
  // Fetch quality metrics (for overview)
  const { data: metricsData, isLoading: metricsLoading } = useQuery({
    queryKey: ['quality-metrics', productFilter, stateFilter],
    queryFn: () => api.feedback.getMetrics({
      product: productFilter || undefined,
      state_code: stateFilter || undefined,
    }),
  })
  
  // Fetch golden emails
  const { data: goldenData, isLoading: goldenLoading } = useQuery({
    queryKey: ['golden-emails', productFilter, stateFilter, sourceFilter],
    queryFn: () => api.feedback.listGoldenEmails({
      product: productFilter || undefined,
      state_code: stateFilter || undefined,
      source: sourceFilter || undefined,
      limit: 100,
    }),
    enabled: viewMode === 'golden' || viewMode === 'overview',
  })
  
  // Fetch negative emails
  const { data: negativeData, isLoading: negativeLoading } = useQuery({
    queryKey: ['negative-emails', productFilter, stateFilter],
    queryFn: () => api.feedback.listNegativeEmails({
      product: productFilter || undefined,
      state_code: stateFilter || undefined,
      limit: 100,
    }),
    enabled: viewMode === 'negative' || viewMode === 'overview',
  })
  
  // Fetch email reviews
  const { data: reviewsData, isLoading: reviewsLoading } = useQuery({
    queryKey: ['email-reviews', productFilter, stateFilter],
    queryFn: () => api.feedback.listEmailReviews({
      product: productFilter || undefined,
      state_code: stateFilter || undefined,
      limit: 100,
    }),
    enabled: viewMode === 'reviews',
  })
  
  // Fetch flagged chunks
  const { data: flaggedData, isLoading: flaggedLoading } = useQuery({
    queryKey: ['flagged-chunks', productFilter],
    queryFn: () => api.feedback.listFlaggedChunks({
      product_key: productFilter || undefined,
      resolved: false,
      limit: 100,
    }),
    enabled: viewMode === 'flagged' || viewMode === 'overview',
  })
  
  const loadEmailDetail = async (id: number) => {
    setLoadingDetail(true)
    try {
      const detail = await api.feedback.getGoldenEmail(id)
      setSelectedEmail(detail)
      setSelectedNegative(null)
    } catch (err) {
      toast({
        title: 'Error loading email',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    } finally {
      setLoadingDetail(false)
    }
  }
  
  const loadNegativeDetail = async (id: number) => {
    setLoadingDetail(true)
    try {
      const detail = await api.feedback.getNegativeEmail(id)
      setSelectedNegative(detail)
      setSelectedEmail(null)
    } catch (err) {
      toast({
        title: 'Error loading email',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      })
    } finally {
      setLoadingDetail(false)
    }
  }
  
  const formatDate = (dateStr?: string | null) => {
    if (!dateStr) return 'Unknown'
    const date = new Date(dateStr)
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }
  
  const getRubricAverage = (scores?: Record<string, number> | null): number | null => {
    if (!scores) return null
    const values = Object.values(scores).filter(v => typeof v === 'number')
    if (values.length === 0) return null
    return values.reduce((a, b) => a + b, 0) / values.length
  }
  
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      {/* Header */}
      <header className="border-b border-slate-700/50 bg-slate-900/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Link to="/" className="text-slate-400 hover:text-slate-200 transition-colors">
                ← Back
              </Link>
              <h1 className="text-xl font-semibold text-slate-100">Training Feedback</h1>
            </div>
            
            {/* View Mode Toggle */}
            <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1">
              <button
                onClick={() => setViewMode('overview')}
                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  viewMode === 'overview'
                    ? 'bg-blue-600 text-white'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <TrendingUp className="w-4 h-4 inline mr-1" />
                Overview
              </button>
              <button
                onClick={() => setViewMode('golden')}
                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  viewMode === 'golden'
                    ? 'bg-amber-600 text-white'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <Star className="w-4 h-4 inline mr-1" />
                Golden ({metricsData?.total_golden ?? 0})
              </button>
              <button
                onClick={() => setViewMode('negative')}
                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  viewMode === 'negative'
                    ? 'bg-red-600 text-white'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <ThumbsDown className="w-4 h-4 inline mr-1" />
                Negative ({metricsData?.total_negative ?? 0})
              </button>
              <button
                onClick={() => setViewMode('reviews')}
                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  viewMode === 'reviews'
                    ? 'bg-emerald-600 text-white'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <Edit3 className="w-4 h-4 inline mr-1" />
                Reviews ({metricsData?.total_reviews ?? 0})
              </button>
              <button
                onClick={() => setViewMode('flagged')}
                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  viewMode === 'flagged'
                    ? 'bg-orange-600 text-white'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <FileWarning className="w-4 h-4 inline mr-1" />
                Flagged ({flaggedData?.total ?? 0})
              </button>
            </div>
          </div>
          
          {/* Filters */}
          <div className="mt-4 flex items-center gap-4">
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-slate-500" />
              <span className="text-sm text-slate-500">Filters:</span>
            </div>
            <input
              type="text"
              value={productFilter}
              onChange={(e) => setProductFilter(e.target.value)}
              placeholder="Product..."
              className="px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-md text-sm text-slate-200 placeholder-slate-500 w-40"
            />
            <input
              type="text"
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value.toUpperCase())}
              placeholder="State code..."
              maxLength={2}
              className="px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-md text-sm text-slate-200 placeholder-slate-500 w-24"
            />
            {viewMode === 'golden' && (
              <select
                value={sourceFilter}
                onChange={(e) => setSourceFilter(e.target.value)}
                className="px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-md text-sm text-slate-200 w-40"
              >
                <option value="">All sources</option>
                <option value="edited">Edited</option>
                <option value="rubric_qualified">Rubric Qualified</option>
              </select>
            )}
          </div>
        </div>
      </header>
      
      <main className="max-w-7xl mx-auto px-6 py-8">
        {/* Overview Mode */}
        {viewMode === 'overview' && (
          <OverviewDashboard
            metrics={metricsData}
            isLoading={metricsLoading}
            recentNegative={negativeData?.items?.slice(0, 5) || []}
            flaggedCount={flaggedData?.total || 0}
          />
        )}
        
        {/* List Views */}
        {viewMode !== 'overview' && (
          <div className="flex gap-6">
            {/* List Panel */}
            <div className="flex-1 min-w-0">
              {viewMode === 'golden' && (
                <GoldenEmailsList
                  items={goldenData?.items || []}
                  isLoading={goldenLoading}
                  selectedId={selectedEmail?.id}
                  onSelect={loadEmailDetail}
                  formatDate={formatDate}
                  getRubricAverage={getRubricAverage}
                />
              )}
              {viewMode === 'negative' && (
                <NegativeEmailsList
                  items={negativeData?.items || []}
                  isLoading={negativeLoading}
                  selectedId={selectedNegative?.id}
                  onSelect={loadNegativeDetail}
                  formatDate={formatDate}
                />
              )}
              {viewMode === 'reviews' && (
                <ReviewsList
                  items={reviewsData?.items || []}
                  isLoading={reviewsLoading}
                  formatDate={formatDate}
                />
              )}
              {viewMode === 'flagged' && (
                <FlaggedChunksList
                  items={flaggedData?.items || []}
                  isLoading={flaggedLoading}
                  formatDate={formatDate}
                />
              )}
            </div>
            
            {/* Detail Panel */}
            {(viewMode === 'golden' || viewMode === 'negative') && (
              <div className="w-[500px] flex-shrink-0">
                {viewMode === 'golden' && (
                  <EmailDetailPanel
                    email={selectedEmail}
                    isLoading={loadingDetail}
                  />
                )}
                {viewMode === 'negative' && (
                  <NegativeEmailDetailPanel
                    email={selectedNegative}
                    isLoading={loadingDetail}
                  />
                )}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  )
}

// Golden Emails List Component
function GoldenEmailsList({
  items,
  isLoading,
  selectedId,
  onSelect,
  formatDate,
  getRubricAverage,
}: {
  items: GoldenEmailListItem[]
  isLoading: boolean
  selectedId?: number
  onSelect: (id: number) => void
  formatDate: (d?: string | null) => string
  getRubricAverage: (scores?: Record<string, number> | null) => number | null
}) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
        <span className="ml-2 text-slate-400">Loading golden emails...</span>
      </div>
    )
  }
  
  if (items.length === 0) {
    return (
      <div className="text-center py-12 text-slate-400">
        <Star className="w-12 h-12 mx-auto mb-4 opacity-30" />
        <p className="text-lg">No golden emails yet</p>
        <p className="text-sm mt-2">
          Emails become "golden" when you edit them or give them high rubric scores (4+).
        </p>
      </div>
    )
  }
  
  return (
    <div className="space-y-2">
      {items.map((item) => {
        const avg = getRubricAverage(item.rubric_scores)
        const isSelected = selectedId === item.id
        
        return (
          <div
            key={item.id}
            onClick={() => onSelect(item.id)}
            className={`p-4 rounded-lg border cursor-pointer transition-all ${
              isSelected
                ? 'bg-amber-900/20 border-amber-600/50'
                : 'bg-slate-800/50 border-slate-700/50 hover:bg-slate-800 hover:border-slate-600'
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <Badge variant={item.source === 'edited' ? 'default' : 'secondary'} className={
                    item.source === 'edited'
                      ? 'bg-blue-600/20 text-blue-300 border-blue-600/30'
                      : 'bg-emerald-600/20 text-emerald-300 border-emerald-600/30'
                  }>
                    {item.source === 'edited' ? (
                      <><Edit3 className="w-3 h-3 mr-1" /> Edited</>
                    ) : (
                      <><CheckCircle2 className="w-3 h-3 mr-1" /> Rubric 4+</>
                    )}
                  </Badge>
                  <span className="text-xs text-slate-500">{item.product}</span>
                  <span className="text-xs text-slate-600">•</span>
                  <span className="text-xs text-slate-500">{item.state_code}</span>
                </div>
                <h3 className="text-sm font-medium text-slate-200 truncate">
                  {item.subject_line}
                </h3>
                <div className="flex items-center gap-3 mt-2 text-xs text-slate-500">
                  <span>{item.audience}</span>
                  <span className="text-slate-600">•</span>
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {formatDate(item.created_at)}
                  </span>
                </div>
              </div>
              
              {avg !== null && (
                <div className="flex items-center gap-1 px-2 py-1 rounded bg-slate-700/50">
                  <Star className="w-3 h-3 text-amber-400" />
                  <span className="text-sm font-medium text-slate-200">{avg.toFixed(1)}</span>
                </div>
              )}
              
              <ChevronRight className={`w-5 h-5 text-slate-500 transition-transform ${isSelected ? 'rotate-90' : ''}`} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

// Reviews List Component
function ReviewsList({
  items,
  isLoading,
  formatDate,
}: {
  items: EmailReviewListItem[]
  isLoading: boolean
  formatDate: (d?: string | null) => string
}) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
        <span className="ml-2 text-slate-400">Loading reviews...</span>
      </div>
    )
  }
  
  if (items.length === 0) {
    return (
      <div className="text-center py-12 text-slate-400">
        <Edit3 className="w-12 h-12 mx-auto mb-4 opacity-30" />
        <p className="text-lg">No email reviews yet</p>
        <p className="text-sm mt-2">
          Reviews are submitted when you click "Save Email" after generating an email.
        </p>
      </div>
    )
  }
  
  const getRubricScore = (rubric: Record<string, { score?: number | null; comment?: string | null }>) => {
    const scores = Object.values(rubric)
      .map(item => item?.score)
      .filter((s): s is number => typeof s === 'number')
    if (scores.length === 0) return null
    return scores.reduce((a, b) => a + b, 0) / scores.length
  }
  
  return (
    <div className="space-y-2">
      {items.map((item) => {
        const avg = getRubricScore(item.rubric)
        
        return (
          <div
            key={item.id}
            className="p-4 rounded-lg border bg-slate-800/50 border-slate-700/50"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  {item.was_edited ? (
                    <Badge className="bg-blue-600/20 text-blue-300 border-blue-600/30">
                      <Edit3 className="w-3 h-3 mr-1" /> Edited
                    </Badge>
                  ) : (
                    <Badge className="bg-slate-600/20 text-slate-400 border-slate-600/30">
                      No edits
                    </Badge>
                  )}
                  <span className="text-xs text-slate-500">{item.product}</span>
                  <span className="text-xs text-slate-600">•</span>
                  <span className="text-xs text-slate-500">{item.state_code}</span>
                </div>
                <h3 className="text-sm font-medium text-slate-200 truncate">
                  {item.subject_preview}
                </h3>
                <div className="flex items-center gap-3 mt-2 text-xs text-slate-500">
                  <span>{item.audience}</span>
                  {item.district_name && (
                    <>
                      <span className="text-slate-600">•</span>
                      <span>{item.district_name}</span>
                    </>
                  )}
                  <span className="text-slate-600">•</span>
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {formatDate(item.created_at)}
                  </span>
                </div>
              </div>
              
              {avg !== null && (
                <div className="flex items-center gap-1 px-2 py-1 rounded bg-slate-700/50">
                  <Star className="w-3 h-3 text-amber-400" />
                  <span className="text-sm font-medium text-slate-200">{avg.toFixed(1)}</span>
                </div>
              )}
            </div>
            
            {/* Rubric Scores Display */}
            {item.rubric && Object.keys(item.rubric).length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {Object.entries(item.rubric).map(([key, value]) => (
                  value?.score && (
                    <span key={key} className="text-xs px-2 py-0.5 rounded bg-slate-700/50 text-slate-400">
                      {key.replace(/_/g, ' ')}: <span className="text-slate-200">{value.score}</span>
                    </span>
                  )
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// Email Detail Panel Component
function EmailDetailPanel({
  email,
  isLoading,
}: {
  email: GoldenEmailDetail | null
  isLoading: boolean
}) {
  if (isLoading) {
    return (
      <div className="p-6 rounded-lg border border-slate-700/50 bg-slate-800/30">
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
        </div>
      </div>
    )
  }
  
  if (!email) {
    return (
      <div className="p-6 rounded-lg border border-slate-700/50 bg-slate-800/30">
        <div className="text-center py-12 text-slate-500">
          <Mail className="w-12 h-12 mx-auto mb-4 opacity-30" />
          <p>Select an email to view details</p>
        </div>
      </div>
    )
  }
  
  return (
    <div className="p-6 rounded-lg border border-slate-700/50 bg-slate-800/30 sticky top-24">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-medium text-slate-100">Email Preview</h3>
        <Badge className={
          email.source === 'edited'
            ? 'bg-blue-600/20 text-blue-300 border-blue-600/30'
            : 'bg-emerald-600/20 text-emerald-300 border-emerald-600/30'
        }>
          {email.source === 'edited' ? 'Edited' : 'Rubric Qualified'}
        </Badge>
      </div>
      
      <div className="space-y-4">
        {/* Context */}
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="px-2 py-1 rounded bg-slate-700/50 text-slate-300">{email.product}</span>
          <span className="px-2 py-1 rounded bg-slate-700/50 text-slate-300">{email.state_code}</span>
          <span className="px-2 py-1 rounded bg-slate-700/50 text-slate-300">{email.audience}</span>
        </div>
        
        {/* Rubric Scores */}
        {email.rubric_scores && Object.keys(email.rubric_scores).length > 0 && (
          <div className="p-3 rounded bg-slate-900/50">
            <div className="text-xs text-slate-500 uppercase tracking-wide mb-2">Rubric Scores</div>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(email.rubric_scores).map(([key, score]) => (
                <div key={key} className="flex items-center justify-between text-sm">
                  <span className="text-slate-400 capitalize">{key.replace(/_/g, ' ')}</span>
                  <span className="text-slate-200 font-medium">{score}/5</span>
                </div>
              ))}
            </div>
          </div>
        )}
        
        {/* Subject Line */}
        <div>
          <div className="text-xs text-slate-500 uppercase tracking-wide mb-1">Subject Line</div>
          <div className="text-sm text-slate-200 font-medium">{email.subject_line}</div>
        </div>
        
        {/* Email Body */}
        <div>
          <div className="text-xs text-slate-500 uppercase tracking-wide mb-1">Email Body</div>
          <div className="p-3 rounded bg-slate-900/50 max-h-80 overflow-y-auto">
            <div className="text-sm text-slate-300 whitespace-pre-wrap">{email.email_body}</div>
          </div>
        </div>
        
        {/* Hook Types Used */}
        {email.hook_types_used && email.hook_types_used.length > 0 && (
          <div>
            <div className="text-xs text-slate-500 uppercase tracking-wide mb-1">Hook Types Used</div>
            <div className="flex flex-wrap gap-1">
              {email.hook_types_used.map((type, idx) => (
                <span key={idx} className="text-xs px-2 py-0.5 rounded bg-slate-700/50 text-slate-400">
                  {type}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Overview Dashboard Component
function OverviewDashboard({
  metrics,
  isLoading,
  recentNegative,
  flaggedCount,
}: {
  metrics?: { total_reviews: number; total_golden: number; total_negative: number; avg_scores_by_category: Record<string, number>; low_score_categories_frequency: Record<string, number> } | null
  isLoading: boolean
  recentNegative: NegativeEmailListItem[]
  flaggedCount: number
}) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
        <span className="ml-2 text-slate-400">Loading metrics...</span>
      </div>
    )
  }
  
  const categoryLabels: Record<string, string> = {
    subject_line: 'Subject Line',
    hook_usage: 'Hook Usage',
    product_relevance: 'Product Relevance',
    tone: 'Tone',
    flow: 'Flow',
    cta: 'CTA',
  }
  
  return (
    <div className="space-y-6">
      {/* Stats Cards */}
      <div className="grid grid-cols-4 gap-4">
        <div className="p-4 rounded-lg border border-slate-700/50 bg-slate-800/50">
          <div className="text-2xl font-semibold text-slate-100">{metrics?.total_reviews ?? 0}</div>
          <div className="text-sm text-slate-400">Total Reviews</div>
        </div>
        <div className="p-4 rounded-lg border border-amber-700/50 bg-amber-900/20">
          <div className="text-2xl font-semibold text-amber-200">{metrics?.total_golden ?? 0}</div>
          <div className="text-sm text-amber-400">Golden Emails</div>
        </div>
        <div className="p-4 rounded-lg border border-red-700/50 bg-red-900/20">
          <div className="text-2xl font-semibold text-red-200">{metrics?.total_negative ?? 0}</div>
          <div className="text-sm text-red-400">Negative Examples</div>
        </div>
        <div className="p-4 rounded-lg border border-orange-700/50 bg-orange-900/20">
          <div className="text-2xl font-semibold text-orange-200">{flaggedCount}</div>
          <div className="text-sm text-orange-400">Flagged Chunks</div>
        </div>
      </div>
      
      {/* Score Averages */}
      {metrics?.avg_scores_by_category && Object.keys(metrics.avg_scores_by_category).length > 0 && (
        <div className="p-4 rounded-lg border border-slate-700/50 bg-slate-800/50">
          <h3 className="text-lg font-medium text-slate-100 mb-4">Average Scores by Category</h3>
          <div className="grid grid-cols-3 gap-4">
            {Object.entries(metrics.avg_scores_by_category).map(([key, score]) => (
              <div key={key} className="flex items-center justify-between p-3 rounded bg-slate-900/50">
                <span className="text-sm text-slate-300">{categoryLabels[key] || key}</span>
                <div className="flex items-center gap-2">
                  {score >= 4 ? (
                    <TrendingUp className="w-4 h-4 text-emerald-400" />
                  ) : score <= 2 ? (
                    <TrendingDown className="w-4 h-4 text-red-400" />
                  ) : null}
                  <span className={`text-lg font-semibold ${
                    score >= 4 ? 'text-emerald-300' : score <= 2 ? 'text-red-300' : 'text-slate-200'
                  }`}>
                    {score.toFixed(1)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      
      {/* Problem Frequency */}
      {metrics?.low_score_categories_frequency && Object.values(metrics.low_score_categories_frequency).some(v => v > 0) && (
        <div className="p-4 rounded-lg border border-red-700/50 bg-red-900/10">
          <h3 className="text-lg font-medium text-red-200 mb-4 flex items-center gap-2">
            <AlertTriangle className="w-5 h-5" />
            Common Problems
          </h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(metrics.low_score_categories_frequency)
              .filter(([, count]) => count > 0)
              .sort(([, a], [, b]) => b - a)
              .map(([key, count]) => (
                <span key={key} className="px-3 py-1 rounded-full bg-red-900/30 text-red-300 text-sm">
                  {categoryLabels[key] || key}: {count} emails
                </span>
              ))}
          </div>
        </div>
      )}
      
      {/* Recent Negative Emails */}
      {recentNegative.length > 0 && (
        <div className="p-4 rounded-lg border border-slate-700/50 bg-slate-800/50">
          <h3 className="text-lg font-medium text-slate-100 mb-4">Recent Issues (Needs Attention)</h3>
          <div className="space-y-2">
            {recentNegative.map((item) => (
              <div key={item.id} className="p-3 rounded bg-slate-900/50 flex items-center justify-between">
                <div>
                  <div className="text-sm text-slate-200 truncate max-w-md">{item.subject_line}</div>
                  <div className="text-xs text-slate-500 mt-1">
                    {item.product} • {item.state_code} • Problems: {item.low_score_categories.join(', ')}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {item.weight >= 2 && (
                    <Badge className="bg-red-600/20 text-red-300 border-red-600/30">Severe</Badge>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// Negative Emails List Component
function NegativeEmailsList({
  items,
  isLoading,
  selectedId,
  onSelect,
  formatDate,
}: {
  items: NegativeEmailListItem[]
  isLoading: boolean
  selectedId?: number
  onSelect: (id: number) => void
  formatDate: (d?: string | null) => string
}) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
        <span className="ml-2 text-slate-400">Loading negative examples...</span>
      </div>
    )
  }
  
  if (items.length === 0) {
    return (
      <div className="text-center py-12 text-slate-400">
        <ThumbsDown className="w-12 h-12 mx-auto mb-4 opacity-30" />
        <p className="text-lg">No negative examples yet</p>
        <p className="text-sm mt-2">
          Emails become "negative" when they receive a 1 or 2 score on any rubric item.
        </p>
      </div>
    )
  }
  
  return (
    <div className="space-y-2">
      {items.map((item) => {
        const isSelected = selectedId === item.id
        
        return (
          <div
            key={item.id}
            onClick={() => onSelect(item.id)}
            className={`p-4 rounded-lg border cursor-pointer transition-all ${
              isSelected
                ? 'bg-red-900/20 border-red-600/50'
                : 'bg-slate-800/50 border-slate-700/50 hover:bg-slate-800 hover:border-slate-600'
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <Badge className={
                    item.weight >= 2
                      ? 'bg-red-600/20 text-red-300 border-red-600/30'
                      : 'bg-orange-600/20 text-orange-300 border-orange-600/30'
                  }>
                    {item.weight >= 2 ? 'Severe (1/5)' : 'Needs Work (2/5)'}
                  </Badge>
                  <span className="text-xs text-slate-500">{item.product}</span>
                  <span className="text-xs text-slate-600">•</span>
                  <span className="text-xs text-slate-500">{item.state_code}</span>
                </div>
                <h3 className="text-sm font-medium text-slate-200 truncate">
                  {item.subject_line}
                </h3>
                <div className="flex items-center gap-2 mt-2">
                  <span className="text-xs text-red-400">Problems:</span>
                  {item.low_score_categories.map((cat) => (
                    <span key={cat} className="text-xs px-2 py-0.5 rounded bg-red-900/30 text-red-300">
                      {cat.replace(/_/g, ' ')}
                    </span>
                  ))}
                </div>
                <div className="flex items-center gap-3 mt-2 text-xs text-slate-500">
                  <span>{item.audience}</span>
                  <span className="text-slate-600">•</span>
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {formatDate(item.created_at)}
                  </span>
                </div>
              </div>
              
              <ChevronRight className={`w-5 h-5 text-slate-500 transition-transform ${isSelected ? 'rotate-90' : ''}`} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

// Negative Email Detail Panel Component
function NegativeEmailDetailPanel({
  email,
  isLoading,
}: {
  email: NegativeEmailDetail | null
  isLoading: boolean
}) {
  if (isLoading) {
    return (
      <div className="p-6 rounded-lg border border-slate-700/50 bg-slate-800/30">
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
        </div>
      </div>
    )
  }
  
  if (!email) {
    return (
      <div className="p-6 rounded-lg border border-slate-700/50 bg-slate-800/30">
        <div className="text-center py-12 text-slate-500">
          <ThumbsDown className="w-12 h-12 mx-auto mb-4 opacity-30" />
          <p>Select an email to view details</p>
        </div>
      </div>
    )
  }
  
  return (
    <div className="p-6 rounded-lg border border-red-700/50 bg-red-900/10 sticky top-24">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-medium text-red-200">Negative Example</h3>
        <Badge className={
          email.weight >= 2
            ? 'bg-red-600/20 text-red-300 border-red-600/30'
            : 'bg-orange-600/20 text-orange-300 border-orange-600/30'
        }>
          {email.weight >= 2 ? 'Severe' : 'Needs Work'}
        </Badge>
      </div>
      
      <div className="space-y-4">
        {/* Problems */}
        <div className="p-3 rounded bg-red-900/30">
          <div className="text-xs text-red-400 uppercase tracking-wide mb-2">Problems</div>
          <div className="flex flex-wrap gap-2">
            {email.low_score_categories.map((cat) => (
              <span key={cat} className="px-2 py-1 rounded bg-red-900/50 text-red-300 text-sm">
                {cat.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
        </div>
        
        {/* Context */}
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="px-2 py-1 rounded bg-slate-700/50 text-slate-300">{email.product}</span>
          <span className="px-2 py-1 rounded bg-slate-700/50 text-slate-300">{email.state_code}</span>
          <span className="px-2 py-1 rounded bg-slate-700/50 text-slate-300">{email.audience}</span>
        </div>
        
        {/* Rubric Scores */}
        {email.rubric_scores && Object.keys(email.rubric_scores).length > 0 && (
          <div className="p-3 rounded bg-slate-900/50">
            <div className="text-xs text-slate-500 uppercase tracking-wide mb-2">Rubric Scores</div>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(email.rubric_scores).map(([key, score]) => (
                <div key={key} className="flex items-center justify-between text-sm">
                  <span className="text-slate-400 capitalize">{key.replace(/_/g, ' ')}</span>
                  <span className={`font-medium ${
                    score <= 2 ? 'text-red-300' : 'text-slate-200'
                  }`}>{score}/5</span>
                </div>
              ))}
            </div>
          </div>
        )}
        
        {/* Subject Line */}
        <div>
          <div className="text-xs text-slate-500 uppercase tracking-wide mb-1">Subject Line</div>
          <div className="text-sm text-slate-200 font-medium">{email.subject_line}</div>
        </div>
        
        {/* Email Body */}
        <div>
          <div className="text-xs text-slate-500 uppercase tracking-wide mb-1">Email Body (Avoid This)</div>
          <div className="p-3 rounded bg-slate-900/50 max-h-80 overflow-y-auto border border-red-900/30">
            <div className="text-sm text-slate-300 whitespace-pre-wrap">{email.email_body}</div>
          </div>
        </div>
      </div>
    </div>
  )
}

// Flagged Chunks List Component
function FlaggedChunksList({
  items,
  isLoading,
  formatDate,
}: {
  items: ChunkFeedbackListItem[]
  isLoading: boolean
  formatDate: (d?: string | null) => string
}) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
        <span className="ml-2 text-slate-400">Loading flagged chunks...</span>
      </div>
    )
  }
  
  if (items.length === 0) {
    return (
      <div className="text-center py-12 text-slate-400">
        <FileWarning className="w-12 h-12 mx-auto mb-4 opacity-30" />
        <p className="text-lg">No flagged chunks</p>
        <p className="text-sm mt-2">
          Chunks get flagged when emails with low product_relevance scores are submitted.
        </p>
      </div>
    )
  }
  
  return (
    <div className="space-y-2">
      {items.map((item) => (
        <div
          key={item.id}
          className="p-4 rounded-lg border bg-slate-800/50 border-slate-700/50"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <Badge className="bg-orange-600/20 text-orange-300 border-orange-600/30">
                  {item.flag_reason.replace(/_/g, ' ')}
                </Badge>
                <span className="text-xs text-slate-500">{item.product_key}</span>
                {item.state_code && (
                  <>
                    <span className="text-xs text-slate-600">•</span>
                    <span className="text-xs text-slate-500">{item.state_code}</span>
                  </>
                )}
              </div>
              <div className="text-sm font-mono text-slate-300 truncate">
                {item.chunk_id}
              </div>
              {item.file_name && (
                <div className="text-xs text-slate-500 mt-1">
                  File: {item.file_name}
                </div>
              )}
              {item.notes && (
                <div className="text-xs text-slate-400 mt-2 italic">
                  "{item.notes}"
                </div>
              )}
              <div className="flex items-center gap-3 mt-2 text-xs text-slate-500">
                <span className="flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  {formatDate(item.created_at)}
                </span>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
