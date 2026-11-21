package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

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
	return gateway, db, err
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

func posterCheckoutCommand() *cobra.Command {
	var packetFile, digest, address string
	cmd := &cobra.Command{
		Use: "test-checkout COLLECTION_DIRECTORY", Short: "Run the approved poster edition against a separate Stripe sandbox",
		Args: cobra.ExactArgs(1), RunE: func(cmd *cobra.Command, args []string) error {
			host, _, err := net.SplitHostPort(address)
			if err != nil || net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback() {
				return errors.New("choose a loopback address and port")
			}
			f, err := os.Open(packetFile)
			if err != nil {
				return err
			}
			defer f.Close()
			raw, err := io.ReadAll(io.LimitReader(f, 1<<20+1))
			if err != nil || len(raw) > 1<<20 {
				return errors.New("invalid poster review file")
			}
			offer, archive, preview, err := posters.TestOffer(os.DirFS(args[0]), raw, digest)
			if err != nil {
				return err
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
				Handler:           shop.Handler(posters.CheckoutPage, "Signal Studies", "AUD 12.00", "https://studio.dropshippr-apps.workers.dev/collections/signal-studies?view=store", preview),
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
	cmd.Flags().StringVar(&digest, "packet-sha256", "", "Packet digest from the approved private listing receipt")
	cmd.Flags().StringVar(&address, "listen", "127.0.0.1:9746", "Loopback listener for the test checkout and signed events")
	_ = cmd.MarkFlagRequired("packet")
	_ = cmd.MarkFlagRequired("packet-sha256")
	return cmd
}
