import { apiUrl } from "./api";

/** Response of POST /api/assistant/chat. */
export type AssistantChatResponse = {
  answer: string;
  /** The Agent Memory session the turn was filed under, absent when signed out. */
  sessionId: string | null;
  /** Turns this conversation has now had, this one included. */
  turnCount: number;
  /**
   * The retention this session's message memories are actually running with, in
   * seconds (0 = never expire). Reported by the backend rather than echoed from
   * the request: retention is fixed when the session opens, so a value sent on a
   * later turn was ignored.
   */
  sessionRetentionSeconds: number | null;
};

/** The presenter controls, for driving the demo. Both are optional. */
export type PresenterOptions = {
  /** Date this session should appear to have happened on ("YYYY-MM-DD"). */
  sessionDate?: string | null;
  /** Retention for this session's message memories, in seconds (0 = never). */
  sessionRetentionSeconds?: number | null;
};

/**
 * Sends a shopper message to the user-facing assistant (backend/agents/user_agent.py)
 * and returns its answer.
 *
 * Distinct from `sendAgentMessage`, which talks to the admin agent and also
 * returns the MCP tool trace behind the reply.
 *
 * `userId` switches Agent Memory on; without it the assistant is stateless.
 * `username` only labels that shopper's Agent Memory user when it is first
 * created — `userId` remains the identity memories are filed under.
 * `sessionId` is whatever the previous turn of this conversation came back
 * with, and is null on its first turn so the backend opens a new session.
 * `turnCount` likewise comes back from the previous turn; it decides how the
 * backend shapes recall, so it is carried by the client rather than counted
 * server-side on every turn.
 * `presenter` carries the demo controls; the retention among them only takes
 * effect on the turn that opens the session.
 */
export async function sendAssistantMessage(
  query: string,
  userId: string | null = null,
  username: string | null = null,
  sessionId: string | null = null,
  turnCount: number = 0,
  presenter: PresenterOptions = {}
): Promise<AssistantChatResponse> {
  const response = await fetch(apiUrl("/api/assistant/chat").toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      user_id: userId,
      username,
      session_id: sessionId,
      turn_count: turnCount,
      session_date: presenter.sessionDate ?? null,
      session_retention_seconds: presenter.sessionRetentionSeconds ?? null,
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(
      typeof detail?.detail === "string"
        ? detail.detail
        : "The assistant could not process your request."
    );
  }

  const data = (await response.json()) as {
    answer: string;
    session_id?: string | null;
    turn_count?: number;
    session_retention_seconds?: number | null;
  };
  return {
    answer: data.answer,
    sessionId: data.session_id ?? null,
    turnCount: data.turn_count ?? turnCount + 1,
    sessionRetentionSeconds: data.session_retention_seconds ?? null,
  };
}
