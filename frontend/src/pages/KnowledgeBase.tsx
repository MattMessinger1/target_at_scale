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

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['kb-stats'],
    queryFn: api.kb.stats,
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
              className="w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
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
                <div key={item.id} className="p-3 rounded-lg border">
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
                  <div key={item.id} className="p-3 rounded-lg border">
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
