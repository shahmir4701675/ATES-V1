import { readFileSync, readdirSync, existsSync, writeFileSync } from 'node:fs'
import { resolve, join } from 'node:path'
import { gzipSync, gunzipSync, brotliDecompressSync } from 'node:zlib'
import assert from 'node:assert/strict'

const folder = resolve(process.argv[2] || 'audit_reports/performance/frontend_build')
const manifest = JSON.parse(readFileSync(join(folder, '.vite/manifest.json'), 'utf8'))
const initial = new Set()
function visit(key) {
  if (initial.has(key)) return
  initial.add(key)
  for (const imported of manifest[key].imports || []) visit(imported)
}
for (const [key, value] of Object.entries(manifest)) if (value.isEntry) visit(key)
const initialFiles = [...initial].map((key) => manifest[key].file).filter((file) => file.endsWith('.js'))
const raw = initialFiles.map((file) => readFileSync(join(folder, file)))
const dynamicPages = Object.values(manifest).filter((item) => item.isDynamicEntry && item.src?.startsWith('src/pages/'))
assert.ok(dynamicPages.length >= 14)
let verifiedCompressedFiles = 0
for (const file of readdirSync(join(folder, 'assets')).filter((f) => /\.(js|css)$/.test(f))) {
  const source = readFileSync(join(folder, 'assets', file))
  for (const [extension, decompress] of [['gz', gunzipSync], ['br', brotliDecompressSync]]) {
    const path = join(folder, 'assets', file + '.' + extension)
    if (existsSync(path)) { assert.ok(decompress(readFileSync(path)).equals(source), `${file}.${extension} must match the final asset`); verifiedCompressedFiles += 1 }
  }
}
const baselineDir = resolve('audit_reports/weekly_grid_frontend_build/assets')
const baseline = readdirSync(baselineDir).filter((f) => f.endsWith('.js')).map((f) => readFileSync(join(baselineDir, f)))
const total = (list) => list.reduce((n, source) => n + source.length, 0)
const gzipTotal = (list) => list.reduce((n, source) => n + gzipSync(source, { level: 6 }).length, 0)
const before = gzipTotal(baseline), after = gzipTotal(raw)
assert.ok(after < before)
const result = {
  baseline_build: 'weekly_grid_frontend_build (before this performance task)',
  baseline_initial_js_bytes: total(baseline), baseline_initial_js_gzip_bytes: before,
  new_initial_files: initialFiles, new_initial_js_bytes: total(raw), new_initial_js_gzip_bytes: after,
  initial_js_gzip_reduction_percent: (1 - after / before) * 100,
  lazy_page_count: dynamicPages.length, compressed_files_roundtrip_verified: verifiedCompressedFiles,
  scope: 'Static import graph before opening a lazy page; not browser LCP/TTI or all-page total-download claim.',
}
writeFileSync(resolve('audit_reports/performance/bundle_measurements.json'), JSON.stringify(result, null, 2))
process.stdout.write(JSON.stringify(result, null, 2) + '\n')
