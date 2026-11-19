import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
// Dev server only: stands in for the API Gateway, so /domain/* reaches a locally
// running Domain API (uvicorn --port 8003) with the /domain prefix removed.
// Docker builds don't use this; Nginx routes the same paths there.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/domain': {
        target: 'http://localhost:8003',
        rewrite: (path) => path.replace(/^\/domain/, ''),
      },
    },
  },
})
