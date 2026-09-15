import { useEffect, useState } from "react";
import { ApiError } from "@/api/client";
import { useConfig, useConfigSchema, usePatchConfig } from "@/api/queries";
import { Panel, ProblemError, Skeleton, Badge } from "@/components/primitives";
import { LastUpdated } from "@/components/LastUpdated";

type SchemaProp = { type?: string; enum?: string[]; minimum?: number; maximum?: number };

export function ConfigView() {
  const cfg = useConfig();
  const schema = useConfigSchema();
  const patch = usePatchConfig();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [result, setResult] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    setDraft({});
    setFieldErrors({});
  }, [cfg.dataUpdatedAt]);

  if (cfg.isLoading || schema.isLoading) return <Skeleton rows={12} />;
  if (cfg.isError) return <ProblemError error={cfg.error} onRetry={() => cfg.refetch()} />;

  const eff = cfg.data!.effective;
  const props = (schema.data?.properties ?? {}) as Record<string, SchemaProp>;
  const scalarKeys = Object.entries(props).filter(
    ([, p]) => p.type === "integer" || p.type === "number" || p.enum,
  );
  const complex = ["scoring.weights", "scoring.label_bands"];

  function submit() {
    setResult(null);
    setFieldErrors({});
    const body: Record<string, unknown> = {};
    for (const [k, raw] of Object.entries(draft)) {
      if (raw === "") continue;
      const p = props[k];
      body[k] = p?.enum ? raw : Number(raw);
    }
    if (Object.keys(body).length === 0) return;
    patch.mutate(body, {
      onSuccess: (r) => setResult(`Updated ${r.updated.join(", ")} — ${r.effective_from}. New hash ${r.config_params_hash}.`),
      onError: (e) => {
        if (e instanceof ApiError && e.problem.errors) setFieldErrors(e.problem.errors);
        else setResult(e instanceof Error ? e.message : String(e));
      },
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="flex items-baseline gap-2 text-lg font-bold">
          Configuration
          <LastUpdated q={cfg} className="font-normal" />
        </h1>
        <Badge tone="muted">hash {cfg.data!.config_params_hash}</Badge>
      </div>
      <p className="text-sm text-slate-500">
        Edits are validated server-side and apply <b>from the next cycle</b>. The NSE session
        (09:15–15:30 IST) is fixed in V1.
      </p>

      <Panel title="Editable settings">
        <div className="grid gap-x-6 gap-y-2 md:grid-cols-2">
          {scalarKeys.map(([key, p]) => {
            const current = eff[key];
            return (
              <label key={key} className="flex flex-col text-sm">
                <span className="font-mono text-xs text-slate-500">{key}</span>
                {p.enum ? (
                  <select
                    value={draft[key] ?? String(current ?? "")}
                    onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                    className="rounded border border-slate-300 px-2 py-1"
                  >
                    {p.enum.map((o) => (
                      <option key={o}>{o}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="number"
                    step={p.type === "number" ? "0.01" : "1"}
                    min={p.minimum}
                    max={p.maximum}
                    placeholder={String(current ?? "")}
                    value={draft[key] ?? ""}
                    onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                    className="rounded border border-slate-300 px-2 py-1"
                  />
                )}
                {fieldErrors[key] && <span className="text-xs text-rose-600">{fieldErrors[key]}</span>}
              </label>
            );
          })}
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={submit}
            disabled={patch.isPending}
            className="rounded bg-slate-800 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {patch.isPending ? "saving…" : "Save changes"}
          </button>
          {result && <span className="text-sm text-emerald-700">{result}</span>}
        </div>
      </Panel>

      {complex.map((k) => (
        <Panel key={k} title={k} right={<Badge tone="muted">edit via API</Badge>}>
          <pre className="overflow-auto rounded bg-slate-50 p-2 text-xs">
            {JSON.stringify(eff[k], null, 2)}
          </pre>
        </Panel>
      ))}

      <Panel title="Effective config (all sections)" right={<Badge tone="muted">read-only</Badge>}>
        <pre className="max-h-[50vh] overflow-auto rounded bg-slate-50 p-2 text-xs">
          {JSON.stringify(cfg.data!.sections, null, 2)}
        </pre>
      </Panel>
    </div>
  );
}
