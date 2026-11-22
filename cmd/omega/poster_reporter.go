package main

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"errors"
	"fmt"
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

func posterReporterCommand() *cobra.Command {
	var directory, credentials string
	parent := &cobra.Command{Use: "reporter", Short: "Send verified Signal Studies test order statements to the private Studio"}
	parent.PersistentFlags().StringVar(&directory, "directory", "", "Private reporter directory (defaults to the user's application support directory)")
	parent.PersistentFlags().StringVar(&credentials, "credentials", "", "Owner-only credential file (defaults to source.env in the reporter directory)")
	paths := func() (string, string, error) {
		dir := directory
		if dir == "" {
			base, err := os.UserConfigDir()
			if err != nil {
				return "", "", errors.New("could not locate the current user's application support directory")
			}
			dir = filepath.Join(base, "Omega", "Signal Studies Reporter")
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
			first, last, err := reporterWindow(from, through, days, cmd.Flags().Changed("days"), time.Now())
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
			gateway, db, err := reporterConnection(source)
			if err != nil {
				return err
			}
			defer func() { _ = db.Close() }()
			ctx, cancel := context.WithTimeout(cmd.Context(), 6*time.Minute)
			defer cancel()
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
				return err
			}
			var receipt *v1.CommerceReporterReceipt
			if from == "" && through == "" {
				receipt, err = commerce.SubmitRollingStatement(ctx, posterReporterEndpoint, key, statement, read)
			} else {
				receipt, err = commerce.SubmitStatement(ctx, posterReporterEndpoint, key, statement)
			}
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
	var binary string
	var scheduledDays int
	install := &cobra.Command{Use: "install", Short: "Install the current Mac user's five-minute reporter", Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			dir, source, err := paths()
			if err != nil {
				return err
			}
			if _, _, err = reporterWindow("", "", scheduledDays, true, time.Now()); err != nil {
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
	parent.AddCommand(initialize, run, install, disable)
	return parent
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
