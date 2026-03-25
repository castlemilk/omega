import React, { useState, useRef, useEffect } from 'react'
import { ChevronDown, Layers, Check } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useProjects } from '../context/ProjectContext'

const domainColors: Record<string, string> = {
  crypto_quant: 'bg-emerald-500/20 text-emerald-300',
  macro_research: 'bg-sky-500/20 text-sky-300',
  options_arb: 'bg-violet-500/20 text-violet-300',
  custom: 'bg-slate-500/20 text-slate-300',
}

export function ProjectSwitcher({ collapsed }: { collapsed: boolean }) {
  const { projects, selectedProject, setSelectedProject } = useProjects()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  function select(p: typeof selectedProject) {
    if (!p) return
    setSelectedProject(p)
    setOpen(false)
    navigate(`/projects/${p.project_id}`)
  }

  const colorCls = domainColors[selectedProject?.domain ?? ''] ?? domainColors.custom

  if (collapsed) {
    return (
      <button
        onClick={() => setOpen(!open)}
        title={selectedProject?.name ?? 'Select project'}
        className="w-full flex justify-center items-center py-2 text-slate-400 hover:text-slate-200 relative"
      >
        <Layers className="w-4 h-4" />
      </button>
    )
  }

  return (
    <div ref={ref} className="relative px-2">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700/50 hover:border-slate-600 transition-colors text-sm"
        aria-haspopup="listbox"
        aria-expanded={open}
        data-testid="project-switcher-trigger"
      >
        <Layers className="w-4 h-4 text-slate-400 shrink-0" />
        <span className="flex-1 text-left truncate text-slate-200 font-medium">
          {selectedProject?.name ?? 'No project'}
        </span>
        <ChevronDown className={`w-3.5 h-3.5 text-slate-500 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div
          className="absolute top-full left-0 right-0 mt-1 z-50 bg-slate-800 border border-slate-700 rounded-xl shadow-xl overflow-hidden"
          role="listbox"
          data-testid="project-switcher-dropdown"
        >
          <div className="px-3 py-2 border-b border-slate-700/50">
            <p className="text-xs text-slate-500 uppercase tracking-wider font-medium">Projects</p>
          </div>
          {projects.map((p) => {
            const isActive = p.project_id === selectedProject?.project_id
            const pc = domainColors[p.domain] ?? domainColors.custom
            return (
              <button
                key={p.project_id}
                role="option"
                aria-selected={isActive}
                onClick={() => select(p)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-slate-700/60 transition-colors ${
                  isActive ? 'bg-slate-700/40' : ''
                }`}
                data-testid={`project-option-${p.project_id}`}
              >
                <span className={`w-2 h-2 rounded-full shrink-0 ${
                  p.status === 'active' ? 'bg-emerald-400' : 'bg-slate-500'
                }`} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-slate-200 font-medium truncate">{p.name}</p>
                  <p className={`text-xs mt-0.5 px-1.5 py-0.5 rounded-full inline-block ${pc}`}>
                    {p.domain.replace('_', ' ')}
                  </p>
                </div>
                {isActive && <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
