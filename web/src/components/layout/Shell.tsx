import type React from "react";
import { Activity, AlertCircle, Network } from "lucide-react";

export function Shell({ children, status, error }: { children?: React.ReactNode; status: string; error?: string }) {
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Network size={24} />
          <div>
            <h1>AgentTrace</h1>
            <p>Multi-agent workflow trace analysis</p>
          </div>
        </div>
        <div className={error ? "status error" : "status"}>
          {error ? <AlertCircle size={16} /> : <Activity size={16} />}
          <span>{status}</span>
        </div>
      </header>
      {error ? <div className="errorPanel">{error}</div> : children}
    </div>
  );
}
