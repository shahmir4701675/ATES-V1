import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Search, X } from 'lucide-react'
import { Button } from './ui'
import { useDebouncedValue } from '../hooks/useDebouncedValue'

const focusable = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** Accessible modal: labelled, Esc to close, focus moves in and returns to the trigger, Tab stays inside. */
export function Modal({ title, onClose, children, footer, wide }: { title: string; onClose: () => void; children: React.ReactNode; footer?: React.ReactNode; wide?: boolean }) {
  const titleId = useId()
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const dialog = ref.current
    ;(dialog?.querySelector<HTMLElement>(focusable) ?? dialog)?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.stopPropagation(); onClose() }
      if (event.key === 'Tab' && ref.current) {
        const items = [...ref.current.querySelectorAll<HTMLElement>(focusable)]
        if (!items.length) { event.preventDefault(); ref.current.focus(); return }
        const first = items[0]
        const last = items[items.length - 1]
        if (!ref.current.contains(document.activeElement)) { event.preventDefault(); first.focus() }
        else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); previous?.focus() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <div className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} ref={ref}>
      <div className="modal-header"><h2 id={titleId}>{title}</h2><button type="button" className="icon-button modal-close" aria-label="Close dialog" onClick={onClose}><X size={18} /></button></div>
      <div className="modal-body">{children}</div>
      {footer && <div className="modal-footer">{footer}</div>}
    </div>
  </div>
}

/** Confirmation for destructive or irreversible actions (SRS GUI standard 2). Cancel sits next to the primary action. */
export function ConfirmDialog({ title, message, confirmLabel, danger = true, busy, onConfirm, onCancel }: { title: string; message: React.ReactNode; confirmLabel: string; danger?: boolean; busy?: boolean; onConfirm: () => void; onCancel: () => void }) {
  return <Modal title={title} onClose={onCancel} footer={<><Button variant="secondary" onClick={onCancel}>Cancel</Button><Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm} disabled={busy}>{busy ? 'Working…' : confirmLabel}</Button></>}>
    <div className="confirm-message">{message}</div>
  </Modal>
}

export interface Column<T> {
  key: string
  label: string
  value: (row: T) => string | number
  render?: (row: T) => React.ReactNode
  sortable?: boolean
}

export interface RemoteTable {
  page: number; total: number; query: string; sort: { key: string; dir: 1 | -1 }
  onPage: (page: number) => void; onQuery: (query: string) => void; onSort: (key: string) => void
}

/** Searchable, sortable table with paging (25 rows by default, SRS GUI standard 5). */
export function DataTable<T>({ rows, columns, rowKey, searchText, caption, actions, toolbar, pageSize = 25, emptyText = 'No records match the current search.', remote }: {
  rows: T[]; columns: Column<T>[]; rowKey: (row: T) => string; searchText: (row: T) => string; caption: string
  actions?: (row: T) => React.ReactNode; toolbar?: React.ReactNode; pageSize?: number; emptyText?: string; remote?: RemoteTable
}) {
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null)
  const [page, setPage] = useState(1)
  const debouncedQuery = useDebouncedValue(query)
  const searchId = useId()
  const filtered = useMemo(() => {
    if (remote) return rows
    const needle = debouncedQuery.trim().toLowerCase()
    const list = needle ? rows.filter((row) => searchText(row).toLowerCase().includes(needle)) : rows
    const column = columns.find((item) => item.key === sort?.key)
    if (!sort || !column) return list
    return [...list].sort((a, b) => {
      const left = column.value(a)
      const right = column.value(b)
      return (typeof left === 'number' && typeof right === 'number' ? left - right : String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: 'base' })) * sort.dir
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, debouncedQuery, sort, remote, searchText, columns])
  const count = remote?.total ?? filtered.length
  const pages = Math.max(1, Math.ceil(count / pageSize))
  const current = Math.min(remote?.page ?? page, pages)
  useEffect(() => {
    if (remote && remote.page > pages) remote.onPage(pages)
  }, [remote?.page, remote?.onPage, pages])
  const visible = remote ? filtered : filtered.slice((current - 1) * pageSize, current * pageSize)
  const activeSort = remote?.sort ?? sort
  const changePage = remote?.onPage ?? setPage
  const toggleSort = (key: string) => { if (remote) { remote.onSort(key); return }; setSort((value) => (value?.key === key ? (value.dir === 1 ? { key, dir: -1 } : null) : { key, dir: 1 })); setPage(1) }
  return <div className="data-panel">
    <div className="table-toolbar no-print">
      <div className="search-box"><Search size={15} aria-hidden="true" /><label htmlFor={searchId} className="sr-only">Search {caption}</label><input id={searchId} type="search" value={remote?.query ?? query} placeholder="Search" title="Search all visible columns" onChange={(event) => { if (remote) remote.onQuery(event.target.value); else { setQuery(event.target.value); setPage(1) } }} /></div>
      <span className="muted tabular">{count} {count === 1 ? 'record' : 'records'}</span>
      {toolbar && <div className="toolbar-actions">{toolbar}</div>}
    </div>
    <div className="table-wrap">
      <table className="data-table">
        <caption className="sr-only">{caption}</caption>
        <thead><tr>{columns.map((column) => {
          const sorted = activeSort?.key === column.key
          const Icon = !sorted ? ArrowUpDown : activeSort!.dir === 1 ? ArrowUp : ArrowDown
          return <th key={column.key} scope="col" aria-sort={sorted ? (activeSort!.dir === 1 ? 'ascending' : 'descending') : undefined}>
            {column.sortable === false ? column.label : <button type="button" className="sort-button" onClick={() => toggleSort(column.key)}>{column.label}<Icon size={12} aria-hidden="true" /></button>}
          </th>
        })}{actions && <th scope="col">Actions</th>}</tr></thead>
        <tbody>{visible.map((row) => <tr key={rowKey(row)}>{columns.map((column) => <td key={column.key}>{column.render ? column.render(row) : column.value(row)}</td>)}{actions && <td><div className="row-actions">{actions(row)}</div></td>}</tr>)}</tbody>
      </table>
      {!visible.length && <div className="empty-state"><Search size={20} aria-hidden="true" /><strong>{emptyText}</strong></div>}
    </div>
    <div className="pager no-print">
      <span className="muted tabular">Page {current} of {pages}</span>
      <div><button type="button" className="button button-secondary" disabled={current <= 1} onClick={() => changePage(current - 1)} aria-label="Previous page"><ChevronLeft size={15} aria-hidden="true" />Previous</button><button type="button" className="button button-secondary" disabled={current >= pages} onClick={() => changePage(current + 1)} aria-label="Next page">Next<ChevronRight size={15} aria-hidden="true" /></button></div>
    </div>
  </div>
}
