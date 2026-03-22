import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { projectClient } from "../client";
import type { Project } from "../gen/omega/v1/types_pb";

interface ProjectContextValue {
  projects: Project[];
  selectedProject: Project | null;
  setSelectedProject: (p: Project) => void;
  loading: boolean;
}

const ProjectContext = createContext<ProjectContextValue>({
  projects: [],
  selectedProject: null,
  setSelectedProject: () => {},
  loading: true,
});

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    projectClient
      .listProjects({})
      .then((res) => {
        setProjects(res.projects);
        if (res.projects.length > 0) {
          setSelectedProject(res.projects[0]);
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <ProjectContext.Provider value={{ projects, selectedProject, setSelectedProject, loading }}>
      {children}
    </ProjectContext.Provider>
  );
}

export function useProject() {
  return useContext(ProjectContext);
}
