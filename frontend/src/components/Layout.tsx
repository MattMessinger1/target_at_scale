import { Outlet, NavLink } from 'react-router-dom'
import { 
  LayoutDashboard, 
  Building2, 
  BookOpen, 
  Download,
  Mail
} from 'lucide-react'
import { cn } from '@/lib/utils'

const navigation = [
  { name: 'Dashboard', href: '/admin', icon: LayoutDashboard },
  { name: 'Districts', href: '/admin/districts', icon: Building2 },
  { name: 'Knowledge Base', href: '/admin/knowledge-base', icon: BookOpen },
  { name: 'Export', href: '/admin/export', icon: Download },
]

export default function Layout() {
  return (
    <div className="min-h-screen bg-background">
      {/* Sidebar */}
      <div className="fixed inset-y-0 left-0 z-50 w-64 bg-wceps-blue">
        <div className="flex h-16 items-center px-6">
          <Mail className="h-8 w-8 text-wceps-gold" />
          <span className="ml-3 text-xl font-bold text-white">WCEPS</span>
        </div>
        <nav className="mt-6 px-3">
          {navigation.map((item) => (
            <NavLink
              key={item.name}
              to={item.href}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors mb-1',
                  isActive
                    ? 'bg-white/10 text-white'
                    : 'text-white/70 hover:bg-white/5 hover:text-white'
                )
              }
            >
              <item.icon className="h-5 w-5" />
              {item.name}
            </NavLink>
          ))}
        </nav>
        
        {/* Bottom info */}
        <div className="absolute bottom-0 left-0 right-0 p-4">
          <div className="rounded-lg bg-white/5 p-3">
            <p className="text-xs text-white/60">Pilot Version</p>
            <p className="text-sm text-white/80">5 Districts</p>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="pl-64">
        <main className="min-h-screen p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
