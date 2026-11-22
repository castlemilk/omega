package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/commerce"
	"github.com/benebsworth/omega/projects/posters"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/spf13/cobra"
	"google.golang.org/protobuf/encoding/protojson"
)

func posterTestConnection() (*commerce.StripeTest, *sql.DB, error) {
	gateway, err := commerce.NewStripeTest(os.Getenv("OMEGA_POSTER_STRIPE_TEST_KEY"))
	if err != nil {
		return nil, nil, err
	}
	dsn := os.Getenv("OMEGA_POSTER_COMMERCE_DATABASE_URL")
	if dsn == "" {
		return nil, nil, errors.New("set OMEGA_POSTER_COMMERCE_DATABASE_URL to the sandbox order database")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, nil, errors.New("the sandbox order database connection could not be opened")
	}
	return gateway, db, nil
}

func posterOrderReceiptCommand() *cobra.Command {
	return &cobra.Command{
		Use: "test-order-receipt ORDER_ID", Short: "Verify and export a Signal Studies sandbox order for the operator",
		Args: cobra.ExactArgs(1), RunE: func(cmd *cobra.Command, args []string) error {
			gateway, db, err := posterTestConnection()
			if err != nil {
				return err
			}
			defer db.Close()
			ctx, cancel := context.WithTimeout(cmd.Context(), 25*time.Second)
			defer cancel()
			receipt, err := commerce.OperatorReceipt(ctx, db, gateway, posters.StudioBusinessID, posters.StudioProductID, args[0])
			if err != nil {
				return err
			}
			body, err := (protojson.MarshalOptions{Indent: "  ", EmitDefaultValues: true}).Marshal(receipt)
			if err != nil {
				return err
			}
			_, err = fmt.Fprintln(cmd.OutOrStdout(), string(body))
			return err
		},
	}
}

func posterStatementCommand() *cobra.Command {
	var from, through string
	command := &cobra.Command{
		Use: "test-statement", Short: "Export a provider-verified statement for Signal Studies test orders",
		Args: cobra.NoArgs, RunE: func(cmd *cobra.Command, _ []string) error {
			gateway, db, err := posterTestConnection()
			if err != nil {
				return err
			}
			defer func() { _ = db.Close() }()
			ctx, cancel := context.WithTimeout(cmd.Context(), 5*time.Minute)
			defer cancel()
			statement, err := commerce.OperatorStatement(ctx, db, gateway, posters.StudioBusinessID, posters.StudioProductID, from, through)
			if err != nil {
				return err
			}
			body, err := commerce.StatementJSON(statement)
			if err != nil {
				return err
			}
			_, err = cmd.OutOrStdout().Write(body)
			return err
		},
	}
	command.Flags().StringVar(&from, "from", "", "First UTC order creation day (YYYY-MM-DD)")
	command.Flags().StringVar(&through, "through", "", "Last UTC order creation day, inclusive (YYYY-MM-DD)")
	_ = command.MarkFlagRequired("from")
	_ = command.MarkFlagRequired("through")
	return command
}

func posterVerifyTestOfferCommand() *cobra.Command {
	var link string
	cmd := &cobra.Command{
		Use: "verify-test-offer OFFER_FILE REVIEW_PACKET", Short: "Check a private Studio test quote and print the verified offer",
		Args: cobra.ExactArgs(2), RunE: func(cmd *cobra.Command, args []string) error {
			review, err := readPosterDocument(args[1])
			if err != nil {
				return err
			}
			offer, err := readStudioTestOffer(args[0], review, link)
			if err != nil {
				return err
			}
			raw, err := (protojson.MarshalOptions{Indent: "  "}).Marshal(offer)
			if err != nil {
				return err
			}
			_, err = fmt.Fprintln(cmd.OutOrStdout(), string(raw))
			return err
		},
	}
	cmd.Flags().StringVar(&link, "from", "", "Full test offer download link copied from the issued Studio edition")
	_ = cmd.MarkFlagRequired("from")
	return cmd
}

func readStudioTestOffer(name string, review []byte, link string) (*v1.DigitalOffer, error) {
	body, err := readPosterDocument(name)
	if err != nil {
		return nil, err
	}
	return posters.VerifyTestOffer(body, review, link)
}

func posterCheckoutCommand() *cobra.Command {
	var packetFile, digest, address, captionFiles, offerFile, offerFrom string
	cmd := &cobra.Command{
		Use: "test-checkout COLLECTION_DIRECTORY", Short: "Run the approved poster edition against a separate Stripe sandbox",
		Args: cobra.ExactArgs(1), RunE: func(cmd *cobra.Command, args []string) error {
			host, _, err := net.SplitHostPort(address)
			if err != nil || net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback() {
				return errors.New("choose a loopback address and port")
			}
			raw, err := readPosterDocument(packetFile)
			if err != nil {
				return err
			}
			var studioOffer *v1.DigitalOffer
			if cmd.Flags().Changed("offer-file") || cmd.Flags().Changed("offer-from") {
				studioOffer, err = readStudioTestOffer(offerFile, raw, offerFrom)
				if err != nil {
					return err
				}
				if studioOffer.PacketSha256 != digest {
					return errors.New("the selected offer and the supplied packet digest differ")
				}
			}
			offer, archive, preview, err := posters.TestOffer(posterCollection(args[0], captionFiles), raw, digest)
			if err != nil {
				return err
			}
			if studioOffer != nil {
				offer = studioOffer
			}
			gateway, db, err := posterTestConnection()
			if err != nil {
				return err
			}
			defer db.Close()
			ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt, syscall.SIGTERM)
			defer stop()
			setup, cancel := context.WithTimeout(ctx, 20*time.Second)
			defer cancel()
			account, err := gateway.Account(setup)
			if err != nil {
				return errors.New("Stripe could not verify the sandbox account")
			}
			listener, err := net.Listen("tcp", address)
			if err != nil {
				return err
			}
			defer listener.Close()
			origin := "http://" + listener.Addr().String()
			shop, err := commerce.Open(setup, db, account, origin, os.Getenv("OMEGA_POSTER_STRIPE_SIGNING_SECRET"), gateway, offer, archive)
			if err != nil {
				return err
			}
			server := &http.Server{
				Handler:           shop.Handler(posters.CheckoutPage, "Signal Studies", "https://studio.dropshippr-apps.workers.dev/collections/signal-studies?view=store", preview),
				ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 35 * time.Second, IdleTimeout: 60 * time.Second,
			}
			go func() {
				<-ctx.Done()
				closeCtx, end := context.WithTimeout(context.Background(), 5*time.Second)
				defer end()
				_ = server.Shutdown(closeCtx)
			}()
			go func() {
				ticker := time.NewTicker(4 * time.Second)
				defer ticker.Stop()
				for {
					select {
					case <-ctx.Done():
						return
					case <-ticker.C:
						run, done := context.WithTimeout(ctx, 25*time.Second)
						err := shop.Drain(run)
						done()
						if err != nil && ctx.Err() == nil {
							fmt.Fprintln(cmd.ErrOrStderr(), "A sandbox order check will retry.")
						}
					}
				}
			}()
			fmt.Fprintln(cmd.OutOrStdout(), "Private poster test checkout", origin)
			if err = server.Serve(listener); errors.Is(err, http.ErrServerClosed) {
				return nil
			}
			return err
		},
	}
	cmd.Flags().StringVar(&packetFile, "packet", "", "Exact review packet downloaded from Studio")
	cmd.Flags().StringVar(&captionFiles, "caption-files", "", "Directory containing the exported caption edition's signal-studies.zip and edition-preview.pdf")
	cmd.Flags().StringVar(&digest, "packet-sha256", "", "Packet digest from the approved private listing receipt")
	cmd.Flags().StringVar(&offerFile, "offer-file", "", "Optional issued Studio test offer JSON")
	cmd.Flags().StringVar(&offerFrom, "offer-from", "", "Exact Studio download link for --offer-file")
	cmd.MarkFlagsRequiredTogether("offer-file", "offer-from")
	cmd.Flags().StringVar(&address, "listen", "127.0.0.1:9746", "Loopback listener for the test checkout and signed events")
	_ = cmd.MarkFlagRequired("packet")
	_ = cmd.MarkFlagRequired("packet-sha256")
	return cmd
}
