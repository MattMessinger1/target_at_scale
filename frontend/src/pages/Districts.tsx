import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type District } from '@/lib/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { 
  Building2, 
  RefreshCw,
  ExternalLink,
  Play
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { formatNumber, formatPercentage, getStatusColor, formatDate } from '@/lib/utils'
import { toast } from '@/components/ui/use-toast'

function getScrapeProgress(phase: string | null): number {
  switch (phase) {
    case 'mapping': return 20
    case 'contacts': return 50
    case 'research': return 80
    default: return 100
  }
}

export default function Districts() {
  const queryClient = useQueryClient()
  
  const { data: districts, isLoading } = useQuery({
    queryKey: ['districts'],
    queryFn: api.districts.list,
  })

  const scrapeMutation = useMutation({
    mutationFn: (districtId: string) => api.districts.scrape(districtId),
    onSuccess: () => {
      toast({
        title: 'Scraping started',
        description: `Started scraping district data`,
      })
      queryClient.invalidateQueries({ queryKey: ['districts'] })
    },
    onError: (error) => {
      toast({
        title: 'Error',
        description: error instanceof Error ? error.message : 'Failed to start scraping',
        variant: 'destructive',
      })
    },
  })

  const loadPilotMutation = useMutation({
    mutationFn: api.districts.loadPilot,
    onSuccess: (data) => {
      toast({
        title: 'Districts loaded',
        description: data.message,
      })
      queryClient.invalidateQueries({ queryKey: ['districts'] })
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Districts</h1>
          <p className="text-muted-foreground">
            Manage and scrape school district data
          </p>
        </div>
        {districts?.length === 0 && (
          <Button 
            onClick={() => loadPilotMutation.mutate()}
            disabled={loadPilotMutation.isPending}
          >
            {loadPilotMutation.isPending && (
              <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
            )}
            Load Pilot Districts
          </Button>
        )}
      </div>

      {/* Districts Grid */}
      {districts?.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Building2 className="h-12 w-12 text-muted-foreground mb-4" />
            <h3 className="text-lg font-medium mb-2">No Districts</h3>
            <p className="text-muted-foreground text-center mb-4">
              Load the pilot districts to get started with the email generation pipeline.
            </p>
            <Button 
              onClick={() => loadPilotMutation.mutate()}
              disabled={loadPilotMutation.isPending}
            >
              Load Pilot Districts
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {districts?.map((district) => (
            <DistrictCard 
              key={district.id} 
              district={district}
              onScrape={() => scrapeMutation.mutate(district.id)}
              isScraping={scrapeMutation.isPending && scrapeMutation.variables === district.id}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function DistrictCard({ 
  district, 
  onScrape, 
  isScraping 
}: { 
  district: District
  onScrape: () => void
  isScraping: boolean
}) {
  const isInProgress = district.scrape_status === 'in_progress'
  const progress = isInProgress ? getScrapeProgress(district.scrape_phase) : 
    district.scrape_status === 'completed' ? 100 : 0

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center">
              <span className="text-lg font-bold text-primary">
                {district.state}
              </span>
            </div>
            <div>
              <CardTitle className="text-lg">{district.name}</CardTitle>
              <CardDescription>{district.state_full}</CardDescription>
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Stats */}
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-muted-foreground">Students</p>
            <p className="font-medium">{formatNumber(district.student_count)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">EL Population</p>
            <p className="font-medium">{formatPercentage(district.el_percentage)}</p>
          </div>
        </div>

        {/* Scrape Status */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Badge className={getStatusColor(district.scrape_status)}>
              {district.scrape_status}
              {district.scrape_phase && ` - ${district.scrape_phase}`}
            </Badge>
            {district.last_scraped_at && (
              <span className="text-xs text-muted-foreground">
                {formatDate(district.last_scraped_at)}
              </span>
            )}
          </div>
          {(isInProgress || progress > 0) && (
            <Progress value={progress} className="h-1" />
          )}
        </div>

        {/* Identified Needs */}
        {district.identified_needs && (
          <div className="text-sm">
            <p className="text-muted-foreground mb-1">Identified Needs:</p>
            <div className="flex flex-wrap gap-1">
              {(district.identified_needs as { pain_points?: string[] }).pain_points?.slice(0, 3).map((need, i) => (
                <Badge key={i} variant="outline" className="text-xs">
                  {need}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 pt-2">
          <Link to={`/districts/${district.id}`} className="flex-1">
            <Button variant="outline" className="w-full" size="sm">
              View Details
            </Button>
          </Link>
          {district.scrape_status === 'pending' && (
            <Button 
              size="sm" 
              onClick={onScrape}
              disabled={isScraping}
            >
              {isScraping ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                <>
                  <Play className="mr-1 h-4 w-4" />
                  Scrape
                </>
              )}
            </Button>
          )}
          <a 
            href={district.website_url} 
            target="_blank" 
            rel="noopener noreferrer"
          >
            <Button variant="ghost" size="sm">
              <ExternalLink className="h-4 w-4" />
            </Button>
          </a>
        </div>
      </CardContent>
    </Card>
  )
}
