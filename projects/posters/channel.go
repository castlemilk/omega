package posters

import (
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"fmt"
	"io"
	"math/big"
	"net/url"
	"regexp"
	"slices"
	"sort"
	"strings"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
)

var (
	metricHeader = []string{"observed_at", "period_start", "period_end", "source_url", "experiment_id", "metric", "value", "unit", "currency", "notes"}
	countMetrics = []string{"impressions", "clicks", "listing_visits", "orders", "refunds"}
	moneyMetrics = []string{"gross_revenue", "fees", "ad_spend"}
	exactValue   = regexp.MustCompile(`^(0|[1-9][0-9]{0,11})(\.[0-9]{1,6})?$`)
	currencyCode = regexp.MustCompile(`^[A-Z]{3}$`)
)

type (
	seriesKey   struct{ metric, currency string }
	dailySeries map[string]*big.Rat
)

func decimal(value *big.Rat) string {
	return strings.TrimRight(strings.TrimRight(value.FloatString(6), "0"), ".")
}

// MeasureChannel reads the collection's original daily CSV template. A window
// belongs to one experiment and one source. A missing observation differs from
// a recorded zero. Daily scope must remain identical for derived rates.
func MeasureChannel(input io.Reader, experiment, sourceURL, start, end string, kind v1.PosterObservationKind, asOf time.Time) (*v1.PosterChannelReport, error) {
	source, err := url.Parse(sourceURL)
	if err != nil || source.Scheme != "https" || source.Hostname() == "" || source.User != nil || source.Fragment != "" || strings.TrimSpace(experiment) == "" {
		return nil, fmt.Errorf("select an experiment and its HTTPS listing measurement source")
	}
	reported := kind == v1.PosterObservationKind_POSTER_OBSERVATION_KIND_REPORTED
	if !reported && kind != v1.PosterObservationKind_POSTER_OBSERVATION_KIND_SIMULATED {
		return nil, fmt.Errorf("identify the observations as reported or simulated")
	}
	first, err := time.Parse(time.DateOnly, start)
	if err != nil {
		return nil, fmt.Errorf("invalid first UTC date: %w", err)
	}
	last, err := time.Parse(time.DateOnly, end)
	if err != nil || first.After(last) || (reported && asOf.Before(last.AddDate(0, 0, 1))) {
		return nil, fmt.Errorf("select a valid date window that has ended for reported observations")
	}
	window := uint32((last.Unix()-first.Unix())/86400 + 1)
	hash := sha256.New()
	records := csv.NewReader(io.TeeReader(input, hash))
	header, err := records.Read()
	if err != nil || !slices.Equal(header, metricHeader) {
		return nil, fmt.Errorf("expected the Signal Studies metrics-template.csv header")
	}
	series := make(map[seriesKey]dailySeries)
	for _, metric := range countMetrics {
		series[seriesKey{metric: metric}] = dailySeries{}
	}
	for {
		row, err := records.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		if row[3] != sourceURL || row[4] != experiment {
			continue
		}
		line, _ := records.FieldPos(0)
		day, err := time.Parse(time.DateOnly, row[1])
		if err != nil || row[1] != row[2] {
			return nil, fmt.Errorf("row %d requires a single UTC reporting day", line)
		}
		if day.Before(first) || day.After(last) || row[6] == "" {
			continue
		}
		observed, err := time.Parse(time.RFC3339, row[0])
		if err != nil || observed.Before(day.AddDate(0, 0, 1)) || (reported && observed.After(asOf)) {
			return nil, fmt.Errorf("row %d requires the observation time of a completed daily report", line)
		}
		metric, value, unit, currency := row[5], row[6], row[7], row[8]
		count := slices.Contains(countMetrics, metric)
		money := slices.Contains(moneyMetrics, metric)
		if !exactValue.MatchString(value) || !(count || money) ||
			(count && (unit != "count" || currency != "" || strings.Contains(value, "."))) ||
			(money && (unit != "currency" || !currencyCode.MatchString(currency))) {
			return nil, fmt.Errorf("row %d has an invalid metric, value, unit or currency", line)
		}
		amount, _ := new(big.Rat).SetString(value)
		key := seriesKey{metric, currency}
		if series[key] == nil {
			series[key] = dailySeries{}
		}
		existing := series[key][row[1]]
		if existing != nil && existing.Cmp(amount) != 0 {
			return nil, fmt.Errorf("row %d conflicts with another %s observation for %s", line, metric, row[1])
		}
		series[key][row[1]] = amount
	}
	report := &v1.PosterChannelReport{
		ExperimentId: experiment, SourceUrl: sourceURL, ObservationKind: kind,
		PeriodStart: start, PeriodEnd: end, WindowDays: window, SourceFileSha256: hex.EncodeToString(hash.Sum(nil)),
	}
	// Preserve a stable order and report different currencies separately.
	var keys []seriesKey
	for key := range series {
		keys = append(keys, key)
	}
	sort.Slice(keys, func(i, j int) bool {
		if keys[i].metric == keys[j].metric {
			return keys[i].currency < keys[j].currency
		}
		return keys[i].metric < keys[j].metric
	})
	counts := make(map[string]*big.Rat)
	for _, key := range keys {
		days := series[key]
		item := &v1.PosterMetricWindow{Metric: key.metric, Currency: key.currency, Unit: "count", ObservedDays: uint32(len(days))}
		if key.currency != "" {
			item.Unit = "currency"
		}
		if item.ObservedDays == window {
			total := new(big.Rat)
			for _, amount := range days {
				total.Add(total, amount)
			}
			item.Total = decimal(total)
			if key.currency == "" {
				counts[key.metric] = total
			}
		}
		report.Metrics = append(report.Metrics, item)
	}
	ratio := func(numerator, denominator string) string {
		n, d := counts[numerator], counts[denominator]
		if n == nil || d == nil || d.Sign() == 0 {
			return ""
		}
		return decimal(new(big.Rat).Quo(n, d))
	}
	report.ClickThroughRate = ratio("clicks", "impressions")
	report.OrdersPerListingVisit = ratio("orders", "listing_visits")
	visits := counts["listing_visits"]
	switch {
	case window < 14 || visits == nil:
		report.Verdict = v1.PosterChannelVerdict_POSTER_CHANNEL_VERDICT_INSUFFICIENT_COVERAGE
		report.NextAction = "Collect a complete daily listing-visit series covering at least 14 days."
	case visits.Cmp(big.NewRat(100, 1)) < 0:
		report.Verdict = v1.PosterChannelVerdict_POSTER_CHANNEL_VERDICT_INSUFFICIENT_TRAFFIC
		report.NextAction = "Continue observation until the window includes 100 relevant listing visits."
	default:
		report.Verdict = v1.PosterChannelVerdict_POSTER_CHANNEL_VERDICT_READY_FOR_REVIEW
		report.NextAction = "Review the channel outcome with the owner. Orders, refunds and costs each require their own observations."
	}
	if !reported {
		report.SimulationResult = report.Verdict
		report.Verdict = v1.PosterChannelVerdict_POSTER_CHANNEL_VERDICT_SIMULATED
		report.NextAction = "Simulation only. " + report.NextAction
	}
	return report, nil
}
