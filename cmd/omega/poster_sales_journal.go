package main

import (
	"context"
	"database/sql"
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
	"google.golang.org/protobuf/proto"
)

func journalConnection(source string) (*commerce.StripeTest, *sql.DB, error) {
	if source != "" {
		return reporterConnection(source)
	}
	if os.Getenv("OMEGA_POSTER_STRIPE_TEST_KEY") != "" || os.Getenv("OMEGA_POSTER_COMMERCE_DATABASE_URL") != "" {
		return posterTestConnection()
	}
	dir, err := defaultPosterReporterDir()
	if err != nil {
		return nil, nil, err
	}
	return reporterConnection(filepath.Join(dir, "source.env"))
}

func posterSalesJournalCommand() *cobra.Command {
	return posterMonthlySettlementCommand("test-journal", "Read Signal Studies settlement movements directly from the isolated test merchant", commerce.OperatorSalesJournal)
}

func posterSettlementLedgerCommand() *cobra.Command {
	var directory, costBook string
	read := func(ctx context.Context, db *sql.DB, gateway *commerce.StripeTest, business, product, month string) (*v1.SettlementLedger, error) {
		var save commerce.SettlementSourceSink
		if directory != "" {
			dir, err := openSettlementEvidenceDir(directory)
			if err != nil {
				return nil, err
			}
			defer func() { _ = dir.Close() }()
			save = func(digest string, raw []byte) error { return saveSettlementStatement(dir, digest, raw) }
		}
		if costBook == "" {
			return commerce.OperatorSettlementLedger(ctx, db, gateway, business, product, month, save)
		}
		sources := make(map[string][]byte)
		ledger, account, err := commerce.OperatorSettlementLedgerWithMerchant(ctx, db, gateway, business, product, month, func(digest string, raw []byte) error {
			if save != nil {
				if err := save(digest, raw); err != nil {
					return err
				}
			}
			sources[digest] = raw
			return nil
		})
		if err != nil {
			return nil, err
		}
		book, err := openPosterCostBook(costBook, false)
		if err != nil {
			return nil, err
		}
		defer book.Close()
		if err := book.RecordTestFees(account, ledger, sources); err != nil {
			return nil, err
		}
		return ledger, nil
	}
	command := posterMonthlySettlementCommand("test-ledger", "Read Signal Studies processor settlement postings and refund evidence from the isolated test merchant", read)
	command.Flags().StringVar(&directory, "evidence-dir", "", "Keep each exact source statement as <sha256>.json in this private directory")
	command.Flags().StringVar(&costBook, "cost-book", "", "Record verified Stripe test fees against each order's edition in this local cost book")
	command.PreRunE = func(cmd *cobra.Command, _ []string) error {
		if cmd.Flags().Changed("evidence-dir") && directory == "" {
			return errors.New("--evidence-dir requires a directory path")
		}
		if cmd.Flags().Changed("cost-book") && costBook == "" {
			return errors.New("--cost-book requires a file path")
		}
		return nil
	}
	return command
}

func posterMonthlySettlementCommand[T proto.Message](use, short string, read func(context.Context, *sql.DB, *commerce.StripeTest, string, string, string) (T, error)) *cobra.Command {
	var month, source string
	command := &cobra.Command{Use: use, Short: short, Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			gateway, db, err := journalConnection(source)
			if err != nil {
				return err
			}
			defer func() { _ = db.Close() }()
			ctx, cancel := context.WithTimeout(cmd.Context(), 5*time.Minute)
			defer cancel()
			report, err := read(ctx, db, gateway, posters.StudioBusinessID, posters.StudioProductID, month)
			if err != nil {
				return err
			}
			body, err := (protojson.MarshalOptions{Indent: "  ", EmitDefaultValues: true}).Marshal(report)
			if err != nil {
				return err
			}
			_, err = fmt.Fprintln(cmd.OutOrStdout(), string(body))
			return err
		}}
	command.Flags().StringVar(&month, "month", time.Now().UTC().Format("2006-01"), "UTC transaction month (YYYY-MM)")
	command.Flags().StringVar(&source, "credentials", "", "Owner-only source file (defaults to the paired reporter when test environment variables are absent)")
	return command
}
