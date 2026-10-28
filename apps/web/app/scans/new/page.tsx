import { NewScanForm } from "@/components/NewScanForm";

export const metadata = { title: "New scan" };

export default function NewScanPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">Queue a scan</h1>
        <p className="mt-1 text-sm text-[var(--cs-muted)]">
          Configure the target and analysis profile. Sandbox reproduction is a separate, approved
          action and is never triggered by a scan.
        </p>
      </header>

      <div className="rounded-lg border border-[var(--cs-border)] bg-[var(--cs-surface)] p-5">
        <NewScanForm />
      </div>
    </div>
  );
}
