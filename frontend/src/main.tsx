import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

const THEME_STORAGE_KEY = 'wceps_theme'
type Theme = 'light' | 'dark'

const initTheme = () => {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    const theme: Theme = stored === 'light' || stored === 'dark' ? stored : 'dark'
    document.documentElement.classList.toggle('dark', theme === 'dark')
  } catch {
    // Default to dark for a modern look (and to match the main email tool UI).
    document.documentElement.classList.add('dark')
  }
}

// Apply theme before first render to avoid flashing
initTheme()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
