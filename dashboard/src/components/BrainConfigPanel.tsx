import { useState, useEffect } from "react";
import { client } from "../client";
import type { NodeConfig, ProviderInfo } from "../gen/omega/v1/types_pb";

interface Props {
  nodeId: string;
}

export default function BrainConfigPanel({ nodeId }: Props) {
  const [config, setConfig] = useState<NodeConfig | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState({
    provider: "",
    model: "",
    temperature: 0.7,
    maxTokens: 4096,
  });

  useEffect(() => {
    if (!nodeId) return;
    client
      .getNodeConfig({ nodeId })
      .then((r) => {
        setConfig(r.config ?? null);
        if (r.config?.brain) {
          const b = r.config.brain;
          setDraft({
            provider: b.provider,
            model: b.model,
            temperature: b.temperature,
            maxTokens: b.maxTokens,
          });
        }
      })
      .catch(console.error);
    client
      .listAvailableProviders({})
      .then((r) => setProviders(r.providers))
      .catch(console.error);
  }, [nodeId]);

  const currentProvider = providers.find((p) => p.id === draft.provider);

  async function save() {
    setSaving(true);
    try {
      const r = await client.updateNodeBrain({
        nodeId,
        brain: {
          provider: draft.provider,
          model: draft.model,
          temperature: draft.temperature,
          maxTokens: draft.maxTokens,
          systemPrompt: config?.brain?.systemPrompt ?? "",
          extraConfig: {},
        },
      });
      setConfig(r.config ?? null);
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  }

  if (!config) return <div className="text-gray-500 text-sm">Loading brain config…</div>;

  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-5 space-y-4">
      <h3 className="text-sm font-semibold text-white flex items-center gap-2">
        LLM Brain Config
      </h3>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-400 block mb-1">Provider</label>
          <select
            className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-sm text-white"
            value={draft.provider}
            onChange={(e) => setDraft({ ...draft, provider: e.target.value, model: "" })}
          >
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.displayName}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 block mb-1">Model</label>
          <select
            className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-sm text-white"
            value={draft.model}
            onChange={(e) => setDraft({ ...draft, model: e.target.value })}
          >
            {(currentProvider?.models ?? []).map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 block mb-1">Temperature</label>
          <input
            type="number"
            step="0.05"
            min="0"
            max="2"
            className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-sm text-white"
            value={draft.temperature}
            onChange={(e) => setDraft({ ...draft, temperature: parseFloat(e.target.value) })}
          />
        </div>
        <div>
          <label className="text-xs text-gray-400 block mb-1">Max Tokens</label>
          <input
            type="number"
            step="256"
            min="256"
            max="32000"
            className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-sm text-white"
            value={draft.maxTokens}
            onChange={(e) => setDraft({ ...draft, maxTokens: parseInt(e.target.value, 10) })}
          />
        </div>
      </div>
      <button
        onClick={save}
        disabled={saving}
        className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
      >
        {saving ? "Saving…" : "Apply Brain Config"}
      </button>
    </div>
  );
}
