/**
 * AudienceSelector component for selecting target audiences.
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
  selectedAudience: string
  onSelect: (audience: string) => void
}

export function AudienceSelector({ selectedAudience, onSelect }: AudienceSelectorProps) {
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

  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium text-slate-300">
        Target Audience
      </label>
      
      <div className="grid grid-cols-2 gap-2">
        {audiences.map((audience) => {
          const info = AUDIENCE_INFO[audience] || { description: '', icon: '👤' }
          const isSelected = selectedAudience === audience
          
          return (
            <button
              key={audience}
              onClick={() => onSelect(audience)}
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
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
