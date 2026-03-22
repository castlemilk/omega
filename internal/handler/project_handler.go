package handler

import (
	"context"
	"fmt"
	"sync"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/types/known/timestamppb"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
)

// ProjectHandler implements omegav1connect.ProjectServiceHandler with an
// in-memory store. All methods are safe for concurrent use.
type ProjectHandler struct {
	omegav1connect.UnimplementedProjectServiceHandler
	mu       sync.RWMutex
	projects map[string]*omegav1.Project
}

// NewProject creates a new in-memory ProjectHandler.
func NewProject() *ProjectHandler {
	return &ProjectHandler{
		projects: make(map[string]*omegav1.Project),
	}
}

// SeedProject adds a project to the store. Used for startup seeding.
func (h *ProjectHandler) SeedProject(p *omegav1.Project) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.projects[p.ProjectId] = p
}

func (h *ProjectHandler) CreateProject(
	_ context.Context, req *connect.Request[omegav1.CreateProjectRequest],
) (*connect.Response[omegav1.CreateProjectResponse], error) {
	now := timestamppb.Now()
	id := fmt.Sprintf("proj_%d", time.Now().UnixNano())
	p := &omegav1.Project{
		ProjectId:         id,
		Name:              req.Msg.Name,
		Description:       req.Msg.Description,
		Domain:            req.Msg.Domain,
		AutonomyLevel:     req.Msg.AutonomyLevel,
		Status:            "active",
		NodeIds:           req.Msg.NodeIds,
		PipelineConfig:    req.Msg.PipelineConfig,
		EvalConfig:        req.Msg.EvalConfig,
		ImprovementConfig: req.Msg.ImprovementConfig,
		Metadata:          req.Msg.Metadata,
		CreatedAt:         now,
		UpdatedAt:         now,
	}
	h.mu.Lock()
	h.projects[id] = p
	h.mu.Unlock()
	return connect.NewResponse(&omegav1.CreateProjectResponse{Project: p}), nil
}

func (h *ProjectHandler) GetProject(
	_ context.Context, req *connect.Request[omegav1.GetProjectRequest],
) (*connect.Response[omegav1.GetProjectResponse], error) {
	h.mu.RLock()
	p, ok := h.projects[req.Msg.ProjectId]
	h.mu.RUnlock()
	if !ok {
		return nil, connect.NewError(connect.CodeNotFound, fmt.Errorf("project %q not found", req.Msg.ProjectId))
	}
	return connect.NewResponse(&omegav1.GetProjectResponse{Project: p}), nil
}

func (h *ProjectHandler) ListProjects(
	_ context.Context, _ *connect.Request[omegav1.ListProjectsRequest],
) (*connect.Response[omegav1.ListProjectsResponse], error) {
	h.mu.RLock()
	out := make([]*omegav1.Project, 0, len(h.projects))
	for _, p := range h.projects {
		out = append(out, p)
	}
	h.mu.RUnlock()
	return connect.NewResponse(&omegav1.ListProjectsResponse{Projects: out}), nil
}

func (h *ProjectHandler) UpdateProject(
	_ context.Context, req *connect.Request[omegav1.UpdateProjectRequest],
) (*connect.Response[omegav1.UpdateProjectResponse], error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	p, ok := h.projects[req.Msg.ProjectId]
	if !ok {
		return nil, connect.NewError(connect.CodeNotFound, fmt.Errorf("project %q not found", req.Msg.ProjectId))
	}
	if req.Msg.Name != "" {
		p.Name = req.Msg.Name
	}
	if req.Msg.Description != "" {
		p.Description = req.Msg.Description
	}
	if req.Msg.Status != "" {
		p.Status = req.Msg.Status
	}
	if req.Msg.Domain != "" {
		p.Domain = req.Msg.Domain
	}
	if req.Msg.AutonomyLevel != "" {
		p.AutonomyLevel = req.Msg.AutonomyLevel
	}
	if len(req.Msg.PipelineConfig) > 0 {
		p.PipelineConfig = req.Msg.PipelineConfig
	}
	if req.Msg.EvalConfig != nil {
		p.EvalConfig = req.Msg.EvalConfig
	}
	if req.Msg.ImprovementConfig != nil {
		p.ImprovementConfig = req.Msg.ImprovementConfig
	}
	p.UpdatedAt = timestamppb.Now()
	return connect.NewResponse(&omegav1.UpdateProjectResponse{Project: p}), nil
}

func (h *ProjectHandler) DeleteProject(
	_ context.Context, req *connect.Request[omegav1.DeleteProjectRequest],
) (*connect.Response[omegav1.DeleteProjectResponse], error) {
	h.mu.Lock()
	_, ok := h.projects[req.Msg.ProjectId]
	if ok {
		delete(h.projects, req.Msg.ProjectId)
	}
	h.mu.Unlock()
	if !ok {
		return nil, connect.NewError(connect.CodeNotFound, fmt.Errorf("project %q not found", req.Msg.ProjectId))
	}
	return connect.NewResponse(&omegav1.DeleteProjectResponse{Success: true}), nil
}

func (h *ProjectHandler) AssignNodeToProject(
	_ context.Context, req *connect.Request[omegav1.AssignNodeToProjectRequest],
) (*connect.Response[omegav1.AssignNodeToProjectResponse], error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	p, ok := h.projects[req.Msg.ProjectId]
	if !ok {
		return nil, connect.NewError(connect.CodeNotFound, fmt.Errorf("project %q not found", req.Msg.ProjectId))
	}
	for _, id := range p.NodeIds {
		if id == req.Msg.NodeId {
			return connect.NewResponse(&omegav1.AssignNodeToProjectResponse{Project: p}), nil
		}
	}
	p.NodeIds = append(p.NodeIds, req.Msg.NodeId)
	p.UpdatedAt = timestamppb.Now()
	return connect.NewResponse(&omegav1.AssignNodeToProjectResponse{Project: p}), nil
}

func (h *ProjectHandler) RemoveNodeFromProject(
	_ context.Context, req *connect.Request[omegav1.RemoveNodeFromProjectRequest],
) (*connect.Response[omegav1.RemoveNodeFromProjectResponse], error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	p, ok := h.projects[req.Msg.ProjectId]
	if !ok {
		return nil, connect.NewError(connect.CodeNotFound, fmt.Errorf("project %q not found", req.Msg.ProjectId))
	}
	filtered := make([]string, 0, len(p.NodeIds))
	for _, id := range p.NodeIds {
		if id != req.Msg.NodeId {
			filtered = append(filtered, id)
		}
	}
	p.NodeIds = filtered
	p.UpdatedAt = timestamppb.Now()
	return connect.NewResponse(&omegav1.RemoveNodeFromProjectResponse{Project: p}), nil
}
