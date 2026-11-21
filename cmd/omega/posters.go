package main

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/projects/posters"
	"github.com/spf13/cobra"
	"google.golang.org/protobuf/encoding/protojson"
)

func posterCollection(directory, captionFiles string) fs.FS {
	collection := os.DirFS(directory)
	if captionFiles == "" {
		return collection
	}
	return posters.WithCaptionFiles(collection, os.DirFS(captionFiles))
}

func readPosterReview(name string) ([]byte, error) {
	f, err := os.Open(name)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	const maxReviewSize = 1 << 20
	raw, err := io.ReadAll(io.LimitReader(f, maxReviewSize+1))
	if err != nil || len(raw) > maxReviewSize {
		return nil, errors.New("invalid poster review file")
	}
	return raw, nil
}

func posterVerifySellerCommand() *cobra.Command {
	var link string
	command := &cobra.Command{
		Use:   "verify-seller SELLER_ZIP REVIEW_PACKET",
		Short: "Check the seller photos, listing and buyer files against the selected Studio download",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			raw, err := readPosterReview(args[1])
			if err != nil {
				return err
			}
			draft, err := posters.VerifySellerPack(os.DirFS(filepath.Dir(args[0])), filepath.Base(args[0]), raw, link)
			if err != nil {
				return err
			}
			_, err = cmd.OutOrStdout().Write(draft)
			return err
		},
	}
	command.Flags().StringVar(&link, "from", "", "Full seller ZIP download link copied from the selected Studio edition")
	_ = command.MarkFlagRequired("from")
	return command
}

func init() {
	command := &cobra.Command{Use: "posters", Short: "Operate the Signal Studies poster business"}
	command.AddCommand(posterCheckoutCommand(), posterOrderReceiptCommand(), posterStatementCommand(), posterReporterCommand(), posterVerifySellerCommand())
	var edition, captionFiles string
	prepare := &cobra.Command{
		Use:   "prepare COLLECTION_DIRECTORY",
		Short: "Verify the six delivery PDFs and emit the selected release candidate",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			candidate, err := posters.CandidateForEdition(posterCollection(args[0], captionFiles), edition)
			if err != nil {
				return err
			}
			data, err := posters.StableJSON(candidate)
			if err != nil {
				return err
			}
			_, err = fmt.Fprintln(cmd.OutOrStdout(), string(data))
			return err
		},
	}
	prepare.Flags().StringVar(&edition, "edition", posters.OriginalEdition, "Edition to verify ("+posters.OriginalEdition+", "+posters.EditorialEdition+", or "+posters.CaptionEdition+")")
	prepare.Flags().StringVar(&captionFiles, "caption-files", "", "Directory containing the exported caption edition's signal-studies.zip and edition-preview.pdf")
	command.AddCommand(prepare)
	var experiment, source, from, through, evidence string
	measure := &cobra.Command{
		Use:   "measure OBSERVATIONS.csv",
		Short: "Assess one listing's channel experiment from daily observations",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			file, err := os.Open(args[0])
			if err != nil {
				return err
			}
			defer file.Close()
			kinds := map[string]v1.PosterObservationKind{
				"reported":  v1.PosterObservationKind_POSTER_OBSERVATION_KIND_REPORTED,
				"simulated": v1.PosterObservationKind_POSTER_OBSERVATION_KIND_SIMULATED,
			}
			report, err := posters.MeasureChannel(file, experiment, source, from, through, kinds[evidence], time.Now())
			if err != nil {
				return err
			}
			content, err := (protojson.MarshalOptions{Indent: "  "}).Marshal(report)
			if err != nil {
				return err
			}
			_, err = fmt.Fprintln(cmd.OutOrStdout(), string(content))
			return err
		},
	}
	measure.Flags().StringVar(&experiment, "experiment", "", "Experiment ID in the source file")
	measure.Flags().StringVar(&source, "source", "", "Exact HTTPS measurement source for this listing")
	measure.Flags().StringVar(&from, "from", "", "First UTC day (YYYY-MM-DD)")
	measure.Flags().StringVar(&through, "through", "", "Last UTC day, inclusive (YYYY-MM-DD)")
	measure.Flags().StringVar(&evidence, "evidence", "", "Identify the observations as reported or simulated")
	for _, name := range []string{"experiment", "source", "from", "through", "evidence"} {
		_ = measure.MarkFlagRequired(name)
	}
	command.AddCommand(measure)
	rootCmd.AddCommand(command)
}
