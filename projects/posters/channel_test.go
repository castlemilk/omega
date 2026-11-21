package posters

import (
	"crypto/sha256"
	"encoding/csv"
	"fmt"
	"strings"
	"testing"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
)

const channelSource = "https://example.invalid/channel/signal-studies"

func observation(day int, metric, value, unit, currency string) []string {
	date := fmt.Sprintf("2026-11-%02d", day)
	return []string{date + "T23:00:00-02:00", date, date, channelSource, "pilot", metric, value, unit, currency, ""}
}

func measured(rows [][]string, days int, kind v1.PosterObservationKind) (*v1.PosterChannelReport, error) {
	var contents strings.Builder
	writer := csv.NewWriter(&contents)
	if err := writer.WriteAll(append([][]string{metricHeader}, rows...)); err != nil {
		return nil, err
	}
	return MeasureChannel(strings.NewReader(contents.String()), "pilot", channelSource, "2026-11-01", fmt.Sprintf("2026-11-%02d", days),
		kind, time.Date(2026, 11, 21, 0, 0, 0, 0, time.UTC))
}

func metric(report *v1.PosterChannelReport, name, currency string) *v1.PosterMetricWindow {
	for _, item := range report.Metrics {
		if item.Metric == name && item.Currency == currency {
			return item
		}
	}
	return nil
}

func TestChannelDailyTotalsAndScope(t *testing.T) {
	var rows [][]string
	for i := 1; i <= 14; i++ {
		for _, obs := range [][]string{
			observation(i, "listing_visits", "8", "count", ""), observation(i, "orders", "2", "count", ""),
			observation(i, "clicks", "4", "count", ""), observation(i, "impressions", "50", "count", ""),
			observation(i, "gross_revenue", "12.05", "currency", "AUD"), observation(i, "gross_revenue", "0.20", "currency", "USD"),
			observation(i, "refunds", "0", "count", ""),
		} {
			rows = append(rows, obs)
		}
	}
	other := observation(1, "orders", "999", "count", "")
	other[4] = "another"
	foreign := observation(1, "orders", "999", "count", "")
	foreign[3] = "https://example.invalid/other"
	rows = append(rows, other, foreign, observation(15, "orders", "999", "count", ""), rows[0], observation(4, "fees", "", "currency", "AUD"))
	report, err := measured(rows, 14, v1.PosterObservationKind_POSTER_OBSERVATION_KIND_REPORTED)
	if err != nil {
		t.Fatal(err)
	}
	if report.Verdict != v1.PosterChannelVerdict_POSTER_CHANNEL_VERDICT_READY_FOR_REVIEW || report.OrdersPerListingVisit != "0.25" || report.ClickThroughRate != "0.08" {
		t.Fatal(report)
	}
	for _, expected := range [][]string{{"listing_visits", "", "112"}, {"gross_revenue", "AUD", "168.7"}, {"gross_revenue", "USD", "2.8"}, {"refunds", "", "0"}} {
		got := metric(report, expected[0], expected[1])
		if got == nil || got.Total != expected[2] || got.ObservedDays != 14 {
			t.Fatalf("%s: %v", expected, got)
		}
	}
	if metric(report, "fees", "AUD") != nil || len(report.SourceFileSha256) != sha256.Size*2 {
		t.Fatal(report)
	}
}

func TestChannelEvidenceBoundary(t *testing.T) {
	var rows [][]string
	for i := 1; i <= 14; i++ {
		rows = append(rows, observation(i, "listing_visits", "7", "count", ""))
	}
	kind := v1.PosterObservationKind_POSTER_OBSERVATION_KIND_SIMULATED
	report, err := measured(rows, 14, kind)
	if err != nil || report.Verdict != v1.PosterChannelVerdict_POSTER_CHANNEL_VERDICT_SIMULATED || report.SimulationResult != v1.PosterChannelVerdict_POSTER_CHANNEL_VERDICT_INSUFFICIENT_TRAFFIC || metric(report, "listing_visits", "").Total != "98" || !strings.HasPrefix(report.NextAction, "Simulation only.") {
		t.Fatalf("%v %v", report, err)
	}
	// At exactly 100 visits the window is eligible for inspection.
	rows[0][6] = "9"
	report, err = measured(rows, 14, kind)
	if err != nil || report.SimulationResult != v1.PosterChannelVerdict_POSTER_CHANNEL_VERDICT_READY_FOR_REVIEW || report.Verdict != v1.PosterChannelVerdict_POSTER_CHANNEL_VERDICT_SIMULATED {
		t.Fatalf("%v %v", report, err)
	}
	for _, tc := range []struct {
		rows [][]string
		days int
	}{{rows[1:], 14}, {nil, 14}, {rows, 13}} {
		report, err := measured(tc.rows, tc.days, kind)
		if err != nil || report.SimulationResult != v1.PosterChannelVerdict_POSTER_CHANNEL_VERDICT_INSUFFICIENT_COVERAGE || report.OrdersPerListingVisit != "" {
			t.Fatalf("%v %v", report, err)
		}
	}
	rows[0][6] = ""
	report, err = measured(rows, 14, kind)
	if err != nil || metric(report, "listing_visits", "").Total != "" || metric(report, "listing_visits", "").ObservedDays != 13 {
		t.Fatalf("%v %v", report, err)
	}
	zero, err := measured([][]string{observation(1, "listing_visits", "0", "count", ""), observation(1, "orders", "0", "count", "")}, 1, kind)
	if err != nil || zero.OrdersPerListingVisit != "" || metric(zero, "orders", "").Total != "0" {
		t.Fatalf("%v %v", zero, err)
	}
}

func TestChannelRejectsAmbiguousOrPrematureInput(t *testing.T) {
	kind := v1.PosterObservationKind_POSTER_OBSERVATION_KIND_REPORTED
	for _, change := range []struct {
		col   int
		value string
	}{{0, "2026-11-01T23:59:59Z"}, {0, "2026-12-01T12:00:00Z"}, {1, "2026/11/01"}, {2, "2026-11-02"}, {5, "unique_visitors"}, {6, "-1"}, {6, "1.5"}, {7, "visitors"}, {8, "USD"}} {
		bad := observation(1, "listing_visits", "1", "count", "")
		bad[change.col] = change.value
		if _, err := measured([][]string{bad}, 14, kind); err == nil {
			t.Fatalf("accepted invalid observation %#v", bad)
		}
	}
	if _, err := measured([][]string{observation(1, "orders", "1", "count", ""), observation(1, "orders", "2", "count", "")}, 14, kind); err == nil {
		t.Fatal("accepted conflicting repeat")
	}
	if _, err := measured(nil, 24, kind); err == nil {
		t.Fatal("accepted an unfinished reported window")
	}
}
