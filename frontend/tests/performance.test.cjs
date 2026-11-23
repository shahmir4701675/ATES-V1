const { test } = require('node:test')
const assert = require('node:assert/strict')
const { buildSync } = require('esbuild')
const { resolve } = require('node:path')
const Module = require('node:module')
const root = resolve(__dirname, '..')
const result = buildSync({ stdin: { contents: `export { request, requestPage, setAuthToken } from './src/services/http'; export { LoadingSkeleton } from './src/components/ui'; export { DataTable } from './src/components/Modal'; export { createElement } from 'react'; export { renderToStaticMarkup as render } from 'react-dom/server';`, resolveDir: root, loader: 'tsx' }, bundle: true, platform: 'node', format: 'cjs', jsx: 'automatic', write: false, define: { 'import.meta.env': JSON.stringify({ VITE_API_URL: 'http://localhost:8000', VITE_USE_MOCK: 'false' }) } })
const loaded = new Module(resolve(root, 'tests/performance-runtime.cjs'), module)
loaded.filename = resolve(root, 'tests/performance-runtime.cjs'); loaded.paths = Module._nodeModulePaths(root)
loaded._compile(result.outputFiles[0].text, loaded.filename)
const api = loaded.exports
const response = (body, headers = {}) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json', ...headers } })

test('concurrent reads share transport but receive independently mutable data; later reads are fresh', async () => {
  const original = global.fetch
  let release; let calls = 0
  try {
    api.setAuthToken('test-account')
    global.fetch = (_, options) => {
      calls += 1; assert.equal(options.cache, 'no-store')
      return new Promise((resolve) => { release = () => resolve(response({ nested: { value: 1 } })) })
    }
    const a = api.request('/courses'); const b = api.request('/courses')
    assert.equal(calls, 1)
    release(); const [left, right] = await Promise.all([a, b])
    left.nested.value = 99; assert.equal(right.nested.value, 1)
    const again = api.request('/courses'); assert.equal(calls, 2); release(); await again
  } finally { global.fetch = original; api.setAuthToken(null) }
})

test('account changes isolate pending reads and an old401 cannot sign out the new account', async () => {
  const original = global.fetch; let oldRelease
  try {
    api.setAuthToken('old-account')
    global.fetch = () => new Promise((resolve) => { oldRelease = resolve })
    const old = api.request('/courses'); const oldFailure = assert.rejects(old, /session changed/)
    api.setAuthToken('new-account')
    global.fetch = (_, options) => { assert.equal(options.headers.Authorization, 'Bearer new-account'); return Promise.resolve(response(['new'])) }
    assert.deepEqual(await api.request('/courses'), ['new'])
    oldRelease(new Response('{"detail":"revoked"}', { status: 401 }))
    await oldFailure
    assert.deepEqual(await api.request('/courses'), ['new'])
  } finally { global.fetch = original; api.setAuthToken(null) }
})

test('writes invalidate pending-read reuse and are never deduplicated', async () => {
  const original = global.fetch; let release; let getCalls = 0; let writes = 0
  try {
    global.fetch = (_, options) => {
      if (options.method === 'PUT') { writes += 1; return Promise.resolve(response({ updated: true })) }
      getCalls += 1
      if (getCalls === 1) return new Promise((resolve) => { release = resolve })
      return Promise.resolve(response({ fresh: true }))
    }
    const old = api.request('/courses')
    await Promise.all([api.request('/courses/1', { method: 'PUT', body: {} }), api.request('/courses/1', { method: 'PUT', body: {} })])
    assert.equal(writes, 2)
    assert.deepEqual(await api.request('/courses'), { fresh: true }); assert.equal(getCalls, 2)
    release(response({ old: true })); await old
  } finally { global.fetch = original; api.setAuthToken(null) }
})

test('failed reads are not retained in the pending-response cache', async () => {
  const original = global.fetch; let calls = 0
  try {
    global.fetch = () => { calls += 1; return calls === 1 ? Promise.resolve(new Response('{"detail":"temporary"}', { status: 503 })) : Promise.resolve(response([])) }
    await assert.rejects(api.request('/rooms'), /temporary/)
    assert.deepEqual(await api.request('/rooms'), []); assert.equal(calls, 2)
  } finally { global.fetch = original; api.setAuthToken(null) }
})

test('page transport uses server total without fetching every page', async () => {
  const original = global.fetch; let calls = 0
  try {
    global.fetch = (url) => { calls += 1; assert.match(url, /page=2/); return Promise.resolve(response([{ user_id: 26 }], { 'X-Total-Count': '3000' })) }
    assert.deepEqual(await api.requestPage('/users', { query: { page: 2, page_size: 25 } }), { items: [{ user_id: 26 }], total: 3000 })
    assert.equal(calls, 1)
  } finally { global.fetch = original; api.setAuthToken(null) }
})

test('remote table retains server paging count and does not repaginate its received page', () => {
  const html = api.render(api.createElement(api.DataTable, { rows: [{ id: '26' }], columns: [{ key: 'id', label: 'ID', value: (r) => r.id }], rowKey: (r) => r.id, searchText: (r) => r.id, caption: 'Paged users', remote: { page: 2, total: 3000, query: '', sort: { key: 'id', dir: 1 }, onPage() {}, onQuery() {}, onSort() {} } }))
  assert.match(html, /Page 2 of 120/); assert.match(html, /3000 records/); assert.match(html, /<td>26<\/td>/)
})

test('loading skeleton exposes one live status and hides decorative blocks', () => {
  const html = api.render(api.createElement(api.LoadingSkeleton, { label: 'Loading page' }))
  assert.match(html, /role="status"/); assert.match(html, /aria-busy="true"/); assert.match(html, /Loading page/)
  assert.equal((html.match(/aria-hidden="true"/g) ?? []).length, 4)
})
