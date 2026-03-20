import type { SystemHealth } from "../gen/omega/v1/types_pb";
interface DashboardProps { health: SystemHealth | null }
export default function Dashboard({ health }: DashboardProps) {
  return <div className="text-gray-300"><h1 className="text-2xl font-bold mb-4">Dashboard</h1><p>Health: {health?.status ?? "loading…"}</p></div>;
}
