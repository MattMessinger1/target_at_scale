/**
 * CurationStep component for selecting funding and compliance items.
 * Shows Top 3 scored items for user selection.
 */
import { FundingItem, ComplianceItem } from '../lib/api'

interface CurationStepProps {
  fundingItems: FundingItem[]
  complianceItems: ComplianceItem[]
  selectedFunding: FundingItem[]
  selectedCompliance: ComplianceItem[]
  onSelectFunding: (items: FundingItem[]) => void
  onSelectCompliance: (items: ComplianceItem[]) => void
  isLoading?: boolean
}

function ScoreBar({ score }: { score: number }) {
  const getColor = (score: number) => {
    if (score >= 80) return 'bg-emerald-500'
    if (score >= 60) return 'bg-yellow-500'
    return 'bg-orange-500'
  }

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={`h-full ${getColor(score)} transition-all`}
          style={{ width: `${score}%` }}
        />
      </div>
      <span className={`text-sm font-medium min-w-[3ch] ${
        score >= 80 ? 'text-emerald-400' : score >= 60 ? 'text-yellow-400' : 'text-orange-400'
      }`}>
        {score}
      </span>
    </div>
  )
}

function FundingCard({
  item,
  isSelected,
  onToggle,
}: {
  item: FundingItem
  isSelected: boolean
  onToggle: () => void
}) {
  return (
    <div
      onClick={onToggle}
      className={`p-4 rounded-lg border cursor-pointer transition-all ${
        isSelected
          ? 'bg-emerald-600/20 border-emerald-500 ring-2 ring-emerald-500/50'
          : 'bg-slate-800/50 border-slate-700 hover:bg-slate-700/50'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-lg">💰</span>
            <h4 className={`font-medium ${isSelected ? 'text-emerald-400' : 'text-slate-200'}`}>
              {item.title}
            </h4>
          </div>
          
          {item.amount && (
            <div className="mt-1 text-sm text-emerald-400 font-medium">
              {item.amount}
            </div>
          )}
          
          {item.description && (
            <p className="mt-2 text-sm text-slate-400 line-clamp-2">
              {item.description}
            </p>
          )}
          
          {item.deadline && (
            <div className="mt-2 text-xs text-orange-400">
              📅 {item.deadline}
            </div>
          )}
          
          <div className="mt-3">
            <ScoreBar score={item.score} />
          </div>
          
          <div className="mt-2 text-xs text-slate-500">
            {item.score_reason}
          </div>
        </div>
        
        <div className={`w-6 h-6 rounded-full border-2 flex items-center justify-center ${
          isSelected 
            ? 'bg-emerald-500 border-emerald-500 text-white' 
            : 'border-slate-500'
        }`}>
          {isSelected && (
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
            </svg>
          )}
        </div>
      </div>
    </div>
  )
}

function ComplianceCard({
  item,
  isSelected,
  onToggle,
}: {
  item: ComplianceItem
  isSelected: boolean
  onToggle: () => void
}) {
  const typeColors: Record<string, string> = {
    certification: 'bg-blue-900/50 text-blue-400',
    professional_development: 'bg-purple-900/50 text-purple-400',
    reporting: 'bg-orange-900/50 text-orange-400',
    assessment: 'bg-cyan-900/50 text-cyan-400',
    legal: 'bg-red-900/50 text-red-400',
  }

  return (
    <div
      onClick={onToggle}
      className={`p-4 rounded-lg border cursor-pointer transition-all ${
        isSelected
          ? 'bg-blue-600/20 border-blue-500 ring-2 ring-blue-500/50'
          : 'bg-slate-800/50 border-slate-700 hover:bg-slate-700/50'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-lg">📋</span>
            <h4 className={`font-medium ${isSelected ? 'text-blue-400' : 'text-slate-200'}`}>
              {item.title}
            </h4>
          </div>
          
          {item.type && (
            <div className="mt-1">
              <span className={`text-xs px-2 py-0.5 rounded ${typeColors[item.type] || 'bg-slate-700 text-slate-400'}`}>
                {item.type.replace('_', ' ')}
              </span>
            </div>
          )}
          
          {item.description && (
            <p className="mt-2 text-sm text-slate-400 line-clamp-2">
              {item.description}
            </p>
          )}
          
          <div className="mt-2 flex flex-wrap gap-2 text-xs">
            {item.hours_required && (
              <span className="text-purple-400">
                ⏱️ {item.hours_required}
              </span>
            )}
            {item.deadline_or_frequency && (
              <span className="text-orange-400">
                📅 {item.deadline_or_frequency}
              </span>
            )}
          </div>
          
          <div className="mt-3">
            <ScoreBar score={item.score} />
          </div>
          
          <div className="mt-2 text-xs text-slate-500">
            {item.score_reason}
          </div>
        </div>
        
        <div className={`w-6 h-6 rounded-full border-2 flex items-center justify-center ${
          isSelected 
            ? 'bg-blue-500 border-blue-500 text-white' 
            : 'border-slate-500'
        }`}>
          {isSelected && (
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
            </svg>
          )}
        </div>
      </div>
    </div>
  )
}

export function CurationStep({
  fundingItems,
  complianceItems,
  selectedFunding,
  selectedCompliance,
  onSelectFunding,
  onSelectCompliance,
  isLoading,
}: CurationStepProps) {
  const toggleFunding = (item: FundingItem) => {
    const isSelected = selectedFunding.some(f => f.title === item.title)
    if (isSelected) {
      onSelectFunding(selectedFunding.filter(f => f.title !== item.title))
    } else if (selectedFunding.length < 3) {
      onSelectFunding([...selectedFunding, item])
    }
  }

  const toggleCompliance = (item: ComplianceItem) => {
    const isSelected = selectedCompliance.some(c => c.title === item.title)
    if (isSelected) {
      onSelectCompliance(selectedCompliance.filter(c => c.title !== item.title))
    } else if (selectedCompliance.length < 3) {
      onSelectCompliance([...selectedCompliance, item])
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="animate-pulse space-y-3">
          <div className="h-6 bg-slate-700 rounded w-1/3"></div>
          <div className="h-32 bg-slate-700 rounded"></div>
          <div className="h-32 bg-slate-700 rounded"></div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Funding Items */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold text-slate-200 flex items-center gap-2">
            💰 Funding Opportunities
            <span className="text-sm font-normal text-slate-500">
              (select up to 3)
            </span>
          </h3>
          <span className="text-sm text-emerald-400">
            {selectedFunding.length}/3 selected
          </span>
        </div>
        
        {fundingItems.length === 0 ? (
          <div className="p-6 text-center text-slate-500 bg-slate-800/30 rounded-lg border border-slate-700">
            No funding opportunities found above the relevance threshold.
            <br />
            <span className="text-xs">Try adjusting your product or state selection.</span>
          </div>
        ) : (
          <div className="space-y-3">
            {fundingItems.map((item, i) => (
              <FundingCard
                key={`${item.title}-${i}`}
                item={item}
                isSelected={selectedFunding.some(f => f.title === item.title)}
                onToggle={() => toggleFunding(item)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Compliance Items */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold text-slate-200 flex items-center gap-2">
            📋 Compliance Requirements
            <span className="text-sm font-normal text-slate-500">
              (select up to 3)
            </span>
          </h3>
          <span className="text-sm text-blue-400">
            {selectedCompliance.length}/3 selected
          </span>
        </div>
        
        {complianceItems.length === 0 ? (
          <div className="p-6 text-center text-slate-500 bg-slate-800/30 rounded-lg border border-slate-700">
            No compliance requirements found above the relevance threshold.
            <br />
            <span className="text-xs">Try adjusting your product or state selection.</span>
          </div>
        ) : (
          <div className="space-y-3">
            {complianceItems.map((item, i) => (
              <ComplianceCard
                key={`${item.title}-${i}`}
                item={item}
                isSelected={selectedCompliance.some(c => c.title === item.title)}
                onToggle={() => toggleCompliance(item)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
