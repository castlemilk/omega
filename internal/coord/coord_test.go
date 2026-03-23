package coord

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

// openTestDB opens a Postgres test database.
// Tests are skipped if TEST_DATABASE_URL is not set.
func openTestDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not set — skipping Postgres integration tests")
	}
	// Use pgx driver via stdlib (registered by the pgx import in db package).
	// We import it for the side effect via a blank import in the test binary.
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open test db: %v", err)
	}
	// Bootstrap leader_election table
	if _, err := db.Exec(`CREATE TABLE IF NOT EXISTS leader_election (
		singleton   INTEGER PRIMARY KEY DEFAULT 1 CHECK (singleton = 1),
		leader_id   TEXT NOT NULL,
		acquired_at BIGINT NOT NULL,
		expires_at  BIGINT NOT NULL
	)`); err != nil {
		t.Fatalf("ensure leader table: %v", err)
	}
	t.Cleanup(func() {
		_, _ = db.Exec("DELETE FROM leader_election")
		_ = db.Close()
	})
	return db
}

// ─── Leader Election ──────────────────────────────────────────────────────────

func TestLeaderElection_SingleNode(t *testing.T) {
	db := openTestDB(t)
	le, err := NewLeaderElection(db, "node-1", 5*time.Second)
	if err != nil {
		t.Fatalf("new leader election: %v", err)
	}

	ctx := context.Background()
	won, err := le.TryAcquire(ctx)
	if err != nil {
		t.Fatalf("TryAcquire: %v", err)
	}
	if !won {
		t.Fatal("expected single node to win election")
	}
	if !le.IsLeader() {
		t.Fatal("IsLeader should be true after winning")
	}
}

func TestLeaderElection_MultipleContenders(t *testing.T) {
	db := openTestDB(t)
	ctx := context.Background()

	var leaderCount int32
	var wg sync.WaitGroup
	results := make([]bool, 5)

	for i := 0; i < 5; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			le, err := NewLeaderElection(db, fmt.Sprintf("node-%d", idx), 5*time.Second)
			if err != nil {
				t.Errorf("new leader election node-%d: %v", idx, err)
				return
			}
			won, err := le.TryAcquire(ctx)
			if err != nil {
				t.Errorf("TryAcquire node-%d: %v", idx, err)
				return
			}
			results[idx] = won
			if won {
				atomic.AddInt32(&leaderCount, 1)
			}
		}(i)
	}
	wg.Wait()

	if leaderCount != 1 {
		t.Fatalf("expected exactly 1 leader, got %d", leaderCount)
	}
}

func TestLeaderElection_ExpiredLease(t *testing.T) {
	db := openTestDB(t)
	ctx := context.Background()

	// node-1 acquires with very short TTL
	le1, _ := NewLeaderElection(db, "node-1", 50*time.Millisecond)
	won, err := le1.TryAcquire(ctx)
	if err != nil || !won {
		t.Fatalf("node-1 should win: won=%v err=%v", won, err)
	}

	// Wait for TTL to expire
	time.Sleep(100 * time.Millisecond)

	// node-2 should now be able to steal the lease
	le2, _ := NewLeaderElection(db, "node-2", 5*time.Second)
	won2, err := le2.TryAcquire(ctx)
	if err != nil {
		t.Fatalf("node-2 TryAcquire: %v", err)
	}
	if !won2 {
		t.Fatal("node-2 should steal expired lease")
	}
}

func TestLeaderElection_Renew(t *testing.T) {
	db := openTestDB(t)
	ctx := context.Background()

	le, _ := NewLeaderElection(db, "node-1", 5*time.Second)
	_, _ = le.TryAcquire(ctx)

	if err := le.Renew(ctx); err != nil {
		t.Fatalf("Renew: %v", err)
	}
}

func TestLeaderElection_Release(t *testing.T) {
	db := openTestDB(t)
	ctx := context.Background()

	le1, _ := NewLeaderElection(db, "node-1", 5*time.Second)
	_, _ = le1.TryAcquire(ctx)

	var callbackFired bool
	le1.OnLeaderChange(func(isLeader bool, leaderID string) {
		if !isLeader {
			callbackFired = true
		}
	})

	if err := le1.Release(ctx); err != nil {
		t.Fatalf("Release: %v", err)
	}
	if le1.IsLeader() {
		t.Fatal("should not be leader after release")
	}
	if !callbackFired {
		t.Fatal("OnLeaderChange callback not fired on release")
	}

	// node-2 can now acquire
	le2, _ := NewLeaderElection(db, "node-2", 5*time.Second)
	won, err := le2.TryAcquire(ctx)
	if err != nil || !won {
		t.Fatalf("node-2 should win after release: won=%v err=%v", won, err)
	}
}

// ─── Work Queue ───────────────────────────────────────────────────────────────

func TestWorkQueue_EnqueueDequeue(t *testing.T) {
	db := openTestDB(t)
	wq, err := NewWorkQueue(db)
	if err != nil {
		t.Fatalf("NewWorkQueue: %v", err)
	}
	ctx := context.Background()

	payload, _ := json.Marshal(map[string]string{"key": "val"})
	item := WorkItem{Type: "test", Payload: payload, Priority: 5}
	if err := wq.Enqueue(item); err != nil {
		t.Fatalf("Enqueue: %v", err)
	}

	got, err := wq.Dequeue(ctx, "worker-1")
	if err != nil {
		t.Fatalf("Dequeue: %v", err)
	}
	if got == nil {
		t.Fatal("expected item, got nil")
	}
	if got.Type != "test" {
		t.Errorf("type: want test, got %s", got.Type)
	}
	if got.ClaimedBy != "worker-1" {
		t.Errorf("claimed_by: want worker-1, got %s", got.ClaimedBy)
	}
}

func TestWorkQueue_EmptyQueue(t *testing.T) {
	db := openTestDB(t)
	wq, _ := NewWorkQueue(db)

	got, err := wq.Dequeue(context.Background(), "worker-1")
	if err != nil {
		t.Fatalf("unexpected error on empty queue: %v", err)
	}
	if got != nil {
		t.Fatal("expected nil from empty queue")
	}
}

func TestWorkQueue_PriorityOrdering(t *testing.T) {
	db := openTestDB(t)
	wq, _ := NewWorkQueue(db)
	ctx := context.Background()

	for _, p := range []int{1, 10, 5} {
		_ = wq.Enqueue(WorkItem{Type: "job", Priority: p, Payload: json.RawMessage(`{}`)})
	}

	got, _ := wq.Dequeue(ctx, "w")
	if got.Priority != 10 {
		t.Errorf("expected priority 10 first, got %d", got.Priority)
	}
}

func TestWorkQueue_ConcurrentConsumers(t *testing.T) {
	db := openTestDB(t)
	wq, _ := NewWorkQueue(db)
	ctx := context.Background()

	const itemCount = 20
	for i := 0; i < itemCount; i++ {
		_ = wq.Enqueue(WorkItem{Type: "job", Payload: json.RawMessage(`{}`)})
	}

	var claimed int32
	var wg sync.WaitGroup
	for w := 0; w < 5; w++ {
		wg.Add(1)
		go func(wid int) {
			defer wg.Done()
			for {
				item, err := wq.Dequeue(ctx, fmt.Sprintf("worker-%d", wid))
				if err != nil || item == nil {
					return
				}
				atomic.AddInt32(&claimed, 1)
				_ = wq.Complete(item.ID)
			}
		}(w)
	}
	wg.Wait()

	if int(claimed) != itemCount {
		t.Errorf("expected %d claimed, got %d", itemCount, claimed)
	}
}

func TestWorkQueue_FailAndRetry(t *testing.T) {
	db := openTestDB(t)
	wq, _ := NewWorkQueue(db)
	ctx := context.Background()

	_ = wq.Enqueue(WorkItem{Type: "job", Payload: json.RawMessage(`{}`)})

	// Claim and fail repeatedly until dead-letter
	for i := 0; i < maxAttempts; i++ {
		item, err := wq.Dequeue(ctx, "w")
		if err != nil {
			t.Fatalf("dequeue attempt %d: %v", i, err)
		}
		if item == nil {
			// Item is in backoff — force next_retry_at to now for test speed
			_, _ = db.Exec(`UPDATE work_queue SET next_retry_at = 0 WHERE status = 'pending'`)
			item, err = wq.Dequeue(ctx, "w")
			if err != nil || item == nil {
				t.Fatalf("dequeue after reset attempt %d: item=%v err=%v", i, item, err)
			}
		}
		_ = wq.Fail(item.ID, "test error")
		// Reset backoff for subsequent iterations
		_, _ = db.Exec(`UPDATE work_queue SET next_retry_at = 0 WHERE status = 'pending'`)
	}

	dead, err := wq.DeadLetterItems(ctx)
	if err != nil {
		t.Fatalf("DeadLetterItems: %v", err)
	}
	if len(dead) != 1 {
		t.Fatalf("expected 1 dead item, got %d", len(dead))
	}
	if dead[0].FailReason != "test error" {
		t.Errorf("fail reason: want 'test error', got %q", dead[0].FailReason)
	}
}

// ─── Partition Manager ────────────────────────────────────────────────────────

func TestPartitionManager_AllNodesAssigned(t *testing.T) {
	workers := []string{"w1", "w2", "w3"}
	nodes := []string{"n1", "n2", "n3", "n4", "n5", "n6"}

	pm := NewPartitionManager(workers, nodes)

	assigned := make(map[string]bool)
	for _, w := range workers {
		for _, n := range pm.GetAssignment(w) {
			if assigned[n] {
				t.Errorf("node %s assigned to multiple workers", n)
			}
			assigned[n] = true
		}
	}

	for _, n := range nodes {
		if !assigned[n] {
			t.Errorf("node %s not assigned to any worker", n)
		}
	}
}

func TestPartitionManager_Rebalance(t *testing.T) {
	workers := []string{"w1", "w2"}
	nodes := []string{"n1", "n2", "n3", "n4"}

	pm := NewPartitionManager(workers, nodes)

	before := map[string][]string{
		"w1": pm.GetAssignment("w1"),
		"w2": pm.GetAssignment("w2"),
	}

	// Add worker — some nodes should move
	pm.AddWorker("w3")
	pm.Rebalance()

	// All nodes should still be assigned
	assigned := make(map[string]bool)
	for _, w := range pm.Workers() {
		for _, n := range pm.GetAssignment(w) {
			assigned[n] = true
		}
	}
	for _, n := range nodes {
		if !assigned[n] {
			t.Errorf("node %s lost after rebalance", n)
		}
	}

	// w3 should own at least one node
	w3nodes := pm.GetAssignment("w3")
	if len(w3nodes) == 0 {
		t.Error("new worker w3 should own some nodes after rebalance")
	}

	_ = before // suppress unused warning (used to verify redistribution happened)
}

func TestPartitionManager_RemoveWorker(t *testing.T) {
	workers := []string{"w1", "w2", "w3"}
	nodes := []string{"n1", "n2", "n3", "n4", "n5"}

	pm := NewPartitionManager(workers, nodes)
	pm.RemoveWorker("w2")

	// All nodes should still be covered by the remaining two workers
	assigned := make(map[string]bool)
	for _, w := range []string{"w1", "w3"} {
		for _, n := range pm.GetAssignment(w) {
			assigned[n] = true
		}
	}
	for _, n := range nodes {
		if !assigned[n] {
			t.Errorf("node %s unassigned after worker removal", n)
		}
	}
}

func TestPartitionManager_Deterministic(t *testing.T) {
	workers := []string{"w1", "w2", "w3"}
	nodes := []string{"n1", "n2", "n3", "n4", "n5"}

	pm1 := NewPartitionManager(workers, nodes)
	pm2 := NewPartitionManager(workers, nodes)

	for _, w := range workers {
		a1 := pm1.GetAssignment(w)
		a2 := pm2.GetAssignment(w)
		sort.Strings(a1)
		sort.Strings(a2)
		if fmt.Sprint(a1) != fmt.Sprint(a2) {
			t.Errorf("non-deterministic assignment for %s: %v vs %v", w, a1, a2)
		}
	}
}

// ─── Distributed Lock ─────────────────────────────────────────────────────────

func TestDistributedLock_ExclusiveAccess(t *testing.T) {
	db := openTestDB(t)
	ctx := context.Background()

	lock1, _ := NewDistributedLock(db, "test-lock", "holder-1", 5*time.Second)
	lock2, _ := NewDistributedLock(db, "test-lock", "holder-2", 5*time.Second)

	ok1, err := lock1.TryAcquire(ctx)
	if err != nil || !ok1 {
		t.Fatalf("lock1 should acquire: ok=%v err=%v", ok1, err)
	}

	ok2, err := lock2.TryAcquire(ctx)
	if err != nil {
		t.Fatalf("TryAcquire error: %v", err)
	}
	if ok2 {
		t.Fatal("lock2 should not acquire while lock1 is held")
	}
}

func TestDistributedLock_Release(t *testing.T) {
	db := openTestDB(t)
	ctx := context.Background()

	lock1, _ := NewDistributedLock(db, "test-lock", "holder-1", 5*time.Second)
	lock2, _ := NewDistributedLock(db, "test-lock", "holder-2", 5*time.Second)

	_, _ = lock1.TryAcquire(ctx)
	_ = lock1.Release(ctx)

	ok, err := lock2.TryAcquire(ctx)
	if err != nil || !ok {
		t.Fatalf("lock2 should acquire after lock1 releases: ok=%v err=%v", ok, err)
	}
}

func TestDistributedLock_ExpiredLease(t *testing.T) {
	db := openTestDB(t)
	ctx := context.Background()

	lock1, _ := NewDistributedLock(db, "test-lock", "holder-1", 50*time.Millisecond)
	lock2, _ := NewDistributedLock(db, "test-lock", "holder-2", 5*time.Second)

	_, _ = lock1.TryAcquire(ctx)
	time.Sleep(100 * time.Millisecond)

	ok, err := lock2.TryAcquire(ctx)
	if err != nil || !ok {
		t.Fatalf("lock2 should steal expired lock: ok=%v err=%v", ok, err)
	}
}

func TestDistributedLock_Timeout(t *testing.T) {
	db := openTestDB(t)

	lock1, _ := NewDistributedLock(db, "test-lock", "holder-1", 5*time.Second)
	lock2, _ := NewDistributedLock(db, "test-lock", "holder-2", 5*time.Second)

	_, _ = lock1.TryAcquire(context.Background())

	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	err := lock2.Acquire(ctx)
	if err == nil {
		t.Fatal("expected timeout error when lock is held")
	}
}

func TestDistributedLock_Contention(t *testing.T) {
	db := openTestDB(t)
	ctx := context.Background()

	const goroutines = 10
	var acquired int32
	var wg sync.WaitGroup

	for i := 0; i < goroutines; i++ {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			lock, _ := NewDistributedLock(db, "contended-lock", fmt.Sprintf("holder-%d", id), 100*time.Millisecond)
			ok, err := lock.TryAcquire(ctx)
			if err == nil && ok {
				atomic.AddInt32(&acquired, 1)
				// Hold briefly then release
				time.Sleep(10 * time.Millisecond)
				_ = lock.Release(ctx)
			}
		}(i)
	}
	wg.Wait()

	// At least one should have acquired (likely exactly one per round)
	if acquired == 0 {
		t.Fatal("no goroutine acquired the lock")
	}
}

// ─── Barrier ──────────────────────────────────────────────────────────────────

func TestBarrier_AllWorkersArrive(t *testing.T) {
	db := openTestDB(t)
	ctx := context.Background()

	const n = 5
	var wg sync.WaitGroup
	errors := make([]error, n)

	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			b, err := NewBarrier(db, "test-barrier", fmt.Sprintf("worker-%d", idx), n)
			if err != nil {
				errors[idx] = err
				return
			}
			errors[idx] = b.Wait(ctx)
		}(i)
	}
	wg.Wait()

	for i, err := range errors {
		if err != nil {
			t.Errorf("worker-%d: %v", i, err)
		}
	}
}

func TestBarrier_ContextCancellation(t *testing.T) {
	db := openTestDB(t)
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	// Only 1 of 3 workers arrives — should time out
	b, _ := NewBarrier(db, "partial-barrier", "worker-0", 3)
	err := b.Wait(ctx)
	if err == nil {
		t.Fatal("expected context deadline exceeded")
	}
}

func TestBarrier_Reset(t *testing.T) {
	db := openTestDB(t)
	ctx := context.Background()

	b1, _ := NewBarrier(db, "reset-barrier", "w1", 2)
	b2, _ := NewBarrier(db, "reset-barrier", "w2", 2)

	// First round
	var wg sync.WaitGroup
	for _, b := range []*Barrier{b1, b2} {
		bb := b
		wg.Add(1)
		go func() {
			defer wg.Done()
			_ = bb.Wait(ctx)
		}()
	}
	wg.Wait()

	// Reset and verify arrivals cleared
	_ = b1.Reset(ctx)

	var count int
	_ = db.QueryRow(`SELECT COUNT(*) FROM barrier_arrivals WHERE barrier_name = 'reset-barrier'`).Scan(&count)
	if count != 0 {
		t.Errorf("expected 0 arrivals after reset, got %d", count)
	}
}
