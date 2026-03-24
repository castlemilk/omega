package main

import (
	"context"
	"fmt"
	"net/http"
	"strings"

	"connectrpc.com/connect"
	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/spf13/cobra"
)

var projectsCmd = &cobra.Command{
	Use:   "projects",
	Short: "Manage Omega projects",
}

var projectsListCmd = &cobra.Command{
	Use:   "list",
	Short: "List all registered projects",
	RunE:  projectsList,
}

var projectsShowCmd = &cobra.Command{
	Use:   "show <project-id>",
	Short: "Show full config for a project",
	Args:  cobra.ExactArgs(1),
	RunE:  projectsShow,
}

func init() {
	projectsCmd.AddCommand(projectsListCmd)
	projectsCmd.AddCommand(projectsShowCmd)
}

func newProjectClient() omegav1connect.ProjectServiceClient {
	return omegav1connect.NewProjectServiceClient(
		http.DefaultClient,
		getAPIURL(),
		connect.WithGRPC(),
	)
}

func projectsList(_ *cobra.Command, _ []string) error {
	client := newProjectClient()
	ctx := context.Background()

	resp, err := client.ListProjects(ctx, connect.NewRequest(&omegav1.ListProjectsRequest{}))
	if err != nil {
		return fmt.Errorf("ListProjects: %w", err)
	}

	projects := resp.Msg.Projects
	if len(projects) == 0 {
		fmt.Println("No projects registered.")
		return nil
	}

	fmt.Printf("%-20s  %-20s  %-16s  %-12s  %5s  %-8s\n",
		"ID", "NAME", "DOMAIN", "AUTONOMY", "STEPS", "STATUS")
	fmt.Println(strings.Repeat("-", 90))
	for _, p := range projects {
		fmt.Printf("%-20s  %-20s  %-16s  %-12s  %5d  %-8s\n",
			p.ProjectId, p.Name, p.Domain, p.AutonomyLevel, len(p.PipelineConfig), p.Status)
	}
	return nil
}

func projectsShow(_ *cobra.Command, args []string) error {
	client := newProjectClient()
	ctx := context.Background()

	resp, err := client.GetProject(ctx, connect.NewRequest(&omegav1.GetProjectRequest{ProjectId: args[0]}))
	if err != nil {
		return fmt.Errorf("GetProject: %w", err)
	}

	p := resp.Msg.Project
	fmt.Printf("=== Project: %s ===\n", p.Name)
	fmt.Printf("  ID:            %s\n", p.ProjectId)
	fmt.Printf("  Domain:        %s\n", p.Domain)
	fmt.Printf("  Status:        %s\n", p.Status)
	fmt.Printf("  Autonomy:      %s\n", p.AutonomyLevel)
	fmt.Printf("  Description:   %s\n", p.Description)

	if len(p.PipelineConfig) > 0 {
		fmt.Printf("\n  Pipeline steps (%d):\n", len(p.PipelineConfig))
		for _, s := range p.PipelineConfig {
			fmt.Printf("    [%2d] %-12s  %-22s  %s\n", s.Order, s.NodeType, s.Name, s.Description)
		}
	}

	if p.EvalConfig != nil {
		fmt.Printf("\n  Eval config:\n")
		fmt.Printf("    Metrics:    %v\n", p.EvalConfig.PrimaryMetrics)
		fmt.Printf("    Frequency:  %s\n", p.EvalConfig.EvalFrequency)
		if len(p.EvalConfig.MetricTargets) > 0 {
			fmt.Printf("    Targets:\n")
			for k, v := range p.EvalConfig.MetricTargets {
				fmt.Printf("      %-20s  %.4f\n", k, v)
			}
		}
	}

	if p.ImprovementConfig != nil {
		ic := p.ImprovementConfig
		fmt.Printf("\n  Improvement config:\n")
		fmt.Printf("    TPE:            enabled=%v  trials=%d\n", ic.TpeEnabled, ic.TpeTrials)
		fmt.Printf("    Adversarial:    enabled=%v  rounds=%d\n", ic.AdversarialEnabled, ic.AdversarialRounds)
		fmt.Printf("    Walk-forward:   enabled=%v\n", ic.WalkForwardEnabled)
	}

	if len(p.Metadata) > 0 {
		fmt.Printf("\n  Metadata:\n")
		for k, v := range p.Metadata {
			fmt.Printf("    %-16s  %s\n", k, v)
		}
	}

	return nil
}
