import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { 
  Building2, 
  Users, 
  Mail, 
  BookOpen,
  RefreshCw,
  ArrowRight
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { formatNumber, getStatusColor } from '@/lib/utils'

export default function Dashboard() {
  const queryClient = useQueryClient()

  const { data: districts, isLoading: districtsLoading } = useQuery({
    queryKey: ['districts'],
    queryFn: api.districts.list,
  })

  const { data: emails } = useQuery({
    queryKey: ['emails'],
    queryFn: () => api.emails.list(),
  })

  const { data: kbStats } = useQuery({
    queryKey: ['kb-stats'],
    queryFn: api.kb.stats,
  })

  const loadPilotDistricts = useMutation({
    mutationFn: api.districts.loadPilot,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['districts'] })
    },
  })

  const stats = {
    totalDistricts: districts?.length || 0,
    scrapedDistricts: districts?.filter(d => d.scrape_status === 'completed').length || 0,
    totalEmails: emails?.length || 0,
    approvedEmails: emails?.filter(e => e.status === 'approved').length || 0,
    kbItems: kbStats?.total_items || 0,
  }

  const scrapeProgress = stats.totalDistricts > 0 
    ? (stats.scrapedDistricts / stats.totalDistricts) * 100 
    : 0

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">
          WCEPS Email Generator - Pilot Program
        </p>
      </div>

      {/* Quick Actions */}
      {stats.totalDistricts === 0 && (
        <Card className="border-dashed">
          <CardHeader>
            <CardTitle>Get Started</CardTitle>
            <CardDescription>
              Load the 5 pilot districts to begin
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button 
              onClick={() => loadPilotDistricts.mutate()}
              disabled={loadPilotDistricts.isPending}
            >
              {loadPilotDistricts.isPending && (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              )}
              Load Pilot Districts
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Stats Grid */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Districts</CardTitle>
            <Building2 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.totalDistricts}</div>
            <p className="text-xs text-muted-foreground">
              {stats.scrapedDistricts} scraped
            </p>
            <Progress value={scrapeProgress} className="mt-2 h-1" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Emails Generated</CardTitle>
            <Mail className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.totalEmails}</div>
            <p className="text-xs text-muted-foreground">
              {stats.approvedEmails} approved
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Knowledge Base</CardTitle>
            <BookOpen className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatNumber(stats.kbItems)}</div>
            <p className="text-xs text-muted-foreground">
              indexed items
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Ready to Export</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.approvedEmails}</div>
            <p className="text-xs text-muted-foreground">
              emails approved
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Districts Overview */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Pilot Districts</CardTitle>
            <CardDescription>
              5 diverse districts across WIDA states
            </CardDescription>
          </div>
          <Link to="/districts">
            <Button variant="outline" size="sm">
              View All
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </Link>
        </CardHeader>
        <CardContent>
          {districtsLoading ? (
            <div className="text-center py-8 text-muted-foreground">
              Loading districts...
            </div>
          ) : districts?.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No districts loaded yet. Click "Load Pilot Districts" to start.
            </div>
          ) : (
            <div className="space-y-4">
              {districts?.slice(0, 5).map((district) => (
                <div
                  key={district.id}
                  className="flex items-center justify-between p-4 rounded-lg border"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                      <span className="text-sm font-bold text-primary">
                        {district.state}
                      </span>
                    </div>
                    <div>
                      <p className="font-medium">{district.name}</p>
                      <p className="text-sm text-muted-foreground">
                        {formatNumber(district.student_count)} students
                        {district.el_percentage && ` • ${district.el_percentage}% EL`}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge className={getStatusColor(district.scrape_status)}>
                      {district.scrape_status}
                    </Badge>
                    <Link to={`/districts/${district.id}`}>
                      <Button variant="ghost" size="sm">
                        <ArrowRight className="h-4 w-4" />
                      </Button>
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* KB Categories */}
      {kbStats && Object.keys(kbStats.by_category).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Knowledge Base Categories</CardTitle>
            <CardDescription>
              Content available for email generation
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {Object.entries(kbStats.by_category).map(([category, count]) => (
                <div
                  key={category}
                  className="p-4 rounded-lg border text-center"
                >
                  <p className="text-2xl font-bold">{count}</p>
                  <p className="text-sm text-muted-foreground capitalize">
                    {category.replace('_', ' ')}
                  </p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
