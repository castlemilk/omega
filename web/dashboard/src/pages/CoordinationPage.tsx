import React from 'react'
import { GitBranch } from 'lucide-react'

export function CoordinationPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Coordination</h1>
        <p className="text-slate-400 text-sm mt-1">Cross-project coordination and outcome store</p>
      </div>
      <div className="flex flex-col items-center justify-center py-24 text-slate-500 gap-3">
        <GitBranch className="w-10 h-10 text-slate-600" />
        <p className="text-sm">Coordination dashboard coming soon</p>
      </div>
    </div>
  )
}
