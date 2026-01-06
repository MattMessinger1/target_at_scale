/**
 * ProductSelector component for selecting WCEPS products.
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
  selectedProduct: string
  onSelect: (product: string) => void
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

  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium text-slate-300">
        Select Product
      </label>
      
      <div className="grid grid-cols-1 gap-2">
        {products.map((product) => {
          const info = PRODUCT_INFO[product] || { description: '', icon: '📦' }
          const isSelected = selectedProduct === product
          
          return (
            <button
              key={product}
              onClick={() => onSelect(product)}
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
                {isSelected && (
                  <span className="text-emerald-400">
                    <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  </span>
                )}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
