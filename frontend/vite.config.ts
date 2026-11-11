import { fileURLToPath, URL } from 'node:url'
import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'

const NAVIGATE_TO_STRING_LIMIT = 2 * 1024 * 1024
const SAFE_BUDGET = Math.floor(NAVIGATE_TO_STRING_LIMIT * 0.9)

/**
 * The desktop shell renders the UI through WebView2's NavigateToString so that
 * no local HTTP server is started and no port is opened. That requires one
 * self-contained HTML document, so the entry chunk and stylesheet are inlined
 * and every other asset must already be a data URI.
 */
function singleFileHtml(): Plugin {
  return {
    name: 'sheetkit:single-file-html',
    enforce: 'post',
    apply: 'build',
    generateBundle(_options, bundle) {
      const htmlKey = Object.keys(bundle).find((key) => key.endsWith('index.html'))
      if (!htmlKey) return

      const htmlEntry = bundle[htmlKey]
      if (htmlEntry.type !== 'asset') return

      let html =
        typeof htmlEntry.source === 'string'
          ? htmlEntry.source
          : Buffer.from(htmlEntry.source).toString('utf-8')

      const scripts: string[] = []
      const styles: string[] = []

      for (const [name, item] of Object.entries(bundle)) {
        if (name === htmlKey) continue
        if (item.type === 'chunk') {
          scripts.push(item.code)
          delete bundle[name]
        } else if (name.endsWith('.css')) {
          styles.push(String(item.source))
          delete bundle[name]
        } else {
          this.error(
            `single-file build cannot inline "${name}"; raise build.assetsInlineLimit or remove the asset`,
          )
        }
      }

      html = html
        .replace(/<script\b[^>]*>\s*<\/script>/gi, '')
        .replace(/<link\b[^>]*rel=["'](?:stylesheet|modulepreload)["'][^>]*>/gi, '')

      const payload =
        (styles.length ? `<style>\n${styles.join('\n')}\n</style>` : '') +
        (scripts.length
          ? `<script>\n${scripts.join('\n').replace(/<\/script/gi, '<\\/script')}\n</script>`
          : '')

      // The payload must be inserted through a function: as a replacement
      // string, "$&" and friends inside the bundle would be expanded as
      // replacement patterns and silently corrupt the minified code.
      html = html.replace('</body>', () => `${payload}\n</body>`)

      const bytes = Buffer.byteLength(html, 'utf-8')
      if (bytes > SAFE_BUDGET) {
        this.error(
          `inlined HTML is ${bytes} bytes, above the ${SAFE_BUDGET} byte NavigateToString budget`,
        )
      }

      // Guard against the inlined code being altered on the way in.
      for (const script of scripts) {
        if (!html.includes(script)) {
          this.error('the inlined script was modified while embedding it')
        }
      }

      htmlEntry.source = html
      this.info(`single-file HTML: ${(bytes / 1024).toFixed(1)} KiB`)
    },
  }
}

export default defineConfig({
  base: './',
  plugins: [vue(), singleFileHtml()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: '../python/sheetkit/webui',
    emptyOutDir: true,
    modulePreload: false,
    cssCodeSplit: false,
    assetsInlineLimit: Number.MAX_SAFE_INTEGER,
    sourcemap: false,
    rollupOptions: {
      output: {
        format: 'iife',
        inlineDynamicImports: true,
        entryFileNames: 'assets/app.js',
        assetFileNames: 'assets/[name][extname]',
      },
    },
  },
})
