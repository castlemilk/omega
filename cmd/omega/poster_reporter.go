package main

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/commerce"
	"github.com/benebsworth/omega/projects/posters"
	"github.com/spf13/cobra"
	"google.golang.org/protobuf/encoding/protojson"
)

const posterReporterEndpoint = "https://studio.dropshippr-apps.workers.dev/api/reporters/signal-studies/statement"

func defaultPosterReporterDir() (string, error) {
	base, err := os.UserConfigDir()
	if err != nil {
		return "", errors.New("could not locate the current user's application support directory")
	}
	return filepath.Join(base, "Omega", "Signal Studies Reporter"), nil
}

func posterReporterCommand() *cobra.Command {
	return posterReporterCommandWithClock(time.Now)
}

func posterReporterCommandWithClock(now func() time.Time) *cobra.Command {
	var directory, credentials string
	parent := &cobra.Command{Use: "reporter", Short: "Send verified Signal Studies test order statements to the private Studio"}
	parent.PersistentFlags().StringVar(&directory, "directory", "", "Private reporter directory (defaults to the user's application support directory)")
	parent.PersistentFlags().StringVar(&credentials, "credentials", "", "Owner-only credential file (defaults to source.env in the reporter directory)")
	paths := func() (string, string, error) {
		dir := directory
		if dir == "" {
			located, err := defaultPosterReporterDir()
			if err != nil {
				return "", "", err
			}
			dir = located
		}
		dir, err := filepath.Abs(dir)
		if err != nil {
			return "", "", errors.New("invalid reporter directory")
		}
		if credentials == "" {
			return dir, filepath.Join(dir, "source.env"), nil
		}
		source, err := filepath.Abs(credentials)
		return dir, source, err
	}
	initialize := &cobra.Command{Use: "init", Short: "Create or reuse the private signing key and print its public key", Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			dir, _, err := paths()
			if err != nil {
				return err
			}
			key, err := reporterKey(dir, true)
			if err != nil {
				return err
			}
			_, err = fmt.Fprintln(cmd.OutOrStdout(), base64.RawURLEncoding.EncodeToString(key.Public().(ed25519.PublicKey)))
			return err
		}}
	var from, through string
	var days int
	run := &cobra.Command{Use: "run", Short: "Verify the order period and send one signed statement", Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if (cmd.Flags().Changed("from") && from == "") || (cmd.Flags().Changed("through") && through == "") {
				return errors.New("both explicit date flags require a UTC day")
			}
			first, last, err := reporterWindow(from, through, days, cmd.Flags().Changed("days"), now())
			if err != nil {
				return err
			}
			dir, source, err := paths()
			if err != nil {
				return err
			}
			key, err := reporterKey(dir, false)
			if err != nil {
				return err
			}
			state := localReporterState(dir, key)
			receipt, err := runReporterCheck(state, first, last, now, func() (*v1.CommerceReporterReceipt, error) {
				return sendReporterWindow(cmd.Context(), key, source, first, last, from == "" && through == "")
			})
			if receipt == nil {
				return err
			}
			data, marshalErr := protojson.Marshal(receipt)
			if marshalErr != nil {
				return errors.New("could not format the receipt")
			}
			_, printErr := fmt.Fprintln(cmd.OutOrStdout(), string(data))
			return errors.Join(err, printErr)
		}}
	run.Flags().IntVar(&days, "days", 30, "Rolling UTC order creation days through today (1–366)")
	run.Flags().StringVar(&from, "from", "", "First UTC order creation day (YYYY-MM-DD)")
	run.Flags().StringVar(&through, "through", "", "Last UTC order creation day, inclusive (YYYY-MM-DD)")
	var asJSON bool
	status := &cobra.Command{Use: "status", Short: "Show the latest local attempt, retry time and acknowledged check", Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			dir, _, err := paths()
			if err != nil {
				return err
			}
			key, err := reporterKey(dir, false)
			if err != nil {
				return err
			}
			result, err := localReporterState(dir, key).status(now())
			if err != nil {
				return err
			}
			if asJSON {
				data, err := protojson.Marshal(result)
				if err != nil {
					return err
				}
				_, err = fmt.Fprintln(cmd.OutOrStdout(), string(data))
				return err
			}
			return printReporterStatus(cmd.OutOrStdout(), result)
		}}
	status.Flags().BoolVar(&asJSON, "json", false, "Print the local status as JSON")
	var binary string
	var scheduledDays int
	install := &cobra.Command{Use: "install", Short: "Install the current Mac user's five-minute reporter", Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			dir, source, err := paths()
			if err != nil {
				return err
			}
			if _, _, err = reporterWindow("", "", scheduledDays, true, now()); err != nil {
				return err
			}
			if _, err = reporterKey(dir, false); err != nil {
				return err
			}
			_, db, err := reporterConnection(source)
			if err != nil {
				return err
			}
			_ = db.Close()
			if err = installReporterAgent(cmd.Context(), dir, source, binary, scheduledDays); err != nil {
				return err
			}
			_, err = fmt.Fprintln(cmd.OutOrStdout(), "Installed the five-minute Signal Studies reporter.")
			return err
		}}
	install.Flags().StringVar(&binary, "executable", "", "Absolute path to the installed Omega executable (defaults to this executable)")
	install.Flags().IntVar(&scheduledDays, "days", 30, "Rolling UTC order creation days through today (1–366)")
	disable := &cobra.Command{Use: "disable", Short: "Stop the current Mac user's reporter across future logins", Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if err := disableReporterAgent(cmd.Context()); err != nil {
				return err
			}
			_, err := fmt.Fprintln(cmd.OutOrStdout(), "Disabled the Signal Studies reporter.")
			return err
		}}
	parent.AddCommand(initialize, run, status, install, disable)
	return parent
}

func sendReporterWindow(parent context.Context, key ed25519.PrivateKey, source, first, last string, rolling bool) (*v1.CommerceReporterReceipt, error) {
	ctx, cancel := context.WithTimeout(parent, reporterRunTimeout)
	defer cancel()
	gateway, db, err := reporterConnection(source)
	if err != nil {
		return nil, err
	}
	defer func() { _ = db.Close() }()
	read := func(parent context.Context, first, last string) (*v1.CommerceStatement, error) {
		readCtx, endRead := context.WithTimeout(parent, 5*time.Minute)
		defer endRead()
		statement, err := commerce.OperatorStatement(readCtx, db, gateway, posters.StudioBusinessID, posters.StudioProductID, first, last)
		if err != nil && !errors.Is(err, commerce.ErrStatementRateLimited) {
			return nil, errors.New("the reporter could not verify this order period against its isolated database and Stripe account")
		}
		return statement, err
	}
	statement, err := read(ctx, first, last)
	if err != nil {
		return nil, err
	}
	if rolling {
		return commerce.SubmitRollingStatement(ctx, posterReporterEndpoint, key, statement, read)
	}
	return commerce.SubmitStatement(ctx, posterReporterEndpoint, key, statement)
}

func runReporterCheck(state reporterState, from, through string, clock func() time.Time, check func() (*v1.CommerceReporterReceipt, error)) (*v1.CommerceReporterReceipt, error) {
	started := clock()
	if err := state.begin(started, from, through); err != nil {
		return nil, err
	}
	receipt, result := check()
	if receipt == nil && result == nil {
		result = errors.New("Studio did not acknowledge the check")
	}
	status, saveErr := state.finish(started, clock(), receipt, result)
	if saveErr == nil && errors.Is(result, commerce.ErrStatementRateLimited) {
		result = fmt.Errorf("%w. Next eligible check %s", result, status.NextProviderReadAt)
	}
	return receipt, errors.Join(result, saveErr)
}

func printReporterStatus(w io.Writer, s *v1.LocalReporterStatus) error {
	var out string
	switch s.Outcome {
	case "never-run":
		out = "This Mac has not recorded a check for this connection yet."
	case "checking":
		out = "An order check is in progress."
	case "interrupted":
		out = "The last order check was interrupted. The next wake can retry."
	case "rate-limited":
		out = "Stripe is limiting test order reads."
		if s.LimitReason == "sandbox-quota" {
			out = "Stripe has limited reads in this test sandbox."
		}
	case "acknowledged":
		out = "Studio acknowledged the last order check."
	case "recheck-rate-limited":
		out = "Studio acknowledged the order period. Stripe is limiting the check for its earlier dates."
	case "recheck-pending":
		out = "Studio acknowledged the order period. Its earlier dates still need a check."
	default:
		out = "The last order check could not finish."
	}
	if s.AttemptAt != "" {
		out += fmt.Sprintf("\nLast attempt %s for %s through %s", s.AttemptAt, s.FromDay, s.ThroughDay)
	}
	if s.NextProviderReadAt != "" {
		out += "\nNext eligible check " + s.NextProviderReadAt
	}
	if s.LastReceipt != nil {
		out += fmt.Sprintf("\nLast acknowledged check %s for %s through %s", s.LastReceipt.CheckedAt, s.ReceiptFromDay, s.ReceiptThroughDay)
	} else if s.Outcome != "never-run" {
		out += "\nThis Mac has not yet recorded an acknowledgement from Studio for this connection."
	}
	_, err := fmt.Fprintln(w, out)
	return err
}

func reporterWindow(from, through string, days int, daysGiven bool, now time.Time) (string, string, error) {
	now = now.UTC()
	if from == "" && through == "" {
		if days < 1 || days > 366 {
			return "", "", errors.New("choose 1–366 rolling UTC days")
		}
		return now.AddDate(0, 0, 1-days).Format(time.DateOnly), now.Format(time.DateOnly), nil
	}
	if daysGiven {
		return "", "", errors.New("use either --days or both --from and --through")
	}
	if _, _, err := commerce.StatementWindow(from, through, now); err != nil {
		return "", "", err
	}
	return from, through, nil
}
