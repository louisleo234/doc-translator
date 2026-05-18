import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    // Enable code splitting
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/vue') || id.includes('node_modules/vue-router') || id.includes('node_modules/pinia')) {
            return 'vue-vendor'
          }
          if (id.includes('node_modules/@ant-design/icons-vue')) {
            return 'ant-design-icons'
          }
          if (id.includes('node_modules/lodash') || id.includes('node_modules/lodash-es')) {
            return 'lodash'
          }
          if (id.includes('node_modules/dayjs')) {
            return 'dayjs'
          }
          if (id.includes('node_modules/ant-design-vue')) {
            return 'ant-design'
          }
          if (id.includes('node_modules/@apollo/client') || id.includes('node_modules/graphql')) {
            return 'apollo'
          }
        },
      },
    },
    chunkSizeWarningLimit: 1600,
  },
  // Optimize dependencies
  optimizeDeps: {
    include: ['vue', 'vue-router', 'pinia', 'ant-design-vue', '@apollo/client'],
  },
})
