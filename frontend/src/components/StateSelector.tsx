/**
 * StateSelector component for selecting US states.
 * Includes all 50 states with WIDA preset option.
 */
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, StateInfo } from '../lib/api'

interface StateSelectorProps {
  selectedState: string
  onSelect: (stateCode: string, stateName: string) => void
}

export function StateSelector({ selectedState, onSelect }: StateSelectorProps) {
  const [showWidaOnly, setShowWidaOnly] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['states'],
    queryFn: api.research.getStates,
  })

  const filteredStates = useMemo(() => {
    if (!data?.states) return []
    
    let states = data.states
    
    if (showWidaOnly) {
      states = states.filter(s => s.is_wida)
    }
    
    if (searchTerm) {
      const term = searchTerm.toLowerCase()
      states = states.filter(s => 
        s.name.toLowerCase().includes(term) ||
        s.code.toLowerCase().includes(term)
      )
    }
    
    return states.sort((a, b) => a.name.localeCompare(b.name))
  }, [data?.states, showWidaOnly, searchTerm])

  const selectedStateInfo = data?.states.find(s => s.code === selectedState)

  if (isLoading) {
    return (
      <div className="animate-pulse bg-slate-700 rounded-lg h-12"></div>
    )
  }

  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium text-slate-300">
        Target State
      </label>
      
      {/* WIDA Toggle */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => setShowWidaOnly(!showWidaOnly)}
          className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
            showWidaOnly
              ? 'bg-emerald-600 text-white'
              : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
          }`}
        >
          {showWidaOnly ? '✓ WIDA States Only' : 'Show WIDA States Only'}
        </button>
        <span className="text-xs text-slate-500">
          {data?.wida_states.length} WIDA states
        </span>
      </div>

      {/* Search */}
      <input
        type="text"
        placeholder="Search states..."
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        className="w-full px-3 py-2 bg-slate-800 border border-slate-600 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
      />

      {/* State Grid */}
      <div className="max-h-64 overflow-y-auto rounded-lg border border-slate-700 bg-slate-800/50">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-1 p-2">
          {filteredStates.map((state) => (
            <button
              key={state.code}
              onClick={() => onSelect(state.code, state.name)}
              className={`px-3 py-2 text-sm rounded-md transition-all text-left flex items-center justify-between ${
                selectedState === state.code
                  ? 'bg-emerald-600 text-white ring-2 ring-emerald-400'
                  : 'bg-slate-700/50 text-slate-300 hover:bg-slate-600'
              }`}
            >
              <span className="truncate">{state.name}</span>
              {state.is_wida && (
                <span className={`ml-1 text-xs px-1.5 py-0.5 rounded ${
                  selectedState === state.code
                    ? 'bg-emerald-500 text-white'
                    : 'bg-emerald-900/50 text-emerald-400'
                }`}>
                  W
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Selected State Info */}
      {selectedStateInfo && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-slate-400">Selected:</span>
          <span className="text-emerald-400 font-medium">{selectedStateInfo.name}</span>
          {selectedStateInfo.is_wida && (
            <span className="text-xs bg-emerald-900/50 text-emerald-400 px-2 py-0.5 rounded">
              WIDA State
            </span>
          )}
        </div>
      )}
    </div>
  )
}
