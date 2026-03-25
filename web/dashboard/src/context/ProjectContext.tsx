import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { api, type Project } from '../lib/api'

interface ProjectContextValue {
  projects: Project[]
  selectedProject: Project | null
  setSelectedProject: (p: Project) => void
  loading: boolean
  error: string | null
  refetch: () => void
}

const ProjectContext = createContext<ProjectContextValue | null>(null)

// Fallback stub projects so the UI renders even when the backend is unavailable.
const FALLBACK_PROJECTS: Project[] = [
  {
    project_id: 'victoria',
    name: 'Victoria',
    description: 'Crypto quantitative trading system',
    status: 'active',
    domain: 'crypto_quant',
    autonomy_level: 'SUPERVISED',
    node_ids: [],
    pipeline_config: [],
  },
]

export function ProjectProvider({ children }: { children: React.ReactNode }) {
  const [projects, setProjects] = useState<Project[]>(FALLBACK_PROJECTS)
  const [selectedProject, setSelectedProject] = useState<Project | null>(FALLBACK_PROJECTS[0])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchProjects = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.listProjects()
      const list = res.projects ?? []
      if (list.length > 0) {
        setProjects(list)
        // Preserve selection if the current project still exists, else pick first.
        setSelectedProject(prev => {
          const still = prev ? list.find(p => p.project_id === prev.project_id) : null
          return still ?? list[0]
        })
      }
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load projects')
      // Keep fallback projects on error
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchProjects() }, [fetchProjects])

  return (
    <ProjectContext.Provider value={{
      projects,
      selectedProject,
      setSelectedProject,
      loading,
      error,
      refetch: fetchProjects,
    }}>
      {children}
    </ProjectContext.Provider>
  )
}

export function useProjects() {
  const ctx = useContext(ProjectContext)
  if (!ctx) throw new Error('useProjects must be used within ProjectProvider')
  return ctx
}
