/**
 * In-memory mock implementation of the api module.
 * This is the ONLY file allowed to import `../data/mockData`. It is used when `VITE_USE_MOCK=true`
 * and by the clearly named `*Mock` functions whose backend routes do not exist yet.
 * Functions are synchronous here; `api.ts` wraps them in promises.
 */
import {
  audit_log, batches, course_offerings, courses, departments, enrollments, exam_entries, exam_entry_batches, exam_room_allocations,
  exam_slots, instructors, rooms, schedules, students, terms, time_slots, timetable_entries, users,
} from '../data/mockData'
import { DAY_NAMES, IMPORT_SPECS, defaultRules, parseCsv } from '../data/reference'
import type {
  ActivityItem, AppUser, AppUserInput, AuditEntry, AuditFilter, AvailabilityItem, Batch, ConfigInput, ConflictFilter, ConflictItem, Course, CourseOffering, DashboardSummary,
  Department, Enrollment, ExamScheduleRow, ExamSlot, ExamSlotInput, GenerationConfig, GenerationStatus, ImportReport, ImportResult, ImportType, Instructor, MoveResult,
  Room, Schedule, SchedulingConfig, SlotGridInput, Student, Term, TimeSlot, TimetableEntry, TimetableRow,
} from '../types'
import type { ConstraintRule } from '../types'

const clone = <T,>(value: T): T => structuredClone(value)

export class MockError extends Error {}

/* ------------------------------------------------------------------ stores */
const db = {
  terms: clone(terms), courses: clone(courses), instructors: clone(instructors), rooms: clone(rooms), batches: clone(batches), offerings: clone(course_offerings),
  enrollments: clone(enrollments), slots: clone(time_slots), examSlots: clone(exam_slots), schedules: clone(schedules), timetable: clone(timetable_entries),
  examEntries: clone(exam_entries), allocations: clone(exam_room_allocations), users: clone(users), audit: clone(audit_log),
  availability: new Map<string, Map<string, boolean>>(),
  configs: [
    { config_id: 'cfg-tt-1', term_id: 'fall-2026', schedule_type: 'Timetable', name: 'Default timetable', solver_time_limit_s: 120, random_seed: 1, rules: defaultRules('Timetable') },
    { config_id: 'cfg-ex-1', term_id: 'fall-2026', schedule_type: 'Exam schedule', name: 'Default exam schedule', solver_time_limit_s: 120, random_seed: 1, rules: defaultRules('Exam schedule') },
  ] as SchedulingConfig[],
}

// A Generated timetable copy so that manual moves can be demonstrated (the published v3 is read-only).
db.schedules.push({ schedule_id: 'sch-tt-v4', term_id: 'fall-2026', schedule_type: 'Timetable', version_no: 4, status: 'Generated', solver_status: 'Feasible', objective_score: 92.7, run_seconds: 80 })
timetable_entries.forEach((entry) => db.timetable.push({ ...clone(entry), entry_id: entry.entry_id.replace('tte', 'ttf'), schedule_id: 'sch-tt-v4', is_locked: false }))
db.schedules.forEach((schedule) => { schedule.config_id = schedule.schedule_type === 'Timetable' ? 'cfg-tt-1' : 'cfg-ex-1' })

const nextId = (prefix: string) => `${prefix}-${Date.now().toString(36)}${Math.floor(Math.random() * 1000).toString(36)}`

/* --------------------------------------------------------------- simple lists */
export const getTerms = (): Term[] => clone(db.terms)
export const getDepartments = (): Department[] => clone(departments)
export const getCourses = (): Course[] => clone(db.courses)
export const getInstructors = (): Instructor[] => clone(db.instructors)
export const getRooms = (): Room[] => clone(db.rooms)
export const getBatches = (): Batch[] => clone(db.batches)
export const getCourseOfferings = (): CourseOffering[] => clone(db.offerings)
export const getEnrollments = (): Enrollment[] => clone(db.enrollments)
export const getTimeSlots = (termId?: string): TimeSlot[] => clone(db.slots.filter((slot) => !termId || slot.term_id === termId))
export const getExamSlots = (termId?: string): ExamSlot[] => clone(db.examSlots.filter((slot) => !termId || slot.term_id === termId))
export const getStudents = (): Student[] => clone(students)

const withCounts = (schedule: Schedule): Schedule => {
  const entry_count = schedule.schedule_type === 'Timetable' ? db.timetable.filter((item) => item.schedule_id === schedule.schedule_id).length : db.examEntries.filter((item) => item.schedule_id === schedule.schedule_id).length
  const conflicts = conflictsFor(schedule.schedule_id)
  return { ...clone(schedule), entry_count, conflict_count: conflicts.length, hard_violation_count: conflicts.filter((item) => item.severity === 'Hard').length, generated_at: '2026-11-07T16:42:00Z', published_at: schedule.status === 'Published' ? '2026-11-08T10:18:00Z' : null }
}
export const getSchedules = (): Schedule[] => db.schedules.map(withCounts)

/* ------------------------------------------------------------------ dashboard */
const latestOf = (type: Schedule['schedule_type']) => {
  const list = getSchedules().filter((item) => item.schedule_type === type).sort((a, b) => b.version_no - a.version_no)
  return list.find((item) => item.status === 'Published') ?? list[0] ?? null
}

export const getDashboardSummary = (): DashboardSummary => {
  const timetable = latestOf('Timetable')
  const examSchedule = latestOf('Exam schedule')
  const conflicts = [timetable, examSchedule].flatMap((item) => (item ? conflictsFor(item.schedule_id) : []))
  const activity: ActivityItem[] = [...db.audit].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 3).map((item) => ({ id: item.log_id, title: item.details, detail: `${new Date(item.created_at).toLocaleString('en-GB')} · ${item.username}`, tone: item.action === 'PUBLISH' ? 'success' : 'neutral' }))
  return {
    activeTerm: clone(db.terms.find((term) => term.status === 'Active') ?? null),
    timetable, examSchedule,
    counts: { courses: db.courses.filter((item) => item.is_active).length, instructors: db.instructors.filter((item) => item.is_active).length, rooms: db.rooms.filter((item) => item.is_active).length, batches: db.batches.filter((item) => item.is_active).length, offerings: db.offerings.length, departments: departments.length },
    conflicts: { hard: conflicts.filter((item) => item.severity === 'Hard').length, warning: conflicts.filter((item) => item.severity === 'Warning').length },
    activity,
  }
}

/* ------------------------------------------------------------------ timetable */
export const getTimetable = (scheduleId = 'sch-tt-v3', termId = 'fall-2026'): TimetableRow[] => {
  const byOfferingAndDay = new Map<string, TimetableEntry[]>()
  db.timetable.filter((entry) => entry.schedule_id === scheduleId).forEach((entry) => {
    const slot = db.slots.find((item) => item.slot_id === entry.slot_id)!
    if (slot.term_id !== termId) return
    const key = `${entry.offering_id}-${slot.day_of_week}-${entry.room_id}`
    byOfferingAndDay.set(key, [...(byOfferingAndDay.get(key) ?? []), entry])
  })
  const slotOf = (entry: TimetableEntry) => db.slots.find((slot) => slot.slot_id === entry.slot_id)!
  return [...byOfferingAndDay.values()].flatMap((entries) => {
    const sorted = [...entries].sort((a, b) => slotOf(a).slot_index - slotOf(b).slot_index)
    const runs: TimetableEntry[][] = []
    sorted.forEach((entry, index) => {
      const previous = sorted[index - 1]
      const contiguous = Boolean(previous && slotOf(entry).slot_index === slotOf(previous).slot_index + 1 && previous.session_type === entry.session_type)
      if (!runs.length || !contiguous) runs.push([entry]); else runs[runs.length - 1].push(entry)
    })
    return runs.map((run) => {
      const first = run[0]
      const startSlot = slotOf(first)
      const offering = db.offerings.find((item) => item.offering_id === first.offering_id)!
      return {
        entry: clone(first), entries: clone(run),
        course: clone(db.courses.find((course) => course.course_id === offering.course_id)!),
        room: clone(db.rooms.find((room) => room.room_id === first.room_id)!),
        instructor: clone(db.instructors.find((instructor) => instructor.instructor_id === first.instructor_id)!),
        batch: clone(db.batches.find((batch) => batch.batch_id === first.batch_id)!),
        startSlot: clone(startSlot), day: startSlot.day_of_week, durationSlots: run.length,
      }
    })
  }).sort((a, b) => a.startSlot.slot_index - b.startSlot.slot_index)
}

export const getExamSchedule = (scheduleId = 'sch-ex-v2'): ExamScheduleRow[] => db.examEntries.filter((entry) => entry.schedule_id === scheduleId).map((entry) => {
  const batch = db.batches.find((item) => item.batch_id === exam_entry_batches[entry.exam_entry_id])!
  return {
    entry: clone(entry),
    course: clone(db.courses.find((item) => item.course_id === entry.course_id)!),
    examSlot: clone(db.examSlots.find((slot) => slot.exam_slot_id === entry.exam_slot_id)!),
    rooms: db.allocations.filter((item) => item.exam_entry_id === entry.exam_entry_id).map((allocation) => ({ room: clone(db.rooms.find((room) => room.room_id === allocation.room_id)!), seats: allocation.seats_allocated })),
    batch: clone(batch), batches: [clone(batch)],
  }
}).sort((a, b) => `${a.examSlot.exam_date}${a.examSlot.start_time}`.localeCompare(`${b.examSlot.exam_date}${b.examSlot.start_time}`))

/* ----------------------------------------------------------------- conflicts */
const seedConflicts: ConflictItem[] = [
  { conflict_id: 'cf-1', schedule_id: 'sch-tt-v4', conflict_type: 'S01', severity: 'Warning', description: 'Batch B.Tech CSE 2024 A has a two-slot gap on Wednesday.', entity_ref: 'batch_id=b-cse24a', detected_at: '2026-11-07T16:42:00Z', is_resolved: false },
  { conflict_id: 'cf-2', schedule_id: 'sch-tt-v3', conflict_type: 'S06', severity: 'Warning', description: 'CSE 101 is in A-101 (72 seats) for 62 students; a smaller room is free.', entity_ref: 'offering_id=off-101-a', detected_at: '2026-11-06T12:00:00Z', is_resolved: false },
  { conflict_id: 'cf-3', schedule_id: 'sch-ex-v2', conflict_type: 'ES03', severity: 'Warning', description: 'CSE 204 uses Main Hall and Seminar Hall; both are in Central Hall, so this is informational.', entity_ref: 'exam_entry_id=ex-003', detected_at: '2026-11-07T16:42:00Z', is_resolved: false },
]
const conflictsFor = (scheduleId: string) => seedConflicts.filter((item) => item.schedule_id === scheduleId)
export const getConflicts = (scheduleId: string, filter: ConflictFilter = {}): ConflictItem[] => clone(conflictsFor(scheduleId).filter((item) => (!filter.conflict_type || item.conflict_type === filter.conflict_type) && (!filter.severity || item.severity === filter.severity)))

/* --------------------------------------------------------------- manual moves */
const scheduleOf = (scheduleId: string) => db.schedules.find((item) => item.schedule_id === scheduleId)
const editable = (schedule: Schedule | undefined): MoveResult | null => (!schedule || schedule.status === 'Published' || schedule.status === 'Archived'
  ? { ok: false, message: `Schedule version ${schedule?.version_no ?? ''} is ${schedule?.status ?? 'missing'} and cannot be edited in place. Only Generated or Draft versions allow manual moves.`, rule_code: null, violated_constraints: [] } : null)

export const moveTimetableEntry = (scheduleId: string, entryId: string, change: { slot_id?: string; room_id?: string }): MoveResult => {
  const blocked = editable(scheduleOf(scheduleId)); if (blocked) return blocked
  const entry = db.timetable.find((item) => item.entry_id === entryId && item.schedule_id === scheduleId)
  if (!entry) throw new MockError(`Timetable entry ${entryId} not found.`)
  const slot_id = change.slot_id ?? entry.slot_id
  const room_id = change.room_id ?? entry.room_id
  const slot = db.slots.find((item) => item.slot_id === slot_id)!
  const others = db.timetable.filter((item) => item.schedule_id === scheduleId && item.entry_id !== entryId && item.slot_id === slot_id)
  const fail = (code: string, why: string): MoveResult => ({ ok: false, message: `Manual move violates hard constraint ${code}: ${why}`, rule_code: code, violated_constraints: [code] })
  if (others.some((item) => item.instructor_id === entry.instructor_id)) return fail('H01', 'the instructor already teaches another session in this slot.')
  if (others.some((item) => item.room_id === room_id)) return fail('H02', 'the room already hosts another session in this slot.')
  if (others.some((item) => item.batch_id === entry.batch_id)) return fail('H03', 'the batch already attends another session in this slot.')
  if (slot.is_blocked) return fail('H07', `the slot is blocked (${slot.block_reason ?? 'break'}).`)
  Object.assign(entry, { slot_id, room_id, is_manual_override: true })
  return { ok: true }
}

export const moveExamEntry = (scheduleId: string, examEntryId: string, change: { exam_slot_id?: string }): MoveResult => {
  const blocked = editable(scheduleOf(scheduleId)); if (blocked) return blocked
  const entry = db.examEntries.find((item) => item.exam_entry_id === examEntryId && item.schedule_id === scheduleId)
  if (!entry) throw new MockError(`Exam entry ${examEntryId} not found.`)
  const exam_slot_id = change.exam_slot_id ?? entry.exam_slot_id
  const myBatch = exam_entry_batches[examEntryId]
  const clash = db.examEntries.find((item) => item.exam_entry_id !== examEntryId && item.schedule_id === scheduleId && item.exam_slot_id === exam_slot_id && exam_entry_batches[item.exam_entry_id] === myBatch)
  if (clash) return { ok: false, message: 'Manual move violates hard constraint E01: two courses that share students would sit in the same exam session.', rule_code: 'E01', violated_constraints: ['E01'] }
  const hallClash = db.allocations.filter((item) => item.exam_entry_id === examEntryId).some((mine) => db.allocations.some((other) => other.exam_entry_id !== examEntryId && other.room_id === mine.room_id && db.examEntries.find((item) => item.exam_entry_id === other.exam_entry_id)?.exam_slot_id === exam_slot_id))
  if (hallClash) return { ok: false, message: 'Manual move violates hard constraint E04: a room would be used by two exams in the same session.', rule_code: 'E04', violated_constraints: ['E04'] }
  entry.exam_slot_id = exam_slot_id
  return { ok: true }
}

/* ------------------------------------------------------------- generation (legacy mock) */
interface RunState { startedAt: number; config: GenerationConfig; cancelled: boolean; simulated_duration_seconds: number }
const runs = new Map<string, RunState>()

export const generateSchedule = (config: GenerationConfig): { run_id: string } => {
  const run_id = `run-${Date.now()}`
  runs.set(run_id, { startedAt: Date.now(), config: clone(config), cancelled: false, simulated_duration_seconds: Math.max(4, Math.min(8, Math.round(config.time_limit / 20))) })
  return { run_id }
}
export const cancelGeneration = (run_id: string): void => { const run = runs.get(run_id); if (run) run.cancelled = true }
export const getScheduleStatus = (run_id: string): GenerationStatus => {
  const run = runs.get(run_id)
  if (!run) return { run_id, status: 'Infeasible', solver_status: 'Stopped', progress: 0, elapsed_seconds: 0, message: 'Generation run was not found.', result: null }
  const elapsed_seconds = Math.max(0, Math.round((Date.now() - run.startedAt) / 1000))
  const duration = run.simulated_duration_seconds
  const progress = Math.min(100, Math.round((elapsed_seconds / duration) * 100))
  if (run.cancelled) return { run_id, status: 'Draft', solver_status: 'Stopped', progress, elapsed_seconds, message: 'Generation cancelled by user.', result: null }
  if (elapsed_seconds >= run.config.time_limit) return { run_id, status: 'Infeasible', solver_status: 'Stopped', progress: 100, elapsed_seconds, message: `No feasible ${run.config.schedule_type.toLowerCase()} found within the configured time limit.`, result: { schedule_id: '', hard_constraint_violations: 1, soft_score: 0 } }
  if (progress < 100) return { run_id, status: 'Generating', solver_status: 'Running', progress, elapsed_seconds, message: progress < 40 ? 'Preparing constraints' : progress < 80 ? 'Searching feasible assignments' : 'Scoring candidate schedule', result: null }
  const isTimetable = run.config.schedule_type === 'Timetable'
  return { run_id, status: 'Generated', solver_status: 'Optimal', progress: 100, elapsed_seconds, message: `${run.config.schedule_type} generated successfully within the ${run.config.time_limit}-second limit.`, result: { schedule_id: isTimetable ? 'sch-tt-v4' : 'sch-ex-v2', hard_constraint_violations: 0, soft_score: isTimetable ? 96.4 : 91.8, entry_count: isTimetable ? 9 : 5, conflict_count: 1 } }
}

/* ----------------------------------------------------------- generic master data */
type Entity = 'courses' | 'instructors' | 'rooms' | 'batches' | 'offerings' | 'terms' | 'enrollments'
const entityMeta: Record<Entity, { key: string; prefix: string; store: () => Array<Record<string, unknown>> }> = {
  courses: { key: 'course_id', prefix: 'c', store: () => db.courses as never }, instructors: { key: 'instructor_id', prefix: 'i', store: () => db.instructors as never },
  rooms: { key: 'room_id', prefix: 'r', store: () => db.rooms as never }, batches: { key: 'batch_id', prefix: 'b', store: () => db.batches as never },
  offerings: { key: 'offering_id', prefix: 'off', store: () => db.offerings as never }, terms: { key: 'term_id', prefix: 'term', store: () => db.terms as never },
  enrollments: { key: 'enrollment_id', prefix: 'enr', store: () => db.enrollments as never },
}

export const saveRecord = <T,>(entity: Entity, id: string | null, payload: Record<string, unknown>): T => {
  const { key, prefix, store } = entityMeta[entity]
  const list = store()
  if (id === null) {
    if (entity === 'terms' && payload.status === 'Active' && db.terms.some((term) => term.status === 'Active')) throw new MockError('Another term is already Active. Only one term may be Active at a time.')
    const record = { ...payload, [key]: nextId(prefix) }
    list.push(record)
    return clone(record) as T
  }
  const record = list.find((item) => item[key] === id)
  if (!record) throw new MockError(`Record ${id} was not found.`)
  if (entity === 'terms' && payload.status === 'Active' && db.terms.some((term) => term.status === 'Active' && term.term_id !== id)) throw new MockError('Another term is already Active. Only one term may be Active at a time.')
  Object.assign(record, payload)
  return clone(record) as T
}

export const deactivateRecord = (entity: Entity, id: string): void => {
  const { key, store } = entityMeta[entity]
  const list = store()
  const index = list.findIndex((item) => item[key] === id)
  if (index < 0) throw new MockError(`Record ${id} was not found.`)
  if (entity === 'terms') list[index].status = 'Closed'
  else if ('is_active' in list[index]) list[index].is_active = false
  else list.splice(index, 1)
}

/* -------------------------------------------------------------- terms and slots */
export const generateSlotGrid = (termId: string, input: SlotGridInput): TimeSlot[] => {
  const [hour, minute] = input.first_start_time.split(':').map(Number)
  const created: TimeSlot[] = []
  const fmt = (total: number) => `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
  ;[...new Set(input.working_days)].sort().forEach((day) => {
    for (let index = 1; index <= input.slots_per_day; index += 1) {
      const start = hour * 60 + minute + (index - 1) * input.slot_length_min
      if (db.slots.some((slot) => slot.term_id === termId && slot.day_of_week === DAY_NAMES[day - 1] && slot.slot_index === index)) throw new MockError('Slot grid overlaps existing slots in this term.')
      created.push({ slot_id: nextId('slot'), term_id: termId, day_of_week: DAY_NAMES[day - 1], slot_index: index, start_time: fmt(start), end_time: fmt(start + input.slot_length_min), is_blocked: false, block_reason: null })
    }
  })
  db.slots.push(...created)
  return clone(created)
}

export const saveSlotGrid = (termId: string, input: SlotGridInput): TimeSlot[] => {
  const existing = db.slots.filter((slot) => slot.term_id === termId)
  const keys = new Set(input.working_days.flatMap((day) => Array.from({ length: input.slots_per_day }, (_, index) => `${DAY_NAMES[day - 1]}:${index + 1}`)))
  if (existing.some((slot) => !keys.has(`${slot.day_of_week}:${slot.slot_index}`))) throw new MockError('Saving this grid would remove existing slots. No slots were changed.')
  const minutes = (value: string) => { const [h, m] = value.split(':').map(Number); return h * 60 + m }
  if (existing.length && minutes(existing[0].end_time) - minutes(existing[0].start_time) !== input.slot_length_min) throw new MockError('Keep the existing fixed slot length.')
  if (!input.working_days.length || new Set(input.working_days).size !== input.working_days.length || input.working_days.some((d) => !Number.isInteger(d) || d < 1 || d > 7) || !Number.isInteger(input.slots_per_day) || input.slots_per_day < 1 || !Number.isInteger(input.slot_length_min) || input.slot_length_min < 1 || !/^([01]\d|2[0-3]):[0-5]\d$/.test(input.first_start_time) || minutes(input.first_start_time) + input.slots_per_day * input.slot_length_min >= 1440) throw new MockError('Invalid weekly grid.')
  const fmt = (n: number) => `${String(Math.floor(n / 60)).padStart(2, '0')}:${String(n % 60).padStart(2, '0')}`
  const saved = [...input.working_days].sort().flatMap((day) => Array.from({ length: input.slots_per_day }, (_, i) => {
    const old = existing.find((slot) => slot.day_of_week === DAY_NAMES[day - 1] && slot.slot_index === i + 1)
    const start = minutes(input.first_start_time) + i * input.slot_length_min
    return { slot_id: old?.slot_id ?? nextId('slot'), term_id: termId, day_of_week: DAY_NAMES[day - 1], slot_index: i + 1, start_time: fmt(start), end_time: fmt(start + input.slot_length_min), is_blocked: old?.is_blocked ?? false, block_reason: old?.block_reason ?? null }
  }))
  for (const slot of saved) {
    const old = existing.find((item) => item.slot_id === slot.slot_id)
    if (old) Object.assign(old, slot); else db.slots.push(slot)
  }
  return clone(saved)
}

export const updateSlot = (termId: string, slotId: string, change: { is_blocked: boolean; block_reason: string | null }): TimeSlot => {
  const slot = db.slots.find((item) => item.slot_id === slotId && item.term_id === termId)
  if (!slot) throw new MockError('Slot not found.')
  if (change.is_blocked && !change.block_reason?.trim()) throw new MockError('block_reason is required when a slot is blocked.')
  slot.is_blocked = change.is_blocked
  slot.block_reason = change.is_blocked ? change.block_reason!.trim() : null
  return clone(slot)
}

export const createExamSlot = (termId: string, input: ExamSlotInput): ExamSlot => {
  const clash = db.examSlots.find((slot) => slot.term_id === termId && slot.exam_date === input.exam_date && input.start_time < slot.end_time && slot.start_time < input.end_time)
  if (clash) throw new MockError(`Exam session ${input.start_time}–${input.end_time} overlaps existing session ${clash.start_time}–${clash.end_time} on ${input.exam_date}.`)
  const slot: ExamSlot = { exam_slot_id: nextId('exslot'), term_id: termId, ...input }
  db.examSlots.push(slot)
  return clone(slot)
}

/* ------------------------------------------------------------------ availability */
export const getAvailability = (instructorId: string): AvailabilityItem[] => [...(db.availability.get(instructorId) ?? new Map()).entries()].map(([slot_id, is_available]) => ({ slot_id, is_available }))
export const saveAvailability = (instructorId: string, items: AvailabilityItem[]): AvailabilityItem[] => {
  const map = db.availability.get(instructorId) ?? new Map<string, boolean>()
  items.forEach((item) => map.set(item.slot_id, item.is_available))
  db.availability.set(instructorId, map)
  return getAvailability(instructorId)
}

/* ------------------------------------------------------------------------ configs */
export const getConfigs = (termId?: string, scheduleType?: SchedulingConfig['schedule_type']): SchedulingConfig[] => clone(db.configs.filter((item) => (!termId || item.term_id === termId) && (!scheduleType || item.schedule_type === scheduleType)))
export const createConfig = (input: ConfigInput): SchedulingConfig => {
  if (db.configs.some((item) => item.term_id === input.term_id && item.schedule_type === input.schedule_type && item.name.toLowerCase() === input.name.trim().toLowerCase())) throw new MockError(`Configuration '${input.name}' already exists for this term and schedule type.`)
  const config: SchedulingConfig = { config_id: nextId('cfg'), term_id: input.term_id, schedule_type: input.schedule_type, name: input.name.trim(), solver_time_limit_s: input.solver_time_limit_s, random_seed: input.random_seed, rules: clone(input.rules ?? defaultRules(input.schedule_type)) }
  db.configs.push(config)
  return clone(config)
}
export const updateConfig = (configId: string, change: Partial<Pick<SchedulingConfig, 'name' | 'solver_time_limit_s' | 'random_seed'>>): SchedulingConfig => {
  const config = db.configs.find((item) => item.config_id === configId)
  if (!config) throw new MockError('Configuration not found.')
  Object.assign(config, change)
  return clone(config)
}
export const saveConfigRules = (configId: string, rules: ConstraintRule[]): ConstraintRule[] => {
  const config = db.configs.find((item) => item.config_id === configId)
  if (!config) throw new MockError('Configuration not found.')
  config.rules = clone(rules)
  return clone(config.rules)
}
export const deleteConfig = (configId: string): void => {
  if (db.schedules.some((schedule) => schedule.config_id === configId)) throw new MockError('This configuration was used to generate a schedule and cannot be deleted.')
  const index = db.configs.findIndex((item) => item.config_id === configId)
  if (index >= 0) db.configs.splice(index, 1)
}

/* ------------------------------------------------------------ publish (no backend route yet) */
export const publishSchedule = (scheduleId: string): Schedule => {
  const schedule = db.schedules.find((item) => item.schedule_id === scheduleId)
  if (!schedule) throw new MockError('Schedule not found.')
  if (schedule.status !== 'Generated') throw new MockError('Only a Generated version can be published.')
  if (conflictsFor(scheduleId).some((item) => item.severity === 'Hard')) throw new MockError('A version with hard violations cannot be published.')
  db.schedules.filter((item) => item.schedule_type === schedule.schedule_type && item.term_id === schedule.term_id && item.status === 'Published').forEach((item) => { item.status = 'Archived' })
  schedule.status = 'Published'
  db.audit.push({ log_id: nextId('a'), user_id: 'u-3', username: 'approver', action: 'PUBLISH', entity_type: 'schedules', entity_id: scheduleId, details: `Published ${schedule.schedule_type.toLowerCase()} version ${schedule.version_no}.`, created_at: new Date().toISOString() })
  return withCounts(schedule)
}

/* ------------------------------------------------------------------- CSV import */
const pending = new Map<string, { type: ImportType; rows: Array<Record<string, string>> }>()
const norm = (value: string) => value.trim().toLowerCase()

export const validateImport = (type: ImportType, fileName: string, text: string): ImportReport => {
  const spec = IMPORT_SPECS[type]
  const parsed = parseCsv(text)
  const import_id = nextId('imp')
  const rejected: ImportReport['rejected'] = []
  if (!parsed.length) return { import_id, type, file_name: fileName, rows_total: 0, rows_valid: 0, rejected: [{ line: 1, column: '(file)', reason: 'The file is empty.' }] }
  const header = parsed[0].cells.map((cell) => cell.trim())
  const missing = spec.columns.filter((column) => !header.includes(column.name))
  if (missing.length) return { import_id, type, file_name: fileName, rows_total: Math.max(parsed.length - 1, 0), rows_valid: 0, rejected: missing.map((column) => ({ line: 1, column: column.name, reason: 'Required column is missing from the header row.' })) }
  const seen = new Set<string>()
  const valid: Array<Record<string, string>> = []
  parsed.slice(1).forEach(({ line, cells }) => {
    const row: Record<string, string> = {}
    header.forEach((name, index) => { row[name] = (cells[index] ?? '').trim() })
    const errors: Array<[string, string]> = []
    spec.columns.forEach((column) => {
      const value = row[column.name]
      if (!value) { errors.push([column.name, 'A value is required.']); return }
      if (column.kind === 'int' && (!/^-?\d+$/.test(value) || Number(value) < (column.min ?? 0))) errors.push([column.name, `Must be a whole number of at least ${column.min ?? 0}.`])
      if (column.kind === 'enum' && !column.enumValues!.includes(value)) errors.push([column.name, `Must be one of: ${column.enumValues!.join(', ')}.`])
    })
    const codeKey = type === 'courses' ? row.course_code : type === 'rooms' ? row.room_code : type === 'instructors' ? row.email : type === 'batches' ? `${row.program_code}|${row.batch_year}|${row.section}` : ''
    if (codeKey) {
      const existing = type === 'courses' ? db.courses.some((item) => norm(item.course_code) === norm(codeKey)) : type === 'rooms' ? db.rooms.some((item) => norm(item.room_code) === norm(codeKey)) : type === 'instructors' ? db.instructors.some((item) => norm(item.email) === norm(codeKey)) : db.batches.some((item) => norm(`${item.program_code}|${item.batch_year}|${item.section}`) === norm(codeKey))
      const column = type === 'courses' ? 'course_code' : type === 'rooms' ? 'room_code' : type === 'instructors' ? 'email' : 'program_code'
      if (existing) errors.push([column, 'Already exists in the system; codes must be unique.'])
      else if (seen.has(norm(codeKey))) errors.push([column, 'Duplicate of an earlier row in this file.'])
      seen.add(norm(codeKey))
    }
    if (type === 'courses' && Number(row.lecture_hours) + Number(row.lab_hours) <= 0) errors.push(['lecture_hours', 'lecture_hours + lab_hours must be greater than 0.'])
    if (type === 'instructors' && Number(row.max_weekly_hours) < Number(row.max_daily_hours)) errors.push(['max_weekly_hours', 'Must be greater than or equal to max_daily_hours.'])
    if ((type === 'courses' || type === 'instructors') && row.department_code && !departments.some((item) => item.code === row.department_code)) errors.push(['department_code', `Unknown department '${row.department_code}'.`])
    if (type === 'offerings' || type === 'enrollments') {
      if (row.course_code && !db.courses.some((item) => norm(item.course_code) === norm(row.course_code))) errors.push(['course_code', `Unknown course '${row.course_code}'.`])
      if (row.term_name && !db.terms.some((item) => norm(item.label) === norm(row.term_name))) errors.push(['term_name', `Unknown term '${row.term_name}'.`])
    }
    if (errors.length) errors.forEach(([column, reason]) => rejected.push({ line, column, reason })); else valid.push(row)
  })
  pending.set(import_id, { type, rows: valid })
  return { import_id, type, file_name: fileName, rows_total: parsed.length - 1, rows_valid: valid.length, rejected }
}

export const confirmImport = (importId: string, mode: 'valid_only' | 'cancel'): ImportResult => {
  const job = pending.get(importId)
  if (!job) throw new MockError('This import session has expired. Upload the file again.')
  pending.delete(importId)
  if (mode === 'cancel') return { rows_imported: 0, rows_rejected: 0 }
  const departmentId = (code: string) => departments.find((item) => item.code === code)?.department_id ?? departments[0].department_id
  job.rows.forEach((row) => {
    if (job.type === 'courses') db.courses.push({ course_id: nextId('c'), course_code: row.course_code, title: row.title, department_id: departmentId(row.department_code), credit_hours: Number(row.credit_hours), lecture_hours: Number(row.lecture_hours), lab_hours: Number(row.lab_hours), is_active: true })
    if (job.type === 'instructors') db.instructors.push({ instructor_id: nextId('i'), full_name: row.full_name, email: row.email, department_id: departmentId(row.department_code), max_daily_hours: Number(row.max_daily_hours), max_weekly_hours: Number(row.max_weekly_hours), is_active: true })
    if (job.type === 'rooms') db.rooms.push({ room_id: nextId('r'), room_code: row.room_code, building: row.building, capacity: Number(row.capacity), room_type: row.room_type as Room['room_type'], is_active: true })
    if (job.type === 'batches') db.batches.push({ batch_id: nextId('b'), program_code: row.program_code, batch_year: Number(row.batch_year), section: row.section, strength: Number(row.strength), is_active: true })
  })
  return { rows_imported: job.rows.length, rows_rejected: 0 }
}

/* ------------------------------------------------------------------ users and audit */
export const getUsers = (): AppUser[] => clone(db.users)
export const saveUser = (id: string | null, input: AppUserInput): AppUser => {
  if (db.users.some((user) => user.user_id !== id && norm(user.username) === norm(input.username))) throw new MockError(`User name '${input.username}' is already taken.`)
  if (db.users.some((user) => user.user_id !== id && norm(user.email) === norm(input.email))) throw new MockError(`E-mail '${input.email}' is already used by another account.`)
  const { password: _password, ...fields } = input
  if (id === null) { const user: AppUser = { user_id: nextId('u'), ...fields }; db.users.push(user); return clone(user) }
  const user = db.users.find((item) => item.user_id === id)
  if (!user) throw new MockError('Account not found.')
  Object.assign(user, fields)
  return clone(user)
}
export const getAuditLog = (filter: AuditFilter = {}): AuditEntry[] => clone(db.audit
  .filter((item) => (!filter.user_id || item.user_id === filter.user_id) && (!filter.action || item.action === filter.action) && (!filter.from || item.created_at.slice(0, 10) >= filter.from) && (!filter.to || item.created_at.slice(0, 10) <= filter.to))
  .sort((a, b) => b.created_at.localeCompare(a.created_at)))
