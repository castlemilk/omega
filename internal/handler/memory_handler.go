package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/types/known/timestamppb"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/core"
	"github.com/benebsworth/omega/internal/db"
)

// Ensure interface satisfaction at compile time.
var _ omegav1connect.MemoryServiceHandler = (*MemoryHandler)(nil)

// MemoryHandler implements MemoryService — episodic, working, and semantic memory operations.
type MemoryHandler struct {
	kernel  *core.MemoryKernel
	nodesMu sync.RWMutex
	nodes   map[string]*core.NodeMemory
}

// NewMemory creates a MemoryHandler backed by the given DB.
// The memory kernel uses the memory SQLite database exposed via db.MemoryDB().
func NewMemory(database *db.DB) (*MemoryHandler, error) {
	kernel, err := core.NewMemoryKernel(database.MemoryDB())
	if err != nil {
		return nil, fmt.Errorf("init memory kernel: %w", err)
	}
	return &MemoryHandler{kernel: kernel, nodes: make(map[string]*core.NodeMemory)}, nil
}

// nodeMemory returns a cached NodeMemory for the given namespace.
// NodeMemory holds in-process working memory, so the same instance must be
// returned across calls within a handler's lifetime.
func (h *MemoryHandler) nodeMemory(ns string) *core.NodeMemory {
	h.nodesMu.RLock()
	nm, ok := h.nodes[ns]
	h.nodesMu.RUnlock()
	if ok {
		return nm
	}
	nm = h.kernel.GetNodeMemory(ns)
	h.nodesMu.Lock()
	h.nodes[ns] = nm
	h.nodesMu.Unlock()
	return nm
}

// ── StoreEpisode ──────────────────────────────────────────────────────────────

func (h *MemoryHandler) StoreEpisode(
	ctx context.Context,
	req *connect.Request[omegav1.StoreEpisodeRequest],
) (*connect.Response[omegav1.StoreEpisodeResponse], error) {
	// Convert map[string]string content → map[string]any
	content := make(map[string]any, len(req.Msg.Content))
	for k, v := range req.Msg.Content {
		content[k] = v
	}
	ep := core.Episode{
		Namespace:  req.Msg.Namespace,
		EventType:  req.Msg.EventType,
		Content:    content,
		Tags:       req.Msg.Tags,
		Importance: req.Msg.Importance,
		Cycle:      int(req.Msg.Cycle),
		Timestamp:  time.Now(),
	}
	id, err := h.kernel.StoreEpisode(ctx, ep)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.StoreEpisodeResponse{EpisodeId: id}), nil
}

// ── QueryEpisodes ─────────────────────────────────────────────────────────────

func (h *MemoryHandler) QueryEpisodes(
	ctx context.Context,
	req *connect.Request[omegav1.QueryEpisodesRequest],
) (*connect.Response[omegav1.QueryEpisodesResponse], error) {
	f := core.EpisodeFilter{
		Namespace: req.Msg.Namespace,
		Limit:     int(req.Msg.TopK),
	}
	if req.Msg.SignalType != "" {
		f.EventType = req.Msg.SignalType
	}

	episodes, err := h.kernel.RetrieveEpisodes(ctx, f)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	var results []*omegav1.ScoredEpisode
	for _, ep := range episodes {
		protoContent := make(map[string]string, len(ep.Content))
		for k, v := range ep.Content {
			protoContent[k] = fmt.Sprintf("%v", v)
		}
		results = append(results, &omegav1.ScoredEpisode{
			Score: ep.Importance,
			Episode: &omegav1.Episode{
				EpisodeId: ep.EpisodeID,
				Namespace: ep.Namespace,
				EventType: ep.EventType,
				Content:   protoContent,
				Tags:      ep.Tags,
				Importance: ep.Importance,
				Cycle:     int64(ep.Cycle),
				Timestamp: timestamppb.New(ep.Timestamp),
			},
		})
	}
	return connect.NewResponse(&omegav1.QueryEpisodesResponse{Results: results}), nil
}

// ── StoreWorking ──────────────────────────────────────────────────────────────

func (h *MemoryHandler) StoreWorking(
	ctx context.Context,
	req *connect.Request[omegav1.StoreWorkingRequest],
) (*connect.Response[omegav1.StoreWorkingResponse], error) {
	// Parse the JSON value
	var value any
	if err := json.Unmarshal([]byte(req.Msg.ValueJson), &value); err != nil {
		value = req.Msg.ValueJson // fall back to raw string
	}
	nm := h.nodeMemory(req.Msg.Namespace)
	ttl := time.Hour // default TTL
	if req.Msg.Ttl != nil {
		ttl = req.Msg.Ttl.AsDuration()
	}
	nm.Remember(req.Msg.Key, value, ttl)
	return connect.NewResponse(&omegav1.StoreWorkingResponse{Ok: true}), nil
}

// ── GetWorking ────────────────────────────────────────────────────────────────

func (h *MemoryHandler) GetWorking(
	ctx context.Context,
	req *connect.Request[omegav1.GetWorkingRequest],
) (*connect.Response[omegav1.GetWorkingResponse], error) {
	nm := h.nodeMemory(req.Msg.Namespace)
	val, found := nm.Recall(req.Msg.Key)
	if !found {
		return connect.NewResponse(&omegav1.GetWorkingResponse{Found: false}), nil
	}
	b, err := json.Marshal(val)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.GetWorkingResponse{
		ValueJson: string(b),
		Found:     true,
	}), nil
}

// ── DeleteWorking ─────────────────────────────────────────────────────────────

func (h *MemoryHandler) DeleteWorking(
	ctx context.Context,
	req *connect.Request[omegav1.DeleteWorkingRequest],
) (*connect.Response[omegav1.DeleteWorkingResponse], error) {
	nm := h.nodeMemory(req.Msg.Namespace)
	nm.ForgetWorking(req.Msg.Key)
	return connect.NewResponse(&omegav1.DeleteWorkingResponse{Ok: true}), nil
}

// ── TriggerConsolidation ──────────────────────────────────────────────────────

func (h *MemoryHandler) TriggerConsolidation(
	ctx context.Context,
	req *connect.Request[omegav1.TriggerConsolidationRequest],
) (*connect.Response[omegav1.TriggerConsolidationResponse], error) {
	newIDs, err := h.kernel.Consolidate(ctx, req.Msg.Namespace)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.TriggerConsolidationResponse{
		Result: &omegav1.ConsolidationResult{
			PromotedToSemantic: int32(len(newIDs)), //nolint:gosec
			NewConceptIds:      newIDs,
		},
	}), nil
}

// ── QuerySemantic ─────────────────────────────────────────────────────────────

func (h *MemoryHandler) QuerySemantic(
	ctx context.Context,
	req *connect.Request[omegav1.QuerySemanticRequest],
) (*connect.Response[omegav1.QuerySemanticResponse], error) {
	f := core.SemanticFilter{
		Namespace: req.Msg.Namespace,
		QueryText: req.Msg.TextQuery,
		Limit:     int(req.Msg.TopK),
	}
	if req.Msg.TagFilter != "" {
		f.Tags = []string{req.Msg.TagFilter}
	}

	memories, err := h.kernel.RetrieveSemantic(ctx, f)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	var concepts []*omegav1.MemoryConcept
	for _, sm := range memories {
		concepts = append(concepts, &omegav1.MemoryConcept{
			ConceptId:     sm.MemoryID,
			Namespace:     sm.Namespace,
			Concept:       sm.Concept,
			Content:       sm.Content,
			Confidence:    sm.Confidence,
			EvidenceCount: int64(sm.EvidenceCount), //nolint:gosec
			Tags:          sm.Tags,
			LastUpdated:   timestamppb.New(sm.LastReinforced),
		})
	}
	return connect.NewResponse(&omegav1.QuerySemanticResponse{Concepts: concepts}), nil
}

// ── BeginCycle ────────────────────────────────────────────────────────────────

func (h *MemoryHandler) BeginCycle(
	ctx context.Context,
	req *connect.Request[omegav1.BeginCycleRequest],
) (*connect.Response[omegav1.BeginCycleResponse], error) {
	if err := h.kernel.BeginCycle(ctx, int(req.Msg.Cycle)); err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	return connect.NewResponse(&omegav1.BeginCycleResponse{Ok: true}), nil
}

// ── EndCycle ──────────────────────────────────────────────────────────────────

func (h *MemoryHandler) EndCycle(
	ctx context.Context,
	req *connect.Request[omegav1.EndCycleRequest],
) (*connect.Response[omegav1.EndCycleResponse], error) {
	// Convert summary map[string]string → map[string]any
	summary := make(map[string]any, len(req.Msg.CycleSummary))
	for k, v := range req.Msg.CycleSummary {
		summary[k] = v
	}

	epID, err := h.kernel.EndCycle(ctx, int(req.Msg.Cycle), summary)
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	resp := &omegav1.EndCycleResponse{EpisodeId: epID}

	if req.Msg.TriggerConsolidation {
		newIDs, err := h.kernel.Consolidate(ctx, req.Msg.Namespace)
		if err == nil {
			resp.Consolidation = &omegav1.ConsolidationResult{
				PromotedToSemantic: int32(len(newIDs)), //nolint:gosec
				NewConceptIds:      newIDs,
			}
		}
	}

	return connect.NewResponse(resp), nil
}

// ── GetMemoryStats ────────────────────────────────────────────────────────────

func (h *MemoryHandler) GetMemoryStats(
	ctx context.Context,
	req *connect.Request[omegav1.MemoryNamespaceStatsRequest],
) (*connect.Response[omegav1.MemoryNamespaceStatsResponse], error) {
	summary := h.kernel.Summary(ctx)
	return connect.NewResponse(&omegav1.MemoryNamespaceStatsResponse{
		Namespace:     req.Msg.Namespace,
		EpisodicCount: int64(summary.EpisodicCount),  //nolint:gosec
		SemanticCount: int64(summary.SemanticCount),  //nolint:gosec
		WorkingCount:  int64(len(summary.WorkingMemoryKeys)), //nolint:gosec
	}), nil
}

// ── StreamMemoryEvents ────────────────────────────────────────────────────────

func (h *MemoryHandler) StreamMemoryEvents(
	ctx context.Context,
	req *connect.Request[omegav1.StreamMemoryEventsRequest],
	stream *connect.ServerStream[omegav1.MemoryLifecycleEvent],
) error {
	<-ctx.Done()
	return nil
}
