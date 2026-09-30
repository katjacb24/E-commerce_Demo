"use client";

import { useState } from "react";

/**
 * Presenter controls for the Agent Memory demo.
 *
 * Neither control belongs in a real shop: one lets the client choose the
 * timestamp memories are stored under, the other how long they survive. They
 * exist so the two things that are otherwise invisible on stage can be shown
 * live — a conversation that appears to have happened months ago, and a
 * transcript that expires while the facts drawn from it persist.
 *
 * Both controls lock once the conversation has started, for related but
 * distinct reasons. Retention is fixed when the session is created, so a value
 * sent on a later turn has nowhere to go. The session date does still reach the
 * server on every turn, but changing it part way through would date one
 * conversation's turns to two different days — so the lock is what makes the
 * control mean "this session happened on this date" rather than "this turn did".
 * Rather than hide either constraint, the locked controls show what is actually
 * in force and say how to change it.
 */

/** Retention presets. 0 means never expire. */
const RETENTION_PRESETS: { label: string; seconds: number | null }[] = [
  { label: "Default (90 days)", seconds: null },
  { label: "1 minute", seconds: 60 },
  { label: "5 minutes", seconds: 300 },
  { label: "1 hour", seconds: 3600 },
  { label: "Never expire", seconds: 0 },
];

function describeRetention(seconds: number | null): string {
  if (seconds === null) return "not set yet";
  if (seconds === 0) return "never expires";
  if (seconds % 86400 === 0) return `${seconds / 86400} day(s)`;
  if (seconds % 3600 === 0) return `${seconds / 3600} hour(s)`;
  if (seconds % 60 === 0) return `${seconds / 60} minute(s)`;
  return `${seconds} second(s)`;
}

/**
 * What to name as the retention in force. Prefers the value read back from the
 * session, falling back to the chosen one while the first reply is still in
 * flight — `describeRetention`'s "not set yet" is true of the control but reads
 * as nonsense next to the word "Locked".
 */
function describeRetentionInForce(
  inForce: number | null,
  chosen: number | null
): string {
  if (inForce !== null) return describeRetention(inForce);
  if (chosen !== null) return describeRetention(chosen);
  return "the default (90 days)";
}

type DemoMemoryControlsProps = {
  sessionDate: string;
  onSessionDateChange: (value: string) => void;
  retentionSeconds: number | null;
  onRetentionChange: (value: number | null) => void;
  /**
   * True once the conversation has started, after which neither the session's
   * date nor its retention can still be changed for that session.
   */
  isLocked: boolean;
  /** The retention the session actually opened with, once it is known. */
  retentionInForce: number | null;
};

export default function DemoMemoryControls({
  sessionDate,
  onSessionDateChange,
  retentionSeconds,
  onRetentionChange,
  isLocked,
  retentionInForce,
}: DemoMemoryControlsProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="border-b border-dashed border-amber-300 bg-amber-50/70 px-3 py-2 text-[11px]">
      <button
        type="button"
        onClick={() => setIsExpanded((open) => !open)}
        aria-expanded={isExpanded}
        className="flex w-full items-center justify-between gap-2 font-semibold text-amber-900"
      >
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden>🎛</span>
          Demo controls
          {!isExpanded && (sessionDate || retentionSeconds !== null) ? (
            <span className="font-normal text-amber-800">
              ({sessionDate || "today"} · {describeRetention(retentionSeconds)})
            </span>
          ) : null}
        </span>
        <span aria-hidden className="text-sm leading-none">
          {isExpanded ? "▾" : "▸"}
        </span>
      </button>

      {isExpanded ? (
        <div className="mt-2 space-y-2.5">
          <label className="block">
            <span className="font-medium text-amber-900">Session date</span>
            <input
              type="date"
              value={sessionDate}
              disabled={isLocked}
              onChange={(event) => onSessionDateChange(event.target.value)}
              className="mt-1 h-8 w-full rounded border border-amber-300 bg-white px-2 text-[11px] outline-none focus:border-amber-500 disabled:cursor-not-allowed disabled:bg-amber-100/70 disabled:text-amber-900/60"
            />
            {isLocked ? (
              <span className="mt-0.5 block text-amber-800">
                Locked — this conversation is dated{" "}
                <strong>{sessionDate || "today"}</strong>. A session is dated as a
                whole; close and reopen the panel to date a new one.
              </span>
            ) : (
              <span className="mt-0.5 block text-amber-800">
                Memories from this conversation are stored as if stated on this date. The
                time of day follows the real clock. Leave empty for today. Must be set{" "}
                <strong>before the first message</strong>.
              </span>
            )}
          </label>

          <label className="block">
            <span className="font-medium text-amber-900">Message retention</span>
            <select
              value={retentionSeconds === null ? "" : String(retentionSeconds)}
              disabled={isLocked}
              onChange={(event) =>
                onRetentionChange(
                  event.target.value === "" ? null : Number(event.target.value)
                )
              }
              className="mt-1 h-8 w-full rounded border border-amber-300 bg-white px-2 text-[11px] outline-none focus:border-amber-500 disabled:cursor-not-allowed disabled:bg-amber-100/70 disabled:text-amber-900/60"
            >
              {RETENTION_PRESETS.map((preset) => (
                <option
                  key={preset.label}
                  value={preset.seconds === null ? "" : String(preset.seconds)}
                >
                  {preset.label}
                </option>
              ))}
            </select>
            {isLocked ? (
              <span className="mt-0.5 block text-amber-800">
                Locked — this session is running with{" "}
                <strong>{describeRetentionInForce(retentionInForce, retentionSeconds)}</strong>.
                Retention is fixed when a session opens; close and reopen the panel to
                set a different one.
              </span>
            ) : (
              <span className="mt-0.5 block text-amber-800">
                Must be set <strong>before the first message</strong>. Facts never
                expire regardless, their own retention overrides the session&apos;s.
              </span>
            )}
          </label>
        </div>
      ) : null}
    </div>
  );
}
