import { formatDuration } from "@/lib/format";
import { STAGE_STATUS_META } from "@/lib/status";
import type { ScanStage } from "@/lib/types";

export interface StageTimelineProps {
  stages: readonly ScanStage[];
}

/** Ordered pipeline stepper for a scan (design document page 7). */
export function StageTimeline({ stages }: StageTimelineProps) {
  if (stages.length === 0) {
    return (
      <p className="text-sm text-[var(--cs-muted)]">
        The backend did not report any pipeline stages for this scan.
      </p>
    );
  }

  return (
    <ol className="space-y-2" aria-label="Scan pipeline stages">
      {stages.map((stage, index) => {
        const meta = STAGE_STATUS_META[stage.status];
        return (
          <li key={stage.key} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span
                aria-hidden="true"
                className={`mt-1.5 h-3 w-3 shrink-0 rounded-full ${meta.dot}`}
              />
              {index < stages.length - 1 ? (
                <span aria-hidden="true" className="w-px flex-1 bg-[var(--cs-border)]" />
              ) : null}
            </div>
            <div className="flex-1 pb-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-[var(--cs-fg)]">{stage.label}</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${meta.badge}`}
                >
                  {meta.label}
                </span>
                {stage.durationMs !== null ? (
                  <span className="font-mono text-xs text-[var(--cs-muted)]">
                    {formatDuration(stage.durationMs)}
                  </span>
                ) : null}
                {stage.version ? (
                  <span className="font-mono text-xs text-[var(--cs-muted)]">v{stage.version}</span>
                ) : null}
              </div>
              {stage.message ? (
                <p className="mt-1 text-xs text-[var(--cs-muted)]">{stage.message}</p>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
