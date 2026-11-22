package main

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/benebsworth/omega/internal/commerce"
	"github.com/benebsworth/omega/projects/posters"
	"github.com/spf13/cobra"
	"google.golang.org/protobuf/encoding/protojson"
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
	var month, source string
	command := &cobra.Command{Use: "test-journal", Short: "Read Signal Studies settlement movements directly from the isolated test merchant", Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			gateway, db, err := journalConnection(source)
			if err != nil {
				return err
			}
			defer func() { _ = db.Close() }()
			ctx, cancel := context.WithTimeout(cmd.Context(), 5*time.Minute)
			defer cancel()
			journal, err := commerce.OperatorSalesJournal(ctx, db, gateway, posters.StudioBusinessID, posters.StudioProductID, month)
			if err != nil {
				return err
			}
			body, err := (protojson.MarshalOptions{Indent: "  ", EmitDefaultValues: true}).Marshal(journal)
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
