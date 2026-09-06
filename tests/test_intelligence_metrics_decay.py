"""Tests for exponential decay composite score in IntelligenceMetricsCollector."""

from __future__ import annotations

from omega.core.intelligence_metrics import IntelligenceMetricsCollector


class TestIntelligenceScoreExponentialDecay:
    def test_initial_score_without_history_uses_current_cycle_checks(self):
        collector = IntelligenceMetricsCollector(db_url=None)
        collector.record("brain_calls", 1)
        collector.record("improve_calls", 1)
        collector.record("episodes_created", 1)
        collector.record("semantic_patterns_extracted", 1)
        collector.record("shared_memory_reads", 1)
        collector.record("signals_nonzero", 15)
        collector.record("rmt_info_ratio", 0.5)
        collector.record("debate_gate_invocations", 1)
        score = collector._compute_intelligence_score()
        # All 8 checks pass → score = 1.0 (no history yet, so just current)
        assert score == 1.0

    def test_score_is_ema_of_current_and_recent_history(self):
        collector = IntelligenceMetricsCollector(db_url=None)

        # Flush 5 cycles with score=0 (no metrics set)
        for i in range(5):
            collector.flush(cycle=i)

        # Now a perfect cycle
        collector.record("brain_calls", 1)
        collector.record("improve_calls", 1)
        collector.record("episodes_created", 1)
        collector.record("semantic_patterns_extracted", 1)
        collector.record("shared_memory_reads", 1)
        collector.record("signals_nonzero", 15)
        collector.record("rmt_info_ratio", 0.5)
        collector.record("debate_gate_invocations", 1)
        score = collector._compute_intelligence_score()

        # With low-history-penalty EMA, score should be less than pure 1.0
        # because recent history of 0-scored cycles drags it down
        assert score < 1.0
        assert score > 0.0

    def test_recent_cycles_weighted_more_than_old_cycles(self):
        collector = IntelligenceMetricsCollector(db_url=None)

        # 10 bad cycles (score ~0)
        for i in range(10):
            collector.flush(cycle=i)

        # 3 recent perfect cycles
        for i in range(10, 13):
            collector.record("brain_calls", 1)
            collector.record("improve_calls", 1)
            collector.record("episodes_created", 1)
            collector.record("semantic_patterns_extracted", 1)
            collector.record("shared_memory_reads", 1)
            collector.record("signals_nonzero", 15)
            collector.record("rmt_info_ratio", 0.5)
            collector.record("debate_gate_invocations", 1)
            collector.flush(cycle=i)

        # Now compute with 3 recent perfect cycles — EMA should reflect recent improvement
        collector.record("brain_calls", 1)
        collector.record("improve_calls", 1)
        collector.record("episodes_created", 1)
        collector.record("semantic_patterns_extracted", 1)
        collector.record("shared_memory_reads", 1)
        collector.record("signals_nonzero", 15)
        collector.record("rmt_info_ratio", 0.5)
        collector.record("debate_gate_invocations", 1)
        score_after_recovery = collector._compute_intelligence_score()

        # Compare to what score would be with NO recent history (same perfect checks)
        collector2 = IntelligenceMetricsCollector(db_url=None)
        collector2.record("brain_calls", 1)
        collector2.record("improve_calls", 1)
        collector2.record("episodes_created", 1)
        collector2.record("semantic_patterns_extracted", 1)
        collector2.record("shared_memory_reads", 1)
        collector2.record("signals_nonzero", 15)
        collector2.record("rmt_info_ratio", 0.5)
        collector2.record("debate_gate_invocations", 1)
        score_no_history = collector2._compute_intelligence_score()

        # After 3 recent perfect cycles + bad history, should be lower than pure 1.0
        # but recovery trend should push it upward vs 10-bad-cycle baseline
        assert score_no_history == 1.0
        # Recent 3 perfect cycles should make score_after_recovery higher than
        # what it would be with only bad history
        collector_bad = IntelligenceMetricsCollector(db_url=None)
        for i in range(10):
            collector_bad.flush(cycle=i)
        collector_bad.record("brain_calls", 1)
        collector_bad.record("improve_calls", 1)
        collector_bad.record("episodes_created", 1)
        collector_bad.record("semantic_patterns_extracted", 1)
        collector_bad.record("shared_memory_reads", 1)
        collector_bad.record("signals_nonzero", 15)
        collector_bad.record("rmt_info_ratio", 0.5)
        collector_bad.record("debate_gate_invocations", 1)
        score_only_bad = collector_bad._compute_intelligence_score()
        assert score_after_recovery > score_only_bad

    def test_ema_decay_parameter_controls_history_weight(self):
        # Lower alpha = more history weight (slower decay)
        collector_slow = IntelligenceMetricsCollector(db_url=None, ema_alpha=0.1)
        collector_fast = IntelligenceMetricsCollector(db_url=None, ema_alpha=0.9)

        # Flush 5 perfect cycles into both
        for i in range(5):
            for c in (collector_slow, collector_fast):
                c.record("brain_calls", 1)
                c.record("improve_calls", 1)
                c.record("episodes_created", 1)
                c.record("semantic_patterns_extracted", 1)
                c.record("shared_memory_reads", 1)
                c.record("signals_nonzero", 15)
                c.record("rmt_info_ratio", 0.5)
                c.record("debate_gate_invocations", 1)
                c.flush(cycle=i)

        # Now flush 5 empty cycles (score=0)
        for i in range(5, 10):
            for c in (collector_slow, collector_fast):
                c.flush(cycle=i)

        # Then compute with another perfect cycle
        for c in (collector_slow, collector_fast):
            c.record("brain_calls", 1)
            c.record("improve_calls", 1)
            c.record("episodes_created", 1)
            c.record("semantic_patterns_extracted", 1)
            c.record("shared_memory_reads", 1)
            c.record("signals_nonzero", 15)
            c.record("rmt_info_ratio", 0.5)
            c.record("debate_gate_invocations", 1)

        score_slow = collector_slow._compute_intelligence_score()
        score_fast = collector_fast._compute_intelligence_score()

        # Fast EMA reacts more to recent (bad) cycles → lower score than slow EMA
        # Slow EMA retains more of the older perfect cycles → higher score
        assert score_slow > score_fast

    def test_score_history_is_accessible(self):
        collector = IntelligenceMetricsCollector(db_url=None)
        collector.flush(cycle=0)
        collector.flush(cycle=1)
        assert len(collector.score_history) == 2
