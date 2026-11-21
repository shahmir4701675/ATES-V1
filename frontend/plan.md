# ATES implementation plan

## Product scope

ATES is a frontend-only university department administration tool for timetable and exam scheduling. The delivered application uses mock data, has no real login, and is structured so the mock data can later be replaced by FastAPI REST calls without changing the UI.

## Implementation approach

- Use React 18 + TypeScript + Vite for the application shell.
- Use Tailwind CSS with a small amount of project CSS for the timetable grid, print layout, focus states, and visual tokens.
- Keep every mock record in `src/data/mockData.ts`; expose data and simulated operations only through `src/services/api.ts`.
- Keep route state in the browser URL with a lightweight client-side route map so the static deployment works on direct entry to the declared routes.
- Use Lucide React for all interface icons.
- Use `public/manus-routes.json` as the managed route manifest.
- Build as a static Vite site with output in `dist` and publish using the managed static build contract.

## Design direction

Three possible directions were considered: **Registrar Console** (0.07), a highly dense records-first interface; **Civic Operations Desk** (0.06), a restrained public-sector information system; and **Academic Control Room** (0.08), an operational dashboard for schedule governance. The chosen direction is **Registrar Console**, because it best matches the requested formal institutional software context.

### Design movement

Registrar-console administrative UI: quiet, structured, and records-first rather than promotional.

### Core principles

1. Make schedule state and next actions visible before supporting detail.
2. Use clear borders, aligned columns, and predictable control placement.
3. Treat warnings, locks, overrides, and validation as explicit information, never color-only signals.
4. Preserve whitespace and readable density at both desktop and 360 px mobile widths.

### Color philosophy

Deep navy communicates authority and continuity for the department's primary actions and navigation. Pale slate surfaces keep dense operational data calm and readable. One controlled blue accent differentiates schedule content without turning the product into a marketing site. Green, amber, and red appear only for semantic state.

### Layout paradigm

A fixed administrative frame with a persistent top command bar, a centered working canvas, and view-specific data surfaces. The timetable intentionally breaks out into a horizontally scrollable operational grid on narrow screens instead of collapsing away important schedule information.

### Signature elements

- A thin navy command rail with the ATES wordmark and context subtitle.
- Outlined status pills with Lucide icons for every schedule state.
- A bordered schedule matrix with a dedicated grey time axis and restrained session fills.

### Interaction philosophy

Controls are visible and labeled, actions are reversible where possible, and system feedback is written into the fixed status bar. Long-running generation is represented by a simple progress bar with cancel available throughout.

### Animation

No decorative motion. Progress changes only while a generation run is active; dialogs use a short opacity transition and otherwise remain still.

### Typography system

Use Inter when available and fall back to the system sans-serif stack. Body text is 14 px with 1.45 line height. Headings use semibold weight, and schedule times/counts use tabular numerals for alignment.

### Brand essence

ATES is the department's shared operational record for building publishable teaching and exam schedules. Personality: dependable, exact, accountable.

### Brand voice

Headings state the record or decision in sentence case. CTAs are direct and specific, such as “Generate schedule” and “View timetable”. Supporting copy explains what the control changes rather than selling the product.

### Wordmark and logo

The wordmark is a compact ATES lockup with a small timetable-block mark and the product subtitle. It is deliberately typographic and works in the navy command rail without decorative illustration.

### Signature brand color

`#1F3A5F` deep navy is the ownable ATES color used for the command rail, primary buttons, focus ring, and key data accents.

## Project structure

```text
src/
  app/App.tsx              route state and page composition
  components/              shell, controls, status badges, tables, timetable
  data/mockData.ts         single source of mock records
  services/api.ts          single service boundary for mock operations
  types/index.ts           domain types
  styles.css               Tailwind entry and project-specific layout/print rules
public/manus-routes.json   static page route manifest
app.config.ts              project branding metadata
```

## Serving and publication

The Vite dev server listens on the configured Preview port 3000 and binds to `0.0.0.0`. The production configuration declares `pnpm install --frozen-lockfile && pnpm build` with `dist` as the static output directory. No server or database is required.
