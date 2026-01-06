import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type Snippet, type ScrapeResult } from '@/lib/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { 
  ArrowLeft,
  RefreshCw,
  Check,
  X,
  Mail,
  Play,
  RotateCcw,
  User,
  BarChart3,
  Target,
  DollarSign,
  Shield,
  BookOpen,
  CheckSquare,
  Square
} from 'lucide-react'
import { formatNumber, formatPercentage, getStatusColor } from '@/lib/utils'
import { toast } from '@/components/ui/use-toast'
import { useState } from 'react'

// Snippet category configuration
const SNIPPET_CATEGORIES = {
  contact: { label: 'Contacts & Decision Makers', icon: User, color: 'text-blue-600', bgColor: 'bg-blue-50' },
  statistic: { label: 'District Statistics', icon: BarChart3, color: 'text-emerald-600', bgColor: 'bg-emerald-50' },
  priority: { label: 'Strategic Priorities', icon: Target, color: 'text-purple-600', bgColor: 'bg-purple-50' },
  funding: { label: 'Funding Opportunities', icon: DollarSign, color: 'text-amber-600', bgColor: 'bg-amber-50' },
  compliance: { label: 'Compliance Requirements', icon: Shield, color: 'text-red-600', bgColor: 'bg-red-50' },
  program: { label: 'Current EL Programs', icon: BookOpen, color: 'text-indigo-600', bgColor: 'bg-indigo-50' },
}

// Scraping phases for progress display
const SCRAPE_PHASES = [
  { id: 'mapping', label: 'Mapping', progress: 15 },
  { id: 'scraping', label: 'Scraping', progress: 30 },
  { id: 'extracting', label: 'Extracting', progress: 45 },
  { id: 'research', label: 'Researching', progress: 60 },
  { id: 'matching', label: 'Matching', progress: 75 },
  { id: 'snippets', label: 'Processing Snippets', progress: 90 },
]

export default function DistrictDetail() {
  const { districtId } = useParams<{ districtId: string }>()
  const queryClient = useQueryClient()
  const [generatingEmail, setGeneratingEmail] = useState(false)

  const districtQuery = useQuery({
    queryKey: ['district', districtId],
    queryFn: () => api.districts.get(districtId!),
    enabled: !!districtId,
    refetchInterval: (query) => 
      query.state.data?.scrape_status === 'in_progress' ? 2000 : false,
  })
  const { data: district, isLoading: districtLoading } = districtQuery

  const { data: snippets, isLoading: snippetsLoading } = useQuery({
    queryKey: ['snippets', districtId],
    queryFn: () => api.snippets.listByDistrict(districtId!),
    enabled: !!districtId && district?.scrape_status === 'completed',
  })

  const { data: snippetSummary } = useQuery({
    queryKey: ['snippet-summary', districtId],
    queryFn: () => api.snippets.getSummary(districtId!),
    enabled: !!districtId && district?.scrape_status === 'completed',
  })

  const { data: emails } = useQuery({
    queryKey: ['emails', districtId],
    queryFn: () => api.emails.list(districtId),
    enabled: !!districtId,
  })

  const scrapeMutation = useMutation({
    mutationFn: () => api.districts.scrape(districtId!),
    onSuccess: (_data: ScrapeResult) => {
      toast({ 
        title: 'Scraping Complete',
        description: `Scraping completed for district`
      })
      queryClient.invalidateQueries({ queryKey: ['district', districtId] })
      queryClient.invalidateQueries({ queryKey: ['snippets', districtId] })
      queryClient.invalidateQueries({ queryKey: ['snippet-summary', districtId] })
    },
    onError: (error) => {
      toast({ 
        title: 'Scraping Failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive'
      })
      queryClient.invalidateQueries({ queryKey: ['district', districtId] })
    },
  })

  const resetMutation = useMutation({
    mutationFn: () => api.districts.reset(districtId!),
    onSuccess: () => {
      toast({ title: 'District reset to pending' })
      queryClient.invalidateQueries({ queryKey: ['district', districtId] })
      queryClient.invalidateQueries({ queryKey: ['snippets', districtId] })
      queryClient.invalidateQueries({ queryKey: ['snippet-summary', districtId] })
    },
  })

  const toggleSnippetMutation = useMutation({
    mutationFn: ({ id, included }: { id: number; included: boolean }) =>
      api.snippets.update(id, { included_in_email: included }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['snippets', districtId] })
      queryClient.invalidateQueries({ queryKey: ['snippet-summary', districtId] })
    },
  })

  const selectAllMutation = useMutation({
    mutationFn: (category?: string) => api.snippets.selectAll(districtId!, category),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['snippets', districtId] })
      queryClient.invalidateQueries({ queryKey: ['snippet-summary', districtId] })
    },
  })

  const deselectAllMutation = useMutation({
    mutationFn: (category?: string) => api.snippets.deselectAll(districtId!, category),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['snippets', districtId] })
      queryClient.invalidateQueries({ queryKey: ['snippet-summary', districtId] })
    },
  })

  const generateEmailMutation = useMutation({
    mutationFn: () => api.emails.generate({ district_id: districtId! }),
    onSuccess: () => {
      toast({ title: 'Email generated successfully' })
      queryClient.invalidateQueries({ queryKey: ['emails', districtId] })
      setGeneratingEmail(false)
    },
    onError: (error) => {
      toast({ 
        title: 'Error generating email',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive'
      })
      setGeneratingEmail(false)
    },
  })

  const handleGenerateEmail = () => {
    setGeneratingEmail(true)
    generateEmailMutation.mutate()
  }

  if (districtLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!district) {
    return (
      <div className="text-center py-12">
        <p className="text-muted-foreground">District not found</p>
        <Link to="/districts">
          <Button variant="link">Back to districts</Button>
        </Link>
      </div>
    )
  }

  // Group snippets by category
  const snippetsByCategory: Record<string, Snippet[]> = {}
  snippets?.forEach((snippet) => {
    if (!snippetsByCategory[snippet.category]) {
      snippetsByCategory[snippet.category] = []
    }
    snippetsByCategory[snippet.category].push(snippet)
  })

  const selectedCount = snippetSummary?.selected_snippets || 0
  const totalSnippets = snippetSummary?.total_snippets || 0

  // Get current phase progress
  const currentPhaseIndex = SCRAPE_PHASES.findIndex(p => p.id === district.scrape_phase)
  const scrapeProgress = currentPhaseIndex >= 0 ? SCRAPE_PHASES[currentPhaseIndex].progress : 0

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link to="/districts">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-5 w-5" />
          </Button>
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center">
              <span className="text-lg font-bold text-primary">
                {district.state}
              </span>
            </div>
            <div>
              <h1 className="text-2xl font-bold">{district.name}</h1>
              <p className="text-muted-foreground">{district.state_full}</p>
            </div>
          </div>
        </div>
        <Badge className={getStatusColor(district.scrape_status)}>
          {district.scrape_status}
        </Badge>
      </div>

      {/* Stats Row */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">Students</p>
            <p className="text-2xl font-bold">{formatNumber(district.student_count)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">EL Population</p>
            <p className="text-2xl font-bold">{formatPercentage(district.el_percentage)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">Available Snippets</p>
            <p className="text-2xl font-bold">{totalSnippets}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">Selected for Email</p>
            <p className="text-2xl font-bold text-primary">{selectedCount}</p>
          </CardContent>
        </Card>
      </div>

      {/* Scraping Status / Start Scraping */}
      {district.scrape_status === 'pending' && (
        <Card className="border-dashed border-2 border-primary/30 bg-primary/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Play className="h-5 w-5" />
              Ready to Scrape
            </CardTitle>
            <CardDescription>
              Start the scraping pipeline to gather content, research funding opportunities, 
              and extract email-ready snippets from {district.name}.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex gap-3">
            <Button 
              onClick={() => scrapeMutation.mutate()}
              disabled={scrapeMutation.isPending}
              size="lg"
            >
              {scrapeMutation.isPending && (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              )}
              <Play className="mr-2 h-4 w-4" />
              Start Scraping
            </Button>
          </CardContent>
        </Card>
      )}

      {district.scrape_status === 'in_progress' && (
        <Card className="border-blue-200 bg-blue-50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <RefreshCw className="h-5 w-5 animate-spin text-blue-600" />
              Processing District Data
            </CardTitle>
            <CardDescription>
              {district.scrape_phase && (
                <span className="font-medium text-blue-700">
                  {SCRAPE_PHASES.find(p => p.id === district.scrape_phase)?.label || district.scrape_phase}
                </span>
              )}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Progress value={scrapeProgress} className="h-2" />
            <div className="flex justify-between text-xs text-muted-foreground mt-2">
              {SCRAPE_PHASES.map((phase) => (
                <span 
                  key={phase.id}
                  className={district.scrape_phase === phase.id ? 'font-medium text-blue-600' : ''}
                >
                  {phase.label}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {district.scrape_status === 'error' && (
        <Card className="border-red-200 bg-red-50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-red-700">
              <X className="h-5 w-5" />
              Processing Error
            </CardTitle>
            <CardDescription>
              An error occurred. You can reset and try again.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button 
              onClick={() => resetMutation.mutate()}
              disabled={resetMutation.isPending}
              variant="outline"
            >
              <RotateCcw className="mr-2 h-4 w-4" />
              Reset & Retry
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Snippet Curation - Main Content */}
      {district.scrape_status === 'completed' && (
        <>
          {/* Actions Bar */}
          <div className="flex gap-3 flex-wrap items-center">
            <Button
              onClick={handleGenerateEmail}
              disabled={generatingEmail || selectedCount === 0}
              size="lg"
            >
              {generatingEmail && (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              )}
              <Mail className="mr-2 h-4 w-4" />
              Generate Email ({selectedCount} snippets)
            </Button>
            <div className="flex gap-2 ml-auto">
              <Button 
                onClick={() => selectAllMutation.mutate(undefined)}
                disabled={selectAllMutation.isPending}
                variant="outline"
                size="sm"
              >
                <CheckSquare className="mr-2 h-4 w-4" />
                Select All
              </Button>
              <Button 
                onClick={() => deselectAllMutation.mutate(undefined)}
                disabled={deselectAllMutation.isPending}
                variant="outline"
                size="sm"
              >
                <Square className="mr-2 h-4 w-4" />
                Deselect All
              </Button>
              <Button 
                onClick={() => resetMutation.mutate()}
                disabled={resetMutation.isPending}
                variant="ghost"
                size="sm"
              >
                <RotateCcw className="mr-2 h-4 w-4" />
                Re-scrape
              </Button>
            </div>
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            {/* Snippet List by Category */}
            <div className="lg:col-span-2 space-y-6">
              {snippetsLoading ? (
                <Card>
                  <CardContent className="py-8 text-center">
                    <RefreshCw className="h-6 w-6 animate-spin mx-auto text-muted-foreground" />
                    <p className="mt-2 text-muted-foreground">Loading snippets...</p>
                  </CardContent>
                </Card>
              ) : totalSnippets === 0 ? (
                <Card>
                  <CardContent className="py-8 text-center text-muted-foreground">
                    No snippets extracted. Try re-scraping the district.
                  </CardContent>
                </Card>
              ) : (
                Object.entries(SNIPPET_CATEGORIES).map(([categoryKey, config]) => {
                  const categorySnippets = snippetsByCategory[categoryKey] || []
                  if (categorySnippets.length === 0) return null
                  
                  const Icon = config.icon
                  const selectedInCategory = categorySnippets.filter(s => s.included_in_email).length
                  
                  return (
                    <Card key={categoryKey} className={`border-l-4 ${config.bgColor}`} style={{ borderLeftColor: config.color.replace('text-', 'var(--') + ')' }}>
                      <CardHeader className="pb-3">
                        <div className="flex items-center justify-between">
                          <CardTitle className="flex items-center gap-2 text-lg">
                            <Icon className={`h-5 w-5 ${config.color}`} />
                            {config.label}
                            <Badge variant="secondary" className="ml-2">
                              {selectedInCategory}/{categorySnippets.length}
                            </Badge>
                          </CardTitle>
                          <div className="flex gap-1">
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-8 px-2"
                              onClick={() => selectAllMutation.mutate(categoryKey)}
                            >
                              <CheckSquare className="h-4 w-4" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-8 px-2"
                              onClick={() => deselectAllMutation.mutate(categoryKey)}
                            >
                              <Square className="h-4 w-4" />
                            </Button>
                          </div>
                        </div>
                      </CardHeader>
                      <CardContent className="space-y-2">
                        {categorySnippets.map((snippet) => (
                          <SnippetItem
                            key={snippet.id}
                            snippet={snippet}
                            onToggle={(included) =>
                              toggleSnippetMutation.mutate({ id: snippet.id, included })
                            }
                          />
                        ))}
                      </CardContent>
                    </Card>
                  )
                })
              )}
            </div>

            {/* Right Sidebar */}
            <div className="space-y-6">
              {/* Generated Emails */}
              <Card>
                <CardHeader>
                  <CardTitle>Generated Emails</CardTitle>
                  <CardDescription>
                    Emails created for this district
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {emails?.length === 0 ? (
                    <p className="text-sm text-muted-foreground text-center py-4">
                      No emails generated yet
                    </p>
                  ) : (
                    <div className="space-y-3">
                      {emails?.map((email) => (
                        <div key={email.id} className="p-3 rounded-lg border">
                          <div className="flex items-center justify-between mb-2">
                            <Badge className={getStatusColor(email.status)}>
                              {email.status}
                            </Badge>
                          </div>
                          <p className="font-medium text-sm mb-1">
                            {email.subject_line}
                          </p>
                          <p className="text-xs text-muted-foreground line-clamp-2">
                            {email.email_body}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Identified Needs */}
              {district.identified_needs && (
                <Card>
                  <CardHeader>
                    <CardTitle>Identified Needs</CardTitle>
                    <CardDescription>
                      AI-extracted from district content
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {((district.identified_needs as { pain_points?: string[]; priorities?: string[] })?.pain_points?.length ?? 0) > 0 && (
                      <div>
                        <p className="text-xs font-medium text-muted-foreground mb-2">PAIN POINTS</p>
                        <div className="flex flex-wrap gap-1">
                          {(district.identified_needs as { pain_points?: string[] })?.pain_points?.slice(0, 4).map((need, i) => (
                            <Badge key={i} variant="outline" className="text-xs">
                              {need}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}
                    {((district.identified_needs as { priorities?: string[] })?.priorities?.length ?? 0) > 0 && (
                      <div>
                        <p className="text-xs font-medium text-muted-foreground mb-2">PRIORITIES</p>
                        <div className="flex flex-wrap gap-1">
                          {(district.identified_needs as { priorities?: string[] })?.priorities?.slice(0, 4).map((priority, i) => (
                            <Badge key={i} variant="secondary" className="text-xs">
                              {priority}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function SnippetItem({ 
  snippet, 
  onToggle 
}: { 
  snippet: Snippet
  onToggle: (included: boolean) => void
}) {
  return (
    <div 
      className={`p-3 rounded-lg border transition-all cursor-pointer ${
        snippet.included_in_email 
          ? 'border-primary bg-primary/5 ring-1 ring-primary/20' 
          : 'hover:bg-muted/50'
      }`}
      onClick={() => onToggle(!snippet.included_in_email)}
    >
      <div className="flex items-start gap-3">
        <div className={`mt-0.5 shrink-0 w-5 h-5 rounded border-2 flex items-center justify-center ${
          snippet.included_in_email 
            ? 'bg-primary border-primary text-primary-foreground' 
            : 'border-muted-foreground/30'
        }`}>
          {snippet.included_in_email && <Check className="h-3 w-3" />}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm leading-relaxed">{snippet.snippet_text}</p>
          {snippet.relevance_note && (
            <p className="text-xs text-muted-foreground mt-1 italic">
              → {snippet.relevance_note}
            </p>
          )}
          {snippet.matched_product && (
            <Badge variant="outline" className="mt-2 text-xs">
              {snippet.matched_product}
            </Badge>
          )}
        </div>
      </div>
    </div>
  )
}
