export type ScheduleType = 'Timetable' | 'Exam schedule'
export type ScheduleStatus = 'Draft' | 'Generating' | 'Infeasible' | 'Generated' | 'Published' | 'Archived'
export type SolverStatus = 'Not started' | 'Running' | 'Optimal' | 'Feasible' | 'Stopped'
export type SessionType = 'Lecture' | 'Lab'
export type RoomType = 'Lecture' | 'Lab' | 'Exam Hall'
export type TermStatus = 'Planned' | 'Active' | 'Closed'
export type UserRole = 'Administrator' | 'Coordinator' | 'Approver' | 'Faculty' | 'Student'

export interface Department {
  department_id: string
  code: string
  name: string
}

export interface Term {
  term_id: string
  label: string
  start_date: string
  end_date: string
  status: TermStatus
}

export interface Course {
  course_id: string
  course_code: string
  title: string
  department_id: string
  credit_hours: number
  lecture_hours: number
  lab_hours: number
  is_active: boolean
}

export interface Instructor {
  instructor_id: string
  full_name: string
  email: string
  department_id: string
  max_daily_hours: number
  max_weekly_hours: number
  is_active: boolean
}

export interface Room {
  room_id: string
  room_code: string
  building: string
  capacity: number
  room_type: RoomType
  is_active: boolean
}

export interface Batch {
  batch_id: string
  program_code: string
  batch_year: number
  section: string
  strength: number
  is_active: boolean
}

export interface TimeSlot {
  slot_id: string
  term_id: string
  day_of_week: string
  slot_index: number
  start_time: string
  end_time: string
  is_blocked: boolean
  block_reason: string | null
}

export interface CourseOffering {
  offering_id: string
  term_id: string
  course_id: string
  batch_id: string
  instructor_id: string
  enrolled_count: number
}

export interface Enrollment {
  enrollment_id: string
  offering_id: string
  student_id: string
}

export interface TimetableEntry {
  entry_id: string
  schedule_id: string
  offering_id: string
  instructor_id: string
  batch_id: string
  room_id: string
  slot_id: string
  session_type: SessionType
  is_locked: boolean
  is_manual_override: boolean
}

export interface ExamSlot {
  exam_slot_id: string
  term_id: string
  exam_date: string
  start_time: string
  end_time: string
  label: string
}

export interface ExamEntry {
  exam_entry_id: string
  schedule_id: string
  course_id: string
  exam_slot_id: string
  student_count: number
  is_locked: boolean
}

export interface ExamRoomAllocation {
  allocation_id: string
  exam_entry_id: string
  room_id: string
  seats_allocated: number
}

export interface Schedule {
  schedule_id: string
  term_id: string
  schedule_type: ScheduleType
  version_no: number
  status: ScheduleStatus
  solver_status: SolverStatus
  objective_score: number | null
  run_seconds: number | null
  config_id?: string
  entry_count?: number
  conflict_count?: number
  hard_violation_count?: number
  generated_at?: string
  published_at?: string | null
}

export interface ActivityItem {
  id: string
  title: string
  detail: string
  tone: 'success' | 'neutral' | 'warning'
}

export interface DashboardSummary {
  activeTerm: Term | null
  timetable: Schedule | null
  examSchedule: Schedule | null
  counts: {
    courses: number
    instructors: number
    rooms: number
    batches: number
    offerings: number
    departments: number
  }
  /** Open conflicts of the latest timetable and exam schedule, by severity. */
  conflicts: { hard: number; warning: number }
  activity: ActivityItem[]
}

export interface TimetableRow {
  entry: TimetableEntry
  /** Every entry that makes up this block (a lab block spans consecutive slots). */
  entries: TimetableEntry[]
  course: Course
  room: Room
  instructor: Instructor
  batch: Batch
  startSlot: TimeSlot
  day: string
  durationSlots: number
}

export interface ExamScheduleRow {
  entry: ExamEntry
  course: Course
  examSlot: ExamSlot
  rooms: Array<{ room: Room; seats: number }>
  /** First batch taking the course; see `batches` for all of them. */
  batch: Batch
  batches: Batch[]
}

export interface GenerationConfig {
  term_id: string
  schedule_type: ScheduleType
  time_limit: number
  config_id?: string
  random_seed?: number
}

export interface GenerationStatus {
  run_id: string
  status: ScheduleStatus
  solver_status: SolverStatus
  /** Estimated: share of the time limit used while running (the server reports no progress). */
  progress: number
  elapsed_seconds: number
  message: string
  result: {
    schedule_id: string
    hard_constraint_violations: number
    soft_score: number
    version_no?: number
    entry_count?: number
    conflict_count?: number
  } | null
}

export interface ConflictItem {
  conflict_id: string
  schedule_id: string
  conflict_type: string
  severity: 'Hard' | 'Warning'
  description: string
  entity_ref: string | null
  detected_at: string
  is_resolved: boolean
}

export interface ConflictFilter {
  conflict_type?: string
  severity?: string
}

/** Result of a manual move. A 409 is a normal outcome (hard constraint violated), not an exception. */
export type MoveResult =
  | { ok: true }
  | { ok: false; message: string; rule_code: string | null; violated_constraints: string[] }

export interface ConstraintRule {
  rule_code: string
  rule_type: 'Hard' | 'Soft'
  is_enabled: boolean
  weight: number
  param_value: number | null
}

export interface SchedulingConfig {
  config_id: string
  term_id: string
  schedule_type: ScheduleType
  name: string
  solver_time_limit_s: number
  random_seed: number
  rules: ConstraintRule[]
}

export interface ConfigInput {
  term_id: string
  schedule_type: ScheduleType
  name: string
  solver_time_limit_s: number
  random_seed: number
  rules?: ConstraintRule[]
}

export interface SlotGridInput {
  working_days: number[]
  first_start_time: string
  slot_length_min: number
  slots_per_day: number
}

export interface ExamSlotInput {
  exam_date: string
  start_time: string
  end_time: string
  label: string
}

export interface AvailabilityItem {
  slot_id: string
  is_available: boolean
}

export type ImportType = 'courses' | 'instructors' | 'rooms' | 'batches' | 'offerings' | 'enrollments'

export interface ImportRejectedRow {
  line: number
  column: string
  reason: string
}

export interface ImportReport {
  import_id: string
  type: ImportType
  file_name: string
  rows_total: number
  rows_valid: number
  rejected: ImportRejectedRow[]
}

export interface ImportResult {
  rows_imported: number
  rows_rejected: number
}

export interface AppUser {
  user_id: string
  username: string
  full_name: string
  email: string
  role: UserRole
  account_status: 'Active' | 'Locked' | 'Deactivated'
  instructor_id: string | null
  batch_id: string | null
}

export interface AppUserInput {
  username: string
  full_name: string
  email: string
  role: UserRole
  account_status: AppUser['account_status']
  instructor_id: string | null
  batch_id: string | null
  password?: string
}

export interface AuditEntry {
  log_id: string
  user_id: string | null
  username: string
  action: string
  entity_type: string | null
  entity_id: string | null
  details: string
  created_at: string
}

export interface AuditFilter {
  user_id?: string
  from?: string
  to?: string
  action?: string
}

export interface LoginResult {
  ok: boolean
  user?: AppUser
  message?: string
  locked_minutes?: number
}

export interface Student {
  student_id: string
  full_name: string
  batch_id: string | null
}
