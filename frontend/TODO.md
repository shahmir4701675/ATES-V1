# ATES delivery outcomes

## 1. Administrative shell and responsive navigation

- Fixed top navigation shows the ATES product name and the subtitle “Auto Timetable / Exam Scheduler”.
- Navigation includes menu items, a role switcher with Administrator, Coordinator, Approver, Faculty, and Student, and a user menu on the right.
- Changing role changes which menu items are shown.
- Below navigation, every page has a breadcrumb, page title, centered content area with a maximum width near 1280 px, and a slim fixed system status bar at the bottom.
- Interface is responsive from 360 px wide, uses visible keyboard focus outlines, and maintains WCAG AA contrast.

## 2. Dashboard

- Dashboard shows active term Fall 2026, timetable status, exam schedule status, and counts of courses, instructors, rooms, batches, and offerings.
- Status badges include text and an icon and support Draft, Generating, Infeasible, Generated, Published, and Archived states.
- Dashboard includes clear quick actions to generate a schedule and open the timetable or exam schedule views.

## 3. Schedule generation workflow

- Generate page allows choosing term, schedule type (Timetable or Exam schedule), configuration options, and a time limit defaulting to 120 seconds.
- Generate and Cancel buttons are available with the primary action on the right.
- Mock generation displays a progress bar and polls progress every two seconds until completion or cancellation.
- Result summary shows status, solver status, run time, hard-constraint violations, soft score, and links to schedule views.
- Form labels are visible above fields, helper copy is present, and validation errors can be shown beside fields and in a summary at the top.

## 4. Timetable view

- Weekly timetable shows Monday through Friday and hourly slots from 08:00 in a bordered grid with grey time/day headers.
- Filters include batch, instructor, room, course, and day; a version selector is present.
- Lecture cells use pale blue, lab blocks use pale teal, and blocked lunch slots use a hatched light grey Break cell.
- Lab sessions span two hourly slots where applicable.
- Each session shows course code, room, and instructor; locked and manually overridden entries have consistent Lucide icons and labels/tooltips.
- Legend appears above the grid and mock Export PDF and Export CSV actions are available.
- Timetable print output keeps the filters as a print header and hides application chrome and interactive-only controls.

## 5. Exam schedule view

- Exam list is ordered by date and time and includes course, session, rooms, and seat counts.
- Filters include date, batch, course, and room.
- Mock Export PDF and Export CSV actions are available.
- Dates display as DD/MM/YYYY and times use 24-hour formatting.

## 6. Mock-data service boundary

- All mock records use the requested field names for courses, instructors, rooms, batches, time slots, course offerings, timetable entries, exam slots, exam entries, exam room allocations, and schedules.
- Components access records and simulated generation/status/export behavior only through `src/services/api.ts` and never import mock data directly.

## 7. Static build and deployment

- `public/manus-routes.json` declares all application routes.
- TypeScript diagnostics are registered for the project.
- Production build outputs a valid static site in `dist` and is configured for managed publication.
