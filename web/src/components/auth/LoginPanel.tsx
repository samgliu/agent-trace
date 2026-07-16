import { FormEvent, useState } from "react";
import { LockKeyhole } from "lucide-react";

export function LoginPanel({ error, onLogin }: { error?: string; onLogin: (token: string) => Promise<void> }) {
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setMessage(null);
    try {
      await onLogin(token);
    } catch (loginError) {
      setMessage(loginError instanceof Error ? loginError.message : "Could not sign in.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="authPage">
      <form className="authPanel" onSubmit={(event) => void handleSubmit(event)}>
        <div className="authIcon">
          <LockKeyhole size={22} />
        </div>
        <div>
          <small>Protected dashboard</small>
          <h2>Sign in to AgentTrace</h2>
        </div>
        <label>
          <span>Access token</span>
          <input
            autoComplete="current-password"
            autoFocus
            onChange={(event) => setToken(event.target.value)}
            placeholder="Enter access token"
            type="password"
            value={token}
          />
        </label>
        <button disabled={submitting || token.trim().length === 0} type="submit">
          {submitting ? "Signing in..." : "Sign in"}
        </button>
        {message || error ? <p>{message ?? error}</p> : null}
      </form>
    </main>
  );
}
