import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { 
  RefreshCw,
  BookOpen,
  Search,
  Database
} from 'lucide-react'
import { toast } from '@/components/ui/use-toast'
import { useState } from 'react'

export default function KnowledgeBase() {
  const queryClient = useQueryClient()
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const fieldClass =
    'w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background'

  // Upload form state
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadCategory, setUploadCategory] = useState('email_example')
  const [uploadTitle, setUploadTitle] = useState('')
  const [uploadSubcategory, setUploadSubcategory] = useState('')
  const [uploadProduct, setUploadProduct] = useState('')
  const [uploadStatesInput, setUploadStatesInput] = useState('')
  const [uploadAudience, setUploadAudience] = useState('')
  const [uploadMessage, setUploadMessage] = useState('')
  const [uploadTiming, setUploadTiming] = useState('')
  const [uploadTagsInput, setUploadTagsInput] = useState('')
  const [uploadNotes, setUploadNotes] = useState('')

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['kb-stats'],
    queryFn: api.kb.stats,
  })

  const { data: researchProducts } = useQuery({
    queryKey: ['research-products'],
    queryFn: api.research.getProducts,
  })

  const { data: researchStates } = useQuery({
    queryKey: ['research-states'],
    queryFn: api.research.getStates,
  })

  const { data: researchAudiences } = useQuery({
    queryKey: ['research-audiences'],
    queryFn: api.research.getAudiences,
  })

  const { data: products } = useQuery({
    queryKey: ['kb-products'],
    queryFn: api.kb.products,
  })

  const { data: states } = useQuery({
    queryKey: ['kb-states'],
    queryFn: api.kb.states,
  })

  const { data: items, isLoading: itemsLoading } = useQuery({
    queryKey: ['kb-items', selectedCategory],
    queryFn: () => api.kb.list({ category: selectedCategory || undefined }),
    enabled: !!selectedCategory,
  })

  const { data: searchResults, isLoading: searchLoading } = useQuery({
    queryKey: ['kb-search', searchQuery],
    queryFn: () => api.kb.search(searchQuery),
    enabled: searchQuery.length >= 2,
  })

  const indexMutation = useMutation({
    mutationFn: api.kb.index,
    onSuccess: (data) => {
      toast({ title: 'Knowledge base indexed', description: data.message })
      queryClient.invalidateQueries({ queryKey: ['kb'] })
    },
    onError: (error) => {
      toast({
        title: 'Error indexing',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!uploadFile) {
        throw new Error('Please choose a .docx or .pdf file')
      }

      const formData = new FormData()
      formData.append('file', uploadFile)
      formData.append('category', uploadCategory)
      if (uploadTitle.trim()) formData.append('title', uploadTitle.trim())
      if (uploadSubcategory.trim()) formData.append('subcategory', uploadSubcategory.trim())
      if (uploadProduct.trim()) formData.append('product', uploadProduct.trim())

      // Comma-separated inputs -> repeated form fields
      const states = uploadStatesInput
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      states.forEach((s) => formData.append('states', s))

      if (uploadAudience.trim()) formData.append('audience', uploadAudience.trim())
      if (uploadMessage.trim()) formData.append('message', uploadMessage.trim())
      if (uploadTiming.trim()) formData.append('timing', uploadTiming.trim())

      const tags = uploadTagsInput
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean)
      tags.forEach((t) => formData.append('tags', t))

      if (uploadNotes.trim()) formData.append('notes', uploadNotes.trim())

      return api.kb.upload(formData)
    },
    onSuccess: (data) => {
      toast({ title: 'Uploaded to knowledge base', description: data.id })
      setUploadFile(null)
      setUploadTitle('')
      setUploadSubcategory('')
      setUploadProduct('')
      setUploadStatesInput('')
      setUploadAudience('')
      setUploadMessage('')
      setUploadTiming('')
      setUploadTagsInput('')
      setUploadNotes('')
      queryClient.invalidateQueries({ queryKey: ['kb-stats'] })
      queryClient.invalidateQueries({ queryKey: ['kb-search'] })
      queryClient.invalidateQueries({ queryKey: ['kb-items'] })
      queryClient.invalidateQueries({ queryKey: ['kb-products'] })
      queryClient.invalidateQueries({ queryKey: ['kb-states'] })
    },
    onError: (error) => {
      toast({
        title: 'Upload failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      })
    },
  })

  const exportEmailExamples = async () => {
    try {
      const state = uploadStatesInput
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)[0]
      const blob = await api.kb.exportEmailExamples({
        product: uploadProduct.trim() || undefined,
        audience: uploadAudience.trim() || undefined,
        state: state || undefined,
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'wceps_email_examples.jsonl'
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      toast({
        title: 'Export failed',
        description: e instanceof Error ? e.message : 'Unknown error',
        variant: 'destructive',
      })
    }
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Knowledge Base</h1>
          <p className="text-muted-foreground">
            Products, case studies, and state-specific content
          </p>
        </div>
        <Button 
          onClick={() => indexMutation.mutate()}
          disabled={indexMutation.isPending}
        >
          {indexMutation.isPending && (
            <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
          )}
          <Database className="mr-2 h-4 w-4" />
          Re-index KB
        </Button>
      </div>

      {/* Upload */}
      <Card>
        <CardHeader>
          <CardTitle>Upload to Knowledge Base</CardTitle>
          <CardDescription>
            Add docs (including “good email” examples) with structured tags so the generator can learn from them.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">File (.docx or .pdf)</label>
              <input
                type="file"
                accept=".docx,.pdf"
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
              />
              {uploadFile && (
                <p className="text-xs text-muted-foreground">Selected: {uploadFile.name}</p>
              )}
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Category</label>
              <select
                value={uploadCategory}
                onChange={(e) => setUploadCategory(e.target.value)}
                className={fieldClass}
              >
                <option value="email_example">email_example (good email)</option>
                <option value="state_content">state_content</option>
                <option value="product">product</option>
                <option value="case_study">case_study</option>
                <option value="testimonial">testimonial</option>
                <option value="general">general</option>
              </select>
              {uploadCategory === 'email_example' && (
                <p className="text-xs text-muted-foreground">
                  Tip: set <b>Title</b> to the subject line; file content becomes the email body.
                </p>
              )}
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Title</label>
              <input
                type="text"
                placeholder={uploadCategory === 'email_example' ? 'Subject line' : 'Document title (optional)'}
                value={uploadTitle}
                onChange={(e) => setUploadTitle(e.target.value)}
                className={fieldClass}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Subcategory (optional)</label>
              <input
                type="text"
                placeholder="e.g. care_coaching, florida, value_proposition"
                value={uploadSubcategory}
                onChange={(e) => setUploadSubcategory(e.target.value)}
                className={fieldClass}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Product (optional)</label>
              <select
                value={uploadProduct}
                onChange={(e) => setUploadProduct(e.target.value)}
                className={fieldClass}
              >
                <option value="">(none)</option>
                {(researchProducts?.products || []).map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">States (optional)</label>
              <input
                type="text"
                placeholder="Comma-separated codes, e.g. FL, CO"
                value={uploadStatesInput}
                onChange={(e) => setUploadStatesInput(e.target.value)}
                className={fieldClass}
                list="kb-upload-states"
              />
              <datalist id="kb-upload-states">
                {(researchStates?.states || []).map((s) => (
                  <option key={s.code} value={s.code} />
                ))}
              </datalist>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Audience (optional)</label>
              <select
                value={uploadAudience}
                onChange={(e) => setUploadAudience(e.target.value)}
                className={fieldClass}
              >
                <option value="">(none)</option>
                {(researchAudiences?.audiences || []).map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Message type (optional)</label>
              <input
                type="text"
                placeholder="e.g. funding, compliance, product"
                value={uploadMessage}
                onChange={(e) => setUploadMessage(e.target.value)}
                className={fieldClass}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Timing (optional)</label>
              <input
                type="text"
                placeholder="e.g. back_to_school, budget_planning"
                value={uploadTiming}
                onChange={(e) => setUploadTiming(e.target.value)}
                className={fieldClass}
              />
            </div>

            <div className="space-y-2 md:col-span-2">
              <label className="text-sm font-medium">Tags (optional)</label>
              <input
                type="text"
                placeholder="Comma-separated tags"
                value={uploadTagsInput}
                onChange={(e) => setUploadTagsInput(e.target.value)}
                className={fieldClass}
              />
            </div>

            <div className="space-y-2 md:col-span-2">
              <label className="text-sm font-medium">Notes (optional)</label>
              <textarea
                placeholder="Short internal note (kept out of prompt as much as possible)"
                value={uploadNotes}
                onChange={(e) => setUploadNotes(e.target.value)}
                className={`${fieldClass} min-h-[88px]`}
              />
            </div>
          </div>

          <div className="flex flex-wrap gap-3 mt-4">
            <Button
              onClick={() => uploadMutation.mutate()}
              disabled={uploadMutation.isPending}
            >
              {uploadMutation.isPending && (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              )}
              Upload
            </Button>

            <Button
              variant="outline"
              onClick={exportEmailExamples}
              disabled={uploadMutation.isPending}
            >
              Export email examples (JSONL)
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Stats */}
      {statsLoading ? (
        <div className="flex items-center justify-center py-8">
          <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : stats?.total_items === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12">
            <BookOpen className="h-12 w-12 text-muted-foreground mb-4" />
            <h3 className="text-lg font-medium mb-2">Knowledge Base Empty</h3>
            <p className="text-muted-foreground text-center mb-4">
              Index your knowledge base to enable product matching and content recommendations.
            </p>
            <Button 
              onClick={() => indexMutation.mutate()}
              disabled={indexMutation.isPending}
            >
              Index Knowledge Base
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">Total Items</p>
              <p className="text-2xl font-bold">{stats?.total_items.toLocaleString()}</p>
            </CardContent>
          </Card>
          {Object.entries(stats?.by_category || {}).map(([category, count]) => (
            <Card 
              key={category}
              className={`cursor-pointer transition-colors ${
                selectedCategory === category ? 'border-primary' : 'hover:border-primary/50'
              }`}
              onClick={() => setSelectedCategory(
                selectedCategory === category ? null : category
              )}
            >
              <CardContent className="pt-6">
                <p className="text-sm text-muted-foreground capitalize">
                  {category.replace('_', ' ')}
                </p>
                <p className="text-2xl font-bold">{count}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Search */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-5 w-5" />
            Search Knowledge Base
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="relative">
            <input
              type="text"
              placeholder="Search for products, case studies, funding info..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={fieldClass}
            />
          </div>
          {searchLoading && (
            <div className="flex items-center justify-center py-8">
              <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}
          {searchResults && searchResults.length > 0 && (
            <div className="mt-4 space-y-2">
              {searchResults.map((item) => (
                <div key={item.id} className="p-3 rounded-lg border bg-card/50 hover:bg-card/80 transition-colors">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant="outline" className="text-xs">
                      {item.category}
                    </Badge>
                    {item.product_name && (
                      <Badge className="text-xs">{item.product_name}</Badge>
                    )}
                  </div>
                  <p className="font-medium text-sm">{item.title}</p>
                  <p className="text-xs text-muted-foreground line-clamp-2 mt-1">
                    {item.summary}
                  </p>
                </div>
              ))}
            </div>
          )}
          {searchQuery.length >= 2 && searchResults?.length === 0 && !searchLoading && (
            <p className="text-sm text-muted-foreground text-center py-4">
              No results found
            </p>
          )}
        </CardContent>
      </Card>

      {/* Products & States */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Products</CardTitle>
            <CardDescription>WCEPS products in knowledge base</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {products?.products.map((product) => (
                <Badge key={product} variant="secondary" className="capitalize">
                  {product.replace('_', ' ')}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>States with Content</CardTitle>
            <CardDescription>State-specific funding and compliance</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {states?.states.map((state) => (
                <Badge key={state} variant="outline">
                  {state}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Category Items */}
      {selectedCategory && (
        <Card>
          <CardHeader>
            <CardTitle className="capitalize">
              {selectedCategory.replace('_', ' ')} Items
            </CardTitle>
          </CardHeader>
          <CardContent>
            {itemsLoading ? (
              <div className="flex items-center justify-center py-8">
                <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="space-y-2 max-h-96 overflow-auto">
                {items?.map((item) => (
                  <div key={item.id} className="p-3 rounded-lg border bg-card/50 hover:bg-card/80 transition-colors">
                    <div className="flex items-center gap-2 mb-1">
                      {item.product_name && (
                        <Badge className="text-xs">{item.product_name}</Badge>
                      )}
                      {item.applicable_states?.map((state) => (
                        <Badge key={state} variant="outline" className="text-xs">
                          {state}
                        </Badge>
                      ))}
                    </div>
                    <p className="font-medium text-sm">{item.title}</p>
                    <p className="text-xs text-muted-foreground line-clamp-2 mt-1">
                      {item.summary}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
