package terminal_test

import (
	"context"
	"fmt"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/benebsworth/omega/internal/db"
	"github.com/benebsworth/omega/internal/terminal"
)

func newManager(t *testing.T) *terminal.Manager {
	t.Helper()
	return terminal.NewManager()
}

func newManagerWithDB(t *testing.T) (*terminal.Manager, *db.DB) {
	t.Helper()
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not set — skipping Postgres integration tests")
	}
	t.Setenv("DATABASE_URL", dsn)
	database, err := db.New(context.Background())
	require.NoError(t, err)
	t.Cleanup(func() { database.Close() })
	m := terminal.NewManager(terminal.WithDB(database))
	return m, database
}

// 1. CreateSession returns session with correct defaults.
func TestCreateSession_Defaults(t *testing.T) {
	m := newManager(t)
	sess, err := m.CreateSession(context.Background(), terminal.SessionConfig{
		AutonomyLevel: terminal.LevelAutonomous,
	})
	require.NoError(t, err)
	assert.NotEmpty(t, sess.ID)
	assert.Equal(t, terminal.StatusActive, sess.Status)
	assert.Equal(t, terminal.LevelAutonomous, sess.Config.AutonomyLevel)
	assert.Equal(t, terminal.DefaultMaxOutputSize, sess.Config.MaxOutputSize)
}

// 2. Duplicate session ID returns error.
func TestCreateSession_DuplicateID(t *testing.T) {
	m := newManager(t)
	cfg := terminal.SessionConfig{ID: "dup-001", AutonomyLevel: terminal.LevelAutonomous}
	_, err := m.CreateSession(context.Background(), cfg)
	require.NoError(t, err)
	_, err = m.CreateSession(context.Background(), cfg)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "already exists")
}

// 3. Execute simple command succeeds at autonomous level.
func TestExecute_SimpleCommand_Autonomous(t *testing.T) {
	m := newManager(t)
	sess, err := m.CreateSession(context.Background(), terminal.SessionConfig{
		AutonomyLevel: terminal.LevelAutonomous,
	})
	require.NoError(t, err)

	res, err := m.Execute(context.Background(), terminal.CommandRequest{
		SessionID: sess.ID,
		Command:   "echo",
		Args:      []string{"hello"},
	})
	require.NoError(t, err)
	assert.Equal(t, 0, res.ExitCode)
	assert.Contains(t, res.Stdout, "hello")
	assert.Empty(t, res.Error)
}

// 4. PICO level allows read-only command (ls).
func TestExecute_PicoLevel_AllowsReadOnly(t *testing.T) {
	m := newManager(t)
	sess, _ := m.CreateSession(context.Background(), terminal.SessionConfig{
		AutonomyLevel: terminal.LevelPico,
		WorkDir:       t.TempDir(),
	})
	res, err := m.Execute(context.Background(), terminal.CommandRequest{
		SessionID: sess.ID,
		Command:   "ls",
	})
	require.NoError(t, err)
	assert.Empty(t, res.Error, "ls should be allowed at pico level")
}

// 5. PICO level blocks write command (mkdir).
func TestExecute_PicoLevel_BlocksWrite(t *testing.T) {
	m := newManager(t)
	sess, _ := m.CreateSession(context.Background(), terminal.SessionConfig{
		AutonomyLevel: terminal.LevelPico,
	})
	res, err := m.Execute(context.Background(), terminal.CommandRequest{
		SessionID: sess.ID,
		Command:   "mkdir",
		Args:      []string{"newdir"},
	})
	require.NoError(t, err)
	assert.NotEmpty(t, res.Error, "mkdir should be blocked at pico level")
	assert.Contains(t, res.Error, "not permitted")
}

// 6. SUPERVISED level allows mkdir.
func TestExecute_SupervisedLevel_AllowsMkdir(t *testing.T) {
	m := newManager(t)
	dir := t.TempDir()
	sess, _ := m.CreateSession(context.Background(), terminal.SessionConfig{
		AutonomyLevel: terminal.LevelSupervised,
		WorkDir:       dir,
	})
	res, err := m.Execute(context.Background(), terminal.CommandRequest{
		SessionID: sess.ID,
		Command:   "mkdir",
		Args:      []string{"subdir"},
	})
	require.NoError(t, err)
	assert.Empty(t, res.Error, "mkdir should be allowed at supervised level")
}

// 7. Hard-blocked command is rejected at all autonomy levels.
func TestExecute_HardBlocked_RejectedAtAllLevels(t *testing.T) {
	for _, level := range []string{terminal.LevelPico, terminal.LevelSupervised, terminal.LevelAutonomous} {
		t.Run(level, func(t *testing.T) {
			m := newManager(t)
			sess, _ := m.CreateSession(context.Background(), terminal.SessionConfig{
				AutonomyLevel: level,
			})
			res, err := m.Execute(context.Background(), terminal.CommandRequest{
				SessionID: sess.ID,
				Command:   "shutdown",
				Args:      []string{"-h", "now"},
			})
			require.NoError(t, err)
			assert.NotEmpty(t, res.Error, "shutdown must be blocked at %s", level)
			assert.Contains(t, res.Error, "blocked")
		})
	}
}

// 8. Custom blocked command in session config is enforced.
func TestExecute_CustomBlockedCmd(t *testing.T) {
	m := newManager(t)
	sess, _ := m.CreateSession(context.Background(), terminal.SessionConfig{
		AutonomyLevel: terminal.LevelAutonomous,
		BlockedCmds:   []string{"curl"},
	})
	res, err := m.Execute(context.Background(), terminal.CommandRequest{
		SessionID: sess.ID,
		Command:   "curl",
		Args:      []string{"http://example.com"},
	})
	require.NoError(t, err)
	assert.NotEmpty(t, res.Error)
	assert.Contains(t, res.Error, "blocked")
}

// 9. Output is truncated when it exceeds MaxOutputSize.
func TestExecute_OutputTruncation(t *testing.T) {
	m := newManager(t)
	sess, _ := m.CreateSession(context.Background(), terminal.SessionConfig{
		AutonomyLevel: terminal.LevelAutonomous,
		MaxOutputSize: 10, // tiny cap
	})
	res, err := m.Execute(context.Background(), terminal.CommandRequest{
		SessionID: sess.ID,
		Command:   "echo",
		Args:      []string{"this is more than ten bytes of output"},
	})
	require.NoError(t, err)
	assert.True(t, res.Truncated, "output should be truncated")
	assert.True(t, strings.HasSuffix(res.Stdout, terminal.TruncationMarker))
}

// 10. Per-command timeout is enforced.
func TestExecute_CmdTimeout(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping timeout test in short mode")
	}
	m := newManager(t)
	sess, _ := m.CreateSession(context.Background(), terminal.SessionConfig{
		AutonomyLevel: terminal.LevelAutonomous,
		CmdTimeout:    200 * time.Millisecond,
	})
	start := time.Now()
	res, err := m.Execute(context.Background(), terminal.CommandRequest{
		SessionID: sess.ID,
		Command:   "sleep",
		Args:      []string{"10"},
	})
	elapsed := time.Since(start)
	require.NoError(t, err)
	assert.Less(t, elapsed, 2*time.Second, "should timeout well before 10s")
	assert.NotEqual(t, 0, res.ExitCode, "should exit non-zero on timeout")
}

// 11. Execute on a session not found returns error.
func TestExecute_SessionNotFound_ReturnsError(t *testing.T) {
	m := newManager(t)
	_, err := m.Execute(context.Background(), terminal.CommandRequest{
		SessionID: "ghost-session",
		Command:   "echo",
	})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "not found")
}

// 12. Execute on closed session returns error.
func TestExecute_ClosedSession_ReturnsError(t *testing.T) {
	m := newManager(t)
	sess, _ := m.CreateSession(context.Background(), terminal.SessionConfig{
		AutonomyLevel: terminal.LevelAutonomous,
	})
	require.NoError(t, m.CloseSession(context.Background(), sess.ID))

	// Session is removed from the map after close.
	_, err := m.Execute(context.Background(), terminal.CommandRequest{
		SessionID: sess.ID,
		Command:   "echo",
	})
	require.Error(t, err)
}

// 13. CloseSession removes session from ListSessions.
func TestCloseSession_RemovedFromList(t *testing.T) {
	m := newManager(t)
	sess, _ := m.CreateSession(context.Background(), terminal.SessionConfig{
		AutonomyLevel: terminal.LevelAutonomous,
	})
	assert.Len(t, m.ListSessions(context.Background()), 1)
	require.NoError(t, m.CloseSession(context.Background(), sess.ID))
	assert.Empty(t, m.ListSessions(context.Background()))
}

// 14. GetSession returns error for unknown ID.
func TestGetSession_Unknown(t *testing.T) {
	m := newManager(t)
	_, err := m.GetSession(context.Background(), "ghost")
	require.Error(t, err)
}

// 15. Concurrent sessions execute independently without races.
func TestExecute_ConcurrentSessions(t *testing.T) {
	m := newManager(t)
	const n = 10
	var wg sync.WaitGroup
	errs := make(chan error, n)
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			sess, err := m.CreateSession(context.Background(), terminal.SessionConfig{
				AutonomyLevel: terminal.LevelAutonomous,
			})
			if err != nil {
				errs <- err
				return
			}
			res, err := m.Execute(context.Background(), terminal.CommandRequest{
				SessionID: sess.ID,
				Command:   "echo",
				Args:      []string{"concurrent"},
			})
			if err != nil {
				errs <- err
				return
			}
			if res.ExitCode != 0 {
				errs <- fmt.Errorf("non-zero exit from concurrent echo: %d", res.ExitCode)
			}
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		require.NoError(t, err)
	}
}

// 16. Hybrid persistence: session and commands flushed to DB on close.
func TestCloseSession_FlushedToDB(t *testing.T) {
	m, database := newManagerWithDB(t)
	sess, _ := m.CreateSession(context.Background(), terminal.SessionConfig{
		AutonomyLevel: terminal.LevelAutonomous,
	})
	_, _ = m.Execute(context.Background(), terminal.CommandRequest{
		SessionID: sess.ID,
		Command:   "echo",
		Args:      []string{"persist"},
	})
	require.NoError(t, m.CloseSession(context.Background(), sess.ID))

	dbSess, err := database.GetTerminalSession(sess.ID)
	require.NoError(t, err)
	require.NotNil(t, dbSess)
	assert.Equal(t, terminal.StatusClosed, dbSess.Status)

	cmds, err := database.GetTerminalCommands(sess.ID)
	require.NoError(t, err)
	require.Len(t, cmds, 1)
	assert.Equal(t, "echo", cmds[0].Command)
}

// 17. Custom AllowedCmds overrides level defaults at PICO.
func TestExecute_CustomAllowedCmds(t *testing.T) {
	m := newManager(t)
	sess, _ := m.CreateSession(context.Background(), terminal.SessionConfig{
		AutonomyLevel: terminal.LevelPico,
		AllowedCmds:   []string{"git"},
	})
	res, err := m.Execute(context.Background(), terminal.CommandRequest{
		SessionID: sess.ID,
		Command:   "git",
		Args:      []string{"--version"},
	})
	require.NoError(t, err)
	assert.Empty(t, res.Error, "git should be allowed via custom AllowedCmds")
}

// 18. GetCommands returns in-memory command history.
func TestGetCommands_InMemory(t *testing.T) {
	m := newManager(t)
	sess, _ := m.CreateSession(context.Background(), terminal.SessionConfig{
		AutonomyLevel: terminal.LevelAutonomous,
	})
	_, _ = m.Execute(context.Background(), terminal.CommandRequest{
		SessionID: sess.ID, Command: "echo", Args: []string{"a"},
	})
	_, _ = m.Execute(context.Background(), terminal.CommandRequest{
		SessionID: sess.ID, Command: "echo", Args: []string{"b"},
	})
	cmds, err := m.GetCommands(context.Background(), sess.ID)
	require.NoError(t, err)
	assert.Len(t, cmds, 2)
	assert.Equal(t, "echo", cmds[0].Command)
}

// 19. Non-zero exit code propagated correctly with trace ID set.
func TestExecute_NonZeroExitCode(t *testing.T) {
	m := newManager(t)
	sess, _ := m.CreateSession(context.Background(), terminal.SessionConfig{
		AutonomyLevel: terminal.LevelAutonomous,
	})
	res, err := m.Execute(context.Background(), terminal.CommandRequest{
		SessionID: sess.ID,
		Command:   "false",
	})
	require.NoError(t, err)
	assert.Equal(t, 1, res.ExitCode)
	// TraceID is a 32-hex-char string or all-zeros in no-op OTel mode.
	assert.NotEmpty(t, res.TraceID)
}

// 20. Shutdown flushes all sessions to DB.
func TestShutdown_FlushesSessions(t *testing.T) {
	m, database := newManagerWithDB(t)
	sess1, _ := m.CreateSession(context.Background(), terminal.SessionConfig{AutonomyLevel: terminal.LevelAutonomous})
	sess2, _ := m.CreateSession(context.Background(), terminal.SessionConfig{AutonomyLevel: terminal.LevelAutonomous})

	require.NoError(t, m.Shutdown(context.Background()))

	for _, id := range []string{sess1.ID, sess2.ID} {
		s, err := database.GetTerminalSession(id)
		require.NoError(t, err)
		require.NotNil(t, s, "session %s should be in DB", id)
		assert.Equal(t, terminal.StatusTimedOut, s.Status)
	}
}
