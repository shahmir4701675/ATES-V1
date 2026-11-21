/**
 * Public data service for the whole UI. Components import from here only and never call fetch.
 *
 * Real mode talks to the FastAPI server at VITE_API_URL. Set VITE_USE_MOCK=true to run on the
 * in-memory mock instead. Backend response shapes are adapted to the UI shapes in this file only.
 * Functions ending in `Mock` have no backend route yet and always use mock data (see the route list in the hand-over notes).
 * Ids are numbers on the server and strings in the UI; conversion happens in `fromServer` / `toServer`.
 */
import { DAY_NAMES, MAX_IMPORT_BYTES, importTemplateCsv } from '../data/reference'
import { API_URL, ApiError, USE_MOCK, request, setAuthToken } from './http'
import * as mock from './mockApi'
import type {
  AppUser, AppUserInput, AuditEntry, AuditFilter, AvailabilityItem, Batch, ConfigInput, ConflictFilter, ConflictItem, ConstraintRule, Course, CourseOffering, DashboardSummary,
  Department, Enrollment, ExamScheduleRow, ExamSlot, ExamSlotInput, GenerationConfig, GenerationStatus, ImportReport, ImportResult, ImportType, Instructor, LoginResult, MoveResult,
  Room, Schedule, ScheduleStatus, ScheduleType, SchedulingConfig, SlotGridInput, SolverStatus, Term, TimeSlot, TimetableEntry, TimetableRow, ActivityItem,
} from '../types'

export { API_URL, ApiError, USE_MOCK, setAuthToken }
export const errorMessage = (error: unknown): string => (error instanceof Error ? error.message : 'Something went wrong. Try again.')

/* eslint-disable @typescript-eslint/no-explicit-any */
type Raw = Record<string, any>
const via = <T,>(useMock: () => T, useServer: () => Promise<T>): Promise<T> => (USE_MOCK ? Promise.resolve().then(useMock) : useServer())

/* --------------------------------------------------------------- id and shape adapters */
const fromServer = <T,>(row: Raw): T => Object.fromEntries(Object.entries(row).map(([key, value]) => [key, key.endsWith('_id') && typeof value === 'number' ? String(value) : value])) as T
const toServer = (payload: Raw): Raw => Object.fromEntries(Object.entries(payload)
  .filter(([, value]) => value !== undefined)
  .map(([key, value]) => [key, key.endsWith('_id') && typeof value === 'string' && /^\d+$/.test(value) ? Number(value) : value]))
const num = (id: string) => Number(id)

const uiType = (type: string): ScheduleType => (type === 'Exam' ? 'Exam schedule' : 'Timetable')
const serverType = (type: ScheduleType) => (type === 'Exam schedule' ? 'Exam' : 'Timetable')
const uiSolver = (status: string | null, state: string): SolverStatus => {
  if (state === 'Generating') return 'Running'
  if (status === 'optimal') return 'Optimal'
  if (status === 'feasible') return 'Feasible'
  return status ? 'Stopped' : 'Not started'
}
const toTerm = (row: Raw): Term => ({ term_id: String(row.term_id), label: row.name, start_date: row.start_date, end_date: row.end_date, status: row.status })
const toSlot = (row: Raw): TimeSlot => ({ ...fromServer<TimeSlot>(row), day_of_week: DAY_NAMES[row.day_of_week - 1] ?? String(row.day_of_week), block_reason: row.block_reason ?? null })
const toExamSlot = (row: Raw): ExamSlot => ({ ...fromServer<ExamSlot>(row), label: row.label ?? '' })
const toSchedule = (row: Raw): Schedule => ({
  schedule_id: String(row.schedule_id), term_id: String(row.term_id), config_id: String(row.config_id), schedule_type: uiType(row.schedule_type), version_no: row.version_no,
  status: row.status as ScheduleStatus, solver_status: uiSolver(row.solver_status, row.status), objective_score: row.objective_score ?? null, run_seconds: row.run_seconds ?? null,
  entry_count: row.entry_count, conflict_count: row.conflict_count, hard_violation_count: row.hard_violation_count, generated_at: row.generated_at, published_at: row.published_at ?? null,
})
const toRule = (row: Raw): ConstraintRule => ({ rule_code: row.rule_code, rule_type: row.rule_type, is_enabled: row.is_enabled, weight: row.weight, param_value: row.param_value ?? null })
const toConfig = (row: Raw): SchedulingConfig => ({ config_id: String(row.config_id), term_id: String(row.term_id), schedule_type: uiType(row.schedule_type), name: row.name, solver_time_limit_s: row.solver_time_limit_s, random_seed: row.random_seed, rules: (row.rules ?? []).map(toRule) })

const PAGE_SIZE = 200
/** Server lists are paged (max 200 per page); read every page so callers get the full list. */
async function fetchAll<T extends Raw>(path: string, query: Record<string, string | number | boolean | undefined> = {}): Promise<T[]> {
  const all: T[] = []
  for (let page = 1; ; page += 1) {
    const chunk = await request<T[]>(path, { query: { ...query, page, page_size: PAGE_SIZE } })
    all.push(...chunk)
    if (chunk.length < PAGE_SIZE) return all
  }
}

/* ------------------------------------------------------------------------- reads */
export const getTerms = (): Promise<Term[]> => via(mock.getTerms, async () => (await request<Raw[]>('/terms')).map(toTerm))
export const getDepartments = (): Promise<Department[]> => via(mock.getDepartments, async () => (await request<Raw[]>('/departments')).map((row) => fromServer<Department>(row)))
export const getCourses = (): Promise<Course[]> => via(mock.getCourses, async () => (await fetchAll('/courses')).map((row) => fromServer<Course>(row)))
export const getInstructors = (): Promise<Instructor[]> => via(mock.getInstructors, async () => (await fetchAll('/instructors')).map((row) => fromServer<Instructor>(row)))
export const getRooms = (): Promise<Room[]> => via(mock.getRooms, async () => (await fetchAll('/rooms')).map((row) => fromServer<Room>(row)))
export const getBatches = (): Promise<Batch[]> => via(mock.getBatches, async () => (await fetchAll('/batches')).map((row) => fromServer<Batch>(row)))
export const getCourseOfferings = (termId?: string): Promise<CourseOffering[]> => via(() => mock.getCourseOfferings().filter((row) => !termId || row.term_id === termId), async () => (await fetchAll('/offerings', { term_id: termId ? num(termId) : undefined })).map((row) => fromServer<CourseOffering>(row)))
export const getEnrollments = (): Promise<Enrollment[]> => via(mock.getEnrollments, async () => (await request<Raw[]>('/enrollments')).map((row) => fromServer<Enrollment>(row)))

const activeTermId = async (): Promise<string | null> => {
  const list = await getTerms()
  return (list.find((term) => term.status === 'Active') ?? list[0])?.term_id ?? null
}

export const getTimeSlots = (termId?: string): Promise<TimeSlot[]> => via(() => mock.getTimeSlots(termId ?? 'fall-2026'), async () => {
  const id = termId ?? (await activeTermId())
  return id ? (await request<Raw[]>(`/terms/${num(id)}/slots`)).map(toSlot) : []
})
export const getExamSlots = (termId: string): Promise<ExamSlot[]> => via(() => mock.getExamSlots(termId), async () => (await request<Raw[]>(`/terms/${num(termId)}/exam-slots`)).map(toExamSlot))

/** Publication state recorded by `publishScheduleMock` while the server has no publish route. */
const publishOverlay = new Map<string, ScheduleStatus>()
export const getSchedules = (): Promise<Schedule[]> => via(mock.getSchedules, async () => (await request<Raw[]>('/schedules')).map(toSchedule).map((item) => (publishOverlay.has(item.schedule_id) ? { ...item, status: publishOverlay.get(item.schedule_id)! } : item)))

const pickLatest = (list: Schedule[], type: ScheduleType, termId?: string): Schedule | null => {
  const items = list.filter((item) => item.schedule_type === type && (!termId || item.term_id === termId) && item.status !== 'Generating').sort((a, b) => b.version_no - a.version_no)
  return items.find((item) => item.status === 'Published') ?? items[0] ?? null
}

export const getConflicts = (scheduleId: string, filter: ConflictFilter = {}): Promise<ConflictItem[]> => via(() => mock.getConflicts(scheduleId, filter), async () => (await request<Raw[]>(`/schedules/${num(scheduleId)}/conflicts`, { query: { conflict_type: filter.conflict_type, severity: filter.severity } })).map((row) => fromServer<ConflictItem>(row)))

export const getDashboardSummary = (): Promise<DashboardSummary> => via(mock.getDashboardSummary, async () => {
  const [terms, schedules] = await Promise.all([getTerms(), getSchedules()])
  const activeTerm = terms.find((term) => term.status === 'Active') ?? null
  const [courses, instructors, rooms, batches, departments, offerings] = await Promise.all([
    fetchAll('/courses', { is_active: true }), fetchAll('/instructors', { is_active: true }), fetchAll('/rooms', { is_active: true }), fetchAll('/batches', { is_active: true }),
    request<Raw[]>('/departments'), activeTerm ? fetchAll('/offerings', { term_id: num(activeTerm.term_id) }) : Promise.resolve([]),
  ])
  const timetable = pickLatest(schedules, 'Timetable', activeTerm?.term_id)
  const examSchedule = pickLatest(schedules, 'Exam schedule', activeTerm?.term_id)
  const open = await Promise.all([timetable, examSchedule].map((item) => (item ? getConflicts(item.schedule_id).catch(() => []) : Promise.resolve([]))))
  const conflicts = open.flat()
  const activity: ActivityItem[] = [...schedules].sort((a, b) => (b.generated_at ?? '').localeCompare(a.generated_at ?? '')).slice(0, 3).map((item) => ({
    id: item.schedule_id, title: `${item.schedule_type} version ${item.version_no} ${item.status.toLowerCase()}`,
    detail: item.generated_at ? new Date(item.published_at ?? item.generated_at).toLocaleString('en-GB') : '', tone: item.status === 'Published' ? 'success' : item.status === 'Infeasible' ? 'warning' : 'neutral',
  }))
  return {
    activeTerm, timetable, examSchedule,
    counts: { courses: courses.length, instructors: instructors.length, rooms: rooms.length, batches: batches.length, offerings: offerings.length, departments: departments.length },
    conflicts: { hard: conflicts.filter((item) => item.severity === 'Hard').length, warning: conflicts.filter((item) => item.severity === 'Warning').length },
    activity,
  }
})

/* ---------------------------------------------------------------- schedule views */
async function resolveSchedule(scheduleId: string | undefined, type: ScheduleType): Promise<string | null> {
  if (scheduleId) return scheduleId
  const list = await getSchedules()
  return pickLatest(list, type)?.schedule_id ?? null
}

export const getTimetable = (scheduleId?: string, termId?: string): Promise<TimetableRow[]> => via(() => mock.getTimetable(scheduleId, termId), async () => {
  const id = await resolveSchedule(scheduleId, 'Timetable')
  if (!id) return []
  const view = await request<Raw>(`/schedules/${num(id)}/entries`)
  const [courses, rooms, instructors, batches, slots] = await Promise.all([getCourses(), getRooms(), getInstructors(), getBatches(), getTimeSlots(String(view.term_id))])
  const byId = <T,>(list: T[], key: keyof T) => new Map(list.map((item) => [String(item[key]), item]))
  const ctx = { courses: byId(courses, 'course_id'), rooms: byId(rooms, 'room_id'), instructors: byId(instructors, 'instructor_id'), batches: byId(batches, 'batch_id'), slots: byId(slots, 'slot_id') }
  const entries: TimetableEntry[] = (view.timetable_entries as Raw[]).map((row) => fromServer<TimetableEntry>({ entry_id: row.entry_id, schedule_id: row.schedule_id, offering_id: row.offering_id, instructor_id: row.instructor_id, batch_id: row.batch_id, room_id: row.room_id, slot_id: row.slot_id, session_type: row.session_type, is_locked: row.is_locked, is_manual_override: row.is_manual_override }))
  const courseOf = new Map((view.timetable_entries as Raw[]).map((row) => [String(row.entry_id), String(row.course_id)]))
  const groups = new Map<string, TimetableEntry[]>()
  entries.forEach((entry) => {
    const slot = ctx.slots.get(entry.slot_id)
    if (!slot) return
    const key = `${entry.offering_id}-${slot.day_of_week}-${entry.room_id}`
    groups.set(key, [...(groups.get(key) ?? []), entry])
  })
  const rows: TimetableRow[] = []
  groups.forEach((group) => {
    const sorted = [...group].sort((a, b) => ctx.slots.get(a.slot_id)!.slot_index - ctx.slots.get(b.slot_id)!.slot_index)
    const runs: TimetableEntry[][] = []
    sorted.forEach((entry, index) => {
      const previous = sorted[index - 1]
      const contiguous = Boolean(previous && ctx.slots.get(entry.slot_id)!.slot_index === ctx.slots.get(previous.slot_id)!.slot_index + 1 && previous.session_type === entry.session_type)
      if (!runs.length || !contiguous) runs.push([entry]); else runs[runs.length - 1].push(entry)
    })
    runs.forEach((run) => {
      const first = run[0]
      const course = ctx.courses.get(courseOf.get(first.entry_id)!)
      const room = ctx.rooms.get(first.room_id)
      const instructor = ctx.instructors.get(first.instructor_id)
      const batch = ctx.batches.get(first.batch_id)
      const startSlot = ctx.slots.get(first.slot_id)
      if (course && room && instructor && batch && startSlot) rows.push({ entry: first, entries: run, course, room, instructor, batch, startSlot, day: startSlot.day_of_week, durationSlots: run.length })
    })
  })
  return rows.sort((a, b) => a.startSlot.slot_index - b.startSlot.slot_index)
})

export const getExamSchedule = (scheduleId?: string): Promise<ExamScheduleRow[]> => via(() => mock.getExamSchedule(scheduleId), async () => {
  const id = await resolveSchedule(scheduleId, 'Exam schedule')
  if (!id) return []
  const view = await request<Raw>(`/schedules/${num(id)}/entries`)
  const [courses, rooms, batches, offerings] = await Promise.all([getCourses(), getRooms(), getBatches(), getCourseOfferings(String(view.term_id))])
  const courseMap = new Map(courses.map((item) => [item.course_id, item]))
  const roomMap = new Map(rooms.map((item) => [item.room_id, item]))
  const batchMap = new Map(batches.map((item) => [item.batch_id, item]))
  const none: Batch = { batch_id: '', program_code: 'Not linked', batch_year: 0, section: '', strength: 0, is_active: true }
  return (view.exam_entries as Raw[]).flatMap((row): ExamScheduleRow[] => {
    const course = courseMap.get(String(row.course_id))
    if (!course) return []
    const linked = [...new Set(offerings.filter((item) => item.course_id === course.course_id).map((item) => item.batch_id))].map((batchId) => batchMap.get(batchId)).filter((item): item is Batch => Boolean(item))
    return [{
      entry: { exam_entry_id: String(row.exam_entry_id), schedule_id: String(row.schedule_id), course_id: course.course_id, exam_slot_id: String(row.exam_slot_id), student_count: row.student_count, is_locked: row.is_locked },
      course,
      examSlot: { exam_slot_id: String(row.exam_slot_id), term_id: String(view.term_id), exam_date: row.exam_date, start_time: row.start_time, end_time: row.end_time, label: row.label ?? '' },
      rooms: (row.room_allocations as Raw[]).map((alloc) => ({ room: roomMap.get(String(alloc.room_id)) ?? { room_id: String(alloc.room_id), room_code: alloc.room_code, building: alloc.building, capacity: 0, room_type: 'Exam Hall' as const, is_active: true }, seats: alloc.seats_allocated })),
      batch: linked[0] ?? none, batches: linked,
    }]
  }).sort((a, b) => `${a.examSlot.exam_date}${a.examSlot.start_time}`.localeCompare(`${b.examSlot.exam_date}${b.examSlot.start_time}`))
})

/* ------------------------------------------------------------ manual move (re-validation) */
async function putEntry(scheduleId: string, entryId: string, body: Raw): Promise<MoveResult> {
  const res = await request<Raw>(`/schedules/${num(scheduleId)}/entries/${num(entryId)}`, { method: 'PUT', body, passthrough: [409] })
  if (res.__status === 409) return { ok: false, message: String(res.detail ?? 'The move violates a hard constraint.'), rule_code: res.rule_code ?? null, violated_constraints: res.violated_constraints ?? [] }
  return { ok: true }
}
export const moveTimetableEntry = (scheduleId: string, entryId: string, change: { slot_id?: string; room_id?: string }): Promise<MoveResult> => via(() => mock.moveTimetableEntry(scheduleId, entryId, change), () => putEntry(scheduleId, entryId, toServer(change)))
export const moveExamEntry = (scheduleId: string, examEntryId: string, change: { exam_slot_id?: string }): Promise<MoveResult> => via(() => mock.moveExamEntry(scheduleId, examEntryId, change), () => putEntry(scheduleId, examEntryId, toServer(change)))

/* ---------------------------------------------------------------------- generation */
interface RunMeta { startedAt: number; timeLimit: number; cancelled: boolean }
const runMeta = new Map<string, RunMeta>()

export const generateSchedule = (config: GenerationConfig): Promise<{ run_id: string }> => via(() => mock.generateSchedule(config), async () => {
  const res = await request<Raw>('/schedules/generate', { method: 'POST', body: toServer({ term_id: config.term_id, schedule_type: serverType(config.schedule_type), solver_time_limit_s: config.time_limit, config_id: config.config_id, random_seed: config.random_seed }) })
  const run_id = String(res.schedule_id)
  runMeta.set(run_id, { startedAt: Date.now(), timeLimit: config.time_limit, cancelled: false })
  return { run_id }
})

/** The server has no cancel route yet: this stops following the run in the UI; the solver still finishes on the server. */
export const cancelGeneration = (run_id: string): void => {
  if (USE_MOCK) { mock.cancelGeneration(run_id); return }
  const meta = runMeta.get(run_id)
  if (meta) meta.cancelled = true
}

export const getScheduleStatus = (run_id: string): Promise<GenerationStatus> => via(() => mock.getScheduleStatus(run_id), async () => {
  const row = await request<Raw>(`/schedules/${num(run_id)}/status`)
  const schedule = toSchedule(row)
  const meta = runMeta.get(run_id)
  const running = schedule.status === 'Generating'
  const startedAt = meta?.startedAt ?? Date.parse(row.generated_at)
  const elapsed_seconds = running || schedule.run_seconds === null ? Math.max(0, Math.round((Date.now() - startedAt) / 1000)) : Math.round(schedule.run_seconds)
  const unit = schedule.schedule_type === 'Timetable' ? 'sessions' : 'exams'
  const solver = row.solver_status ? ` Solver result: ${row.solver_status}.` : ''
  if (running && meta?.cancelled) {
    return { run_id, status: 'Draft', solver_status: 'Stopped', progress: Math.min(100, Math.round((elapsed_seconds / meta.timeLimit) * 100)), elapsed_seconds, message: 'Stopped following this run. The server has no cancel route, so the solver will finish in the background as a new version.', result: null }
  }
  if (running) {
    const limit = meta?.timeLimit ?? 120
    return { run_id, status: 'Generating', solver_status: 'Running', progress: Math.min(95, Math.round((elapsed_seconds / limit) * 100)), elapsed_seconds, message: 'The solver is running on the server.', result: null }
  }
  const message = schedule.status === 'Generated'
    ? `${schedule.schedule_type} version ${schedule.version_no} generated with ${schedule.entry_count ?? 0} ${unit} and ${schedule.conflict_count ?? 0} conflict record(s).${solver}`
    : schedule.status === 'Infeasible' ? `No feasible ${schedule.schedule_type.toLowerCase()} was found for version ${schedule.version_no}.${solver} Review the conflict report.`
      : `${schedule.schedule_type} version ${schedule.version_no} is ${schedule.status.toLowerCase()}.`
  return {
    run_id, status: schedule.status, solver_status: schedule.solver_status, progress: 100, elapsed_seconds, message,
    result: { schedule_id: schedule.schedule_id, hard_constraint_violations: schedule.hard_violation_count ?? 0, soft_score: schedule.objective_score ?? 0, version_no: schedule.version_no, entry_count: schedule.entry_count, conflict_count: schedule.conflict_count },
  }
})

export const getStatusLabel = (status: Schedule['status']): string => status

/* ------------------------------------------------------------------ master data CRUD */
type Entity = 'courses' | 'instructors' | 'rooms' | 'batches' | 'offerings' | 'terms' | 'enrollments'
const entityPath: Record<Entity, string> = { courses: '/courses', instructors: '/instructors', rooms: '/rooms', batches: '/batches', offerings: '/offerings', terms: '/terms', enrollments: '/enrollments' }

async function saveServer<T>(entity: Entity, id: string | null, payload: Raw): Promise<T> {
  const path = id === null ? entityPath[entity] : `${entityPath[entity]}/${num(id)}`
  if (entity === 'terms') {
    const { label, ...rest } = payload
    return toTerm(await request<Raw>(path, { method: id === null ? 'POST' : 'PUT', body: { ...toServer(rest), ...(label === undefined ? {} : { name: label }) } })) as T
  }
  return fromServer<T>(await request<Raw>(path, { method: id === null ? 'POST' : 'PUT', body: toServer(payload) }))
}
const save = <T,>(entity: Entity, id: string | null, payload: Raw) => via(() => mock.saveRecord<T>(entity, id, payload), () => saveServer<T>(entity, id, payload))
/** Courses, instructors, rooms and batches are deactivated by the server (soft). Offerings and enrollments have only a hard delete route. Terms are closed. */
const remove = (entity: Entity, id: string) => via<void>(() => mock.deactivateRecord(entity, id), async () => {
  if (entity === 'terms') { await request(`/terms/${num(id)}`, { method: 'PUT', body: { status: 'Closed' } }); return }
  await request(`${entityPath[entity]}/${num(id)}`, { method: 'DELETE' })
})
/** Reactivation goes through the normal update route with is_active = true. */
export const reactivateRecord = (entity: 'courses' | 'instructors' | 'rooms' | 'batches', id: string): Promise<void> => save(entity, id, { is_active: true }).then(() => undefined)

export const createCourse = (payload: Omit<Course, 'course_id'>) => save<Course>('courses', null, payload)
export const updateCourse = (id: string, payload: Partial<Omit<Course, 'course_id'>>) => save<Course>('courses', id, payload)
export const deactivateCourse = (id: string) => remove('courses', id)
export const createInstructor = (payload: Omit<Instructor, 'instructor_id'>) => save<Instructor>('instructors', null, payload)
export const updateInstructor = (id: string, payload: Partial<Omit<Instructor, 'instructor_id'>>) => save<Instructor>('instructors', id, payload)
export const deactivateInstructor = (id: string) => remove('instructors', id)
export const createRoom = (payload: Omit<Room, 'room_id'>) => save<Room>('rooms', null, payload)
export const updateRoom = (id: string, payload: Partial<Omit<Room, 'room_id'>>) => save<Room>('rooms', id, payload)
export const deactivateRoom = (id: string) => remove('rooms', id)
export const createBatch = (payload: Omit<Batch, 'batch_id'>) => save<Batch>('batches', null, payload)
export const updateBatch = (id: string, payload: Partial<Omit<Batch, 'batch_id'>>) => save<Batch>('batches', id, payload)
export const deactivateBatch = (id: string) => remove('batches', id)
export const createOffering = (payload: Omit<CourseOffering, 'offering_id'>) => save<CourseOffering>('offerings', null, payload)
export const updateOffering = (id: string, payload: Partial<Omit<CourseOffering, 'offering_id'>>) => save<CourseOffering>('offerings', id, payload)
export const removeOffering = (id: string) => remove('offerings', id)
export const createEnrollment = (payload: Omit<Enrollment, 'enrollment_id'>) => save<Enrollment>('enrollments', null, payload)
export const removeEnrollment = (id: string) => remove('enrollments', id)

/* --------------------------------------------------------------- terms and slot grid */
export const createTerm = (payload: Omit<Term, 'term_id'>) => save<Term>('terms', null, payload)
export const updateTerm = (id: string, payload: Partial<Omit<Term, 'term_id'>>) => save<Term>('terms', id, payload)
/** Marks one term Active. The server allows only one Active term, so the current one is closed first. */
export const activateTerm = (id: string): Promise<void> => via<void>(() => { mock.getTerms().filter((term) => term.status === 'Active' && term.term_id !== id).forEach((term) => mock.saveRecord('terms', term.term_id, { status: 'Closed' })); mock.saveRecord('terms', id, { status: 'Active' }) }, async () => {
  const current = (await getTerms()).filter((term) => term.status === 'Active' && term.term_id !== id)
  for (const term of current) await request(`/terms/${num(term.term_id)}`, { method: 'PUT', body: { status: 'Closed' } })
  await request(`/terms/${num(id)}`, { method: 'PUT', body: { status: 'Active' } })
})
export const closeTerm = (id: string) => remove('terms', id)
export const generateSlotGrid = (termId: string, input: SlotGridInput): Promise<TimeSlot[]> => via(() => mock.generateSlotGrid(termId, input), async () => (await request<Raw[]>(`/terms/${num(termId)}/slots/generate`, { method: 'POST', body: input })).map(toSlot))
export const updateSlot = (termId: string, slotId: string, change: { is_blocked: boolean; block_reason: string | null }): Promise<TimeSlot> => via(() => mock.updateSlot(termId, slotId, change), async () => toSlot(await request<Raw>(`/terms/${num(termId)}/slots/${num(slotId)}`, { method: 'PUT', body: change })))
export const createExamSlot = (termId: string, input: ExamSlotInput): Promise<ExamSlot> => via(() => mock.createExamSlot(termId, input), async () => toExamSlot(await request<Raw>(`/terms/${num(termId)}/exam-slots`, { method: 'POST', body: input })))

/* --------------------------------------------------------------------- availability */
export const getAvailability = (instructorId: string): Promise<AvailabilityItem[]> => via(() => mock.getAvailability(instructorId), async () => (await request<Raw[]>(`/instructors/${num(instructorId)}/availability`)).map((row) => ({ slot_id: String(row.slot_id), is_available: Boolean(row.is_available) })))
export const saveAvailability = (instructorId: string, items: AvailabilityItem[]): Promise<AvailabilityItem[]> => via(() => mock.saveAvailability(instructorId, items), async () => (await request<Raw[]>(`/instructors/${num(instructorId)}/availability`, { method: 'PUT', body: { slots: items.map((item) => ({ slot_id: num(item.slot_id), is_available: item.is_available })) } })).map((row) => ({ slot_id: String(row.slot_id), is_available: Boolean(row.is_available) })))

/* ------------------------------------------------------------ configurations and rules */
const hiddenConfigs = new Set<string>()
export const getConfigs = (termId?: string, scheduleType?: ScheduleType): Promise<SchedulingConfig[]> => via(() => mock.getConfigs(termId, scheduleType), async () => (await request<Raw[]>('/configs', { query: { term_id: termId ? num(termId) : undefined, schedule_type: scheduleType ? serverType(scheduleType) : undefined } })).map(toConfig).filter((item) => !hiddenConfigs.has(item.config_id)))
export const createConfig = (input: ConfigInput): Promise<SchedulingConfig> => via(() => mock.createConfig(input), async () => toConfig(await request<Raw>('/configs', { method: 'POST', body: { term_id: num(input.term_id), schedule_type: serverType(input.schedule_type), name: input.name, solver_time_limit_s: input.solver_time_limit_s, random_seed: input.random_seed, rules: input.rules } })))
/** Clone = create a configuration with the source rules (uses the existing POST /configs). */
export const cloneConfig = (source: SchedulingConfig, name: string): Promise<SchedulingConfig> => createConfig({ term_id: source.term_id, schedule_type: source.schedule_type, name, solver_time_limit_s: source.solver_time_limit_s, random_seed: source.random_seed, rules: source.rules })
export const updateConfig = (configId: string, change: Partial<Pick<SchedulingConfig, 'name' | 'solver_time_limit_s' | 'random_seed'>>): Promise<SchedulingConfig> => via(() => mock.updateConfig(configId, change), async () => toConfig(await request<Raw>(`/configs/${num(configId)}`, { method: 'PUT', body: change })))
export const saveConfigRules = (configId: string, rules: ConstraintRule[]): Promise<ConstraintRule[]> => via(() => mock.saveConfigRules(configId, rules), async () => (await request<Raw[]>(`/configs/${num(configId)}/rules`, { method: 'PUT', body: { rules } })).map(toRule))

/* ------------------------------------------------------- functions without a backend route */
/** No DELETE /configs/{id} on the server. The configuration is only hidden in this browser session. */
export const deleteConfigMock = (configId: string): Promise<void> => via<void>(() => mock.deleteConfig(configId), async () => {
  if ((await getSchedules()).some((item) => item.config_id === configId)) throw new Error('This configuration was used to generate a schedule and cannot be deleted.')
  hiddenConfigs.add(configId)
})

/** No POST /schedules/{id}/publish on the server. Publication is recorded in this browser session only. */
export const publishScheduleMock = (scheduleId: string): Promise<Schedule> => via(() => mock.publishSchedule(scheduleId), async () => {
  const list = await getSchedules()
  const target = list.find((item) => item.schedule_id === scheduleId)
  if (!target) throw new Error('Schedule not found.')
  if (target.status !== 'Generated') throw new Error('Only a Generated version can be published.')
  if ((target.hard_violation_count ?? 0) > 0) throw new Error('A version with hard violations cannot be published.')
  list.filter((item) => item.schedule_type === target.schedule_type && item.term_id === target.term_id && item.status === 'Published').forEach((item) => publishOverlay.set(item.schedule_id, 'Archived'))
  publishOverlay.set(scheduleId, 'Published')
  return { ...target, status: 'Published', published_at: new Date().toISOString() }
})

/** Template download is generated in the browser (no GET /import/{type}/template route). */
export const getImportTemplate = (type: ImportType): Promise<string> => Promise.resolve(importTemplateCsv(type))
/** No POST /import/{type} on the server. The file is validated locally against the schema rules. */
export const validateImportMock = async (type: ImportType, file: File): Promise<ImportReport> => {
  if (file.size > MAX_IMPORT_BYTES) throw new Error('The file is larger than the 10 MB limit.')
  if (!/\.csv$/i.test(file.name)) throw new Error('Only .csv files can be imported.')
  return mock.validateImport(type, file.name, await file.text())
}
export const confirmImportMock = (importId: string, mode: 'valid_only' | 'cancel'): Promise<ImportResult> => Promise.resolve().then(() => mock.confirmImport(importId, mode))

export const loginMock = (username: string, password: string): Promise<LoginResult> => Promise.resolve(mock.login(username, password))
export const getUsersMock = (): Promise<AppUser[]> => Promise.resolve(mock.getUsers())
export const saveUserMock = (id: string | null, input: AppUserInput): Promise<AppUser> => Promise.resolve().then(() => mock.saveUser(id, input))
export const getAuditLogMock = (filter: AuditFilter = {}): Promise<AuditEntry[]> => Promise.resolve(mock.getAuditLog(filter))
