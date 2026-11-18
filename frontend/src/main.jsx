// [01] App entry point — mounts React and wires the global providers


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Provider } from 'react-redux'
import { BrowserRouter } from 'react-router'
import store from './store/store'
import './index.css'
import App from './App.jsx'


// ═══════════════════════════════════════════════════════════════════
// 2. Render — providers wrap <App>, outermost first
// ═══════════════════════════════════════════════════════════════════
//   <StrictMode>     dev only: double-runs effects to surface unsafe side effects
//   <Provider>       Redux store → every component (useSelector / useDispatch)
//   <BrowserRouter>  URL ↔ <Routes> matching in App.jsx
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Provider store={store}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </Provider>
  </StrictMode>,
)
