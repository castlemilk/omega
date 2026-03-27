package db

import "database/sql"

// IntelligenceMetricsSummary holds aggregated intelligence metrics over N cycles.
type IntelligenceMetricsSummary struct {
	CyclesAnalyzed           int64
	BrainProvider            string
	BrainCallsTotal          int64
	BrainCallsPerCycle       float64
	ImproveCallsTotal        int64
	ImproveAcceptedTotal     int64
	SignalVersionLatest      string
	EpisodesTotal            int64
	SemanticPatternsTotal    int64
	SharedMemoryTotal        int64
	IntelligenceScoreAvg     float64
	IntelligenceScoreLast    float64
	AvgBrainCalls            float64
	AvgImproveCalls          float64
	AvgEpisodesCreated       float64
	AvgSemanticExtracted     float64
	AvgSharedMemReads        float64
	AvgSignalsNonzero        float64
	AvgRmtInfoRatio          float64
	AvgDebateGateInvocations float64
}

// GetIntelligenceMetrics queries the intelligence_metrics table and returns
// aggregated stats over the last lastN cycles (default 100 when lastN <= 0).
func (d *DB) GetIntelligenceMetrics(lastN int) (*IntelligenceMetricsSummary, error) {
	if lastN <= 0 {
		lastN = 100
	}

	row := d.db.QueryRow(`
		SELECT
			COUNT(*)                                                                           AS cycles_analyzed,
			COALESCE(
				(SELECT brain_provider FROM intelligence_metrics
				 WHERE brain_provider IS NOT NULL ORDER BY cycle DESC LIMIT 1),
				''
			)                                                                                  AS brain_provider,
			COALESCE(SUM(brain_calls), 0)                                                      AS brain_calls_total,
			CASE WHEN COUNT(*) > 0
				THEN COALESCE(SUM(brain_calls), 0)::double precision / COUNT(*)
				ELSE 0
			END                                                                                AS brain_calls_per_cycle,
			COALESCE(SUM(improve_calls), 0)                                                    AS improve_calls_total,
			COALESCE(SUM(improve_accepted), 0)                                                 AS improve_accepted_total,
			COALESCE(MAX(signal_version) FILTER (WHERE signal_version IS NOT NULL), '')        AS signal_version_latest,
			COALESCE(MAX(episodes_total) FILTER (WHERE episodes_total IS NOT NULL), 0)         AS episodes_total,
			COALESCE(MAX(semantic_patterns_total) FILTER (WHERE semantic_patterns_total IS NOT NULL), 0) AS semantic_patterns_total,
			COALESCE(AVG(intelligence_score) FILTER (WHERE intelligence_score IS NOT NULL), 0) AS score_avg,
			COALESCE(
				(SELECT intelligence_score FROM intelligence_metrics
				 WHERE intelligence_score IS NOT NULL ORDER BY cycle DESC LIMIT 1),
				0
			)                                                                                  AS score_last,
			COALESCE(AVG(brain_calls), 0)                                                      AS avg_brain_calls,
			COALESCE(AVG(improve_calls), 0)                                                    AS avg_improve_calls,
			COALESCE(AVG(episodes_created), 0)                                                 AS avg_episodes_created,
			COALESCE(AVG(semantic_patterns_extracted), 0)                                      AS avg_semantic_extracted,
			COALESCE(AVG(shared_memory_reads), 0)                                              AS avg_shared_mem_reads,
			COALESCE(AVG(signals_nonzero), 0)                                                  AS avg_signals_nonzero,
			COALESCE(AVG(rmt_info_ratio) FILTER (WHERE rmt_info_ratio IS NOT NULL), 0)         AS avg_rmt_info_ratio,
			COALESCE(AVG(debate_gate_invocations), 0)                                          AS avg_debate_gate_invocations
		FROM (
			SELECT * FROM intelligence_metrics ORDER BY cycle DESC LIMIT $1
		) sub
	`, lastN)

	s := &IntelligenceMetricsSummary{}
	err := row.Scan(
		&s.CyclesAnalyzed,
		&s.BrainProvider,
		&s.BrainCallsTotal,
		&s.BrainCallsPerCycle,
		&s.ImproveCallsTotal,
		&s.ImproveAcceptedTotal,
		&s.SignalVersionLatest,
		&s.EpisodesTotal,
		&s.SemanticPatternsTotal,
		&s.IntelligenceScoreAvg,
		&s.IntelligenceScoreLast,
		&s.AvgBrainCalls,
		&s.AvgImproveCalls,
		&s.AvgEpisodesCreated,
		&s.AvgSemanticExtracted,
		&s.AvgSharedMemReads,
		&s.AvgSignalsNonzero,
		&s.AvgRmtInfoRatio,
		&s.AvgDebateGateInvocations,
	)
	if err == sql.ErrNoRows {
		return s, nil
	}
	return s, err
}

// GetSharedMemoryCount returns the total row count in shared_memory.
func (d *DB) GetSharedMemoryCount() (int64, error) {
	row := d.db.QueryRow("SELECT COUNT(*) FROM shared_memory")
	var n int64
	return n, row.Scan(&n)
}
