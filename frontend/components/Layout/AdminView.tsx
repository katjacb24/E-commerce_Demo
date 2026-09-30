"use client";

import { useEffect, useRef, useState } from "react";
import AlertsPanel from "@/components/Admin/AlertsPanel";
import ChatPanel from "@/components/Admin/ChatPanel";
import DetailsPanel from "@/components/Admin/DetailsPanel";
import type { ChatMessage, CheckRun } from "@/components/Admin/types";
import { runClusterChecks, sendAgentMessage } from "@/lib/agent";

const INITIAL_MESSAGES: ChatMessage[] = [
  {
    id: "greeting",
    role: "assistant",
    content:
      "Hi, how can I help you?",
  },
];

let nextMessageId = 1;
let nextCheckRunId = 1;

/**
 * The details pane shows one thing at a time, so the check-run selection and
 * the "Show details" selection are held as a single value rather than two
 * pieces of state that could both be set and disagree about what is on screen.
 */
type DetailsSelection = { kind: "check" } | { kind: "run"; messageId: string };

export default function AdminView() {
  // The panel shows the latest check run only, so it starts empty.
  const [checkRun, setCheckRun] = useState<CheckRun | null>(null);
  const [selection, setSelection] = useState<DetailsSelection | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const [lastCheckedAt, setLastCheckedAt] = useState<Date | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);

  const [messages, setMessages] = useState<ChatMessage[]>(INITIAL_MESSAGES);
  const [isReplying, setIsReplying] = useState(false);

  // AdminView unmounts when the shopper leaves the admin view, which would
  // otherwise let a pending timeout call setState after unmount.
  const isMountedRef = useRef(true);
  // Identifies the current chat session; see handleExitSession.
  const chatSessionRef = useRef(0);
  useEffect(() => {
    // Set true on every (re)mount, not just as the ref's initial value: Strict
    // Mode's dev-only mount->unmount->remount cycle would otherwise leave this
    // stuck at false after the simulated unmount, silently dropping every
    // pending timeout callback below for the rest of the component's life.
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  /**
   * Runs the cluster checks through the admin agent. The panel shows the result
   * of the latest run only, so the previous run is replaced rather than added
   * to — a problem the agent no longer reports has been resolved.
   */
  const handleTriggerChecks = async () => {
    setIsChecking(true);
    setCheckError(null);

    try {
      const { answer, summary, toolCalls, counts } = await runClusterChecks();
      if (!isMountedRef.current) return;

      setCheckRun({
        id: `check-${nextCheckRunId++}`,
        timestamp: new Date().toISOString(),
        summary,
        answer,
        toolCalls,
        counts,
      });
      setLastCheckedAt(new Date());
      // Open the new run, unless the pane is showing a chat run the shopper
      // opened deliberately — that one is not replaced out from under them.
      setSelection((current) => (current?.kind === "run" ? current : { kind: "check" }));
    } catch (error) {
      if (!isMountedRef.current) return;
      setCheckError(
        error instanceof Error ? error.message : "The agent could not run the cluster checks."
      );
    } finally {
      if (isMountedRef.current) setIsChecking(false);
    }
  };

  const handleExit = () => {
    setSelection(null);
  };

  const handleExitSession = () => {
    // Bumping the session invalidates any reply already in flight, so a request
    // sent before the reset cannot land in — and repopulate — the cleared chat.
    chatSessionRef.current += 1;
    setMessages(INITIAL_MESSAGES);
    setIsReplying(false);
    // Every run belonged to a message that no longer exists, so a run left open
    // in the details pane would be showing data the session no longer holds.
    setSelection((current) => (current?.kind === "run" ? null : current));
  };

  const handleAcknowledge = () => {
    setCheckRun(null);
    setSelection((current) => (current?.kind === "check" ? null : current));
  };

  const handleSendMessage = async (content: string) => {
    const userMessage: ChatMessage = {
      id: `msg-${nextMessageId++}`,
      role: "user",
      content,
    };
    setMessages((prev) => [...prev, userMessage]);
    setIsReplying(true);

    // The session this reply belongs to. If it is cleared while the request is
    // in flight, the response is dropped rather than added to the new session.
    const session = chatSessionRef.current;
    const isCurrent = () => isMountedRef.current && chatSessionRef.current === session;

    try {
      const { answer, toolCalls } = await sendAgentMessage(content);
      if (!isCurrent()) return;
      setMessages((prev) => [
        ...prev,
        {
          id: `msg-${nextMessageId++}`,
          role: "assistant",
          content: answer,
          // Carrying the run on the message is what makes "Show details"
          // available, and keeps every past run inspectable, not just the last.
          run: { query: content, answer, toolCalls },
        },
      ]);
    } catch (error) {
      if (!isCurrent()) return;
      const message = error instanceof Error ? error.message : "The agent could not process your request.";
      setMessages((prev) => [...prev, { id: `msg-${nextMessageId++}`, role: "assistant", content: message }]);
    } finally {
      if (isCurrent()) setIsReplying(false);
    }
  };

  const isCheckSelected = selection?.kind === "check";

  const activeDetailsMessageId = selection?.kind === "run" ? selection.messageId : null;
  const activeRun =
    messages.find((message) => message.id === activeDetailsMessageId)?.run ?? null;

  return (
    <main className="flex flex-col px-6 pb-6 pt-20 sm:px-10 lg:h-screen lg:overflow-hidden">
      <div className="mb-4 flex-none">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-violet-700">Admin</p>
        <h1 className="mt-1 text-2xl font-semibold text-black">Operations Dashboard</h1>
      </div>

      <div className="grid flex-1 grid-cols-1 gap-6 lg:min-h-0 lg:grid-cols-[minmax(320px,440px)_1fr]">
        <div className="flex flex-col gap-6 lg:h-full lg:min-h-0">
          <div className="h-[280px] lg:h-auto lg:min-h-0 lg:flex-1">
            <AlertsPanel
              checkRun={checkRun}
              isSelected={isCheckSelected}
              onSelect={() => setSelection({ kind: "check" })}
              onTriggerChecks={handleTriggerChecks}
              isChecking={isChecking}
              lastCheckedAt={lastCheckedAt}
              checkError={checkError}
            />
          </div>
          <div className="h-[480px] lg:h-auto lg:min-h-0 lg:flex-[3]">
            <ChatPanel
              messages={messages}
              onSendMessage={handleSendMessage}
              isReplying={isReplying}
              onShowDetails={(messageId) => setSelection({ kind: "run", messageId })}
              activeDetailsMessageId={activeDetailsMessageId}
              onExitSession={handleExitSession}
            />
          </div>
        </div>

        <div className="h-[480px] min-w-0 lg:h-full lg:min-h-0">
          <DetailsPanel
            checkRun={isCheckSelected ? checkRun : null}
            agentRun={activeRun}
            onAcknowledge={handleAcknowledge}
            onExit={handleExit}
          />
        </div>
      </div>
    </main>
  );
}
