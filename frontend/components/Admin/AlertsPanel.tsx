"use client";

import Spinner from "@/components/Spinner";
import type { CheckRun } from "./types";
import { CLEAN_DOT, SEVERITY_ORDER, SEVERITY_STYLES, highestSeverity } from "./severity";

type AlertsPanelProps = {
  checkRun: CheckRun | null;
  isSelected: boolean;
  onSelect: () => void;
  onTriggerChecks: () => void;
  isChecking: boolean;
  lastCheckedAt: Date | null;
  checkError: string | null;
};

function formatRelativeTime(iso: string): string {
  const deltaSeconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (deltaSeconds < 60) return "just now";
  const minutes = Math.round(deltaSeconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

/**
 * The latest check run, as one block. A run raises findings against individual
 * tool calls rather than as standalone alerts, so the list shows what the run
 * as a whole came back with and the details pane breaks it down per tool.
 */
function CheckRunRow({
  run,
  isSelected,
  onSelect,
}: {
  run: CheckRun;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const raised = SEVERITY_ORDER.filter((severity) => run.counts[severity] > 0);
  // The block is colored by the worst thing the run found, so a critical
  // finding is visible without opening it.
  const worst = highestSeverity(raised);

  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={isSelected}
        className={`flex w-full items-start gap-2.5 px-4 py-3 text-left transition-colors hover:bg-violet-100/70 ${
          isSelected ? "bg-violet-100" : ""
        }`}
      >
        <span
          aria-hidden
          className="mt-1.5 h-2 w-2 flex-none rounded-full"
          style={{ backgroundColor: worst ? SEVERITY_STYLES[worst].dot : CLEAN_DOT }}
        />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-2">
            <span className="text-sm font-medium text-black">Cluster check</span>
            <span className="flex-none text-xs text-black/50">
              {formatRelativeTime(run.timestamp)}
            </span>
          </span>

          <span className="mt-0.5 block text-xs text-black/55">
            {`${run.toolCalls.length} tool${run.toolCalls.length === 1 ? "" : "s"} run`}
            {raised.length === 0 ? " · no findings identified" : ""}
          </span>

          {raised.length > 0 ? (
            <span className="mt-2 flex flex-wrap gap-1.5">
              {raised.map((severity) => {
                const style = SEVERITY_STYLES[severity];
                return (
                  <span
                    key={severity}
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${style.border} ${style.badgeBg} ${style.badgeText}`}
                  >
                    <span
                      aria-hidden
                      className="h-1.5 w-1.5 rounded-full"
                      style={{ backgroundColor: style.dot }}
                    />
                    {run.counts[severity]} {style.label.toLowerCase()}
                  </span>
                );
              })}
            </span>
          ) : null}
        </span>
      </button>
    </li>
  );
}

export default function AlertsPanel({
  checkRun,
  isSelected,
  onSelect,
  onTriggerChecks,
  isChecking,
  lastCheckedAt,
  checkError,
}: AlertsPanelProps) {
  return (
    <section className="flex h-full flex-col rounded-2xl border border-violet-100 bg-violet-50">
      <header className="relative flex items-center justify-between gap-3 rounded-t-2xl border-b border-violet-100 px-4 py-3">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold tracking-wide text-black">Alerts
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
                  "When you trigger the Checks, the agent calls multiple Couchbase MCP Server tools to check different health and performance states, then follows its own findings up with further tool calls.\n\nThe run appears here as one block. Click it to see, per tool call, what the agent found and what it recommends."
                }
              </span>
            </span>
          </h2>
          <p className="text-xs text-black/55">
            {lastCheckedAt
              ? `Last checked ${formatRelativeTime(lastCheckedAt.toISOString())}`
              : "No checks run yet"}
          </p>
        </div>
        <button
          type="button"
          onClick={onTriggerChecks}
          disabled={isChecking}
          className="inline-flex h-9 flex-none items-center gap-2 rounded-full bg-teal-700 px-4 text-xs font-semibold text-white transition-colors hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isChecking ? <Spinner className="h-3.5 w-3.5" /> : null}
          {isChecking ? "Checking…" : "Trigger Checks"}
        </button>
      </header>

      <div className="flex-1 overflow-y-auto overflow-x-hidden rounded-b-2xl">
        {checkError ? (
          <p className="border-b border-red-100 bg-red-50 px-4 py-3 text-xs text-red-700">
            {checkError}
          </p>
        ) : null}

        {checkRun === null ? (
          <div className="flex h-full items-center justify-center px-4 py-6 text-center">
            <p className="text-sm text-black/40">No Alerts are identified</p>
          </div>
        ) : (
          <ul className="divide-y divide-violet-100">
            <CheckRunRow run={checkRun} isSelected={isSelected} onSelect={onSelect} />
          </ul>
        )}
      </div>
    </section>
  );
}
