/**
 * Landing Page - Unified entry point for WCEPS
 * 
 * Presents two clear action cards:
 * 1. Start New Research - Discover funding opportunities and compliance hooks
 * 2. Create New Email - Generate targeted sales emails from research
 */
import { Link } from 'react-router-dom'
import { Search, Mail, FolderOpen, BarChart3 } from 'lucide-react'
import { ThemeToggle } from '@/components/ThemeToggle'

export default function Landing() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur-sm">
        <div className="max-w-5xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-emerald-600 flex items-center justify-center">
                <Mail className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-slate-100">WCEPS</h1>
                <p className="text-xs text-slate-400">Email Generator</p>
              </div>
            </div>
            <ThemeToggle />
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-5xl mx-auto px-6 py-16">
        {/* Hero Section */}
        <div className="text-center mb-12">
          <h2 className="text-3xl md:text-4xl font-bold text-slate-100 mb-4">
            What would you like to do?
          </h2>
          <p className="text-lg text-slate-400 max-w-2xl mx-auto">
            Research funding opportunities and compliance hooks, or generate targeted sales emails for WCEPS products.
          </p>
        </div>

        {/* Action Cards */}
        <div className="grid md:grid-cols-2 gap-6 mb-12">
          {/* Research Card */}
          <Link
            to="/research"
            className="group relative p-8 rounded-2xl border-2 border-slate-700 bg-slate-800/30 hover:border-blue-500/50 hover:bg-slate-800/60 transition-all duration-200"
          >
            <div className="absolute top-4 right-4 w-12 h-12 rounded-xl bg-blue-600/20 flex items-center justify-center group-hover:bg-blue-600/30 transition-colors">
              <Search className="w-6 h-6 text-blue-400" />
            </div>
            
            <h3 className="text-xl font-semibold text-slate-100 mb-3 pr-16">
              Start New Research
            </h3>
            
            <p className="text-slate-400 mb-6 leading-relaxed">
              Discover funding opportunities and compliance hooks for any WCEPS product in any state. Save results to use later.
            </p>
            
            <div className="flex items-center text-blue-400 font-medium group-hover:text-blue-300 transition-colors">
              Begin Research
              <svg className="w-5 h-5 ml-2 group-hover:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
              </svg>
            </div>
            
            <div className="mt-4 pt-4 border-t border-slate-700/50">
              <span className="text-xs text-slate-500">
                Single state or batch research for multiple states
              </span>
            </div>
          </Link>

          {/* Email Card */}
          <Link
            to="/email"
            className="group relative p-8 rounded-2xl border-2 border-slate-700 bg-slate-800/30 hover:border-emerald-500/50 hover:bg-slate-800/60 transition-all duration-200"
          >
            <div className="absolute top-4 right-4 w-12 h-12 rounded-xl bg-emerald-600/20 flex items-center justify-center group-hover:bg-emerald-600/30 transition-colors">
              <Mail className="w-6 h-6 text-emerald-400" />
            </div>
            
            <h3 className="text-xl font-semibold text-slate-100 mb-3 pr-16">
              Create New Email
            </h3>
            
            <p className="text-slate-400 mb-6 leading-relaxed">
              Generate targeted sales emails using AI-powered research. Start from saved research or begin fresh.
            </p>
            
            <div className="flex items-center text-emerald-400 font-medium group-hover:text-emerald-300 transition-colors">
              Create Email
              <svg className="w-5 h-5 ml-2 group-hover:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
              </svg>
            </div>
            
            <div className="mt-4 pt-4 border-t border-slate-700/50">
              <span className="text-xs text-slate-500">
                Full email generation workflow with curation
              </span>
            </div>
          </Link>
        </div>

        {/* Quick Links */}
        <div className="flex flex-wrap items-center justify-center gap-4">
          <Link
            to="/saved-runs"
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800/50 border border-slate-700 text-slate-300 hover:bg-slate-800 hover:text-slate-100 transition-colors"
          >
            <FolderOpen className="w-4 h-4" />
            Saved Research
          </Link>
          
          <Link
            to="/coverage"
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800/50 border border-slate-700 text-slate-300 hover:bg-slate-800 hover:text-slate-100 transition-colors"
          >
            <BarChart3 className="w-4 h-4" />
            Coverage Matrix
          </Link>
          
          <Link
            to="/training"
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800/50 border border-amber-700/50 text-amber-300 hover:bg-amber-900/30 transition-colors"
          >
            Training Data
          </Link>
        </div>

        {/* Stats/Info Section */}
        <div className="mt-16 grid grid-cols-3 gap-6 max-w-2xl mx-auto">
          <div className="text-center">
            <div className="text-2xl font-bold text-slate-100">7</div>
            <div className="text-sm text-slate-400">Products</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-slate-100">38</div>
            <div className="text-sm text-slate-400">WIDA States</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-slate-100">2</div>
            <div className="text-sm text-slate-400">Audiences</div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800 mt-auto">
        <div className="max-w-5xl mx-auto px-6 py-6">
          <div className="text-center text-sm text-slate-500">
            WCEPS Email Generator &middot; Wisconsin Center for Education Products & Services
          </div>
        </div>
      </footer>
    </div>
  )
}
