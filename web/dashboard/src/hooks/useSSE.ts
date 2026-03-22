import { useState, useEffect, useRef } from 'react'
import type { DashboardEvent } from '../lib/api'

interface UseSSEResult {
  events: DashboardEvent[]
  connected: boolean
}

const MAX_EVENTS = 100

export function useSSE(url: string): UseSSEResult {
  const [events, setEvents] = useState<DashboardEvent[]>([])
  const [connected, setConnected] = useState(false)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    const connect = () => {
      const es = new EventSource(url)
      esRef.current = es

      es.onopen = () => setConnected(true)

      es.onmessage = (e) => {
        try {
          const event: DashboardEvent = JSON.parse(e.data)
          setEvents((prev) => [event, ...prev].slice(0, MAX_EVENTS))
        } catch {
          // ignore malformed events
        }
      }

      es.addEventListener('node_update', (e) => {
        try {
          const event: DashboardEvent = JSON.parse((e as MessageEvent).data)
          setEvents((prev) => [{ ...event, type: 'node_update' }, ...prev].slice(0, MAX_EVENTS))
        } catch { /* ignore */ }
      })

      es.addEventListener('cycle_complete', (e) => {
        try {
          const event: DashboardEvent = JSON.parse((e as MessageEvent).data)
          setEvents((prev) => [{ ...event, type: 'cycle_complete' }, ...prev].slice(0, MAX_EVENTS))
        } catch { /* ignore */ }
      })

      es.addEventListener('adversarial_alert', (e) => {
        try {
          const event: DashboardEvent = JSON.parse((e as MessageEvent).data)
          setEvents((prev) => [{ ...event, type: 'adversarial_alert' }, ...prev].slice(0, MAX_EVENTS))
        } catch { /* ignore */ }
      })

      es.onerror = () => {
        setConnected(false)
        es.close()
        // Reconnect after 3s
        setTimeout(connect, 3000)
      }
    }

    connect()
    return () => {
      esRef.current?.close()
    }
  }, [url])

  return { events, connected }
}
