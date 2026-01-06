/**
 * CurationStep component for selecting funding, compliance-linked funding, and compliance items.
 * Shows Top 3 scored items for user selection in each category.
 */
import { FundingItem, ComplianceItem, ComplianceFundingItem, SourceLink } from '../lib/api'

// External link icon component
function ExternalLinkIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
    </svg>
  )
}

// Helper to get display title for a source URL
function getSourceDisplayTitle(source: SourceLink): string {
  if (source.title) return source.title
  try {
    const url = new URL(source.url)
    return url.hostname.replace('www.', '')
  } catch {
    return 'Source'
  }
}

// Source links display component
function SourceLinks({ sources, accentColor = 'slate' }: { sources?: SourceLink[], accentColor?: 'emerald' | 'blue' | 'slate' }) {
  if (!sources || sources.length === 0) return null
  
  const colorClasses = {
    emerald: 'text-emerald-400 hover:text-emerald-300 bg-emerald-900/30 hover:bg-emerald-900/50',
    blue: 'text-blue-400 hover:text-blue-300 bg-blue-900/30 hover:bg-blue-900/50',
    slate: 'text-slate-400 hover:text-slate-300 bg-slate-700/50 hover:bg-slate-700',
  }
  
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {sources.slice(0, 3).map((source, i) => (
        <a
          key={i}
          href={source.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded transition-colors ${colorClasses[accentColor]}`}
          title={source.url}
        >
          <ExternalLinkIcon className="w-3 h-3" />
          {getSourceDisplayTitle(source)}
        </a>
      ))}
      {sources.length > 3 && (
        <span className="text-xs text-slate-500 px-2 py-0.5">
          +{sources.length - 3} more
        </span>
      )}
    </div>
  )
}

interface CurationStepProps {
  fundingItems: FundingItem[]
  complianceFundingItems: ComplianceFundingItem[]
  complianceItems: ComplianceItem[]
  selectedFunding: FundingItem[]
  selectedComplianceFunding: ComplianceFundingItem[]
  selectedCompliance: ComplianceItem[]
  onSelectFunding: (items: FundingItem[]) => void
  onSelectComplianceFunding: (items: ComplianceFundingItem[]) => void
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
          
          {/* Source Links */}
          <SourceLinks sources={item.sources} accentColor="emerald" />
          
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
    consent_decree: 'bg-red-900/50 text-red-400',
    doj_inquiry: 'bg-red-900/50 text-red-400',
    certification: 'bg-blue-900/50 text-blue-400',
    professional_development: 'bg-purple-900/50 text-purple-400',
    reporting: 'bg-orange-900/50 text-orange-400',
    assessment: 'bg-cyan-900/50 text-cyan-400',
    csi_tsi: 'bg-amber-900/50 text-amber-400',
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
            {item.urgency && (
              <span className={`px-1.5 py-0.5 rounded ${
                item.urgency === 'high' ? 'bg-red-900/50 text-red-400' :
                item.urgency === 'medium' ? 'bg-yellow-900/50 text-yellow-400' :
                'bg-slate-700 text-slate-400'
              }`}>
                {item.urgency === 'high' ? '🔴 High Priority' : 
                 item.urgency === 'medium' ? '🟡 Medium' : '🟢 Low'}
              </span>
            )}
          </div>
          
          {/* Source Links */}
          <SourceLinks sources={item.sources} accentColor="blue" />
          
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

function ComplianceFundingCard({
  item,
  isSelected,
  onToggle,
}: {
  item: ComplianceFundingItem
  isSelected: boolean
  onToggle: () => void
}) {
  return (
    <div
      onClick={onToggle}
      className={`p-4 rounded-lg border cursor-pointer transition-all ${
        isSelected
          ? 'bg-amber-600/20 border-amber-500 ring-2 ring-amber-500/50'
          : 'bg-slate-800/50 border-slate-700 hover:bg-slate-700/50'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-lg">🎯</span>
            <h4 className={`font-medium ${isSelected ? 'text-amber-400' : 'text-slate-200'}`}>
              {item.title}
            </h4>
          </div>
          
          {/* Compliance trigger badge */}
          {item.compliance_trigger && (
            <div className="mt-1">
              <span className="text-xs px-2 py-0.5 rounded bg-amber-900/50 text-amber-400">
                📋 Requires: {item.compliance_trigger}
              </span>
            </div>
          )}
          
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
          
          <div className="mt-2 flex flex-wrap gap-2 text-xs">
            {item.deadline && (
              <span className="text-orange-400">
                📅 {item.deadline}
              </span>
            )}
            {item.action_required && (
              <span className="text-cyan-400">
                ⚡ {item.action_required}
              </span>
            )}
          </div>
          
          {/* Districts affected */}
          {item.districts_affected && Array.isArray(item.districts_affected) && item.districts_affected.length > 0 && (
            <div className="mt-2 text-xs text-slate-500">
              🏫 Affects: {item.districts_affected.slice(0, 3).join(', ')}
              {item.districts_affected.length > 3 && ` +${item.districts_affected.length - 3} more`}
            </div>
          )}
          {/* Handle string format */}
          {item.districts_affected && typeof item.districts_affected === 'string' && (
            <div className="mt-2 text-xs text-slate-500">
              🏫 Affects: {item.districts_affected}
            </div>
          )}
          
          {/* Source Links */}
          <SourceLinks sources={item.sources} accentColor="slate" />
          
          <div className="mt-3">
            <ScoreBar score={item.score} />
          </div>
          
          <div className="mt-2 text-xs text-slate-500">
            {item.score_reason}
          </div>
        </div>
        
        <div className={`w-6 h-6 rounded-full border-2 flex items-center justify-center ${
          isSelected 
            ? 'bg-amber-500 border-amber-500 text-white' 
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
  complianceFundingItems,
  complianceItems,
  selectedFunding,
  selectedComplianceFunding,
  selectedCompliance,
  onSelectFunding,
  onSelectComplianceFunding,
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

  const toggleComplianceFunding = (item: ComplianceFundingItem) => {
    const isSelected = selectedComplianceFunding.some(cf => cf.title === item.title)
    if (isSelected) {
      onSelectComplianceFunding(selectedComplianceFunding.filter(cf => cf.title !== item.title))
    } else if (selectedComplianceFunding.length < 3) {
      onSelectComplianceFunding([...selectedComplianceFunding, item])
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
          <div className="p-6 bg-slate-800/30 rounded-lg border border-amber-700/50">
            <div className="flex items-start gap-3">
              <span className="text-2xl">💡</span>
              <div>
                <h4 className="font-medium text-amber-400 mb-2">
                  No Unique Funding "Hidden Gems" Found
                </h4>
                <p className="text-sm text-slate-400 mb-3">
                  Our research found no special funding sources beyond the "table stakes" 
                  (Title I, Title III, and standard state categorical funding) for this state and product.
                </p>
                {complianceFundingItems.length > 0 ? (
                  <p className="text-sm text-slate-300">
                    <strong className="text-amber-400">However:</strong> Check the{' '}
                    <strong>Compliance-Linked Funding</strong> section below — schools with CSI/TSI designations 
                    or under compliance oversight have access to dedicated improvement funds that could support this product.
                  </p>
                ) : (
                  <p className="text-sm text-slate-300">
                    <strong className="text-emerald-400">Good news:</strong> Districts can use their existing 
                    table stakes funding to address the compliance requirements below. Focus on highlighting 
                    how your product helps them meet mandates — that's a compelling reason to allocate their 
                    baseline EL funding to you.
                  </p>
                )}
              </div>
            </div>
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

      {/* Compliance-Linked Funding Section */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold text-slate-200 flex items-center gap-2">
            🎯 Compliance-Linked Funding
            <span className="text-sm font-normal text-slate-500">
              (select up to 3)
            </span>
          </h3>
          <span className="text-sm text-amber-400">
            {selectedComplianceFunding.length}/3 selected
          </span>
        </div>
        
        {complianceFundingItems.length === 0 ? (
          <div className="p-4 bg-slate-800/30 rounded-lg border border-slate-700">
            <div className="flex items-start gap-3">
              <span className="text-xl">ℹ️</span>
              <div>
                <p className="text-sm text-slate-400">
                  No compliance-linked funding found (CSI/TSI improvement grants, consent decree funding, etc.) 
                  for this state and product combination.
                </p>
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {complianceFundingItems.map((item, i) => (
              <ComplianceFundingCard
                key={`${item.title}-${i}`}
                item={item}
                isSelected={selectedComplianceFunding.some(cf => cf.title === item.title)}
                onToggle={() => toggleComplianceFunding(item)}
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
          <div className="p-6 bg-slate-800/30 rounded-lg border border-slate-700">
            <div className="flex items-start gap-3">
              <span className="text-2xl">ℹ️</span>
              <div>
                <h4 className="font-medium text-slate-300 mb-2">
                  No High-Signal Compliance Requirements Found
                </h4>
                <p className="text-sm text-slate-400">
                  Our research didn't find DOJ investigations, consent decrees, CSI/TSI schools, 
                  or other urgent compliance drivers in this state that strongly match your product. 
                  This is still useful — your email can focus on proactive value rather than 
                  compliance pressure.
                </p>
              </div>
            </div>
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
