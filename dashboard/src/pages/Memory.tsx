import { useEffect, useState } from "react";
import { client } from "../client";
import type { Node, SemanticConcept, EpisodeEntry } from "../gen/omega/v1/types_pb";

export default function Memory() {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [concepts, setConcepts] = useState<SemanticConcept[]>([]);
  const [episodes, setEpisodes] = useState<EpisodeEntry[]>([]);
  const [counts, setCounts] = useState({ ep: 0, sem: 0 });

  useEffect(() => {
    client
      .listNodes({})
      .then((r) => setNodes(r.nodes))
      .catch(console.error);
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    client
      .getNodeMemory({ nodeId: selectedId })
      .then((r) => {
        setConcepts(r.topSemantic);
        setEpisodes(r.recentEpisodes);
        setCounts({ ep: Number(r.episodicCount), sem: Number(r.semanticCount) });
      })
      .catch(console.error);
  }, [selectedId]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <label className="text-sm text-gray-400">Node:</label>
        <select
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
          value={selectedId}
          onChange={(e) => setSelectedId(e.target.value)}
        >
          <option value="">— select a node —</option>
          {nodes.map((n) => (
            <option key={n.nodeId} value={n.nodeId}>
              {n.name}
            </option>
          ))}
        </select>
        {selectedId && (
          <span className="text-xs text-gray-500">
            {counts.ep} episodes · {counts.sem} semantic concepts
          </span>
        )}
      </div>

      {selectedId && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
            <h3 className="text-sm font-semibold text-gray-400 uppercase mb-3">
              Semantic Concepts
            </h3>
            <div className="space-y-2">
              {concepts.map((c, i) => (
                <div key={i} className="flex items-start gap-2">
                  <div className="flex-1">
                    <p className="text-sm text-white font-medium">{c.concept}</p>
                    <p className="text-xs text-gray-500 truncate">{c.content}</p>
                  </div>
                  <span className="text-xs text-indigo-400 shrink-0">
                    {(c.confidence * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
              {concepts.length === 0 && (
                <p className="text-gray-600 text-sm">No semantic concepts yet</p>
              )}
            </div>
          </div>
          <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
            <h3 className="text-sm font-semibold text-gray-400 uppercase mb-3">Recent Episodes</h3>
            <div className="space-y-2">
              {episodes.map((e) => (
                <div key={e.episodeId} className="border-l-2 border-indigo-500 pl-3 py-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-indigo-400">{e.eventType}</span>
                    <span className="text-xs text-gray-500">cycle {String(e.cycle)}</span>
                    <span className="text-xs text-gray-600">
                      {(e.importance * 100).toFixed(0)}% importance
                    </span>
                  </div>
                  {e.tags.length > 0 && (
                    <div className="flex gap-1 mt-1 flex-wrap">
                      {e.tags.map((t) => (
                        <span
                          key={t}
                          className="text-xs bg-gray-700 text-gray-400 px-1.5 py-0.5 rounded"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              {episodes.length === 0 && <p className="text-gray-600 text-sm">No episodes yet</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
