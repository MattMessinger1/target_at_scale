/**
 * StateSelector component for selecting US states.
 * Includes all 50 states with WIDA preset option.
 * Supports multi-select mode.
 */
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

export interface SelectedState {
  code: string
  name: string
}

interface StateSelectorProps {
  selectedStates: SelectedState[]
  onSelect: (states: SelectedState[]) => void
}

export function StateSelector({ selectedStates, onSelect }: StateSelectorProps) {
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

  const selectedCodes = selectedStates.map(s => s.code)

  const handleToggleState = (code: string, name: string) => {
    if (selectedCodes.includes(code)) {
      onSelect(selectedStates.filter(s => s.code !== code))
    } else {
      onSelect([...selectedStates, { code, name }])
    }
  }

  const handleSelectAllWida = () => {
    if (!data?.states) return
    const widaStates = data.states.filter(s => s.is_wida)
    const allWidaSelected = widaStates.every(s => selectedCodes.includes(s.code))
    
    if (allWidaSelected) {
      // Remove all WIDA states
      onSelect(selectedStates.filter(s => !data.wida_states.includes(s.code)))
    } else {
      // Add all WIDA states
      const newStates = [...selectedStates]
      widaStates.forEach(state => {
        if (!selectedCodes.includes(state.code)) {
          newStates.push({ code: state.code, name: state.name })
        }
      })
      onSelect(newStates)
    }
  }

  const handleClearAll = () => {
    onSelect([])
  }

  if (isLoading) {
    return (
      <div className="animate-pulse bg-slate-700 rounded-lg h-12"></div>
    )
  }

  const widaStates = data?.states.filter(s => s.is_wida) || []
  const allWidaSelected = widaStates.length > 0 && widaStates.every(s => selectedCodes.includes(s.code))

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="block text-sm font-medium text-slate-300">
          Target State{selectedStates.length > 1 ? 's' : ''}
        </label>
        {selectedStates.length > 0 && (
          <button
            onClick={handleClearAll}
            className="text-xs text-slate-400 hover:text-slate-300 transition-colors"
          >
            Clear All
          </button>
        )}
      </div>
      
      {/* Action Buttons */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => setShowWidaOnly(!showWidaOnly)}
          className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
            showWidaOnly
              ? 'bg-emerald-600 text-white'
              : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
          }`}
        >
          {showWidaOnly ? '✓ WIDA Only' : 'Show WIDA Only'}
        </button>
        <button
          onClick={handleSelectAllWida}
          className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
            allWidaSelected
              ? 'bg-emerald-600 text-white'
              : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
          }`}
        >
          {allWidaSelected ? '✓ All WIDA Selected' : 'Select All WIDA'}
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
          {filteredStates.map((state) => {
            const isSelected = selectedCodes.includes(state.code)
            return (
              <button
                key={state.code}
                onClick={() => handleToggleState(state.code, state.name)}
                className={`px-3 py-2 text-sm rounded-md transition-all text-left flex items-center justify-between ${
                  isSelected
                    ? 'bg-emerald-600 text-white ring-2 ring-emerald-400'
                    : 'bg-slate-700/50 text-slate-300 hover:bg-slate-600'
                }`}
              >
                <span className="truncate">{state.name}</span>
                {state.is_wida && (
                  <span className={`ml-1 text-xs px-1.5 py-0.5 rounded ${
                    isSelected
                      ? 'bg-emerald-500 text-white'
                      : 'bg-emerald-900/50 text-emerald-400'
                  }`}>
                    W
                  </span>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Selected States Summary */}
      {selectedStates.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-slate-400">Selected:</span>
            <span className="text-emerald-400 font-medium">
              {selectedStates.length} state{selectedStates.length > 1 ? 's' : ''}
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            {selectedStates.slice(0, 10).map(state => (
              <span 
                key={state.code}
                className="text-xs bg-emerald-900/50 text-emerald-400 px-2 py-0.5 rounded"
              >
                {state.code}
              </span>
            ))}
            {selectedStates.length > 10 && (
              <span className="text-xs text-slate-500">
                +{selectedStates.length - 10} more
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
