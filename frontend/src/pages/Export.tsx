import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { 
  Download,
  RefreshCw,
  CheckCircle,
  FileSpreadsheet
} from 'lucide-react'
import { toast } from '@/components/ui/use-toast'
import { getStatusColor } from '@/lib/utils'

export default function Export() {
  const { data: preview, isLoading, refetch } = useQuery({
    queryKey: ['export-preview'],
    queryFn: () => api.emails.previewExport('approved'),
  })

  const { data: draftPreview } = useQuery({
    queryKey: ['export-preview-draft'],
    queryFn: () => api.emails.previewExport('draft'),
  })

  const exportMutation = useMutation({
    mutationFn: async () => {
      const response = await api.emails.export('approved')
      if (!response.ok) {
        throw new Error('Export failed')
      }
      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `wceps_emails_${new Date().toISOString().slice(0, 10)}.csv`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    },
    onSuccess: () => {
      toast({ title: 'Export complete', description: 'CSV file downloaded' })
      refetch()
    },
    onError: (error) => {
      toast({
        title: 'Export failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })

  const approvedCount = preview?.count || 0
  const draftCount = draftPreview?.count || 0

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Export</h1>
        <p className="text-muted-foreground">
          Export emails to Salesforce Account Engagement CSV format
        </p>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center">
                <CheckCircle className="h-6 w-6 text-green-600" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Ready to Export</p>
                <p className="text-2xl font-bold">{approvedCount}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-full bg-yellow-100 flex items-center justify-center">
                <FileSpreadsheet className="h-6 w-6 text-yellow-600" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Drafts</p>
                <p className="text-2xl font-bold">{draftCount}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6 flex items-center justify-center">
            <Button
              size="lg"
              onClick={() => exportMutation.mutate()}
              disabled={exportMutation.isPending || approvedCount === 0}
              className="w-full"
            >
              {exportMutation.isPending ? (
                <RefreshCw className="mr-2 h-5 w-5 animate-spin" />
              ) : (
                <Download className="mr-2 h-5 w-5" />
              )}
              Download CSV
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* CSV Format Info */}
      <Card>
        <CardHeader>
          <CardTitle>Account Engagement CSV Format</CardTitle>
          <CardDescription>
            The exported CSV includes these columns for direct import
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            {[
              'Email',
              'First Name',
              'Last Name',
              'Title',
              'Company',
              'Salutation',
              'Email Opt Out',
              'Campaign',
              'Custom_Subject',
              'Custom_Body',
              'State',
              'District_ID',
              'Generated_At',
            ].map((col) => (
              <Badge key={col} variant="outline">
                {col}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Preview */}
      <Card>
        <CardHeader>
          <CardTitle>Export Preview</CardTitle>
          <CardDescription>
            {approvedCount} approved emails ready for export
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : approvedCount === 0 ? (
            <div className="text-center py-8">
              <p className="text-muted-foreground mb-4">
                No approved emails to export. Approve emails from the district detail pages.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {(preview?.emails as Array<{
                email_id: number
                district_name: string
                contact: { email: string; name: string; title: string } | null
                email: { subject: string; body_preview: string }
                status: string
              }>)?.map((item) => (
                <div key={item.email_id} className="p-4 rounded-lg border">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-2">
                        <Badge className={getStatusColor(item.status)}>
                          {item.status}
                        </Badge>
                        <span className="text-sm font-medium">
                          {item.district_name}
                        </span>
                      </div>
                      <p className="font-medium">{item.email.subject}</p>
                      <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                        {item.email.body_preview}
                      </p>
                      {item.contact && (
                        <div className="mt-2 text-xs text-muted-foreground">
                          To: {item.contact.name} ({item.contact.email})
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Instructions */}
      <Card>
        <CardHeader>
          <CardTitle>Import Instructions</CardTitle>
          <CardDescription>
            Steps to import the CSV into Salesforce Account Engagement
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <h4 className="font-medium">1. Prepare Account Engagement</h4>
            <p className="text-sm text-muted-foreground">
              Ensure custom fields (Custom_Subject, Custom_Body) are created in Account Engagement.
            </p>
          </div>
          <div className="space-y-2">
            <h4 className="font-medium">2. Download the CSV</h4>
            <p className="text-sm text-muted-foreground">
              Click the Download CSV button above to export approved emails.
            </p>
          </div>
          <div className="space-y-2">
            <h4 className="font-medium">3. Import to Account Engagement</h4>
            <p className="text-sm text-muted-foreground">
              Go to Prospects → Import → Upload CSV. Map the columns to your fields.
            </p>
          </div>
          <div className="space-y-2">
            <h4 className="font-medium">4. Create Email Template</h4>
            <p className="text-sm text-muted-foreground">
              Use merge fields to pull Custom_Subject and Custom_Body into your email template.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
