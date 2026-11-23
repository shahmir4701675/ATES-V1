const { test } = require('node:test')
const assert = require('node:assert/strict')
const { buildSync } = require('esbuild')
const { resolve } = require('node:path')
const Module = require('node:module')
const root = resolve(__dirname, '..')
const bundled = buildSync({ stdin: { contents: `export { saveSlotGrid, generateSlotGrid, setAuthToken } from './src/services/api'; export { slotGridInputFromSlots } from './src/pages/data/TermsSlotsTab';`, resolveDir: root, loader: 'tsx' }, bundle: true, platform: 'node', format: 'cjs', jsx: 'automatic', write: false, define: { 'import.meta.env': JSON.stringify({ VITE_API_URL: 'http://127.0.0.1:8000', VITE_USE_MOCK: 'false' }) } })
const compiled = new Module(resolve(root, 'tests/weekly-grid-runtime.cjs'), module)
compiled.filename = resolve(root, 'tests/weekly-grid-runtime.cjs')
compiled.paths = Module._nodeModulePaths(root)
compiled._compile(bundled.outputFiles[0].text, compiled.filename)
const api = compiled.exports
const input = { working_days: [1, 2, 3, 4, 5], first_start_time: '08:00', slot_length_min: 60, slots_per_day: 6 }

test('real-mode grid form service saves one parameter payload with PUT on every save', async () => {
  const originalFetch = global.fetch
  const requests = []
  const rows = input.working_days.flatMap((day, d) => Array.from({ length: 6 }, (_, i) => ({ slot_id: d * 6 + i + 1, term_id: 7, day_of_week: day, slot_index: i + 1, start_time: `${String(8 + i).padStart(2, '0')}:00`, end_time: `${String(9 + i).padStart(2, '0')}:00`, is_blocked: i === 4, block_reason: i === 4 ? 'Prayer' : null })))
  try {
    api.setAuthToken('test-only-token')
    global.fetch = async (url, options) => {
      requests.push({ url, method: options.method, body: JSON.parse(options.body) })
      assert.equal(options.headers.Authorization, 'Bearer test-only-token')
      return new Response(JSON.stringify(rows), { headers: { 'Content-Type': 'application/json' } })
    }
    const first = await api.saveSlotGrid('7', input)
    const again = await api.saveSlotGrid('7', input)
    assert.deepEqual(again, first)
    assert.equal(first.length, 30)
    assert.equal(new Set(first.map((r) => r.slot_id)).size, 30)
    assert.equal(first[0].day_of_week, 'Monday')
    assert.equal(first[4].block_reason, 'Prayer')
    await api.saveSlotGrid('7', { ...input, first_start_time: '09:00' })
    assert.equal(requests.length, 3)
    for (const request of requests) {
      assert.match(request.url, /\/terms\/7\/slots\/generate$/)
      assert.equal(request.method, 'PUT')
      assert.deepEqual(Object.keys(request.body).sort(), Object.keys(input).sort())
      assert.equal(new Set(request.body.working_days).size, 5)
    }
    assert.equal(requests[2].body.first_start_time, '09:00')
  } finally { global.fetch = originalFetch; api.setAuthToken(null) }
})

test('grid form initializes from the selected saved grid, not hardcoded defaults', () => {
  const rows = ['Tuesday', 'Thursday'].flatMap((day) => Array.from({ length: 4 }, (_, i) => ({ slot_id: `${day}${i}`, term_id: '9', day_of_week: day, slot_index: i + 1, start_time: `${String(9 + i).padStart(2, '0')}:30`, end_time: `${String(10 + i).padStart(2, '0')}:30`, is_blocked: false, block_reason: null })))
  assert.deepEqual(api.slotGridInputFromSlots(rows.reverse()), { working_days: [2, 4], first_start_time: '09:30', slot_length_min: 60, slots_per_day: 4 })
  assert.deepEqual(api.slotGridInputFromSlots([]), input)
})

test('legacy explicit grid creation still sends POST rather than acting as an upsert', async () => {
  const originalFetch = global.fetch
  try {
    global.fetch = async (_, options) => {
      assert.equal(options.method, 'POST')
      return new Response('[]', { headers: { 'Content-Type': 'application/json' } })
    }
    await api.generateSlotGrid('7', input)
  } finally { global.fetch = originalFetch }
})
