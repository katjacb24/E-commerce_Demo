import type { AgentToolCall, AlertSeverity } from "@/components/Admin/types";
import { apiUrl } from "./api";

/** Response of POST /api/agent/chat. */
export type AgentChatResponse = {
  answer: string;
  toolCalls: AgentToolCall[];
};

/** Response of POST /api/agent/checks. */
export type ClusterChecksResponse = {
  answer: string;
  summary: string;
  toolCalls: AgentToolCall[];
  counts: Record<AlertSeverity, number>;
};

const EMPTY_COUNTS: Record<AlertSeverity, number> = { critical: 0, serious: 0, warning: 0 };

/**
 * Sends a chat query to the admin agent and returns its answer along with the
 * trace of Couchbase MCP tool calls that produced it.
 */
export async function sendAgentMessage(query: string): Promise<AgentChatResponse> {
  const response = await fetch(apiUrl("/api/agent/chat").toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
    cache: "no-store",
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail || "The agent could not process your request.");
  }

  const data = (await response.json()) as AgentChatResponse;
  return { answer: data.answer, toolCalls: data.toolCalls ?? [] };
}

/**
 * Runs the Operations Dashboard's cluster checks. The agent picks the tools
 * itself and follows its own findings up with further calls, so the trace
 * that comes back is longer than the list of baseline checks — and each call
 * in it carries the finding and recommendation the agent wrote for it.
 */
export async function runClusterChecks(): Promise<ClusterChecksResponse> {
  const response = await fetch(apiUrl("/api/agent/checks").toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail || "The agent could not run the cluster checks.");
  }

  const data = (await response.json()) as ClusterChecksResponse;
  return {
    answer: data.answer ?? "",
    summary: data.summary ?? "",
    toolCalls: data.toolCalls ?? [],
    counts: data.counts ?? EMPTY_COUNTS,
  };
}
