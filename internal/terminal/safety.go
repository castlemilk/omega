package terminal

import "strings"

// defaultBlockedCmds are ALWAYS rejected regardless of autonomy level.
// Matching is case-insensitive substring search on the full command string
// to catch variants like "sudo shutdown" or "env rm -rf /".
var defaultBlockedCmds = []string{
	"rm -rf /",
	"shutdown",
	"reboot",
	"halt",
	"poweroff",
	"mkfs",
	"dd if=/dev/zero",
	"dd if=/dev/urandom of=/dev/sd",
	":(){ :|:& };:",
	"> /dev/sda",
	">/dev/sda",
}

// picoAllowedPrefixes are the only commands permitted at PICO autonomy level.
// Read-only introspection only.
var picoAllowedPrefixes = []string{
	"ls", "cat", "head", "tail", "grep", "find", "ps", "top", "df", "du",
	"echo", "date", "whoami", "pwd", "env", "printenv", "uname",
	"go test", "go build", "go vet",
	"python -c", "python3 -c",
	"wc", "sort", "uniq", "cut", "awk", "sed -n", "diff", "file", "stat",
}

// supervisedAllowedPrefixes are the commands permitted at SUPERVISED level
// (extends pico with safe writes and common dev tooling).
var supervisedAllowedPrefixes = []string{
	"mkdir", "touch", "cp", "mv", "chmod", "chown",
	"go run", "go get", "go mod",
	"python", "python3", "pip", "pip3",
	"npm", "npx", "node",
	"git status", "git log", "git diff", "git fetch", "git pull",
	"git branch", "git show", "git stash",
	"curl", "wget",
	"make", "cargo", "rustc",
}

// isHardBlocked returns true if cmd matches any entry in the hard-block list
// (defaults merged with any session-level extras). Matching is case-insensitive
// substring to catch "sudo rm -rf /" etc.
func isHardBlocked(cmd string, extra []string) bool {
	normalised := strings.ToLower(strings.TrimSpace(cmd))
	all := append(defaultBlockedCmds, extra...) //nolint:gocritic
	for _, b := range all {
		if strings.Contains(normalised, strings.ToLower(b)) {
			return true
		}
	}
	return false
}

// isAllowedForLevel returns true if the command is permitted at the given
// autonomy level.  At "autonomous" everything that isn't hard-blocked is
// allowed.  If the session has an explicit AllowedCmds list that takes
// precedence over the level defaults.
func isAllowedForLevel(cmd string, level string, sessionAllowed []string) bool {
	if level == LevelAutonomous {
		return true
	}
	var candidates []string
	if len(sessionAllowed) > 0 {
		candidates = sessionAllowed
	} else {
		switch level {
		case LevelSupervised:
			combined := make([]string, 0, len(picoAllowedPrefixes)+len(supervisedAllowedPrefixes))
			combined = append(combined, picoAllowedPrefixes...)
			combined = append(combined, supervisedAllowedPrefixes...)
			candidates = combined
		default: // "pico" and any unrecognised level
			candidates = picoAllowedPrefixes
		}
	}
	normalised := strings.ToLower(strings.TrimSpace(cmd))
	for _, allowed := range candidates {
		if strings.HasPrefix(normalised, strings.ToLower(allowed)) {
			return true
		}
	}
	return false
}
