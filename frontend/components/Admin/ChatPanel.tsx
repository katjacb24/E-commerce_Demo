"use client";

import { useEffect, useRef, useState } from "react";
import Spinner from "@/components/Spinner";
import type { ChatMessage } from "./types";

type ChatPanelProps = {
  messages: ChatMessage[];
  onSendMessage: (content: string) => void;
  isReplying: boolean;
  onShowDetails: (messageId: string) => void;
  activeDetailsMessageId: string | null;
  onExitSession: () => void;
};

export default function ChatPanel({
  messages,
  onSendMessage,
  isReplying,
  onShowDetails,
  activeDetailsMessageId,
  onExitSession,
}: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, isReplying]);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed) return;
    onSendMessage(trimmed);
    setDraft("");
  };

  return (
    <section className="flex h-full flex-col rounded-2xl border border-violet-100 bg-violet-50">
      <header className="relative flex items-start justify-between gap-3 rounded-t-2xl border-b border-violet-100 px-4 py-3">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold tracking-wide text-black">
            Couchbase Ops Assistant
            <span className="group inline-flex">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                aria-hidden
                className="h-4 w-4 flex-none text-black/40"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.5}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"
                />
              </svg>
              <span
                role="tooltip"
                className="pointer-events-none absolute left-1/2 top-full z-10 mt-2 w-64 -translate-x-1/2 whitespace-pre-line rounded-xl bg-neutral-900 px-3 py-2 text-[11px] font-normal leading-5 text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100"
              >
                {
                  "Ask this assistant about cluster health, slow queries, index status, or search data in your Couchbase database. It answers by calling the Couchbase MCP server's tools live against your cluster.\n\nClick “Show details” on any reply to see exactly which tools it called and what they returned. \n\n Press the exit icon to finish this session and clear the chat window."
                }
              </span>
            </span>
          </h2>
          <p className="text-xs text-black/55">Ask about cluster health, queries, or indexes.</p>
        </div>
        <button
          type="button"
          onClick={onExitSession}
          aria-label="End session and clear the chat"
          title="End session and clear the chat"
          className="-mr-1 inline-flex h-8 w-8 flex-none items-center justify-center rounded-full text-black/45 transition-colors hover:bg-violet-100 hover:text-black"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </header>

      <div
        ref={scrollRef}
        className="flex-1 space-y-3 overflow-y-auto overflow-x-hidden rounded-b-2xl bg-violet-50/40 p-4"
      >
        {messages.map((message) => {
          const isUser = message.role === "user";
          const isActive = activeDetailsMessageId === message.id;

          return (
            <div key={message.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[80%] min-w-0 rounded-2xl px-3 py-2 text-xs shadow-sm ${
                  isUser
                    ? "rounded-br-md bg-violet-700 text-white"
                    : "rounded-bl-md bg-white text-black/80"
                }`}
              >
                {/* Only replies backed by a real agent run have a trace to open. */}
                {message.run ? (
                  <button
                    type="button"
                    onClick={() => onShowDetails(message.id)}
                    aria-pressed={isActive}
                    className={`mb-2 inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-colors ${
                      isActive
                        ? "border-teal-700 bg-teal-700 text-white"
                        : "border-teal-200 text-teal-800 hover:bg-teal-50"
                    }`}
                  >
                    Show details
                  </button>
                ) : null}
                <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{message.content}</div>
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
          placeholder="Ask the agent something…"
          className="h-10 flex-1 rounded-full border border-violet-200 px-4 text-sm outline-none transition-colors focus:border-violet-600"
        />
        <button
          type="submit"
          disabled={!draft.trim()}
          className="inline-flex h-10 items-center justify-center rounded-full bg-violet-700 px-4 text-sm font-semibold text-white transition-colors hover:bg-violet-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          Send
        </button>
      </form>
    </section>
  );
}
