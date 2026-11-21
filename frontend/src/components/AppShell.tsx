import { useState } from 'react'
import { AlertTriangle, Bell, BookOpen, CalendarDays, CalendarRange, ChevronDown, Clock, FileClock, FileUp, LayoutDashboard, LogIn, Menu, Settings2, ShieldCheck, Table2, UsersRound, X } from 'lucide-react'

export type Role = 'Administrator' | 'Coordinator' | 'Approver' | 'Faculty' | 'Student'

export const roleMenus: Record<Role, Array<{ label: string; path: string; icon: typeof LayoutDashboard }>> = {
  Administrator: [
    { label: 'Dashboard', path: '/', icon: LayoutDashboard },
    { label: 'Data management', path: '/data', icon: Table2 },
    { label: 'Import CSV', path: '/import', icon: FileUp },
    { label: 'Availability', path: '/availability', icon: Clock },
    { label: 'Constraints', path: '/settings', icon: Settings2 },
    { label: 'Generate', path: '/generate', icon: FileClock },
    { label: 'Timetable', path: '/timetable', icon: CalendarRange },
    { label: 'Exams', path: '/exams', icon: CalendarDays },
    { label: 'Conflicts', path: '/conflicts', icon: AlertTriangle },
    { label: 'Users & audit', path: '/users', icon: UsersRound },
  ],
  Coordinator: [
    { label: 'Dashboard', path: '/', icon: LayoutDashboard },
    { label: 'Data management', path: '/data', icon: Table2 },
    { label: 'Import CSV', path: '/import', icon: FileUp },
    { label: 'Availability', path: '/availability', icon: Clock },
    { label: 'Constraints', path: '/settings', icon: Settings2 },
    { label: 'Generate', path: '/generate', icon: FileClock },
    { label: 'Timetable', path: '/timetable', icon: CalendarRange },
    { label: 'Exams', path: '/exams', icon: CalendarDays },
    { label: 'Conflicts', path: '/conflicts', icon: AlertTriangle },
  ],
  Approver: [
    { label: 'Dashboard', path: '/', icon: LayoutDashboard },
    { label: 'Review & publish', path: '/approvals', icon: ShieldCheck },
    { label: 'Timetable', path: '/timetable', icon: CalendarRange },
    { label: 'Exams', path: '/exams', icon: CalendarDays },
    { label: 'Conflicts', path: '/conflicts', icon: AlertTriangle },
    { label: 'Data management', path: '/data', icon: Table2 },
  ],
  Faculty: [
    { label: 'Dashboard', path: '/', icon: LayoutDashboard },
    { label: 'Availability', path: '/availability', icon: BookOpen },
    { label: 'Timetable', path: '/timetable', icon: CalendarRange },
    { label: 'Exams', path: '/exams', icon: CalendarDays },
  ],
  Student: [
    { label: 'Dashboard', path: '/', icon: LayoutDashboard },
    { label: 'My schedule', path: '/timetable', icon: CalendarRange },
    { label: 'Exams', path: '/exams', icon: CalendarDays },
  ],
}

export const getAllowedPaths = (role: Role): string[] => [...roleMenus[role].map((item) => item.path), '/login']

export function AppShell({ children, path, role, userName = 'Alex Roy', onRoleChange, onNavigate, statusMessage }: { children: React.ReactNode; path: string; role: Role; userName?: string; onRoleChange: (role: Role) => void; onNavigate: (path: string) => void; statusMessage: string }) {
  const [mobileOpen, setMobileOpen] = useState(false)
  const menu = roleMenus[role]
  const go = (nextPath: string) => { setMobileOpen(false); onNavigate(nextPath) }
  const initials = userName.split(' ').map((part) => part[0]).join('').slice(0, 2).toUpperCase() || 'AR'
  return <div className="app-shell">
    <header className="topbar no-print">
      <div className="topbar-inner">
        <button className="mobile-menu-button" type="button" onClick={() => setMobileOpen((open) => !open)} aria-label={mobileOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={mobileOpen}>{mobileOpen ? <X size={20} /> : <Menu size={20} />}</button>
        <button className="brand" onClick={() => go('/')} type="button" aria-label="ATES dashboard">
          <span className="ates-mark">A</span>
          <span className="brand-copy"><strong>ATES</strong><small>Auto Timetable / Exam Scheduler</small></span>
        </button>
        <nav className={`main-nav ${mobileOpen ? 'main-nav-open' : ''}`} aria-label="Primary navigation">
          {menu.map(({ label, path: itemPath, icon: Icon }) => <button key={itemPath} className={`nav-link ${path === itemPath ? 'nav-link-active' : ''}`} type="button" onClick={() => go(itemPath)} aria-current={path === itemPath ? 'page' : undefined}><Icon size={16} aria-hidden="true" /><span>{label}</span></button>)}
        </nav>
        <div className="topbar-actions">
          <label className="role-switcher"><span className="sr-only">Current role</span><select value={role} onChange={(event) => onRoleChange(event.target.value as Role)} aria-label="Current role">{(Object.keys(roleMenus) as Role[]).map((item) => <option key={item}>{item}</option>)}</select><ChevronDown size={14} aria-hidden="true" /></label>
          <button className="icon-button" type="button" aria-label="Notifications"><Bell size={17} /><span className="notification-dot" /></button>
          <details className="user-menu"><summary><span className="avatar">{initials}</span><span className="user-copy"><strong>{userName}</strong><small>{role}</small></span><ChevronDown size={14} aria-hidden="true" /></summary><div className="user-popover">
            {role === 'Administrator' && <button type="button" onClick={() => go('/users')}><UsersRound size={15} />Users & audit log</button>}
            {(role === 'Coordinator' || role === 'Administrator') && <button type="button" onClick={() => go('/settings')}><Settings2 size={15} />Constraints & settings</button>}
            <button type="button" onClick={() => go('/login')}><LogIn size={15} />Sign in / switch user</button>
          </div></details>
        </div>
      </div>
    </header>
    <main className="main-content">{children}</main>
    <footer className="status-bar" role="status" aria-live="polite"><div className="status-bar-inner"><span className="status-pulse" aria-hidden="true" /><span>{statusMessage}</span><span className="status-meta">Last sync: {new Date().toLocaleDateString('en-GB')}</span></div></footer>
  </div>
}
