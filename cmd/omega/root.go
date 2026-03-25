package main

import (
	"fmt"
	"net/http"
	"os"
	"strings"

	"connectrpc.com/connect"
	"github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

var (
	cfgFile string
	apiURL  string

	rootCmd = &cobra.Command{
		Use:   "omega",
		Short: "Omega — self-improving AI orchestration CLI",
		Long:  "Control and observe the Omega AI orchestration system via Connect-RPC.",
	}
)

func init() {
	cobra.OnInitialize(initConfig)

	rootCmd.PersistentFlags().StringVar(&cfgFile, "config", "", "config file (default: omega.yml)")
	rootCmd.PersistentFlags().StringVar(&apiURL, "api-url", "http://localhost:8080", "Omega API base URL")

	_ = viper.BindPFlag("api_url", rootCmd.PersistentFlags().Lookup("api-url"))
	viper.SetEnvPrefix("OMEGA")
	viper.SetEnvKeyReplacer(strings.NewReplacer("-", "_"))
	viper.AutomaticEnv()

	rootCmd.AddCommand(runCmd)    // omega run  — start full stack
	rootCmd.AddCommand(cycleCmd)  // omega cycle — orchestrator heartbeat loop
	rootCmd.AddCommand(statusCmd)
	rootCmd.AddCommand(backtestCmd)
	rootCmd.AddCommand(challengesCmd)
	rootCmd.AddCommand(nodesCmd)
	rootCmd.AddCommand(projectsCmd)
	rootCmd.AddCommand(marketsCmd)
	rootCmd.AddCommand(brainCmd)
}

func initConfig() {
	if cfgFile != "" {
		viper.SetConfigFile(cfgFile)
	} else {
		viper.SetConfigName("omega")
		viper.SetConfigType("yml")
		viper.AddConfigPath(".")
		viper.AddConfigPath("$HOME/.omega")
	}

	if err := viper.ReadInConfig(); err == nil {
		fmt.Fprintf(os.Stderr, "Using config: %s\n", viper.ConfigFileUsed())
	}

	// Override from flag if explicitly set
	if rootCmd.PersistentFlags().Lookup("api-url").Changed {
		viper.Set("api_url", apiURL)
	}
}

func getAPIURL() string {
	if u := viper.GetString("api_url"); u != "" {
		return u
	}
	return "http://localhost:8080"
}

func newOrchestratorClient() omegav1connect.OrchestratorServiceClient {
	return omegav1connect.NewOrchestratorServiceClient(
		http.DefaultClient,
		getAPIURL(),
		connect.WithGRPC(),
	)
}
