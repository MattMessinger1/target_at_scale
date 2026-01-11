/**
 * ProductSelector component for selecting WCEPS products.
 * Supports multi-select mode.
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
    description: 'Assessment and curriculum alignment tools',
    icon: '📊',
  },
  'CALL': {
    description: 'Academic language assessment and intervention',
    icon: '💬',
  },
  'The Discussion Project': {
    description: 'Academic discourse and discussion-based learning',
    icon: '🗣️',
  },
  'WIDA MODEL Online': {
    description: 'English language proficiency assessment',
    icon: '📝',
  },
  'WIDA SIS': {
    description: 'Student information systems for EL programs',
    icon: '💻',
  },
}

interface ProductSelectorProps {
  selectedProducts: string[]
  onSelect: (products: string[]) => void
}

export function ProductSelector({ selectedProducts, onSelect }: ProductSelectorProps) {
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

  const handleToggleProduct = (product: string) => {
    if (selectedProducts.includes(product)) {
      onSelect(selectedProducts.filter(p => p !== product))
    } else {
      onSelect([...selectedProducts, product])
    }
  }

  const handleSelectAll = () => {
    if (selectedProducts.length === products.length) {
      onSelect([])
    } else {
      onSelect([...products])
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="block text-sm font-medium text-slate-300">
          Select Product{selectedProducts.length > 1 ? 's' : ''}
        </label>
        <button
          onClick={handleSelectAll}
          className="text-xs text-emerald-400 hover:text-emerald-300 transition-colors"
        >
          {selectedProducts.length === products.length ? 'Clear All' : 'Select All'}
        </button>
      </div>
      
      {selectedProducts.length > 0 && (
        <div className="text-xs text-slate-400">
          {selectedProducts.length} product{selectedProducts.length > 1 ? 's' : ''} selected
        </div>
      )}
      
      <div className="grid grid-cols-1 gap-2">
        {products.map((product) => {
          const info = PRODUCT_INFO[product] || { description: '', icon: '📦' }
          const isSelected = selectedProducts.includes(product)
          
          return (
            <button
              key={product}
              onClick={() => handleToggleProduct(product)}
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
                <div className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-colors ${
                  isSelected 
                    ? 'bg-emerald-500 border-emerald-500' 
                    : 'border-slate-500'
                }`}>
                  {isSelected && (
                    <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
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
