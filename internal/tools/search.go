package tools

import (
	"context"
	"math"
	"strings"
)

// ---------------------------------------------------------------------------
// TF-IDF-like scoring
// ---------------------------------------------------------------------------

// tokenise splits text into lowercase tokens, stripping punctuation.
func tokenise(text string) []string {
	text = strings.ToLower(text)
	// Replace common punctuation with spaces.
	replacer := strings.NewReplacer("_", " ", "-", " ", ".", " ", ",", " ", ":", " ", "(", " ", ")", " ")
	text = replacer.Replace(text)
	raw := strings.Fields(text)
	tokens := make([]string, 0, len(raw))
	for _, tok := range raw {
		if tok != "" {
			tokens = append(tokens, tok)
		}
	}
	return tokens
}

// tf returns the term frequency of token t in a document's token list.
func tf(token string, tokens []string) float64 {
	if len(tokens) == 0 {
		return 0
	}
	count := 0
	for _, tok := range tokens {
		if tok == token {
			count++
		}
	}
	return float64(count) / float64(len(tokens))
}

// idf returns the inverse document frequency of token t across all corpora.
// corpus is a slice of token lists (one per document).
func idf(token string, corpus [][]string) float64 {
	docsContaining := 0
	for _, doc := range corpus {
		for _, tok := range doc {
			if tok == token {
				docsContaining++
				break
			}
		}
	}
	if docsContaining == 0 {
		return 0
	}
	return math.Log(float64(len(corpus)+1) / float64(docsContaining+1))
}

// scoredTool pairs a tool with its relevance score.
type scoredTool struct {
	tool  Tool
	score float64
}

// scoreQuery ranks tools by TF-IDF relevance to the query tokens.
// Returns the top-n tools in descending score order.
func scoreQuery(query string, tools []Tool, topN int) []Tool {
	if len(tools) == 0 || query == "" {
		return nil
	}

	queryTokens := tokenise(query)
	if len(queryTokens) == 0 {
		return nil
	}

	// Build a corpus: name + description tokens per tool.
	corpus := make([][]string, len(tools))
	for i, t := range tools {
		corpus[i] = tokenise(t.Name() + " " + t.Description())
	}

	// Score each tool.
	// IDF can collapse to 0 when a token appears in every document (e.g. single-doc
	// corpus). Apply a minimum floor of 1.0 so TF always contributes to the score.
	scored := make([]scoredTool, 0, len(tools))
	for i, t := range tools {
		docTokens := corpus[i]
		total := 0.0
		for _, qt := range queryTokens {
			rawIDF := idf(qt, corpus)
			if rawIDF < 1.0 {
				rawIDF = 1.0
			}
			total += tf(qt, docTokens) * rawIDF
		}
		if total > 0 {
			scored = append(scored, scoredTool{tool: t, score: total})
		}
	}

	if len(scored) == 0 {
		return nil
	}

	// Sort descending by score (insertion sort; tool counts are small).
	for i := 1; i < len(scored); i++ {
		for j := i; j > 0 && scored[j].score > scored[j-1].score; j-- {
			scored[j], scored[j-1] = scored[j-1], scored[j]
		}
	}

	if topN > len(scored) {
		topN = len(scored)
	}
	result := make([]Tool, topN)
	for i := range result {
		result[i] = scored[i].tool
	}
	return result
}

// ---------------------------------------------------------------------------
// ToolSearchTool — the meta-tool that drives deferred discovery
// ---------------------------------------------------------------------------

// ToolSearchTool is always registered in the active pool. When the LLM calls
// it, it searches the deferred registry and activates the top matches.
//
// This is the entry point for DeerFlow-style deferred tool discovery: the LLM
// only sees a single "search tools" entry in its active context; the full
// catalogue stays hidden until requested.
type ToolSearchTool struct {
	registry *Registry
}

// NewToolSearchTool constructs the meta-tool bound to the given registry.
func NewToolSearchTool(reg *Registry) *ToolSearchTool {
	return &ToolSearchTool{registry: reg}
}

func (t *ToolSearchTool) Name() string { return "tool_search" }

func (t *ToolSearchTool) Description() string {
	return "Search and activate tools from the deferred registry by keyword query. " +
		"Use this when a required capability is not in the active tool list."
}

func (t *ToolSearchTool) Schema() ToolSchema {
	return ToolSchema{
		Name:        t.Name(),
		Description: t.Description(),
		Parameters: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"query": map[string]any{
					"type":        "string",
					"description": "Keywords describing the capability you need",
				},
				"max_results": map[string]any{
					"type":        "integer",
					"description": "Maximum number of tools to activate (default 5)",
					"default":     5,
				},
			},
			"required": []string{"query"},
		},
		RequiredAutonomyLevel: 0, // always available
	}
}

// Execute searches the deferred registry and returns activated tool schemas.
//
// args:
//   - "query"       string  (required) — keyword search string
//   - "max_results" int     (optional) — cap on results, default 5
func (t *ToolSearchTool) Execute(_ context.Context, args map[string]any) (ToolResult, error) {
	query, _ := args["query"].(string)
	if query == "" {
		return ToolResult{IsError: true, Content: "query argument is required"}, nil
	}

	maxResults := 5
	if mr, ok := args["max_results"].(int); ok && mr > 0 {
		maxResults = mr
	}

	schemas := t.registry.Search(query, maxResults)
	return ToolResult{Content: schemas}, nil
}
