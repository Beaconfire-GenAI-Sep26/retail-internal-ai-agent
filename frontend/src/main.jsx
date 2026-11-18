// [01] App entry point — mounts React and wires the global providers
// Reference: zara-returns-web/src/main.jsx


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
// TODO (commit 4): Redux <Provider> + store, react-router <BrowserRouter>


// ═══════════════════════════════════════════════════════════════════
// 2. Render — providers wrap <App>, outermost first
// ═══════════════════════════════════════════════════════════════════
// TODO (commit 4): <StrictMode> → <Provider store> → <BrowserRouter> → <App />
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
