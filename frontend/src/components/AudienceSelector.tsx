/**
 * AudienceSelector component for selecting target audiences.
 * Supports multi-select mode.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

// Audience descriptions and icons
const AUDIENCE_INFO: Record<string, { description: string; icon: string }> = {
  'District Leadership': {
    description: 'Superintendents, Assistant Superintendents, Chiefs',
    icon: '👔',
  },
  'Curriculum Directors': {
    description: 'Directors of Curriculum & Instruction',
    icon: '📋',
  },
  'ELL/Multilingual Directors': {
    description: 'Directors of ELL, ESL, Multilingual Programs',
    icon: '🌍',
  },
  'Principals': {
    description: 'Building-level administrators',
    icon: '🏫',
  },
  'Teachers': {
    description: 'Classroom teachers and specialists',
    icon: '👩‍🏫',
  },
  'Title III Coordinators': {
    description: 'Federal program coordinators',
    icon: '📑',
  },
}

interface AudienceSelectorProps {
  selectedAudiences: string[]
  onSelect: (audiences: string[]) => void
}

export function AudienceSelector({ selectedAudiences, onSelect }: AudienceSelectorProps) {
  const { data, isLoading } = useQuery({
    queryKey: ['audiences'],
    queryFn: api.research.getAudiences,
  })

  if (isLoading) {
    return (
      <div className="animate-pulse bg-slate-700 rounded-lg h-12"></div>
    )
  }

  const audiences = data?.audiences || []

  const handleToggleAudience = (audience: string) => {
    if (selectedAudiences.includes(audience)) {
      onSelect(selectedAudiences.filter(a => a !== audience))
    } else {
      onSelect([...selectedAudiences, audience])
    }
  }

  const handleSelectAll = () => {
    if (selectedAudiences.length === audiences.length) {
      onSelect([])
    } else {
      onSelect([...audiences])
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="block text-sm font-medium text-slate-300">
          Target Audience{selectedAudiences.length > 1 ? 's' : ''}
        </label>
        <button
          onClick={handleSelectAll}
          className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
        >
          {selectedAudiences.length === audiences.length ? 'Clear All' : 'Select All'}
        </button>
      </div>
      
      {selectedAudiences.length > 0 && (
        <div className="text-xs text-slate-400">
          {selectedAudiences.length} audience{selectedAudiences.length > 1 ? 's' : ''} selected
        </div>
      )}
      
      <div className="grid grid-cols-2 gap-2">
        {audiences.map((audience) => {
          const info = AUDIENCE_INFO[audience] || { description: '', icon: '👤' }
          const isSelected = selectedAudiences.includes(audience)
          
          return (
            <button
              key={audience}
              onClick={() => handleToggleAudience(audience)}
              className={`p-3 rounded-lg border text-left transition-all ${
                isSelected
                  ? 'bg-blue-600/20 border-blue-500 ring-2 ring-blue-500/50'
                  : 'bg-slate-800/50 border-slate-700 hover:bg-slate-700/50 hover:border-slate-600'
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="text-xl">{info.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className={`font-medium text-sm ${isSelected ? 'text-blue-400' : 'text-slate-200'}`}>
                    {audience}
                  </div>
                  <div className="text-xs text-slate-500 truncate">
                    {info.description}
                  </div>
                </div>
                <div className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-colors ${
                  isSelected 
                    ? 'bg-blue-500 border-blue-500' 
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
