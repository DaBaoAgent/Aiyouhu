import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: './',  // 相对路径，适配 proxy
  server: {
    port: 5173,
    // 前端用相对路径调 /api、/static；dev 时转发到本机后端(7860)。
    // 仅 dev server 生效，build 产物不受影响。
    proxy: {
      '/api': { target: 'http://127.0.0.1:7860', changeOrigin: true },
      '/static': { target: 'http://127.0.0.1:7860', changeOrigin: true },
    },
  },
})
