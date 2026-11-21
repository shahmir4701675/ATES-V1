import { ArrowLeft, Construction, ShieldCheck } from 'lucide-react'
import { Button, Card, PageHeader } from '../components/ui'

const copy: Record<string, { title: string; description: string; note: string }> = {
  '/approvals': { title: 'Approval queue', description: 'Review generated schedules before they are published to the department.', note: 'Approval workflow is reserved for the next implementation phase.' },
  '/teaching': { title: 'My teaching', description: 'Review assigned teaching sessions, rooms, and exception notes.', note: 'Faculty-specific schedule views will be connected to the same service boundary.' },
  '/my-schedule': { title: 'My schedule', description: 'A student-facing view of teaching sessions and exams for the current batch.', note: 'Student filtering will be added after the department schedule is approved.' },
  '/data': { title: 'Data management', description: 'Maintain course offerings, rooms, instructors, and batch records.', note: 'The current release is read-only and uses mock records.' },
  '/settings': { title: 'System settings', description: 'Review workspace preferences and department scheduling defaults.', note: 'Settings are represented as a placeholder until the backend integration is added.' },
}

export function PlaceholderPage({ path, onNavigate }: { path: string; onNavigate: (path: string) => void }) {
  const item = copy[path] ?? { title: 'Module placeholder', description: 'This ATES module is not part of the current frontend scope.', note: 'The navigation is ready for a future implementation.' }
  return <div className="page-stack"><PageHeader eyebrow="Module" title={item.title} description={item.description} /><Card className="placeholder-card"><div className="placeholder-icon"><Construction size={24} /></div><h2>{item.note}</h2><p>This screen intentionally preserves the administrative shell, role-aware navigation, and service-layer boundaries while the full module is scheduled for a later release.</p><div className="placeholder-actions"><Button variant="secondary" icon={ArrowLeft} onClick={() => onNavigate('/')}>Back to dashboard</Button><Button icon={ShieldCheck} onClick={() => onNavigate('/timetable')}>Open timetable view</Button></div></Card></div>
}
