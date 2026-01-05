import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type ScrapedContent } from '@/lib/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { 
  ArrowLeft,
  RefreshCw,
  Check,
  X,
  Sparkles,
  Mail
} from 'lucide-react'
import { formatNumber, formatPercentage, getStatusColor, getScoreColor } from '@/lib/utils'
import { toast } from '@/components/ui/use-toast'
import { useState } from 'react'

export default function DistrictDetail() {
  const { districtId } = useParams<{ districtId: string }>()
  const queryClient = useQueryClient()
  const [generatingEmail, setGeneratingEmail] = useState(false)

  const { data: district, isLoading: districtLoading } = useQuery({
    queryKey: ['district', districtId],
    queryFn: () => api.districts.get(districtId!),
    enabled: !!districtId,
  })

  const { data: content, isLoading: contentLoading } = useQuery({
    queryKey: ['content', districtId],
    queryFn: () => api.content.listByDistrict(districtId!),
    enabled: !!districtId,
  })

  const { data: emails } = useQuery({
    queryKey: ['emails', districtId],
    queryFn: () => api.emails.list(districtId),
    enabled: !!districtId,
  })

  const toggleContentMutation = useMutation({
    mutationFn: ({ id, included }: { id: number; included: boolean }) =>
      api.content.update(id, { included_in_email: included }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['content', districtId] })
    },
  })

  const scoreContentMutation = useMutation({
    mutationFn: () => api.content.scoreAll(districtId!),
    onSuccess: () => {
      toast({ title: 'Content scored successfully' })
      queryClient.invalidateQueries({ queryKey: ['content', districtId] })
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

  // Group content by type
  const contentByType: Record<string, ScrapedContent[]> = {}
  content?.forEach((item) => {
    if (!contentByType[item.content_type]) {
      contentByType[item.content_type] = []
    }
    contentByType[item.content_type].push(item)
  })

  const selectedCount = content?.filter(c => c.included_in_email).length || 0

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
            <p className="text-sm text-muted-foreground">Content Items</p>
            <p className="text-2xl font-bold">{content?.length || 0}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">Selected for Email</p>
            <p className="text-2xl font-bold">{selectedCount}</p>
          </CardContent>
        </Card>
      </div>

      {/* Actions Bar */}
      <div className="flex gap-3">
        <Button 
          onClick={() => scoreContentMutation.mutate()}
          disabled={scoreContentMutation.isPending || !content?.length}
          variant="outline"
        >
          {scoreContentMutation.isPending && (
            <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
          )}
          <Sparkles className="mr-2 h-4 w-4" />
          Score All Content
        </Button>
        <Button
          onClick={handleGenerateEmail}
          disabled={generatingEmail || selectedCount === 0}
        >
          {generatingEmail && (
            <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
          )}
          <Mail className="mr-2 h-4 w-4" />
          Generate Email
        </Button>
      </div>

      {/* Content Curation */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Content List */}
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Content Curation</CardTitle>
              <CardDescription>
                Select content to include in the generated email
              </CardDescription>
            </CardHeader>
            <CardContent>
              {contentLoading ? (
                <div className="text-center py-8">
                  <RefreshCw className="h-6 w-6 animate-spin mx-auto text-muted-foreground" />
                </div>
              ) : content?.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  No content scraped yet. Run scraping first.
                </div>
              ) : (
                <div className="space-y-6">
                  {Object.entries(contentByType)
                    .filter(([type]) => type !== 'url_mapping' && type !== 'research_cache')
                    .map(([type, items]) => (
                      <div key={type}>
                        <h3 className="font-medium capitalize mb-3">
                          {type.replace('_', ' ')} ({items.length})
                        </h3>
                        <div className="space-y-2">
                          {items.map((item) => (
                            <ContentItem
                              key={item.id}
                              item={item}
                              onToggle={(included) =>
                                toggleContentMutation.mutate({ id: item.id, included })
                              }
                            />
                          ))}
                        </div>
                      </div>
                    ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Generated Emails */}
        <div className="space-y-6">
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
              </CardHeader>
              <CardContent className="space-y-3">
                {(district.identified_needs as { pain_points?: string[] }).pain_points?.map((need, i) => (
                  <Badge key={i} variant="outline" className="mr-1">
                    {need}
                  </Badge>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

function ContentItem({ 
  item, 
  onToggle 
}: { 
  item: ScrapedContent
  onToggle: (included: boolean) => void
}) {
  const score = item.scores?.[0]?.final_score || 0

  return (
    <div className={`p-3 rounded-lg border ${item.included_in_email ? 'border-primary bg-primary/5' : ''}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="font-medium text-sm truncate">{item.title}</p>
          <p className="text-xs text-muted-foreground line-clamp-2 mt-1">
            {item.summary || item.content.slice(0, 150)}
          </p>
          {score > 0 && (
            <div className="flex items-center gap-2 mt-2">
              <span className="text-xs text-muted-foreground">Score:</span>
              <span className={`text-xs font-medium ${getScoreColor(score)}`}>
                {(score * 100).toFixed(0)}%
              </span>
              {item.scores?.[0]?.matched_product && (
                <Badge variant="outline" className="text-xs">
                  {item.scores[0].matched_product}
                </Badge>
              )}
            </div>
          )}
        </div>
        <Button
          variant={item.included_in_email ? 'default' : 'outline'}
          size="sm"
          onClick={() => onToggle(!item.included_in_email)}
        >
          {item.included_in_email ? (
            <Check className="h-4 w-4" />
          ) : (
            <X className="h-4 w-4" />
          )}
        </Button>
      </div>
    </div>
  )
}
