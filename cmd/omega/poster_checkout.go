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
	"path/filepath"
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

func readLaunchReview(name, link string) (*v1.VerifiedChannelLaunchReview, []byte, error) {
	return posters.VerifyLaunchReview(os.DirFS(filepath.Dir(name)), filepath.Base(name), link)
}

func posterVerifyLaunchReviewCommand() *cobra.Command {
	var link string
	cmd := &cobra.Command{
		Use: "verify-launch-review REVIEW_ZIP", Short: "Verify the private Etsy preparation package and its exact Studio checksum",
		Args: cobra.ExactArgs(1), RunE: func(cmd *cobra.Command, args []string) error {
			result, _, err := readLaunchReview(args[0], link)
			if err != nil {
				return err
			}
			body, err := (protojson.MarshalOptions{Indent: "  "}).Marshal(result)
			if err != nil {
				return err
			}
			_, err = fmt.Fprintln(cmd.OutOrStdout(), string(body))
			return err
		},
	}
	cmd.Flags().StringVar(&link, "from", "", "Full launch review ZIP download link copied from Studio")
	_ = cmd.MarkFlagRequired("from")
	return cmd
}

type posterCheckoutSource struct {
	packetFile, digest, offerFile, offerFrom, launchFile, launchFrom string
}

func (source posterCheckoutSource) selectOffer(cmd *cobra.Command) ([]byte, string, *v1.DigitalOffer, error) {
	if cmd.Flags().Changed("launch-review") {
		checked, packet, err := readLaunchReview(source.launchFile, source.launchFrom)
		if err != nil {
			return nil, "", nil, err
		}
		return packet, checked.PacketSha256, checked.Offer, nil
	}
	raw, err := readPosterDocument(source.packetFile)
	if err != nil {
		return nil, "", nil, err
	}
	var offer *v1.DigitalOffer
	if cmd.Flags().Changed("offer-file") {
		offer, err = readStudioTestOffer(source.offerFile, raw, source.offerFrom)
		if err != nil {
			return nil, "", nil, err
		}
		if offer.PacketSha256 != source.digest {
			return nil, "", nil, errors.New("the selected offer and the supplied packet digest differ")
		}
	}
	return raw, source.digest, offer, nil
}

func posterCheckoutCommand() *cobra.Command {
	var source posterCheckoutSource
	var address, captionFiles string
	cmd := &cobra.Command{
		Use: "test-checkout COLLECTION_DIRECTORY", Short: "Run the approved poster edition against a separate Stripe sandbox",
		Args: cobra.ExactArgs(1), RunE: func(cmd *cobra.Command, args []string) error {
			host, _, err := net.SplitHostPort(address)
			if err != nil || net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback() {
				return errors.New("choose a loopback address and port")
			}
			raw, digest, studioOffer, err := source.selectOffer(cmd)
			if err != nil {
				return err
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
	cmd.Flags().StringVar(&source.packetFile, "packet", "", "Exact review packet downloaded from Studio")
	cmd.Flags().StringVar(&captionFiles, "caption-files", "", "Directory containing the exported caption edition's signal-studies.zip and edition-preview.pdf")
	cmd.Flags().StringVar(&source.digest, "packet-sha256", "", "Packet digest from the approved private listing receipt")
	cmd.Flags().StringVar(&source.offerFile, "offer-file", "", "Optional issued Studio test offer JSON")
	cmd.Flags().StringVar(&source.offerFrom, "offer-from", "", "Exact Studio download link for --offer-file")
	cmd.MarkFlagsRequiredTogether("offer-file", "offer-from")
	cmd.Flags().StringVar(&address, "listen", "127.0.0.1:9746", "Loopback listener for the test checkout and signed events")
	cmd.Flags().StringVar(&source.launchFile, "launch-review", "", "Studio launch review ZIP containing its issued packet and test offer")
	cmd.Flags().StringVar(&source.launchFrom, "launch-review-from", "", "Exact Studio download link for --launch-review")
	cmd.MarkFlagsRequiredTogether("packet", "packet-sha256")
	cmd.MarkFlagsRequiredTogether("launch-review", "launch-review-from")
	cmd.MarkFlagsOneRequired("packet", "launch-review")
	cmd.MarkFlagsMutuallyExclusive("packet", "launch-review")
	cmd.MarkFlagsMutuallyExclusive("offer-file", "launch-review")
	return cmd
}
