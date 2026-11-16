"use client";

import { Download, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import type { ApiPrivacy } from "@/lib/api/types";
import { cn } from "@/lib/utils";

function Row({ title, body, control }: { title: ReactNode; body: ReactNode; control: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 py-4 first:pt-0 last:pb-0">
      <div className="max-w-xl">
        <div className="font-medium text-fg">{title}</div>
        <div className="text-sm text-fg-muted">{body}</div>
      </div>
      {control}
    </div>
  );
}

function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors disabled:opacity-50",
        checked ? "border-brand-400 bg-brand-500" : "border-line-strong bg-surface-raised",
      )}
    >
      <span
        className={cn(
          "inline-block size-4 rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-6" : "translate-x-1",
        )}
      />
    </button>
  );
}

/** Privacy controls (spec §34): training opt-out, daily sync, export, deletion. */
export function PrivacyControls({ initial, steamImport }: { initial: ApiPrivacy; steamImport: boolean }) {
  const router = useRouter();
  const [privacy, setPrivacy] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");
  const [deleting, setDeleting] = useState(false);

  async function update(change: Partial<Pick<ApiPrivacy, "contribute_to_global_training" | "allow_scheduled_sync">>) {
    const previous = privacy;
    setPrivacy({ ...privacy, ...change });
    setSaving(true);
    setError(null);
    try {
      const res = await fetch("/api/me/privacy", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(change),
      });
      if (!res.ok) throw new Error(String(res.status));
      setPrivacy((await res.json()) as ApiPrivacy);
    } catch {
      setPrivacy(previous);
      setError("Couldn't save that setting. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  async function deleteAccount() {
    setDeleting(true);
    setError(null);
    try {
      const res = await fetch("/api/me", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: "DELETE" }),
      });
      if (res.status !== 204) throw new Error(String(res.status));
      router.replace("/");
      router.refresh();
    } catch {
      setDeleting(false);
      setError("Couldn't delete your account. Nothing was removed; please try again.");
    }
  }

  return (
    <div className="divide-y divide-line">
      {steamImport ? (
        <Row
          title="Keep my library synced daily"
          body="We re-read your Steam library once a day while you use the site, to track playtime over time."
          control={
            <Switch
              checked={privacy.allow_scheduled_sync}
              onChange={(v) => update({ allow_scheduled_sync: v })}
              label="Keep my library synced daily"
              disabled={saving}
            />
          }
        />
      ) : null}
      <Row
        title="Help improve recommendations for everyone"
        body={
          <>
            Let your activity be used, under a one-off pseudonym, to train the shared model. Turn it
            off and your data is left out of every training run from the next one on. Your own
            recommendations keep working either way.
          </>
        }
        control={
          <Switch
            checked={privacy.contribute_to_global_training}
            onChange={(v) => update({ contribute_to_global_training: v })}
            label="Help improve recommendations for everyone"
            disabled={saving}
          />
        }
      />
      <Row
        title="Export my data"
        body="Download everything we store about you as a JSON file: library, playtime history, ratings, feedback, events and recommendations."
        control={
          <a href="/api/me/export" download className={buttonVariants({ variant: "secondary" })}>
            <Download aria-hidden="true" /> Export
          </a>
        }
      />
      <div className="py-4 last:pb-0">
        <Row
          title="Delete my account"
          body="Permanently removes your account and all personal data. This can't be undone."
          control={
            confirming ? null : (
              <Button variant="secondary" className="text-negative" onClick={() => setConfirming(true)}>
                <Trash2 aria-hidden="true" /> Delete
              </Button>
            )
          }
        />
        {confirming ? (
          <div className="mt-3 space-y-3 rounded-lg border border-negative/40 bg-negative/10 p-4 text-sm">
            <p className="text-fg">
              This deletes your profile, library, playtime history, ratings, feedback and
              recommendations right away. Shared models never stored rows about you; older model
              versions are replaced and deleted within 30 days.
            </p>
            <label className="block">
              <span className="text-fg-muted">Type DELETE to confirm</span>
              <input
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                autoComplete="off"
                className="mt-1 block h-9 w-48 rounded-lg border border-line bg-surface px-2.5 text-fg focus:border-negative focus:outline-none"
              />
            </label>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                className="text-negative"
                disabled={typed !== "DELETE" || deleting}
                onClick={deleteAccount}
              >
                {deleting ? "Deleting…" : "Delete my account"}
              </Button>
              <Button variant="ghost" onClick={() => { setConfirming(false); setTyped(""); }} disabled={deleting}>
                Cancel
              </Button>
            </div>
          </div>
        ) : null}
      </div>
      {error ? <p className="pt-3 text-sm text-negative" role="alert">{error}</p> : null}
    </div>
  );
}
