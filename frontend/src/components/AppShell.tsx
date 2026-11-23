import { formatToday, t } from '../locales'
import { useState } from 'react'
import { AlertTriangle, BookOpen, CalendarDays, CalendarRange, ChevronDown, Clock, FileClock, FileUp, LayoutDashboard, LogIn, Menu, Settings2, ShieldCheck, Table2, UsersRound, X } from 'lucide-react'

export type Role = 'Administrator' | 'Coordinator' | 'Approver' | 'Faculty' | 'Student'

export const roleMenus: Record<Role, Array<{ label: string; path: string; icon: typeof LayoutDashboard }>> = {
  Administrator: [
    { label: t('nav.dashboard'), path: '/', icon: LayoutDashboard },
    { label: t('nav.users.audit'), path: '/users', icon: UsersRound },
  ],
  Coordinator: [
    { label: t('nav.dashboard'), path: '/', icon: LayoutDashboard },
    { label: t('nav.data.management'), path: '/data', icon: Table2 },
    { label: t('nav.import.csv'), path: '/import', icon: FileUp },
    { label: t('nav.availability'), path: '/availability', icon: Clock },
    { label: t('nav.constraints'), path: '/settings', icon: Settings2 },
    { label: t('nav.generate'), path: '/generate', icon: FileClock },
    { label: t('nav.timetable'), path: '/timetable', icon: CalendarRange },
    { label: t('nav.exams'), path: '/exams', icon: CalendarDays },
    { label: t('nav.conflicts'), path: '/conflicts', icon: AlertTriangle },
  ],
  Approver: [
    { label: t('nav.dashboard'), path: '/', icon: LayoutDashboard },
    { label: t('nav.review.publish'), path: '/approvals', icon: ShieldCheck },
    { label: t('nav.timetable'), path: '/timetable', icon: CalendarRange },
    { label: t('nav.exams'), path: '/exams', icon: CalendarDays },
    { label: t('nav.conflicts'), path: '/conflicts', icon: AlertTriangle },
    { label: t('nav.data.management'), path: '/data', icon: Table2 },
  ],
  Faculty: [
    { label: t('nav.dashboard'), path: '/', icon: LayoutDashboard },
    { label: t('nav.availability'), path: '/availability', icon: BookOpen },
    { label: t('nav.timetable'), path: '/timetable', icon: CalendarRange },
    { label: t('nav.exams'), path: '/exams', icon: CalendarDays },
  ],
  Student: [
    { label: t('nav.dashboard'), path: '/', icon: LayoutDashboard },
    { label: t('nav.my.schedule'), path: '/timetable', icon: CalendarRange },
    { label: t('nav.exams'), path: '/exams', icon: CalendarDays },
  ],
}

export const getAllowedPaths = (role: Role): string[] => [...roleMenus[role].map((item) => item.path), '/login', '/password', '/help']

export function AppShell({ children, path, role, userName = 'Alex Roy', onLogout, onNavigate, statusMessage }: { children: React.ReactNode; path: string; role: Role; userName?: string; onLogout: () => void; onNavigate: (path: string) => void; statusMessage: string }) {
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
          <button className="icon-button" type="button" aria-label="Help for this screen" onClick={() => go(`/help`)}><BookOpen size={17} /></button>
          <details className="user-menu"><summary><span className="avatar">{initials}</span><span className="user-copy"><strong>{userName}</strong><small>{role}</small></span><ChevronDown size={14} aria-hidden="true" /></summary><div className="user-popover">
            {role === 'Administrator' && <button type="button" onClick={() => go('/users')}><UsersRound size={15} />Users & audit log</button>}
            {role === 'Coordinator' && <button type="button" onClick={() => go('/settings')}><Settings2 size={15} />Constraints & settings</button>}
            <button type="button" onClick={() => go('/password')}><ShieldCheck size={15} />Change password</button>
            <button type="button" onClick={onLogout}><LogIn size={15} />Log out</button>
          </div></details>
        </div>
      </div>
    </header>
    <a className="skip-link" href="#main-content">Skip to main content</a><main id="main-content" tabIndex={-1} className="main-content">{children}</main>
    <footer className="status-bar" role="status" aria-live="polite"><div className="status-bar-inner"><span className="status-pulse" aria-hidden="true" /><span>{statusMessage}</span><span className="status-meta">Asia/Karachi · {formatToday()}</span></div></footer>
  </div>
}
