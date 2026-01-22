/**
 * AudienceSelector component for selecting target audience.
 * Supports product-specific audience options for WebbAlign and CALL.
 */
import { useEffect } from 'react'

// Default audience descriptions
const DEFAULT_AUDIENCE_INFO: Record<string, { description: string; icon: string }> = {
  'Decision Makers': {
    description: 'Superintendents, ESOL Directors, Curriculum Leaders, Title III Coordinators',
    icon: '💼',
  },
  'Users': {
    description: 'Teachers, Instructional Coaches (for training invites)',
    icon: '👩‍🏫',
  },
}

// Product-specific audience configurations
const PRODUCT_AUDIENCES: Record<string, { 
  audiences: string[]
  info: Record<string, { description: string; icon: string }> 
}> = {
  'WebbAlign': {
    audiences: ['WebbAlign Decision Makers', 'Users'],
    info: {
      'WebbAlign Decision Makers': {
        description: 'State and district assessment leaders, State and district curriculum leaders',
        icon: '📊',
      },
      'Users': DEFAULT_AUDIENCE_INFO['Users'],
    }
  },
  'CALL': {
    audiences: ['CALL Decision Makers', 'Users'],
    info: {
      'CALL Decision Makers': {
        description: 'State and district School Improvement leaders',
        icon: '📋',
      },
      'Users': DEFAULT_AUDIENCE_INFO['Users'],
    }
  }
}

const DEFAULT_AUDIENCES = ['Decision Makers', 'Users'] as const

interface AudienceSelectorProps {
  selectedAudience: string
  onSelect: (audience: string) => void
  selectedProduct?: string | null
}

export function AudienceSelector({ selectedAudience, onSelect, selectedProduct = null }: AudienceSelectorProps) {
  // Determine which audiences to show based on selected product
  const productConfig = selectedProduct ? PRODUCT_AUDIENCES[selectedProduct] : null
  
  const audiences = productConfig?.audiences || [...DEFAULT_AUDIENCES]
  const audienceInfo = productConfig?.info || DEFAULT_AUDIENCE_INFO

  // Auto-select first audience if current selection is not valid for the product
  useEffect(() => {
    if (audiences.length > 0 && !audiences.includes(selectedAudience)) {
      onSelect(audiences[0])
    }
  }, [selectedProduct, audiences, selectedAudience, onSelect])

  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium text-slate-300">
        Target Audience
      </label>
      
      <div className="flex gap-3">
        {audiences.map((audience) => {
          const info = audienceInfo[audience] || DEFAULT_AUDIENCE_INFO['Decision Makers']
          const isSelected = selectedAudience === audience
          
          return (
            <button
              key={audience}
              onClick={() => onSelect(audience)}
              className={`flex-1 p-4 rounded-lg border text-left transition-all ${
                isSelected
                  ? 'bg-blue-600/20 border-blue-500 ring-2 ring-blue-500/50'
                  : 'bg-slate-800/50 border-slate-700 hover:bg-slate-700/50 hover:border-slate-600'
              }`}
            >
              <div className="flex items-center gap-3">
                <span className="text-2xl">{info.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className={`font-medium ${isSelected ? 'text-blue-400' : 'text-slate-200'}`}>
                    {audience}
                  </div>
                  <div className="text-xs text-slate-400 mt-0.5">
                    {info.description}
                  </div>
                </div>
                <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center transition-colors ${
                  isSelected 
                    ? 'bg-blue-500 border-blue-500' 
                    : 'border-slate-500'
                }`}>
                  {isSelected && (
                    <div className="w-2 h-2 rounded-full bg-white" />
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
