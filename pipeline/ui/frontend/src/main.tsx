import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ToastProvider } from './components/Toast'
import { ThemeProvider } from './hooks/useTheme'
import App from './App'
import './index.css'

// Router basename. Priority:
//   1. VITE_ROUTER_BASENAME (explicit override)
//   2. Vite's BASE_URL (the `base` config option, set via VITE_BASE_PATH)
//   3. undefined (mounted at root)
// Vite's BASE_URL always ends with '/', which BrowserRouter does not accept,
// so strip it. '/' itself collapses to undefined.
const baseUrl = (import.meta.env.BASE_URL || '/').replace(/\/$/, '')
const basename =
  import.meta.env.VITE_ROUTER_BASENAME?.trim() ||
  (baseUrl || undefined)

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter basename={basename}>
      <ThemeProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
