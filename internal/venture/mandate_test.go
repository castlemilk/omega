package venture

import (
	"strings"
	"testing"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
)

func TestReadAuthority(t *testing.T) {
	const started = "2026-11-23T01:00:00Z"
	resource := &v1.VentureResourceGrant{Role: "archive", Id: "edition", Sha256: strings.Repeat("a", 64)}
	inputs := []*v1.VentureResourceGrant{resource}
	base := &v1.VentureTaskMandate{
		RunId: "run", TenantId: "owner", AuthorizingActor: "actor", VentureId: "project", VentureRevision: 3,
		Principal: "inspector", Objective: "Check a file", Tools: []string{"read"}, Resources: inputs,
		IssuedAt: started, ExpiresAt: "2026-11-23T01:02:00Z", MaxTasks: 1,
		EffectPolicy: v1.VentureEffectPolicy_VENTURE_EFFECT_POLICY_READ_ONLY,
	}
	context := &v1.VentureTaskContext{TenantId: "owner", AuthorizingActor: "actor", VentureId: "project", VentureRevision: 3, CheckedAt: started}
	check := func(m *v1.VentureTaskMandate, c *v1.VentureTaskContext) error {
		return CheckRead(m, c, "inspector", "read", 2*time.Minute, inputs)
	}
	require.NoError(t, check(base, context))
	for name, change := range map[string]func(*v1.VentureTaskMandate, *v1.VentureTaskContext){
		"other tenant":      func(_ *v1.VentureTaskMandate, c *v1.VentureTaskContext) { c.TenantId = "other" },
		"other actor":       func(_ *v1.VentureTaskMandate, c *v1.VentureTaskContext) { c.AuthorizingActor = "other" },
		"other venture":     func(_ *v1.VentureTaskMandate, c *v1.VentureTaskContext) { c.VentureId = "other" },
		"changed venture":   func(_ *v1.VentureTaskMandate, c *v1.VentureTaskContext) { c.VentureRevision++ },
		"revoked":           func(_ *v1.VentureTaskMandate, c *v1.VentureTaskContext) { c.Revoked = true },
		"expired":           func(m *v1.VentureTaskMandate, c *v1.VentureTaskContext) { c.CheckedAt = m.ExpiresAt },
		"not issued":        func(m *v1.VentureTaskMandate, _ *v1.VentureTaskContext) { m.IssuedAt = "2026-11-23T01:00:01Z" },
		"extended deadline": func(m *v1.VentureTaskMandate, _ *v1.VentureTaskContext) { m.ExpiresAt = "2026-11-23T01:02:01Z" },
		"other principal":   func(m *v1.VentureTaskMandate, _ *v1.VentureTaskContext) { m.Principal = "other" },
		"additional tool":   func(m *v1.VentureTaskMandate, _ *v1.VentureTaskContext) { m.Tools = append(m.Tools, "another") },
		"additional task":   func(m *v1.VentureTaskMandate, _ *v1.VentureTaskContext) { m.MaxTasks++ },
		"delegate":          func(m *v1.VentureTaskMandate, _ *v1.VentureTaskContext) { m.MaxDelegationDepth++ },
		"model budget":      func(m *v1.VentureTaskMandate, _ *v1.VentureTaskContext) { m.ModelLimitUsdMicros++ },
		"tool budget":       func(m *v1.VentureTaskMandate, _ *v1.VentureTaskContext) { m.ToolLimitUsdMicros++ },
		"no policy":         func(m *v1.VentureTaskMandate, _ *v1.VentureTaskContext) { m.EffectPolicy = 0 },
		"missing resource":  func(m *v1.VentureTaskMandate, _ *v1.VentureTaskContext) { m.Resources = nil },
		"changed role":      func(m *v1.VentureTaskMandate, _ *v1.VentureTaskContext) { m.Resources[0].Role = "other" },
		"changed resource":  func(m *v1.VentureTaskMandate, _ *v1.VentureTaskContext) { m.Resources[0].Id = "other" },
		"changed version": func(m *v1.VentureTaskMandate, _ *v1.VentureTaskContext) {
			m.Resources[0].Sha256 = strings.Repeat("b", 64)
		},
		"invalid digest": func(m *v1.VentureTaskMandate, _ *v1.VentureTaskContext) { m.Resources[0].Sha256 = "abc" },
	} {
		t.Run(name, func(t *testing.T) {
			m, c := proto.CloneOf(base), proto.CloneOf(context)
			change(m, c)
			require.Error(t, check(m, c))
		})
	}
	duplicated := proto.CloneOf(base)
	duplicated.Resources = append(duplicated.Resources, resource)
	require.Error(t, CheckRead(duplicated, context, "inspector", "read", 2*time.Minute, duplicated.Resources))
}
