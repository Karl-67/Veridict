import React from "react";
import RedesignHost from "./RedesignHost.jsx";

interface ErrorBoundaryState {
  error: Error | null;
}

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, ErrorBoundaryState> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100vh", padding: 32, textAlign: "center", fontFamily: "system-ui, sans-serif" }}>
          <p style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "#999", marginBottom: 16 }}>Unexpected Error</p>
          <h1 style={{ fontSize: 28, fontWeight: 700, color: "#1a1a1a", marginBottom: 12 }}>Something went wrong</h1>
          <p style={{ fontSize: 14, color: "#666", marginBottom: 8, maxWidth: 420 }}>
            {this.state.error.message || "An unexpected error occurred."}
          </p>
          <p style={{ fontSize: 13, color: "#999", marginBottom: 32 }}>Please reload the page. If the problem persists, contact your administrator.</p>
          <button
            onClick={() => window.location.reload()}
            style={{ fontSize: 14, fontWeight: 600, color: "#fff", background: "#1a1a1a", border: "none", borderRadius: 8, padding: "10px 28px", cursor: "pointer" }}>
            Reload page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  return (
    <ErrorBoundary>
      <RedesignHost />
    </ErrorBoundary>
  );
}
