"use client";

import type {
  AgentRun,
  AgentToolCall,
  AgentToolCallStatus,
  AlertSeverity,
  CheckRun,
} from "./types";
import {
  CLEAN_DOT,
  SEVERITY_ORDER,
  SEVERITY_STYLES,
  highestSeverity,
  severityClasses,
} from "./severity";

type DetailsPanelProps = {
  /** The check run to show, or null when the pane is on something else. */
  checkRun: CheckRun | null;
  agentRun: AgentRun | null;
  onAcknowledge: () => void;
  onExit: () => void;
};

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

const TOOL_STATUS_STYLES: Record<AgentToolCallStatus, { label: string; className: string }> = {
  success: { label: "Success", className: "border-emerald-200 bg-emerald-50 text-emerald-800" },
  error: { label: "Error", className: "border-red-200 bg-red-50 text-red-700" },
  pending: { label: "No result", className: "border-amber-200 bg-amber-50 text-amber-800" },
};

/**
 * Tool results arrive as strings, but the Couchbase MCP tools mostly return
 * JSON. Re-indenting it when it parses makes query results readable; anything
 * else (plain prose, an error message) is shown untouched.
 */
function formatToolResult(result: string): string {
  const trimmed = result.trim();
  if (!trimmed) return "";
  if (!/^[[{]/.test(trimmed)) return result;

  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2);
  } catch {
    return result;
  }
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <p className="text-xs font-medium uppercase tracking-wide text-black/45">{children}</p>;
}

/**
 * What the agent concluded from one tool call. Only a check run carries this —
 * a chat reply's trace has no verdicts, so the section is left out entirely
 * there rather than repeating "No findings." down the whole trace.
 */
function CallVerdict({ call }: { call: AgentToolCall }) {
  const finding = call.finding?.trim();
  const recommendation = call.recommendation?.trim();

  return (
    <div className="mt-3 space-y-3">
      <div>
        <SectionLabel>Finding</SectionLabel>
        <p className="mt-1.5 text-sm leading-6 text-black/75">
          {finding || <span className="italic text-black/45">No findings.</span>}
        </p>
      </div>

      {recommendation ? (
        <div className="rounded-lg border border-teal-100 bg-teal-50/60 p-3">
          <SectionLabel>Recommendation</SectionLabel>
          <p className="mt-1.5 text-sm leading-6 text-black/75">{recommendation}</p>
        </div>
      ) : null}
    </div>
  );
}

function ToolCallCard({
  call,
  index,
  showVerdicts,
}: {
  call: AgentToolCall;
  index: number;
  showVerdicts: boolean;
}) {
  const status = TOOL_STATUS_STYLES[call.status] ?? TOOL_STATUS_STYLES.pending;
  const severity = call.severity ?? null;
  const severityStyle = severity ? SEVERITY_STYLES[severity] : null;
  const args = JSON.stringify(call.args ?? {}, null, 2);
  const hasArgs = Boolean(call.args) && Object.keys(call.args).length > 0;
  const result = formatToolResult(call.result);

  return (
    <li className="min-w-0 rounded-xl border border-violet-100 bg-violet-50/30 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-sm font-semibold text-black">
          <span className="mr-2 text-black/40">{index + 1}.</span>
          {call.name}
        </p>
        <span className="flex flex-none items-center gap-1.5">
          {severityStyle ? (
            <span
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${severityStyle.border} ${severityStyle.badgeBg} ${severityStyle.badgeText}`}
            >
              <span
                aria-hidden
                className="h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: severityStyle.dot }}
              />
              {severityStyle.label}
            </span>
          ) : null}
          <span
            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${status.className}`}
          >
            {status.label}
          </span>
        </span>
      </div>

      {showVerdicts ? <CallVerdict call={call} /> : null}

      {hasArgs ? (
        <div className="mt-3">
          <SectionLabel>Arguments</SectionLabel>
          <pre className="mt-1.5 max-h-48 overflow-auto rounded-lg bg-white p-3 text-xs leading-5 text-black/75">
            <code>{args}</code>
          </pre>
        </div>
      ) : null}

      <div className="mt-3">
        <SectionLabel>Response</SectionLabel>
        {result ? (
          <pre className="mt-1.5 max-h-64 overflow-auto rounded-lg bg-neutral-900 p-3 text-xs leading-5 text-violet-100">
            <code>{result}</code>
          </pre>
        ) : (
          <p className="mt-1.5 text-sm italic text-black/45">
            The tool returned no result for this call.
          </p>
        )}
      </div>
    </li>
  );
}

/**
 * The Couchbase MCP tool calls behind a run, shown the same way whether the run
 * was a chat reply ("Show details") or the cluster check that raised an alert.
 * Only a check run has verdicts to show, so `showVerdicts` gates them.
 */
function ToolCallTrace({
  toolCalls,
  showVerdicts,
}: {
  toolCalls: AgentToolCall[];
  showVerdicts: boolean;
}) {
  // Distinct tool names, in the order the agent first reached for each, with a
  // count so a tool called repeatedly reads as one entry rather than several —
  // and the worst severity across its calls, which is what colors the bubble.
  const toolUsage = toolCalls.reduce<
    Array<{ name: string; count: number; severities: Array<AlertSeverity | null> }>
  >((acc, call) => {
    const existing = acc.find((entry) => entry.name === call.name);
    if (existing) {
      existing.count += 1;
      existing.severities.push(call.severity ?? null);
    } else {
      acc.push({ name: call.name, count: 1, severities: [call.severity ?? null] });
    }
    return acc;
  }, []);

  if (toolCalls.length === 0) return null;

  return (
    <>
      <section className="mt-6">
        <p className="text-sm font-medium text-black/75">Tools used</p>
        <p className="mt-1 text-xs text-black/40">
          {`${toolCalls.length} tool call${toolCalls.length === 1 ? "" : "s"}`}
        </p>
        <ul className="mt-2 flex flex-wrap gap-2">
          {toolUsage.map(({ name, count, severities }) => {
            const severity = highestSeverity(severities);
            return (
              <li
                key={name}
                title={severity ? `${SEVERITY_STYLES[severity].label} finding` : undefined}
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-xs ${severityClasses(severity)}`}
              >
                {severity ? (
                  <span
                    aria-hidden
                    className="h-1.5 w-1.5 flex-none rounded-full"
                    style={{ backgroundColor: SEVERITY_STYLES[severity].dot }}
                  />
                ) : null}
                {name}
                {count > 1 ? <span className="opacity-60">×{count}</span> : null}
                {/* Color alone never carries the severity. */}
                {severity ? (
                  <span className="sr-only">{`${SEVERITY_STYLES[severity].label} finding`}</span>
                ) : null}
              </li>
            );
          })}
        </ul>
      </section>

      <section className="mt-6">
        <p className="text-sm font-medium text-black/75">Tool calls</p>
        <ol className="mt-2 space-y-3">
          {toolCalls.map((call, index) => (
            <ToolCallCard
              key={`${call.name}-${index}`}
              call={call}
              index={index}
              showVerdicts={showVerdicts}
            />
          ))}
        </ol>
      </section>
    </>
  );
}

function AgentRunView({ run }: { run: AgentRun }) {
  return (
    <div className="min-w-0 flex-1 overflow-y-auto p-6 pt-2">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-violet-700">Agent Run</p>

      <h1 className="mt-2 text-xl font-semibold text-black">Question: {run.query}</h1>

      <ToolCallTrace toolCalls={run.toolCalls} showVerdicts={false} />

      <section className="mt-6">
        <p className="text-sm font-medium text-black/75">Final answer</p>
        <div className="mt-2 whitespace-pre-wrap rounded-xl border border-violet-100 bg-white p-4 text-sm leading-5 text-black/75">
          {run.answer}
        </div>
      </section>
    </div>
  );
}

/**
 * One check run: what the agent made of the cluster overall, then the trace,
 * with the finding and recommendation it wrote against each tool call.
 */
function CheckRunView({ run, onAcknowledge }: { run: CheckRun; onAcknowledge: () => void }) {
  const raised = SEVERITY_ORDER.filter((severity) => run.counts[severity] > 0);
  const worst = highestSeverity(raised);

  return (
    <div className="min-w-0 flex-1 overflow-y-auto p-6 pt-2">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-violet-700">
            Cluster Check
          </p>
          <h1 className="mt-2 text-xl font-semibold text-black">
            {`${run.toolCalls.length} tool${run.toolCalls.length === 1 ? "" : "s"} run`}
            {raised.length === 0 ? " · no findings" : ""}
          </h1>
          <p className="mt-1 text-sm text-black/50">{formatTimestamp(run.timestamp)}</p>
        </div>
        <button
          type="button"
          onClick={onAcknowledge}
          className="inline-flex h-9 flex-none items-center rounded-full border border-violet-200 px-4 text-xs font-semibold text-violet-800 transition-colors hover:bg-violet-50"
        >
          Acknowledge
        </button>
      </div>

      <ul className="mt-4 flex flex-wrap gap-2">
        {raised.length === 0 ? (
          <li className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: CLEAN_DOT }} />
            Nothing to report
          </li>
        ) : (
          raised.map((severity) => {
            const style = SEVERITY_STYLES[severity];
            return (
              <li
                key={severity}
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${style.border} ${style.badgeBg} ${style.badgeText}`}
              >
                <span
                  aria-hidden
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ backgroundColor: style.dot }}
                />
                {run.counts[severity]} {style.label.toLowerCase()}
              </li>
            );
          })
        )}
      </ul>

      {run.summary ? (
        <p
          className={`mt-5 rounded-xl border p-4 text-sm leading-6 text-black/75 ${
            worst ? SEVERITY_STYLES[worst].border : "border-violet-100"
          } bg-white`}
        >
          {run.summary}
        </p>
      ) : null}

      <ToolCallTrace toolCalls={run.toolCalls} showVerdicts />
    </div>
  );
}

function ClusterOverview() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-8 text-center">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-violet-700">Details Overview</p>
      <p className="mt-3 max-w-md text-sm text-black/60">
        Trigger the checks and select the run on the left to see what the agent found, or open
        &ldquo;Show details&rdquo; on a chat reply to inspect the tools it called through the
        Couchbase MCP server.
      </p>
    </div>
  );
}

export default function DetailsPanel({
  checkRun,
  agentRun,
  onAcknowledge,
  onExit,
}: DetailsPanelProps) {
  return (
    <section className="flex h-full min-w-0 flex-col overflow-hidden rounded-2xl border border-violet-100 bg-white shadow-[0_10px_30px_rgba(17,17,17,0.06)]">
      {/* A static bar, not the scrollable content below, so these controls
          never end up overlaid on top of content scrolled underneath them. */}
      <div className="flex flex-none items-start justify-end gap-3 px-4 pt-3">
        <a
          href="https://mcp-server.couchbase.com/tools"
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1.5 flex items-center gap-1 text-[11px] text-black/40 underline underline-offset-2 hover:text-violet-700"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden
            className="h-3.5 w-3.5 flex-none"
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
          Docs: Couchbase MCP Server Tools
        </a>
        <button
          type="button"
          onClick={onExit}
          aria-label="Close and reset the dashboard"
          className="-mr-1 -mt-1 inline-flex h-8 w-8 flex-none items-center justify-center rounded-full text-black/45 transition-colors hover:bg-violet-50 hover:text-black"
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
      </div>

      {agentRun ? (
        <AgentRunView run={agentRun} />
      ) : checkRun ? (
        <CheckRunView run={checkRun} onAcknowledge={onAcknowledge} />
      ) : (
        <ClusterOverview />
      )}
    </section>
  );
}
