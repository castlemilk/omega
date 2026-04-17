package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

// ---------------------------------------------------------------------------
// brain command tree
// ---------------------------------------------------------------------------

var brainCmd = &cobra.Command{
	Use:   "brain",
	Short: "Brain provider management and evaluation",
}

var brainEvalCmd = &cobra.Command{
	Use:   "eval",
	Short: "Run baseline prompts against all configured brain providers",
	Long: `Run a standardized set of trading/analysis prompts against every
configured brain provider, measuring response quality and latency.

Configured via environment:
  CLAUDE_API_KEY / ANTHROPIC_API_KEY  — Anthropic Claude
  OPENROUTER_API_KEY                  — OpenRouter gateway (GPT-4o, DeepSeek, ...)
  KIMI_API_KEY                        — Moonshot AI Kimi (OpenAI-compatible)

Example:
  omega brain eval
  omega brain eval --provider anthropic-haiku
  omega brain eval --json`,
	RunE: runBrainEval,
}

var (
	brainEvalProvider string
	brainEvalJSON     bool
	brainEvalPrompt   string
)

func init() {
	brainEvalCmd.Flags().StringVar(&brainEvalProvider, "provider", "", "Only test this provider name")
	brainEvalCmd.Flags().BoolVar(&brainEvalJSON, "json", false, "Output results as JSON")
	brainEvalCmd.Flags().StringVar(&brainEvalPrompt, "prompt", "", "Only run this prompt ID")
	brainCmd.AddCommand(brainEvalCmd)
}

// ---------------------------------------------------------------------------
// Eval prompts
// ---------------------------------------------------------------------------

type evalPrompt struct {
	ID               string   `json:"id"`
	Prompt           string   `json:"prompt"`
	ExpectedContains []string `json:"expected_contains"`
	Tier             string   `json:"tier"`
}

var evalPrompts = []evalPrompt{
	{
		ID: "signal_analysis",
		Prompt: "BTC order flow is bullish (+0.94), cross-asset correlation is bearish (-0.93), " +
			"sentiment is extreme fear (+0.15), VRP is neutral. " +
			"Should we go LONG, SHORT, or FLAT? " +
			"Answer with one word then a one-sentence reason.",
		ExpectedContains: []string{"LONG", "SHORT", "FLAT"},
		Tier:             "DEEP",
	},
	{
		ID: "market_regime",
		Prompt: "MVRV ratio is 1.59, Puell Multiple is 0.83, exchange netflow is -365 BTC, " +
			"taker buy/sell ratio is 0.89. What market regime are we in? " +
			"Answer: ACCUMULATION, DISTRIBUTION, EUPHORIA, or CAPITULATION. " +
			"One word then one sentence.",
		ExpectedContains: []string{"ACCUMULATION", "DISTRIBUTION", "EUPHORIA", "CAPITULATION"},
		Tier:             "QUICK",
	},
	{
		ID: "risk_assessment",
		Prompt: "Portfolio has 40% in BTCUSDT long and 35% in ETHUSDT long. " +
			"BTC dominance is 56.5% and rising. Is this concentration acceptable? " +
			"Answer YES or NO then one sentence.",
		ExpectedContains: []string{"YES", "NO"},
		Tier:             "QUICK",
	},
	{
		ID: "cycle_reflection",
		Prompt: "Cycle 50: 11 signals computed, quality score 0.896, top signal cross_asset (IC=0.93), " +
			"VRP regime NEUTRAL, composite direction bearish. What is the key lesson? One sentence.",
		ExpectedContains: nil,
		Tier:             "QUICK",
	},
	{
		ID: "weather_edge",
		Prompt: "GEFS ensemble: 25 of 31 members predict NYC temperature above 30C tomorrow. " +
			"Polymarket YES price is 0.65. Model probability is 0.806. Edge is 15.6%. " +
			"Kelly fraction is 0.80. Should we bet? Answer BET or SKIP then one sentence.",
		ExpectedContains: []string{"BET", "SKIP"},
		Tier:             "DEEP",
	},
}

// ---------------------------------------------------------------------------
// Provider definitions
// ---------------------------------------------------------------------------

type brainProvider struct {
	Name   string
	Type   string // anthropic | openrouter | openai_compat
	Model  string
	apiURL string
	apiKey string //nolint:gosec
	Tier   string
}

func loadBrainProviders(filterName string) []brainProvider {
	var providers []brainProvider

	// Resolve CLAUDE_API_KEY as Anthropic alias
	anthropicKey := os.Getenv("ANTHROPIC_API_KEY")
	if anthropicKey == "" {
		anthropicKey = os.Getenv("CLAUDE_API_KEY")
	}

	if anthropicKey != "" {
		providers = append(providers,
			brainProvider{
				Name:   "anthropic-haiku",
				Type:   "anthropic",
				Model:  "claude-haiku-4-5-20251001",
				apiURL: "https://api.anthropic.com/v1/messages",
				apiKey: anthropicKey,
				Tier:   "QUICK",
			},
			brainProvider{
				Name:   "anthropic-sonnet",
				Type:   "anthropic",
				Model:  "claude-sonnet-4-6",
				apiURL: "https://api.anthropic.com/v1/messages",
				apiKey: anthropicKey,
				Tier:   "DEEP",
			},
		)
	}

	if orKey := os.Getenv("OPENROUTER_API_KEY"); orKey != "" {
		orURL := "https://openrouter.ai/api/v1/chat/completions"
		providers = append(providers,
			brainProvider{
				Name:   "openrouter-gpt4o-mini",
				Type:   "openrouter",
				Model:  "openai/gpt-4o-mini",
				apiURL: orURL,
				apiKey: orKey,
				Tier:   "QUICK",
			},
			brainProvider{
				Name:   "openrouter-gpt4o",
				Type:   "openrouter",
				Model:  "openai/gpt-4o",
				apiURL: orURL,
				apiKey: orKey,
				Tier:   "DEEP",
			},
			brainProvider{
				Name:   "openrouter-deepseek-chat",
				Type:   "openrouter",
				Model:  "deepseek/deepseek-chat",
				apiURL: orURL,
				apiKey: orKey,
				Tier:   "QUICK",
			},
		)
	}

	if kimiKey := os.Getenv("KIMI_API_KEY"); kimiKey != "" {
		providers = append(providers, brainProvider{
			Name:   "kimi-moonshot-v1-8k",
			Type:   "openai_compat",
			Model:  "moonshot-v1-8k",
			apiURL: "https://api.moonshot.cn/v1/chat/completions",
			apiKey: kimiKey,
			Tier:   "QUICK",
		})
	}

	if filterName != "" {
		var filtered []brainProvider
		for _, p := range providers {
			if p.Name == filterName {
				filtered = append(filtered, p)
			}
		}
		return filtered
	}
	return providers
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

var httpClient = &http.Client{Timeout: 45 * time.Second}

func callAnthropic(p brainProvider, prompt string) (string, time.Duration, error) {
	body, _ := json.Marshal(map[string]any{
		"model":      p.Model,
		"max_tokens": 200,
		"messages":   []map[string]string{{"role": "user", "content": prompt}},
	})
	req, _ := http.NewRequest("POST", p.apiURL, bytes.NewReader(body)) //nolint:gosec
	req.Header.Set("x-api-key", p.apiKey)
	req.Header.Set("anthropic-version", "2023-06-01")
	req.Header.Set("content-type", "application/json")

	t0 := time.Now()
	resp, err := httpClient.Do(req) //nolint:gosec
	latency := time.Since(t0)
	if err != nil {
		return "", latency, err
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return "", latency, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(raw))
	}

	var out struct {
		Content []struct {
			Text string `json:"text"`
		} `json:"content"`
	}
	if err := json.Unmarshal(raw, &out); err != nil {
		return "", latency, err
	}
	if len(out.Content) == 0 {
		return "", latency, fmt.Errorf("empty content")
	}
	return out.Content[0].Text, latency, nil
}

func callOpenAICompat(p brainProvider, prompt string) (string, time.Duration, error) {
	body, _ := json.Marshal(map[string]any{
		"model":      p.Model,
		"max_tokens": 200,
		"messages":   []map[string]string{{"role": "user", "content": prompt}},
	})
	req, _ := http.NewRequest("POST", p.apiURL, bytes.NewReader(body)) //nolint:gosec
	req.Header.Set("Authorization", "Bearer "+p.apiKey)
	req.Header.Set("Content-Type", "application/json")

	t0 := time.Now()
	resp, err := httpClient.Do(req) //nolint:gosec
	latency := time.Since(t0)
	if err != nil {
		return "", latency, err
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return "", latency, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(raw))
	}

	var out struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.Unmarshal(raw, &out); err != nil {
		return "", latency, err
	}
	if len(out.Choices) == 0 {
		return "", latency, fmt.Errorf("empty choices")
	}
	return out.Choices[0].Message.Content, latency, nil
}

func runProviderEval(p brainProvider, prompt string) (string, time.Duration, error) {
	switch p.Type {
	case "anthropic":
		return callAnthropic(p, prompt)
	case "openrouter", "openai_compat":
		return callOpenAICompat(p, prompt)
	default:
		return "", 0, fmt.Errorf("unknown provider type: %s", p.Type)
	}
}

// ---------------------------------------------------------------------------
// Scoring
// ---------------------------------------------------------------------------

func scoreResponse(response string, expected []string) float64 {
	if len(response) < 5 {
		return 0.0
	}
	if len(expected) == 0 {
		if len(response) > 10 {
			return 1.0
		}
		return 0.5
	}
	upper := strings.ToUpper(response)
	for _, kw := range expected {
		if strings.Contains(upper, strings.ToUpper(kw)) {
			return 1.0
		}
	}
	return 0.5
}

// ---------------------------------------------------------------------------
// Result types
// ---------------------------------------------------------------------------

type evalResult struct {
	PromptID        string  `json:"prompt_id"`
	Score           float64 `json:"score"`
	LatencyMS       int64   `json:"latency_ms"`
	ResponsePreview string  `json:"response_preview,omitempty"`
	Error           string  `json:"error,omitempty"`
}

type providerResult struct {
	Name          string       `json:"name"`
	Type          string       `json:"type"`
	Model         string       `json:"model"`
	Evals         []evalResult `json:"evals"`
	AvgScore      float64      `json:"avg_score"`
	AvgLatencyMS  int64        `json:"avg_latency_ms"`
}

// ---------------------------------------------------------------------------
// Command entry point
// ---------------------------------------------------------------------------

func runBrainEval(cmd *cobra.Command, _ []string) error {
	// Load .env from project root (best-effort)
	loadDotEnv()

	providers := loadBrainProviders(brainEvalProvider)
	if len(providers) == 0 {
		return fmt.Errorf("no brain providers available — configure CLAUDE_API_KEY, OPENROUTER_API_KEY, or KIMI_API_KEY")
	}

	prompts := evalPrompts
	if brainEvalPrompt != "" {
		var filtered []evalPrompt
		for _, p := range evalPrompts {
			if p.ID == brainEvalPrompt {
				filtered = append(filtered, p)
			}
		}
		prompts = filtered
	}

	if !brainEvalJSON {
		fmt.Printf("Brain Provider Eval — %d providers, %d prompts\n", len(providers), len(prompts))
		fmt.Println(strings.Repeat("=", 80))
	}

	allResults := make([]providerResult, 0, len(providers))

	for _, prov := range providers {
		if !brainEvalJSON {
			fmt.Printf("\n--- %s (%s, %s) ---\n", prov.Name, prov.Type, prov.Model)
		}

		pr := providerResult{
			Name:  prov.Name,
			Type:  prov.Type,
			Model: prov.Model,
		}

		for _, ep := range prompts {
			if !brainEvalJSON {
				fmt.Printf("  %-20s: ", ep.ID)
			}

			text, latency, err := runProviderEval(prov, ep.Prompt)
			ms := latency.Milliseconds()

			if err != nil {
				if !brainEvalJSON {
					fmt.Printf("ERROR: %v\n", err)
				}
				pr.Evals = append(pr.Evals, evalResult{
					PromptID: ep.ID, Score: 0, LatencyMS: ms, Error: err.Error(),
				})
				continue
			}

			score := scoreResponse(text, ep.ExpectedContains)
			preview := text
			if len(preview) > 80 {
				preview = preview[:80]
			}
			preview = strings.ReplaceAll(preview, "\n", " ")

			if !brainEvalJSON {
				fmt.Printf("score=%.1f  latency=%dms  — %s\n", score, ms, preview)
			}

			rp := text
			if len(rp) > 200 {
				rp = rp[:200]
			}
			pr.Evals = append(pr.Evals, evalResult{
				PromptID: ep.ID, Score: score, LatencyMS: ms, ResponsePreview: rp,
			})
		}

		// Aggregate
		var totalScore float64
		var totalMS, msCount int64
		for _, e := range pr.Evals {
			totalScore += e.Score
			if e.LatencyMS > 0 {
				totalMS += e.LatencyMS
				msCount++
			}
		}
		if n := int64(len(pr.Evals)); n > 0 {
			pr.AvgScore = totalScore / float64(n)
		}
		if msCount > 0 {
			pr.AvgLatencyMS = totalMS / msCount
		}
		allResults = append(allResults, pr)
	}

	if brainEvalJSON {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		return enc.Encode(map[string]any{"providers": allResults, "prompts": prompts})
	}

	// Summary table
	fmt.Println("\n" + strings.Repeat("=", 80))
	fmt.Println("SUMMARY")
	fmt.Printf("%-30s %-30s %7s %10s %6s\n", "Provider", "Model", "Score", "Latency", "Evals")
	fmt.Println(strings.Repeat("-", 87))

	sort.Slice(allResults, func(i, j int) bool {
		return allResults[i].AvgScore > allResults[j].AvgScore
	})
	for _, r := range allResults {
		fmt.Printf("%-30s %-30s %7.2f %8dms %6d\n",
			r.Name, r.Model, r.AvgScore, r.AvgLatencyMS, len(r.Evals))
	}

	// Save results
	if err := os.MkdirAll("data", 0o750); err == nil { //nolint:gosec
		out, _ := json.MarshalIndent(map[string]any{
			"timestamp": time.Now().UTC().Format(time.RFC3339),
			"providers": allResults,
			"prompts":   prompts,
		}, "", "  ")
		path := "data/brain_eval_results.json"
		if err := os.WriteFile(path, out, 0o600); err == nil { //nolint:gosec
			fmt.Printf("\nSaved → %s\n", path)
		}
	}

	return nil
}

// loadDotEnv reads PROJECT_ROOT/.env (best-effort, no overwrite of existing vars).
func loadDotEnv() {
	// Walk up from cwd to find .env
	dir, _ := os.Getwd()
	for i := 0; i < 5; i++ {
		path := dir + "/.env"
		data, err := os.ReadFile(path) //nolint:gosec
		if err == nil {
			for _, line := range strings.Split(string(data), "\n") {
				line = strings.TrimSpace(line)
				if line == "" || strings.HasPrefix(line, "#") {
					continue
				}
				k, v, found := strings.Cut(line, "=")
				if !found {
					continue
				}
				k = strings.TrimSpace(k)
				v = strings.Trim(strings.TrimSpace(v), `"'`)
				if os.Getenv(k) == "" {
					_ = os.Setenv(k, v)
				}
			}
			break
		}
		parent := dir[:strings.LastIndexByte(dir, '/')]
		if parent == dir {
			break
		}
		dir = parent
	}

	// Alias CLAUDE_API_KEY → ANTHROPIC_API_KEY
	if os.Getenv("ANTHROPIC_API_KEY") == "" {
		if v := os.Getenv("CLAUDE_API_KEY"); v != "" {
			_ = os.Setenv("ANTHROPIC_API_KEY", v)
		}
	}
}
