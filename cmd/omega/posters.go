package main

import (
	"fmt"
	"os"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/projects/posters"
	"github.com/spf13/cobra"
	"google.golang.org/protobuf/encoding/protojson"
)

func init() {
	command := &cobra.Command{Use: "posters", Short: "Operate the Signal Studies poster business"}
	command.AddCommand(posterCheckoutCommand(), posterOrderReceiptCommand(), posterStatementCommand())
	var edition string
	prepare := &cobra.Command{
		Use:   "prepare COLLECTION_DIRECTORY",
		Short: "Verify the six delivery PDFs and emit the selected release candidate",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			candidate, err := posters.CandidateForEdition(os.DirFS(args[0]), edition)
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
	prepare.Flags().StringVar(&edition, "edition", posters.OriginalEdition, "Edition to verify ("+posters.OriginalEdition+" or "+posters.EditorialEdition+")")
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
