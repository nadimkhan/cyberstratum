import type { Finding, ScanSource } from "@/lib/types";

/**
 * The source that was analysed, with the lines the findings point at.
 *
 * A finding that says "tx.origin at line 17" is half a finding until
 * the reader can see line 17. The source is stored as a scan artifact,
 * and this puts the code beside the findings that name it.
 *
 * The panel says so in words when there is no source to show: a scan
 * made from runtime bytecode alone has none, and its findings still
 * stand.
 */
export function SourcePanel({
  source,
  findings,
}: {
  source: ScanSource | null;
  findings: Finding[];
}) {
  if (!source) return null;

  if (!source.available) {
    return (
      <section className="rounded-lg border border-[var(--cs-border)] bg-[var(--cs-card)] p-4">
        <h2 className="text-sm font-semibold text-[var(--cs-fg)]">Source</h2>
        <p className="mt-1 text-sm text-[var(--cs-muted)]">
          {source.reason ?? "No source was stored for this scan."}
        </p>
      </section>
    );
  }

  // The lines the findings name, grouped by the file they belong to.
  const linesByFile = new Map<string, Set<number>>();
  for (const finding of findings) {
    if (finding.sourceLine === null) continue;
    const key = finding.sourceFile ?? "";
    const lines = linesByFile.get(key) ?? new Set<number>();
    lines.add(finding.sourceLine);
    linesByFile.set(key, lines);
  }

  return (
    <section className="rounded-lg border border-[var(--cs-border)] bg-[var(--cs-card)] p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-[var(--cs-fg)]">Source</h2>
        <p className="text-xs text-[var(--cs-muted)]">
          {[
            source.language,
            source.compilerVersion ? `solc ${source.compilerVersion}` : null,
            source.verified === true ? "verified" : null,
            source.sourceUri,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>

      {source.files.map((file, index) => {
        const key = file.path ?? "";
        const marked = linesByFile.get(key) ?? new Set<number>();
        const lines = file.content.split("\n");
        return (
          <div key={`${file.path ?? "source"}-${index}`} className="mt-3">
            {file.path ? (
              <p className="text-xs font-medium text-[var(--cs-muted)]">{file.path}</p>
            ) : null}
            <pre className="mt-1 max-h-96 overflow-auto rounded border border-[var(--cs-border)] bg-[var(--cs-bg)] p-2 text-xs leading-5 text-[var(--cs-fg)]">
              {lines.map((line, lineIndex) => {
                const number = lineIndex + 1;
                const isMarked = marked.has(number);
                return (
                  <span
                    key={number}
                    className={
                      isMarked
                        ? "block bg-[var(--cs-accent)]/15 font-medium"
                        : "block"
                    }
                  >
                    <span className="mr-3 inline-block w-8 select-none text-right text-[var(--cs-muted)]">
                      {number}
                    </span>
                    {line}
                  </span>
                );
              })}
            </pre>
          </div>
        );
      })}
    </section>
  );
}
