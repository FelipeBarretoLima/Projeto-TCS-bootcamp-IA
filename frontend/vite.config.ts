import basicSsl from '@vitejs/plugin-basic-ssl'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  // `npm run dev:celular`: aberto na rede (--host) e com HTTPS de teste (certificado próprio), porque o
  // navegador do celular só libera o microfone da mensagem de voz em HTTPS. O `npm run dev` segue igual.
  plugins: [react(), ...(mode === 'celular' ? [basicSsl()] : [])],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
}))
