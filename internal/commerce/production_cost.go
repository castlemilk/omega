package commerce

import (
	"cmp"
	"errors"
	"fmt"
	"math/big"
	"regexp"
	"slices"
	"strings"
	"time"
	"unicode"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"golang.org/x/text/currency"
)

const (
	costProvisional = v1.ProductionCostStage_PRODUCTION_COST_STAGE_PROVISIONAL
	costEstimated   = v1.ProductionCostStage_PRODUCTION_COST_STAGE_ESTIMATED
	costReserved    = v1.ProductionCostStage_PRODUCTION_COST_STAGE_RESERVED
	costIncurred    = v1.ProductionCostStage_PRODUCTION_COST_STAGE_INCURRED
	costSettled     = v1.ProductionCostStage_PRODUCTION_COST_STAGE_SETTLED
	costWithdrawn   = v1.ProductionCostStage_PRODUCTION_COST_STAGE_WITHDRAWN
)

var (
	costID       = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,159}$`)
	costDigest   = regexp.MustCompile(`^[0-9a-f]{64}$`)
	costCurrency = regexp.MustCompile(`^[A-Z]{3}$`)
)

func costText(s string) bool {
	return s != "" && len(s) <= 600 && strings.TrimSpace(s) == s && strings.IndexFunc(s, unicode.IsControl) < 0
}

func costDay(day string) bool {
	t, err := time.Parse(time.DateOnly, day)
	return err == nil && t.Year() > 0 && len(day) == len(time.DateOnly)
}

func costTargetKey(t *v1.ProductionCostTarget) string {
	return strings.Join([]string{t.BusinessId, t.ProductId, t.RunId, t.ExperimentId, t.Edition, t.ArtifactSha256}, "\x00")
}

func validateCostReceipt(r *v1.ProductionCostReceipt) error {
	if r == nil || !costID.MatchString(r.Provider) || !costID.MatchString(r.Account) || !costID.MatchString(r.LineId) || r.Simulated == nil {
		return errors.New("a cost needs a provider, account alias, stable source line and explicit simulated mode")
	}
	if !costDay(r.ServiceDate) || !costDigest.MatchString(r.EvidenceSha256) || !costText(r.Description) || !costText(r.AllocationBasis) {
		return errors.New("the service date, evidence SHA-256, description and allocation basis are required")
	}
	if _, ok := v1.ProductionCostCategory_name[int32(r.Category)]; !ok || r.Category == 0 {
		return errors.New("choose a supported cost category")
	}
	if r.PreviousReceiptSha256 == "" {
		if r.RevisionReason != "" || r.Stage == costWithdrawn {
			return errors.New("a withdrawal or correction requires the previous receipt SHA-256")
		}
	} else if !costDigest.MatchString(r.PreviousReceiptSha256) || !costText(r.RevisionReason) {
		return errors.New("a revision needs its previous receipt SHA-256 and a reason")
	}
	if r.Currency != "" {
		unit, err := currency.ParseISO(r.Currency)
		if !costCurrency.MatchString(r.Currency) || err != nil || unit.String() == "XXX" {
			return errors.New("use a recognised three-letter uppercase currency")
		}
	}
	if r.SourceObservedAt != "" {
		if _, err := time.Parse(time.RFC3339Nano, r.SourceObservedAt); err != nil {
			return errors.New("source observation time must include an RFC 3339 date, time and offset")
		}
	}
	switch r.Stage {
	case costProvisional, costWithdrawn:
		if r.AmountMicros != nil || r.Rate != nil {
			return errors.New("provisional and withdrawn costs omit an amount and rate")
		}
	case costEstimated, costReserved, costIncurred, costSettled:
		if r.Currency == "" || r.AmountMicros == nil {
			return errors.New("a priced cost needs a currency and an explicit amount in millionths")
		}
		if (r.Stage == costEstimated || r.Stage == costReserved) && r.GetAmountMicros() < 0 {
			return errors.New("estimated and reserved costs must be nonnegative")
		}
	default:
		return errors.New("choose a supported cost stage")
	}
	if rate := r.Rate; rate != nil {
		if r.Stage != costEstimated || !costText(rate.Unit) || rate.Units == 0 || rate.PriceMicrosPerUnit == nil ||
			!costDay(rate.EffectiveFrom) || rate.EffectiveFrom > r.ServiceDate ||
			(rate.EffectiveThrough != "" && (!costDay(rate.EffectiveThrough) || rate.EffectiveThrough < r.ServiceDate)) {
			return errors.New("a rate-based estimate needs units and a rate in force on the service day")
		}
		expected := new(big.Int).Mul(new(big.Int).SetUint64(rate.Units), new(big.Int).SetUint64(rate.GetPriceMicrosPerUnit()))
		if expected.Cmp(big.NewInt(r.GetAmountMicros())) != 0 {
			return errors.New("the estimated amount differs from its units and dated price")
		}
	}
	if len(r.Targets) == 0 || len(r.Targets) > 10000 {
		return errors.New("provide one or more distinct allocation targets")
	}
	seen := make(map[string]bool, len(r.Targets))
	var shares uint32
	for _, target := range r.Targets {
		if target == nil || !costID.MatchString(target.BusinessId) || !costID.MatchString(target.ProductId) ||
			!costID.MatchString(target.RunId) || !costDigest.MatchString(target.ArtifactSha256) ||
			(target.ExperimentId != "" && !costID.MatchString(target.ExperimentId)) || (target.Edition != "" && !costID.MatchString(target.Edition)) ||
			target.ShareBps == 0 || target.ShareBps > 10000 {
			return errors.New("each share needs a business, product, run, artifact SHA-256 and positive basis points")
		}
		key := costTargetKey(target)
		if seen[key] {
			return fmt.Errorf("duplicate allocation target for run %s", target.RunId)
		}
		seen[key] = true
		shares += target.ShareBps
	}
	if shares != 10000 {
		return fmt.Errorf("allocation shares add to %d basis points, expected 10000", shares)
	}
	return nil
}

// Apportion the absolute amount first, then restore its sign. Remaining
// millionths go to largest remainders, with ties broken by the target's identity.
func costShares(amount int64, targets []*v1.ProductionCostTarget) []int64 {
	type fraction struct {
		index     int
		remainder uint64
		key       string
	}
	fractions := make([]fraction, len(targets))
	shares := make([]int64, len(targets))
	magnitude := new(big.Int).Abs(big.NewInt(amount))
	unassigned := magnitude.Uint64()
	for i, target := range targets {
		product := new(big.Int).Mul(magnitude, new(big.Int).SetUint64(uint64(target.ShareBps)))
		quotient, remainder := new(big.Int), new(big.Int)
		quotient.QuoRem(product, big.NewInt(10000), remainder)
		unassigned -= quotient.Uint64()
		if amount < 0 {
			quotient.Neg(quotient)
		}
		shares[i] = quotient.Int64()
		fractions[i] = fraction{i, remainder.Uint64(), costTargetKey(target)}
	}
	slices.SortFunc(fractions, func(a, b fraction) int {
		if byRemainder := cmp.Compare(b.remainder, a.remainder); byRemainder != 0 {
			return byRemainder
		}
		return cmp.Compare(a.key, b.key)
	})
	step := int64(1)
	if amount < 0 {
		step = -1
	}
	for _, part := range fractions[:unassigned] {
		shares[part.index] += step
	}
	return shares
}
