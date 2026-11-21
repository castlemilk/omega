package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"html"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

const reporterAgentLabel = "com.omega.signal-studies-reporter"

func reporterAgentPlist(dir, source, binary string, days int) []byte {
	var arguments strings.Builder
	for _, arg := range []string{binary, "posters", "reporter", "run", "--directory", dir, "--credentials", source, "--days", strconv.Itoa(days)} {
		arguments.WriteString("    <string>" + html.EscapeString(arg) + "</string>\n")
	}
	return []byte(fmt.Sprintf(`<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>%s</string>
  <key>ProgramArguments</key>
  <array>
%s  </array>
  <key>WorkingDirectory</key><string>%s</string>
  <key>ProcessType</key><string>Background</string>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>300</integer>
  <key>StandardOutPath</key><string>/dev/null</string>
  <key>StandardErrorPath</key><string>/dev/null</string>
</dict>
</plist>
`, reporterAgentLabel, arguments.String(), html.EscapeString(dir)))
}

func reporterLaunchctl(ctx context.Context, args ...string) error {
	// launchctl's output may include the process environment. Only a checked
	// exit status is needed for install and disable.
	run, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	return exec.CommandContext(run, "/bin/launchctl", args...).Run() // #nosec G204 -- fixed executable, fixed operations, separate argv
}

func reporterAgentTarget() (string, string, error) {
	if runtime.GOOS != "darwin" || os.Geteuid() == 0 {
		return "", "", errors.New("run this command as the designated signed-in Mac user")
	}
	domain := "gui/" + strconv.Itoa(os.Geteuid())
	return domain, domain + "/" + reporterAgentLabel, nil
}

func installReporterAgent(ctx context.Context, dir, source, binary string, days int) error {
	domain, target, err := reporterAgentTarget()
	if err != nil {
		return err
	}
	if binary == "" {
		binary, err = os.Executable()
		if err != nil {
			return errors.New("could not locate the Omega executable")
		}
	}
	info, err := os.Stat(binary)
	if !filepath.IsAbs(binary) || err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0111 == 0 {
		return errors.New("choose an absolute path to the installed Omega executable")
	}
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return errors.New("could not locate the Mac user's home directory")
	}
	agents := filepath.Join(homeDir, "Library", "LaunchAgents")
	return configureReporterAgent(ctx, reporterLaunchctl, domain, target, agents, reporterAgentPlist(dir, source, binary, days))
}

func configureReporterAgent(ctx context.Context, ctl func(context.Context, ...string) error, domain, target, agents string, plist []byte) error {
	if err := os.MkdirAll(agents, 0700); err != nil {
		return errors.New("could not create the user's LaunchAgents directory")
	}
	path := filepath.Join(agents, reporterAgentLabel+".plist")
	old, readErr := os.ReadFile(path) // #nosec G304 -- fixed LaunchAgent basename in the designated user directory
	if readErr != nil && !os.IsNotExist(readErr) {
		return errors.New("could not read the existing LaunchAgent configuration")
	}
	loaded := ctl(ctx, "print", target) == nil
	if !bytes.Equal(old, plist) {
		if loaded {
			if ctl(ctx, "bootout", target) != nil {
				return errors.New("could not unload the previous reporter schedule")
			}
			loaded = false
		}
		temp, err := os.CreateTemp(agents, ".omega-reporter-*")
		if err != nil {
			return errors.New("could not create the LaunchAgent configuration")
		}
		defer func() { _ = os.Remove(temp.Name()) }()
		_, writeErr := temp.Write(plist)
		closeErr := temp.Close()
		if errors.Join(writeErr, closeErr) != nil || os.Rename(temp.Name(), path) != nil {
			return errors.New("could not save the LaunchAgent configuration")
		}

	}
	if ctl(ctx, "enable", target) != nil {
		return errors.New("could not enable the reporter for this user")
	}
	if !loaded && ctl(ctx, "bootstrap", domain, path) != nil {
		return errors.New("could not start the reporter LaunchAgent for this user")
	}
	return nil
}

func disableReporterAgent(ctx context.Context) error {
	_, target, err := reporterAgentTarget()
	if err != nil {
		return err
	}
	return stopReporterAgent(ctx, reporterLaunchctl, target)
}

func stopReporterAgent(ctx context.Context, ctl func(context.Context, ...string) error, target string) error {
	if ctl(ctx, "disable", target) != nil {
		return errors.New("could not disable the reporter for this user")
	}
	if ctl(ctx, "print", target) == nil && ctl(ctx, "bootout", target) != nil {
		return errors.New("could not stop the running reporter LaunchAgent")
	}
	return nil
}
