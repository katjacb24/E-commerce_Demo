"use client";

type AssistantMemoryInfoProps = {
  isLoggedIn: boolean;
};

const LOGGED_IN_TEXT =
  "When you are logged in, Couchbase Agent Memory will store your conversations as memories and use those memories to personalize your Personal Assistant experience.\n\nOpening the chat window starts a new session. To end the session, close the chat window or log out on the top of the page.\n\nWhen you are logged out, no memories will be stored or used to personalise your experience with the Personal Assistant.";

const LOGGED_OUT_TEXT =
  "When you are logged out, Couchbase Agent Memory will not collect any conversational memories. This also means that there will be no personalization. Each conversation turn will start from zero.\n\nIn order to benefit from personalised experience, please log in.";

// Hover-only tooltip, matching the search bar info icon in the NavBar.
export default function AssistantMemoryInfo({ isLoggedIn }: AssistantMemoryInfoProps) {
  return (
    <span className="group relative inline-flex shrink-0">
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
      {/* Anchored to the icon's left edge rather than centred: the panel clips
          its own overflow, and the icon sits close to the panel's left edge. */}
      <span
        role="tooltip"
        className="pointer-events-none absolute left-0 top-full z-10 mt-2 w-72 whitespace-pre-line rounded-xl bg-neutral-900 px-3 py-2 text-xs font-normal leading-5 text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100"
      >
        {isLoggedIn ? LOGGED_IN_TEXT : LOGGED_OUT_TEXT}
      </span>
    </span>
  );
}
