import { Component } from "react";
import type { ReactNode, ErrorInfo } from "react";

interface Props {
  children: ReactNode;
  fallbackLabel?: string;
}

interface State {
  error: Error | null;
}

/**
 * ErrorBoundary — catches JS errors in child component trees and renders a
 * dark-themed fallback panel instead of a completely blank white page.
 */
export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            background: "#000",
            color: "#00ff00",
            fontFamily: "'IBM Plex Mono','Courier New',monospace",
            padding: 24,
            minHeight: "60vh",
            display: "flex",
            flexDirection: "column",
            gap: 16,
          }}
        >
          <div style={{ color: "#ff2200", fontSize: 12, letterSpacing: "0.1em" }}>
            ■ RENDER ERROR — {this.props.fallbackLabel ?? "component"}
          </div>
          <pre
            style={{
              color: "#ff2200",
              fontSize: 11,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              maxHeight: 300,
              overflow: "auto",
              border: "1px solid #ff2200",
              padding: "8px 12px",
            }}
          >
            {this.state.error.message}
            {"\n\n"}
            {this.state.error.stack}
          </pre>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              background: "transparent",
              border: "1px solid #00ff00",
              color: "#00ff00",
              fontFamily: "inherit",
              fontSize: 11,
              padding: "6px 14px",
              cursor: "pointer",
              alignSelf: "flex-start",
              letterSpacing: "0.1em",
            }}
          >
            &gt; RETRY
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
