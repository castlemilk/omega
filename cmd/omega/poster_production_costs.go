package main

import (
	"context"
	"crypto/sha256"
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
	"google.golang.org/protobuf/proto"
)

func openPosterCostBook(path string, readOnly bool) (*commerce.ProductionCostBook, error) {
	if path == "" {
		config, err := os.UserConfigDir()
		if err != nil {
			return nil, err
		}
		path = filepath.Join(config, "Omega", "Signal Studies Costs", "costs.db")
	}
	if !readOnly {
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			return nil, err
		}
	}
	return commerce.OpenProductionCostBook(path, readOnly, openPrivateCostFile)
}

func readCostDocument(path string, limit int64) ([]byte, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() == 0 || info.Size() > limit {
		return nil, fmt.Errorf("expected a nonempty regular file no larger than %d bytes", limit)
	}
	raw, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil {
		return nil, err
	}
	if len(raw) == 0 || int64(len(raw)) > limit {
		return nil, errors.New("source file size changed during read")
	}
	return raw, nil
}

func recordPosterPreparation(bookPath, run, experiment string, candidate *v1.PosterReleaseCandidate, manifest []byte, day time.Time) (string, error) {
	book, err := openPosterCostBook(bookPath, false)
	if err != nil {
		return "", err
	}
	defer book.Close()
	r := &v1.ProductionCostReceipt{
		Provider: "omega", Account: "local-poster-production", LineId: run, Simulated: proto.Bool(false),
		ServiceDate: day.UTC().Format(time.DateOnly), Category: v1.ProductionCostCategory_PRODUCTION_COST_CATEGORY_COMPUTE, Stage: v1.ProductionCostStage_PRODUCTION_COST_STAGE_PROVISIONAL,
		EvidenceSha256: fmt.Sprintf("%x", sha256.Sum256(manifest)), Description: "Verified the edition's buyer archive and release files on the local computer.",
		AllocationBasis: "All work in this preparation belongs to the selected edition.",
		Targets: []*v1.ProductionCostTarget{{BusinessId: posters.StudioBusinessID, ProductId: posters.StudioProductID, RunId: run, ExperimentId: experiment,
			Edition: candidate.Edition, ArtifactSha256: candidate.PrintPack.Sha256, ShareBps: 10000}},
	}
	return book.Observe(r, manifest)
}

func posterProductionCostsCommand() *cobra.Command {
	var bookPath, month string
	var simulated bool
	costs := &cobra.Command{Use: "costs", Short: "Trace Signal Studies production costs to work, release files and supporting documents"}
	costs.PersistentFlags().StringVar(&bookPath, "book", "", "Private local cost book (defaults to Signal Studies Costs in the user configuration directory)")
	statement := &cobra.Command{Use: "statement", Short: "Read recorded costs for one service month and evidence mode", Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			book, err := openPosterCostBook(bookPath, true)
			if err != nil {
				return err
			}
			defer book.Close()
			value, err := book.Statement(posters.StudioBusinessID, posters.StudioProductID, month, simulated)
			if err != nil {
				return err
			}
			body, err := (protojson.MarshalOptions{Indent: "  ", EmitDefaultValues: true}).Marshal(value)
			if err != nil {
				return err
			}
			_, err = fmt.Fprintln(cmd.OutOrStdout(), string(body))
			return err
		}}
	statement.Flags().StringVar(&month, "month", time.Now().UTC().Format("2006-01"), "UTC service month (YYYY-MM)")
	statement.Flags().BoolVar(&simulated, "simulated", false, "Show the separate rehearsal costs")
	record := &cobra.Command{Use: "record RECEIPT.json SUPPORTING_FILE", Short: "Record a sourced cost or correct its current receipt", Args: cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			raw, err := readCostDocument(args[0], 1<<20)
			if err != nil {
				return err
			}
			r := new(v1.ProductionCostReceipt)
			if err := protojson.Unmarshal(raw, r); err != nil {
				return err
			}
			inScope := false
			for _, t := range r.Targets {
				if t.GetBusinessId() == posters.StudioBusinessID && t.GetProductId() == posters.StudioProductID {
					inScope = true
					break
				}
			}
			if !inScope {
				return errors.New("the receipt has no allocation to Signal Studies")
			}
			support, err := readCostDocument(args[1], commerce.MaxCostEvidenceBytes)
			if err != nil {
				return err
			}
			book, err := openPosterCostBook(bookPath, false)
			if err != nil {
				return err
			}
			defer book.Close()
			digest, err := book.Record(r, support)
			if err != nil {
				return err
			}
			_, err = fmt.Fprintln(cmd.OutOrStdout(), digest)
			return err
		}}
	var credentials string
	recoverFees := &cobra.Command{
		Use:   "recover-test-fees LEDGER.json STATEMENT.json [STATEMENT.json...]",
		Short: "Recover earlier test fees from their original ledger, source statements and local orders",
		Args:  cobra.MinimumNArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			raw, err := readCostDocument(args[0], 32<<20)
			if err != nil {
				return err
			}
			ledger := new(v1.SettlementLedger)
			if err := protojson.Unmarshal(raw, ledger); err != nil {
				return err
			}
			sources := make(map[string][]byte)
			for _, path := range args[1:] {
				bytes, err := readCostDocument(path, commerce.MaxCostEvidenceBytes)
				if err != nil {
					return err
				}
				sources[fmt.Sprintf("%x", sha256.Sum256(bytes))] = bytes
			}
			_, db, err := journalConnection(credentials)
			if err != nil {
				return err
			}
			defer db.Close()
			book, err := openPosterCostBook(bookPath, false)
			if err != nil {
				return err
			}
			defer book.Close()
			ctx, cancel := context.WithTimeout(cmd.Context(), time.Minute)
			defer cancel()
			if err := book.RecoverTestFees(ctx, db, posters.StudioBusinessID, posters.StudioProductID, ledger, sources); err != nil {
				return err
			}
			_, err = fmt.Fprintf(cmd.OutOrStdout(), "Recovered %d test fee lines for %s from sources checked at %s.\n", len(ledger.Entries), ledger.Month, ledger.LastCheckedAt)
			return err
		},
	}
	recoverFees.Flags().StringVar(&credentials, "credentials", "", "Owner-only source file for the local order database (defaults to the paired reporter)")
	costs.AddCommand(statement, record, recoverFees)
	for _, source := range []bool{false, true} {
		use, short := "receipt SHA256", "Read the exact saved cost receipt"
		if source {
			use, short = "evidence SHA256", "Read the exact supporting file bytes"
		}
		costs.AddCommand(&cobra.Command{Use: use, Short: short, Args: cobra.ExactArgs(1), RunE: func(cmd *cobra.Command, args []string) error {
			book, err := openPosterCostBook(bookPath, true)
			if err != nil {
				return err
			}
			defer book.Close()
			raw, err := book.Export(args[0], source)
			if err != nil {
				return err
			}
			_, err = cmd.OutOrStdout().Write(raw)
			return err
		}})
	}
	return costs
}
