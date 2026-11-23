import { Component, lazy, Suspense, useCallback, useEffect, useState } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { LoadingSkeleton, Notice } from './components/ui'
import { AppShell, getAllowedPaths } from './components/AppShell'
import { LoginPage } from './pages/LoginPage'
import { API_URL, USE_MOCK, logout } from './services/api'
import type { AppUser } from './types'

const HelpPage = lazy(() => import('./pages/HelpPage').then((page) => ({ default: page.HelpPage })))
const AvailabilityPage = lazy(() => import('./pages/AvailabilityPage').then((page) => ({ default: page.AvailabilityPage })))
const ConflictReportPage = lazy(() => import('./pages/ConflictReportPage').then((page) => ({ default: page.ConflictReportPage })))
const ConstraintsSettingsPage = lazy(() => import('./pages/ConstraintsSettingsPage').then((page) => ({ default: page.ConstraintsSettingsPage })))
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((page) => ({ default: page.DashboardPage })))
const DataManagementPage = lazy(() => import('./pages/DataManagementPage').then((page) => ({ default: page.DataManagementPage })))
const ExamSchedulePage = lazy(() => import('./pages/ExamSchedulePage').then((page) => ({ default: page.ExamSchedulePage })))
const GeneratePage = lazy(() => import('./pages/GeneratePage').then((page) => ({ default: page.GeneratePage })))
const ImportWizardPage = lazy(() => import('./pages/ImportWizardPage').then((page) => ({ default: page.ImportWizardPage })))
const PlaceholderPage = lazy(() => import('./pages/PlaceholderPage').then((page) => ({ default: page.PlaceholderPage })))
const ReviewPublishPage = lazy(() => import('./pages/ReviewPublishPage').then((page) => ({ default: page.ReviewPublishPage })))
const TimetablePage = lazy(() => import('./pages/TimetablePage').then((page) => ({ default: page.TimetablePage })))
const PasswordPage = lazy(() => import('./pages/PasswordPage').then((page) => ({ default: page.PasswordPage })))
const UsersAuditPage = lazy(() => import('./pages/UsersAuditPage').then((page) => ({ default: page.UsersAuditPage })))

class PageLoadBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(_error: Error, _info: ErrorInfo) { /* Render a recoverable message without exposing server data. */ }
  render() {
    return this.state.failed ? <Notice tone="error" title="This page could not be loaded" action={<button type="button" onClick={() => window.location.reload()}>Reload application</button>}>Check your connection and reload to fetch the current application files.</Notice> : this.props.children
  }
}

const validPaths = [
  '/',
  '/generate',
  '/timetable',
  '/exams',
  '/conflicts',
  '/approvals',
  '/availability',
  '/teaching',
  '/my-schedule',
  '/data',
  '/import',
  '/settings',
  '/users',
  '/login',
  '/password',
  '/help',
]

function useRoute() {
  const [path, setPath] = useState(() => (validPaths.includes(window.location.pathname) ? window.location.pathname : '/'))
  useEffect(() => {
    const onPopState = () => setPath(validPaths.includes(window.location.pathname) ? window.location.pathname : '/')
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])
  const navigate = useCallback((nextPath: string) => {
    const safePath = validPaths.includes(nextPath) ? nextPath : '/'
    if (safePath !== window.location.pathname) window.history.pushState({}, '', safePath)
    setPath(safePath)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])
  return { path, navigate }
}

export default function App() {
  const { path, navigate } = useRoute()
  const [currentUser, setCurrentUser] = useState<AppUser | null>(null)
  const [statusMessage, setStatusMessage] = useState(
    USE_MOCK ? 'System ready · Mock data mode enabled' : `System ready · Connected to ${API_URL}`,
  )
  const notify = useCallback((message: string) => setStatusMessage(message), [])
  const role = currentUser?.role
  const signOut = async () => {
    try { await logout() } catch { notify('Signed out locally. The server session will expire if it could not be reached.') }
    setCurrentUser(null)
    navigate('/login')
  }
  useEffect(() => {
    const expired = () => { setCurrentUser(null); navigate('/login') }
    window.addEventListener('ates:auth-required', expired)
    return () => window.removeEventListener('ates:auth-required', expired)
  }, [])

  useEffect(() => {
    if (role && !getAllowedPaths(role).includes(path)) {
      navigate('/')
      notify(`Route not available for ${role}. Returned to the dashboard.`)
    }
  }, [path, role])

  const onLoginSuccess = (user: AppUser) => {
    setCurrentUser(user)
    notify(`Signed in as ${user.full_name} (${user.role}).`)
    navigate('/')
  }

  if (!currentUser || !role) return <LoginPage onSuccess={onLoginSuccess} />

  const page =
    path === '/help' ? <HelpPage role={role} />
    : path === '/' ? <DashboardPage onNavigate={navigate} onStatus={notify} role={role} />
    : path === '/generate' ? <GeneratePage onNavigate={navigate} onStatus={notify} />
    : path === '/timetable' || path === '/my-schedule' ? <TimetablePage onStatus={notify} role={role} />
    : path === '/exams' ? <ExamSchedulePage onStatus={notify} role={role} />
    : path === '/conflicts' ? <ConflictReportPage onStatus={notify} />
    : path === '/data' ? <DataManagementPage role={role} onNavigate={navigate} onStatus={notify} />
    : path === '/import' ? <ImportWizardPage onNavigate={navigate} onStatus={notify} />
    : path === '/settings' ? <ConstraintsSettingsPage onStatus={notify} />
    : path === '/availability' || path === '/teaching' ? <AvailabilityPage role={role} facultyInstructorId={currentUser?.instructor_id} onStatus={notify} />
    : path === '/approvals' ? <ReviewPublishPage onNavigate={navigate} onStatus={notify} />
    : path === '/users' ? <UsersAuditPage onStatus={notify} />
    : path === '/password' ? <PasswordPage onStatus={notify} />
    : path === '/login' ? <LoginPage onSuccess={onLoginSuccess} onCancel={() => navigate('/')} />
    : <PlaceholderPage path={path} onNavigate={navigate} />

  return (
    <AppShell
      path={path}
      role={role}
      userName={currentUser.full_name}
      onLogout={() => void signOut()}
      onNavigate={navigate}
      statusMessage={statusMessage}
    >
      <PageLoadBoundary key={path}><Suspense fallback={<LoadingSkeleton label="Loading page…" />}>{page}</Suspense></PageLoadBoundary>
    </AppShell>
  )
}
