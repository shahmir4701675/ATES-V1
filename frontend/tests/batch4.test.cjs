const { test } = require('node:test')
const assert = require('node:assert/strict')
const { buildSync } = require('esbuild')
const { resolve } = require('node:path')
const Module = require('node:module')
const root = resolve(__dirname, '..')
function load(source) {
  const result = buildSync({ stdin: { contents: source, resolveDir: root, loader: 'tsx' }, bundle: true, platform: 'node', format: 'cjs', jsx: 'automatic', write: false, define: { 'import.meta.env': JSON.stringify({ VITE_API_URL: 'http://127.0.0.1:8000', VITE_USE_MOCK: 'false' }) } })
  const module = new Module(resolve(root, 'tests/runtime.cjs'), moduleParent)
  module.filename = resolve(root, 'tests/runtime.cjs')
  module.paths = Module._nodeModulePaths(root)
  module._compile(result.outputFiles[0].text, module.filename)
  return module.exports
}
const moduleParent = module
const ui = load(`import { renderToStaticMarkup as render } from 'react-dom/server';
import { TimetableGrid } from './src/components/TimetableGrid';
import { InputField } from './src/components/ui';
import { HelpPage } from './src/pages/HelpPage';
import { formatTimestamp } from './src/locales';
export { render, TimetableGrid, InputField, HelpPage, formatTimestamp };
import { createElement } from 'react'; export { createElement };`)
const h = ui.createElement

test('parallel classes share a normal-flow stack; complete lab continuation remains visible', () => {
  const slots = [1, 2].map((n) => ({ slot_id: String(n), slot_index: n, day_of_week: 'Monday', start_time: n === 1 ? '08:00' : '09:00', end_time: n === 1 ? '09:00' : '10:00', is_blocked: false }))
  const row = (id, duration) => ({ entry: { entry_id: id, session_type: duration === 1 ? 'Lecture' : 'Lab', is_locked: true }, startSlot: slots[0], durationSlots: duration, day: 'Monday', course: { course_code: id, title: 'اردو / UTF-8' }, batch: { program_code: id, batch_year: 2026, section: 'A' }, instructor: { full_name: 'Instructor ' + id }, room: { room_code: 'R' + id } })
  const html = ui.render(h(ui.TimetableGrid, { rows: [row('A101', 1), row('B202', 1), row('LAB303', 2)], slots, days: ['Monday'], canMove: false, onMove: () => {} }))
  const cells = html.split('grid-cell session-stack').slice(1)
  assert.equal(cells.length, 2)
  assert.ok(cells[0].includes('A101') && cells[0].includes('B202') && cells[0].includes('LAB303'))
  assert.ok(!cells[1].includes('A101') && cells[1].includes('LAB303'))
  assert.ok(cells[1].includes('(continued)') && cells[1].includes('09:00'))
  assert.ok(html.includes('اردو') && !html.includes('Adjust / lock'))
})

test('field error description references a real element and visible label', () => {
  const html = ui.render(h(ui.InputField, { id: 'room-capacity', label: 'Capacity', value: '0', onChange: () => {}, error: 'Enter a positive number' }))
  assert.match(html, /for="room-capacity"/)
  assert.match(html, /aria-describedby="room-capacity-error"/)
  assert.match(html, /id="room-capacity-error"/)
  assert.match(html, /aria-invalid="true"/)
})

test('Karachi display is independent of host timezone and handles UTC or explicit offsets', () => {
  process.env.TZ = 'America/New_York'
  assert.match(ui.formatTimestamp('2026-11-21T20:00:00'), /22\/11\/2026.*01:00:00/)
  assert.equal(ui.formatTimestamp('2026-11-21T20:00:00Z'), ui.formatTimestamp('2026-11-22T01:00:00+05:00'))
})

test('every role has real help/document links without inventing permission', () => {
  for (const role of ['Coordinator', 'Approver', 'Faculty', 'Student', 'Administrator']) {
    const html = ui.render(h(ui.HelpPage, { role }))
    assert.ok(html.includes('Your role: ' + role))
    assert.ok(html.includes('/help/user-manual.pdf') && html.includes('/help/quick-start.pdf'))
    assert.ok(html.includes('Asia/Karachi') && html.includes('No screenshot') === false)
  }
})

test('API presentation distinguishes cancellation, timeout, worker failure, unknown and proven infeasibility', async () => {
  const api = load(`export { getScheduleStatus } from './src/services/api';`)
  const original = global.fetch
  try {
    for (const [state, solver, expected] of [['Cancelled', 'interrupted', 'Cancelled'], ['TimedOut', 'interrupted', 'TimedOut'], ['Interrupted', 'interrupted', 'Failed'], ['Completed', 'unknown', 'Unknown'], ['Completed', 'infeasible', 'Infeasible']]) {
      global.fetch = async () => new Response(JSON.stringify({ schedule_id: 1, term_id: 1, config_id: 1, schedule_type: 'Timetable', version_no: 2, status: 'Infeasible', solver_status: solver, run_seconds: 10, generation_state: state, worker_stopped: true, generated_at: '2026-11-21T10:00:00', entry_count: 0, conflict_count: 1 }), { headers: { 'Content-Type': 'application/json' } })
      const result = await api.getScheduleStatus('1')
      assert.equal(result.solver_status, expected)
      assert.notEqual(result.status, 'Generated')
      if (expected === 'Infeasible') assert.match(result.message, /^No feasible/)
      else { assert.equal(result.result, null); assert.ok(!result.message.startsWith('No feasible')) }
    }
  } finally { global.fetch = original }
})
