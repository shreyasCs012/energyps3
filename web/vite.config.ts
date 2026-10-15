import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/scenarios': 'http://127.0.0.1:8000',
      '/tariff': 'http://127.0.0.1:8000',
      '/run': 'http://127.0.0.1:8000',
      '/kpis': 'http://127.0.0.1:8000',
      '/recommendations': 'http://127.0.0.1:8000',
      '/what-if': 'http://127.0.0.1:8000',
      '/forecast': 'http://127.0.0.1:8000',
      '/anomalies': 'http://127.0.0.1:8000',
      '/cv': 'http://127.0.0.1:8000',
      '/report': 'http://127.0.0.1:8000',
      '/copilot': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
});
