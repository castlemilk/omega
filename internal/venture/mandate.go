// Package venture checks the authority of a private venture task. The caller
// supplies the authenticated context and the immutable resources it actually
// resolved. A project adapter supplies the registered principal and tool.
package venture

import (
	"encoding/hex"
	"errors"
	"slices"
	"strings"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
)

// CheckRead verifies a single, zero-cost dispatch. The caller checks it again
// at settlement against the current clock and stored revocation state.
func CheckRead(m *v1.VentureTaskMandate, c *v1.VentureTaskContext, principal, tool string, maxDuration time.Duration, inputs []*v1.VentureResourceGrant) error {
	if m == nil || c == nil || c.Revoked {
		return errors.New("the task has no active mandate")
	}
	if m.RunId == "" || c.TenantId == "" || c.VentureId == "" || c.VentureRevision == 0 || c.AuthorizingActor == "" ||
		m.TenantId != c.TenantId || m.VentureId != c.VentureId || m.VentureRevision != c.VentureRevision || m.AuthorizingActor != c.AuthorizingActor {
		return errors.New("the owner or venture does not match the mandate")
	}
	issued, issueErr := time.Parse(time.RFC3339Nano, m.IssuedAt)
	expires, expiryErr := time.Parse(time.RFC3339Nano, m.ExpiresAt)
	now, clockErr := time.Parse(time.RFC3339Nano, c.CheckedAt)
	if issueErr != nil || expiryErr != nil || clockErr != nil || maxDuration <= 0 || expires.Sub(issued) > maxDuration ||
		now.Before(issued) || !now.Before(expires) {
		return errors.New("the task is outside its authorized time")
	}
	if strings.TrimSpace(m.Objective) == "" || principal == "" || tool == "" || m.Principal != principal ||
		!slices.Equal(m.Tools, []string{tool}) || m.EffectPolicy != v1.VentureEffectPolicy_VENTURE_EFFECT_POLICY_READ_ONLY ||
		m.MaxTasks != 1 || m.MaxDelegationDepth != 0 || m.ModelLimitUsdMicros != 0 || m.ToolLimitUsdMicros != 0 {
		return errors.New("the mandate must authorize this single read-only tool at zero spend")
	}
	if len(inputs) == 0 || len(m.Resources) != len(inputs) {
		return errors.New("the task's resource grants differ from its inputs")
	}
	grants := make(map[string]*v1.VentureResourceGrant, len(m.Resources))
	for _, g := range m.Resources {
		raw, err := hex.DecodeString(g.GetSha256())
		if err != nil || len(raw) != 32 || g.GetSha256() != strings.ToLower(g.GetSha256()) ||
			g.GetId() == "" || g.GetRole() == "" || grants[g.Role] != nil {
			return errors.New("an immutable resource grant is invalid")
		}
		grants[g.Role] = g
	}
	for _, in := range inputs {
		g := grants[in.GetRole()]
		if g == nil || g.Id != in.GetId() || g.Sha256 != in.GetSha256() {
			return errors.New("a selected resource or its version has changed")
		}
		delete(grants, g.Role)
	}
	return nil
}
