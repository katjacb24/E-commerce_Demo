"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import AssistantMemoryInfo from "@/components/AssistantMemoryInfo";
import DemoMemoryControls from "@/components/DemoMemoryControls";
import Markdown from "@/components/Markdown";
import Spinner from "@/components/Spinner";
import { sendAssistantMessage } from "@/lib/assistant";
import type { DemoUser } from "@/lib/auth";

type ChatMessage = {
  id: string;
  role: "assistant" | "user";
  content: string;
};

let nextMessageId = 1;

type ChatbotPanelProps = {
  isOpen: boolean;
  onClose: () => void;
  currentUser: DemoUser | null;
};

export default function ChatbotPanel({ isOpen, onClose, currentUser }: ChatbotPanelProps) {
  // The greeting is rendered from `currentUser` on every pass rather than seeded
  // into state, so it follows a log in that happens with the panel already open.
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [isReplying, setIsReplying] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Presenter controls. Both are properties of the session rather than of a
  // turn: `retentionSeconds` only reaches the server on the request that opens
  // the session, and `sessionDate` would date a conversation's turns
  // inconsistently if it changed part way through. So both lock once the
  // conversation has started, and both clear when it ends.
  const [sessionDate, setSessionDate] = useState("");
  const [retentionSeconds, setRetentionSeconds] = useState<number | null>(null);
  const [retentionInForce, setRetentionInForce] = useState<number | null>(null);
  // Whether a memory session exists yet. Held in state, not read off the ref
  // below, because the retention control's locked state is rendered from it and
  // a ref mutation does not re-render.
  const [hasMemorySession, setHasMemorySession] = useState(false);

  // The username identifies the shopper for UI purposes (greeting, reset
  // triggers); userId is the opaque identity Agent Memory stores facts under.
  // They are deliberately kept distinct so a future username change/rename
  // does not fork a shopper's memory under a new identity.
  const username = currentUser?.username ?? null;
  const userId = currentUser?.user_id ?? null;

  // Guards setState after unmount for a reply that is still in flight.
  const isMountedRef = useRef(true);
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // Identifies the current conversation, together with the Agent Memory session
  // it maps to. The two are one thing: whatever ends the visible thread ends the
  // session with it, and the next question opens a new one.
  const conversationRef = useRef(0);
  const memorySessionIdRef = useRef<string | null>(null);
  // How many turns this conversation has had. Sent with every request because
  // the backend picks the shape of recall from it; reset with the conversation
  // so a reopened panel starts its window over.
  const turnCountRef = useRef(0);

  const resetConversation = useCallback(() => {
    conversationRef.current += 1;
    memorySessionIdRef.current = null;
    turnCountRef.current = 0;
    setMessages([]);
    setDraft("");
    setIsReplying(false);
    // A new conversation opens a new session, so both controls clear back to
    // their defaults and become settable again. Carrying a date or a retention
    // over from a closed session is the wrong default: the presenter's next
    // conversation is a fresh one, and a stale date silently backdating it is
    // the harder mistake to notice.
    setSessionDate("");
    setRetentionSeconds(null);
    setRetentionInForce(null);
    setHasMemorySession(false);
  }, []);

  // Signing in or out starts a fresh conversation: the next shopper must not
  // inherit the previous one's thread or write into their memory session, and a
  // reply still in flight when the identity changes is dropped, not appended.
  // A browser reload is covered by the same rule for free — AppShell holds the
  // sign-in in state only, so reloading signs the shopper out and remounts this
  // panel empty.
  useEffect(() => {
    resetConversation();
  }, [username, resetConversation]);

  // Closing the panel ends the conversation too. The component stays mounted
  // (AppShell only flips `isOpen`), so without this the thread would outlive the
  // close and reopening would keep filing turns under a finished session.
  useEffect(() => {
    if (!isOpen) {
      resetConversation();
    }
  }, [isOpen, resetConversation]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, isReplying, isOpen]);

  // The open/closed flag lives in AppShell and this component stays mounted, so
  // the thread survives a close and reopen. The early return sits below every
  // hook so the hook order never changes.
  if (!isOpen) {
    return null;
  }

  // The conversation has started once the shopper has sent anything, which is
  // also the point at which both presenter controls stop being actionable: the
  // retention of the session being opened has already gone out with that
  // request, and dating later turns differently from earlier ones would only
  // produce a conversation that is internally inconsistent. `hasMemorySession`
  // is kept in the condition so a reply that arrives after an identity change
  // cannot unlock the controls mid-session.
  const hasConversationStarted =
    hasMemorySession || messages.some((message) => message.role === "user");

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const trimmed = draft.trim();
    if (!trimmed || isReplying) {
      return;
    }

    setDraft("");
    setMessages((prev) => [
      ...prev,
      { id: `msg-${nextMessageId++}`, role: "user", content: trimmed },
    ]);
    setIsReplying(true);

    const conversation = conversationRef.current;
    const isCurrent = () =>
      isMountedRef.current && conversationRef.current === conversation;

    try {
      const { answer, sessionId, turnCount, sessionRetentionSeconds } =
        await sendAssistantMessage(
          trimmed,
          userId,
          username,
          memorySessionIdRef.current,
          turnCountRef.current,
          { sessionDate: sessionDate || null, sessionRetentionSeconds: retentionSeconds }
        );
      if (!isCurrent()) return;
      turnCountRef.current = turnCount;
      setRetentionInForce(sessionRetentionSeconds);
      // Kept for the rest of the conversation so every later turn is filed under
      // the same session. A reset while this was in flight fails the guard above,
      // so a stale session is never carried into the new conversation.
      if (sessionId) {
        memorySessionIdRef.current = sessionId;
        setHasMemorySession(true);
      }
      setMessages((prev) => [
        ...prev,
        { id: `msg-${nextMessageId++}`, role: "assistant", content: answer },
      ]);
    } catch (error) {
      if (!isCurrent()) return;
      const message =
        error instanceof Error ? error.message : "The assistant could not process your request.";
      setMessages((prev) => [
        ...prev,
        { id: `msg-${nextMessageId++}`, role: "assistant", content: message },
      ]);
    } finally {
      if (isCurrent()) setIsReplying(false);
    }
  };

  return (
    <aside
      aria-label="Personal Assistant chat panel"
      className="fixed bottom-4 right-4 z-40 flex h-[min(70vh,34rem)] w-[calc(100vw-2rem)] max-w-md flex-col overflow-hidden rounded-2xl border border-purple-900/50 bg-white shadow-[0_0_0_3px_rgba(88,28,135,0.15),0_18px_40px_rgba(17,17,17,0.2)] sm:bottom-6 sm:right-6"
    >
      <header className="flex items-center justify-between gap-2 border-b border-violet-100 px-4 py-3">
        <div className="flex min-w-0 items-center gap-1">
          <h2 className="text-sm font-semibold tracking-wide text-violet-900">Personal Assistant</h2>
          <AssistantMemoryInfo isLoggedIn={Boolean(currentUser)} />

          {/* Whether Agent Memory is recording this conversation, which follows
              the sign-in state. */}
          <span
            title={
              currentUser
                ? "Agent Memory is on — this conversation is stored and personalized."
                : "Agent Memory is off — log in for a personalized conversation."
            }
            className={`inline-flex flex-none items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${
              currentUser ? "bg-violet-100 text-violet-800" : "bg-neutral-100 text-black/50"
            }`}
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden
              className="h-3.5 w-3.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 3.75a3 3 0 00-3 3v.324A2.625 2.625 0 007.125 12 2.625 2.625 0 009 16.926V17.25a3 3 0 006 0v-.324A2.625 2.625 0 0016.875 12 2.625 2.625 0 0015 7.074V6.75a3 3 0 00-3-3zM12 3.75v16.5"
              />
            </svg>
            Memory {currentUser ? "on" : "off"}
          </span>
        </div>

        <button
          type="button"
          aria-label="Close Personal Assistant"
          onClick={onClose}
          className="inline-flex h-8 w-8 items-center justify-center rounded-full text-black/70 transition-colors hover:bg-violet-50 hover:text-black"
        >
          <span aria-hidden className="text-xl leading-none">
            ×
          </span>
        </button>
      </header>

      {/* Demo-only, and only useful while memory is recording. */}
      {currentUser ? (
        <DemoMemoryControls
          sessionDate={sessionDate}
          onSessionDateChange={setSessionDate}
          retentionSeconds={retentionSeconds}
          onRetentionChange={setRetentionSeconds}
          isLocked={hasConversationStarted}
          retentionInForce={retentionInForce}
        />
      ) : null}

      <div
        ref={scrollRef}
        className="flex-1 space-y-3 overflow-y-auto overflow-x-hidden bg-violet-100/70 p-4"
      >
        <div className="max-w-[90%] rounded-2xl rounded-bl-md bg-white px-3 py-2 text-sm text-black/80 shadow-sm">
          {currentUser ? `Hello ${currentUser.displayName}!` : "Hello!"} I am your personal shopping
          assistant. What can I help you with today?
        </div>

        {messages.map((message) => {
          const isUser = message.role === "user";
          return (
            <div key={message.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
              <div
                className={`min-w-0 max-w-[90%] break-words [overflow-wrap:anywhere] rounded-2xl px-3 py-2 text-sm shadow-sm ${
                  isUser
                    ? "whitespace-pre-wrap rounded-br-md bg-violet-700 text-white"
                    : "rounded-bl-md bg-white text-black/80"
                }`}
              >
                {/* The shopper's own text is shown verbatim; only agent replies
                    are markdown. */}
                {isUser ? message.content : <Markdown content={message.content} />}
              </div>
            </div>
          );
        })}

        {isReplying ? (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-2xl rounded-bl-md bg-white px-3 py-2 text-sm text-black/60 shadow-sm">
              <Spinner className="h-3.5 w-3.5" />
              Thinking…
            </div>
          </div>
        ) : null}
      </div>

      <form
        className="flex items-center gap-2 border-t border-violet-100 bg-white p-3"
        onSubmit={handleSubmit}
      >
        <input
          type="text"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Type a message..."
          className="h-10 flex-1 rounded-full border border-violet-200 px-4 text-sm outline-none transition-colors focus:border-violet-600"
        />
        <button
          type="submit"
          disabled={!draft.trim() || isReplying}
          className="inline-flex h-10 items-center justify-center rounded-full bg-violet-700 px-4 text-sm font-semibold text-white transition-colors hover:bg-violet-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          Send
        </button>
      </form>
    </aside>
  );
}
