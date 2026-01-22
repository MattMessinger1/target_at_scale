/**
 * ProductSelector component for selecting a single WCEPS product.
 * Single-select mode - one product per email generation session.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

// Product descriptions for tooltips
const PRODUCT_INFO: Record<string, { description: string; icon: string }> = {
  'CARE Coaching': {
    description: 'Job-embedded professional development through coaching',
    icon: '🎯',
  },
  'WIDA Professional Learning': {
    description: 'Educator PD for EL instructional strategies',
    icon: '📚',
  },
  'WebbAlign': {
    description: 'Depth of Knowledge alignment and assessment tools',
    icon: '📊',
  },
  'CALL': {
    description: 'School-wide leadership assessment for distributed leadership practices',
    icon: '📋',
  },
  'The Discussion Project': {
    description: 'Academic discourse and discussion-based learning',
    icon: '🗣️',
  },
  'WIDA MODEL Online': {
    description: 'Interim English language proficiency assessment',
    icon: '📝',
  },
  'WIDA SIS': {
    description: 'Student information system for EL program management',
    icon: '💻',
  },
}

interface ProductSelectorProps {
  selectedProduct: string | null
  onSelect: (product: string | null) => void
}

export function ProductSelector({ selectedProduct, onSelect }: ProductSelectorProps) {
  const { data, isLoading } = useQuery({
    queryKey: ['products'],
    queryFn: api.research.getProducts,
  })

  if (isLoading) {
    return (
      <div className="animate-pulse bg-slate-700 rounded-lg h-12"></div>
    )
  }

  const products = data?.products || []

  const handleSelectProduct = (product: string) => {
    // Toggle off if clicking the same product, otherwise select the new one
    if (selectedProduct === product) {
      onSelect(null)
    } else {
      onSelect(product)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="block text-sm font-medium text-slate-300">
          Select Product
        </label>
        {selectedProduct && (
          <button
            onClick={() => onSelect(null)}
            className="text-xs text-slate-400 hover:text-slate-300 transition-colors"
          >
            Clear
          </button>
        )}
      </div>
      
      {selectedProduct && (
        <div className="text-xs text-emerald-400">
          1 product selected
        </div>
      )}
      
      <div className="grid grid-cols-1 gap-2">
        {products.map((product) => {
          const info = PRODUCT_INFO[product] || { description: '', icon: '📦' }
          const isSelected = selectedProduct === product
          
          return (
            <button
              key={product}
              onClick={() => handleSelectProduct(product)}
              className={`p-4 rounded-lg border text-left transition-all ${
                isSelected
                  ? 'bg-emerald-600/20 border-emerald-500 ring-2 ring-emerald-500/50'
                  : 'bg-slate-800/50 border-slate-700 hover:bg-slate-700/50 hover:border-slate-600'
              }`}
            >
              <div className="flex items-start gap-3">
                <span className="text-2xl">{info.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className={`font-medium ${isSelected ? 'text-emerald-400' : 'text-slate-200'}`}>
                    {product}
                  </div>
                  <div className="text-sm text-slate-400 mt-0.5">
                    {info.description}
                  </div>
                </div>
                <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center transition-colors ${
                  isSelected 
                    ? 'bg-emerald-500 border-emerald-500' 
                    : 'border-slate-500'
                }`}>
                  {isSelected && (
                    <div className="w-2 h-2 rounded-full bg-white"></div>
                  )}
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
