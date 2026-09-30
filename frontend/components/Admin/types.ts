export type AlertSeverity = "critical" | "serious" | "warning";

export type ChatRole = "assistant" | "user";

/** Outcome of a tool call: "pending" means the tool never returned a result. */
export type AgentToolCallStatus = "success" | "error" | "pending";

/** One Couchbase MCP tool invocation the agent made during a run. */
export type AgentToolCall = {
  name: string;
  args: Record<string, unknown>;
  result: string;
  status: AgentToolCallStatus;
  /**
   * The check run's verdict on this call, written by the agent's reporting
   * pass. Null on every call in a chat reply's trace, and on a check call that
   * surfaced nothing — which is what makes a call read as "No findings."
   */
  severity?: AlertSeverity | null;
  finding?: string | null;
  recommendation?: string | null;
};

/**
 * The trace behind one assistant reply — what the agent was asked, which tools
 * it called, and what it concluded. Attached to assistant messages that came
 * from a real agent run, which is what makes "Show details" available on them.
 */
export type AgentRun = {
  query: string;
  answer: string;
  toolCalls: AgentToolCall[];
};

/**
 * One press of "Trigger Checks": the tools the agent ran, the finding and
 * recommendation it attached to each, and its read of the cluster overall.
 * The dashboard shows the latest run only, as a single block in the alert
 * list rather than one row per finding.
 */
export type CheckRun = {
  id: string;
  timestamp: string; // ISO string
  /** The agent's one- or two-sentence read of the cluster. */
  summary: string;
  /** Its full prose answer, kept as the unabridged version of the summary. */
  answer: string;
  toolCalls: AgentToolCall[];
  counts: Record<AlertSeverity, number>;
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  /** Absent on the greeting and on error replies, which have no run behind them. */
  run?: AgentRun;
};
