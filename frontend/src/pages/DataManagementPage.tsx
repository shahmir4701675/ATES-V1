import { useState } from 'react'
import { FileUp } from 'lucide-react'
import { Button, Card, Notice, PageHeader } from '../components/ui'
import type { Role } from '../components/AppShell'
import { BatchesTab, CoursesTab, EnrollmentsTab, InstructorsTab, OfferingsTab, RoomsTab } from './data/MasterTabs'
import { TermsSlotsTab } from './data/TermsSlotsTab'

const TABS = [
  { key: 'courses', label: 'Courses' },
  { key: 'instructors', label: 'Instructors' },
  { key: 'rooms', label: 'Rooms' },
  { key: 'batches', label: 'Batches' },
  { key: 'terms', label: 'Terms and slots' },
  { key: 'offerings', label: 'Offerings' },
  { key: 'enrollments', label: 'Enrollments' },
] as const

type TabKey = (typeof TABS)[number]['key']

export function DataManagementPage({ role, onNavigate, onStatus }: { role: Role; onNavigate: (path: string) => void; onStatus: (message: string) => void }) {
  const [tab, setTab] = useState<TabKey>('courses')
  const readOnly = role === 'Approver'

  return <div className="page-stack">
    <PageHeader
      eyebrow="Master data"
      title="Data management"
      description={readOnly ? 'Read-only view of departmental courses, instructors, rooms, batches, terms, offerings and enrollments.' : 'Maintain courses, instructors, rooms, batches, academic terms, time slots, offerings and enrollments.'}
      actions={!readOnly && <Button variant="secondary" icon={FileUp} onClick={() => onNavigate('/import')}>Import CSV</Button>}
    />
    {readOnly && <Notice title="Read-only access">Approvers can inspect all master data records. Only Coordinators and Administrators can add, edit or deactivate records.</Notice>}
    <div className="tabs" role="tablist" aria-label="Master data sections">
      {TABS.map((item) => (
        <button
          key={item.key}
          type="button"
          role="tab"
          id={`tab-${item.key}`}
          aria-selected={tab === item.key}
          aria-controls={`panel-${item.key}`}
          className="tab"
          onClick={() => setTab(item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
    <div id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>
      {tab === 'terms' ? (
        <TermsSlotsTab readOnly={readOnly} onStatus={onStatus} />
      ) : (
        <Card title={TABS.find((item) => item.key === tab)?.label}>
          {tab === 'courses' && <CoursesTab readOnly={readOnly} onStatus={onStatus} />}
          {tab === 'instructors' && <InstructorsTab readOnly={readOnly} onStatus={onStatus} />}
          {tab === 'rooms' && <RoomsTab readOnly={readOnly} onStatus={onStatus} />}
          {tab === 'batches' && <BatchesTab readOnly={readOnly} onStatus={onStatus} />}
          {tab === 'offerings' && <OfferingsTab readOnly={readOnly} onStatus={onStatus} />}
          {tab === 'enrollments' && <EnrollmentsTab readOnly={readOnly} onStatus={onStatus} />}
        </Card>
      )}
    </div>
  </div>
}
