import { Moon, Sun } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const THEME_STORAGE_KEY = 'wceps_theme'
type Theme = 'light' | 'dark'

const getStoredTheme = (): Theme => {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    return stored === 'light' || stored === 'dark' ? stored : 'dark'
  } catch {
    return 'dark'
  }
}

const applyTheme = (theme: Theme) => {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

export function ThemeToggle({ className }: { className?: string }) {
  const [theme, setTheme] = useState<Theme>('dark')

  useEffect(() => {
    const t = getStoredTheme()
    setTheme(t)
    applyTheme(t)
  }, [])

  const nextTheme = useMemo<Theme>(() => (theme === 'dark' ? 'light' : 'dark'), [theme])

  const toggle = () => {
    const t = nextTheme
    setTheme(t)
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, t)
    } catch {
      // ignore
    }
    applyTheme(t)
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="icon"
      className={cn(
        'bg-background/60 text-foreground border-border hover:bg-background backdrop-blur supports-[backdrop-filter]:bg-background/40',
        className,
      )}
      onClick={toggle}
      title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  )
}

