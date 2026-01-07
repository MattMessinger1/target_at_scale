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
  // KB items (from our knowledge base)
  kbFunding: FundingItem[]
  kbCompliance: ComplianceItem[]
  // Web items (from Perplexity research)
  webFunding: FundingItem[]
  webCompliance: ComplianceItem[]
  // Legacy: combined items (for backwards compatibility)
  fundingItems?: FundingItem[]
  complianceFundingItems?: ComplianceFundingItem[]
  complianceItems?: ComplianceItem[]
  // Selection state
  selectedFunding: FundingItem[]
  selectedComplianceFunding?: ComplianceFundingItem[]
  selectedCompliance: ComplianceItem[]
  onSelectFunding: (items: FundingItem[]) => void
  onSelectComplianceFunding?: (items: ComplianceFundingItem[]) => void
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

// Source type badge - shows if item is from Knowledge Base or Web Research
function SourceTypeBadge({ sourceType, status }: { sourceType?: string, status?: string }) {
  const isKB = sourceType === 'knowledge_base'
  
  return (
    <div className="flex items-center gap-1.5">
      {/* Source type badge */}
      <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
        isKB 
          ? 'bg-violet-900/50 text-violet-400 border border-violet-700/50' 
          : 'bg-slate-700/50 text-slate-400 border border-slate-600/50'
      }`}>
        {isKB ? '📚 From KB' : '🌐 Web Research'}
      </span>
      
      {/* Status badge */}
      {status && (
        <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
          status === 'verified' ? 'bg-emerald-900/50 text-emerald-400 border border-emerald-700/50' :
          status === 'active' ? 'bg-emerald-900/50 text-emerald-400 border border-emerald-700/50' :
          status === 'upcoming' ? 'bg-cyan-900/50 text-cyan-400 border border-cyan-700/50' :
          status === 'unverified' ? 'bg-amber-900/50 text-amber-400 border border-amber-700/50' :
          'bg-slate-700/50 text-slate-400 border border-slate-600/50'
        }`}>
          {status === 'verified' ? '✓ Verified' :
           status === 'active' ? '✓ Active' :
           status === 'upcoming' ? '📅 Upcoming' :
           status === 'unverified' ? '⚠ Unverified' :
           status}
        </span>
      )}
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
          <div className="flex items-center gap-2 mb-1">
            <span className="text-lg">💰</span>
            <h4 className={`font-medium ${isSelected ? 'text-emerald-400' : 'text-slate-200'}`}>
              {item.title}
            </h4>
          </div>
          
          {/* Source type badge */}
          <SourceTypeBadge sourceType={item.source_type} status={item.status} />
          
          {item.amount && (
            <div className="mt-2 text-sm text-emerald-400 font-medium">
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
          <div className="flex items-center gap-2 mb-1">
            <span className="text-lg">📋</span>
            <h4 className={`font-medium ${isSelected ? 'text-blue-400' : 'text-slate-200'}`}>
              {item.title}
            </h4>
          </div>
          
          {/* Source type and status badges */}
          <div className="flex items-center gap-2 flex-wrap">
            <SourceTypeBadge sourceType={item.source_type} status={item.status} />
            {item.type && (
              <span className={`text-xs px-2 py-0.5 rounded ${typeColors[item.type] || 'bg-slate-700 text-slate-400'}`}>
                {item.type.replace('_', ' ')}
              </span>
            )}
          </div>
          
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
  kbFunding = [],
  kbCompliance = [],
  webFunding = [],
  webCompliance = [],
  fundingItems = [],
  complianceFundingItems = [],
  complianceItems = [],
  selectedFunding,
  selectedComplianceFunding = [],
  selectedCompliance,
  onSelectFunding,
  onSelectComplianceFunding,
  onSelectCompliance,
  isLoading,
}: CurationStepProps) {
  // Combine KB and Web items for display (with KB items first)
  const allFunding = [...kbFunding, ...webFunding, ...fundingItems]
  const allCompliance = [...kbCompliance, ...webCompliance, ...complianceItems]
  
  const toggleFunding = (item: FundingItem) => {
    const isSelected = selectedFunding.some(f => f.title === item.title)
    if (isSelected) {
      onSelectFunding(selectedFunding.filter(f => f.title !== item.title))
    } else if (selectedFunding.length < 5) {
      onSelectFunding([...selectedFunding, item])
    }
  }

  const toggleComplianceFunding = (item: ComplianceFundingItem) => {
    if (!onSelectComplianceFunding) return
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
    } else if (selectedCompliance.length < 5) {
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
    <div className="space-y-8">
      {/* Funding Items - KB and Web combined */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold text-slate-200 flex items-center gap-2">
            💰 Funding Opportunities
            <span className="text-sm font-normal text-slate-500">
              (select up to 5)
            </span>
          </h3>
          <span className="text-sm text-emerald-400">
            {selectedFunding.length}/5 selected
          </span>
        </div>
        
        {/* KB Funding Section */}
        {kbFunding.length > 0 && (
          <div className="mb-4">
            <h4 className="text-sm font-medium text-violet-400 mb-2 flex items-center gap-1.5">
              <span>📚</span> From Knowledge Base
            </h4>
            <div className="space-y-3">
              {kbFunding.map((item, i) => (
                <FundingCard
                  key={`kb-${item.title}-${i}`}
                  item={{ ...item, source_type: 'knowledge_base' }}
                  isSelected={selectedFunding.some(f => f.title === item.title)}
                  onToggle={() => toggleFunding(item)}
                />
              ))}
            </div>
          </div>
        )}
        
        {/* Web Funding Section */}
        {webFunding.length > 0 && (
          <div className="mb-4">
            <h4 className="text-sm font-medium text-slate-400 mb-2 flex items-center gap-1.5">
              <span>🌐</span> From Web Research
            </h4>
            <div className="space-y-3">
              {webFunding.map((item, i) => (
                <FundingCard
                  key={`web-${item.title}-${i}`}
                  item={{ ...item, source_type: 'web_research' as const }}
                  isSelected={selectedFunding.some(f => f.title === item.title)}
                  onToggle={() => toggleFunding(item)}
                />
              ))}
            </div>
          </div>
        )}
        
        {/* Legacy funding items (backwards compat) */}
        {fundingItems.length > 0 && kbFunding.length === 0 && webFunding.length === 0 && (
          <div className="space-y-3">
            {fundingItems.map((item, i) => (
              <FundingCard
                key={`legacy-${item.title}-${i}`}
                item={item}
                isSelected={selectedFunding.some(f => f.title === item.title)}
                onToggle={() => toggleFunding(item)}
              />
            ))}
          </div>
        )}
        
        {allFunding.length === 0 && (
          <div className="p-6 bg-slate-800/30 rounded-lg border border-amber-700/50">
            <div className="flex items-start gap-3">
              <span className="text-2xl">💡</span>
              <div>
                <h4 className="font-medium text-amber-400 mb-2">
                  No Funding Opportunities Found
                </h4>
                <p className="text-sm text-slate-400 mb-3">
                  Our research found no special funding sources beyond "table stakes" 
                  (Title I, Title III, standard state funding) for this state and product.
                </p>
                <p className="text-sm text-slate-300">
                  <strong className="text-emerald-400">Good news:</strong> Districts can use existing 
                  funding to address compliance requirements. Focus on how your product helps meet mandates.
                </p>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Compliance-Linked Funding Section (if available) */}
      {complianceFundingItems.length > 0 && onSelectComplianceFunding && (
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
          
          <div className="space-y-3">
            {complianceFundingItems.map((item, i) => (
              <ComplianceFundingCard
                key={`cf-${item.title}-${i}`}
                item={item}
                isSelected={selectedComplianceFunding.some(cf => cf.title === item.title)}
                onToggle={() => toggleComplianceFunding(item)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Compliance Items - KB and Web combined */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold text-slate-200 flex items-center gap-2">
            📋 Compliance Requirements
            <span className="text-sm font-normal text-slate-500">
              (select up to 5)
            </span>
          </h3>
          <span className="text-sm text-blue-400">
            {selectedCompliance.length}/5 selected
          </span>
        </div>
        
        {/* KB Compliance Section */}
        {kbCompliance.length > 0 && (
          <div className="mb-4">
            <h4 className="text-sm font-medium text-violet-400 mb-2 flex items-center gap-1.5">
              <span>📚</span> From Knowledge Base
            </h4>
            <div className="space-y-3">
              {kbCompliance.map((item, i) => (
                <ComplianceCard
                  key={`kb-${item.title}-${i}`}
                  item={{ ...item, source_type: 'knowledge_base' }}
                  isSelected={selectedCompliance.some(c => c.title === item.title)}
                  onToggle={() => toggleCompliance(item)}
                />
              ))}
            </div>
          </div>
        )}
        
        {/* Web Compliance Section */}
        {webCompliance.length > 0 && (
          <div className="mb-4">
            <h4 className="text-sm font-medium text-slate-400 mb-2 flex items-center gap-1.5">
              <span>🌐</span> From Web Research
            </h4>
            <div className="space-y-3">
              {webCompliance.map((item, i) => (
                <ComplianceCard
                  key={`web-${item.title}-${i}`}
                  item={{ ...item, source_type: 'web_research' as const }}
                  isSelected={selectedCompliance.some(c => c.title === item.title)}
                  onToggle={() => toggleCompliance(item)}
                />
              ))}
            </div>
          </div>
        )}
        
        {/* Legacy compliance items (backwards compat) */}
        {complianceItems.length > 0 && kbCompliance.length === 0 && webCompliance.length === 0 && (
          <div className="space-y-3">
            {complianceItems.map((item, i) => (
              <ComplianceCard
                key={`legacy-${item.title}-${i}`}
                item={item}
                isSelected={selectedCompliance.some(c => c.title === item.title)}
                onToggle={() => toggleCompliance(item)}
              />
            ))}
          </div>
        )}
        
        {allCompliance.length === 0 && (
          <div className="p-6 bg-slate-800/30 rounded-lg border border-slate-700">
            <div className="flex items-start gap-3">
              <span className="text-2xl">ℹ️</span>
              <div>
                <h4 className="font-medium text-slate-300 mb-2">
                  No Compliance Requirements Found
                </h4>
                <p className="text-sm text-slate-400">
                  Our research didn't find DOJ investigations, consent decrees, CSI/TSI schools, 
                  or other urgent compliance drivers. Your email can focus on proactive value.
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
