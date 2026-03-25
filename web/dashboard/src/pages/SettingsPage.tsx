import React from 'react'
import { Settings } from 'lucide-react'

export function SettingsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Settings</h1>
        <p className="text-slate-400 text-sm mt-1">Platform configuration</p>
      </div>
      <div className="flex flex-col items-center justify-center py-24 text-slate-500 gap-3">
        <Settings className="w-10 h-10 text-slate-600" />
        <p className="text-sm">Settings dashboard coming soon</p>
      </div>
    </div>
  )
}
