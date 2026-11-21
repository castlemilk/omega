package main

import (
	"fmt"
	"os"

	"github.com/benebsworth/omega/projects/posters"
	"github.com/spf13/cobra"
)

func init() {
	command := &cobra.Command{Use: "posters", Short: "Operate the Signal Studies poster business"}
	command.AddCommand(&cobra.Command{
		Use:   "prepare COLLECTION_DIRECTORY",
		Short: "Verify the six delivery PDFs and emit the selected release candidate",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			candidate, err := posters.Candidate(os.DirFS(args[0]))
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
	})
	rootCmd.AddCommand(command)
}
