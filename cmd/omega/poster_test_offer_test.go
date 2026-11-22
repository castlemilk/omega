package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"github.com/stripe/stripe-go/v87"
	"google.golang.org/protobuf/encoding/protojson"
)

type countOfferTransport int

func (c *countOfferTransport) RoundTrip(*http.Request) (*http.Response, error) {
	*c++
	return nil, fmt.Errorf("unexpected outbound request")
}

func TestPosterVerifyTestOfferAndRejectBeforeProvider(t *testing.T) {
	t.Setenv("OMEGA_POSTER_STRIPE_TEST_KEY", "sk_test_offline")
	t.Setenv("OMEGA_POSTER_COMMERCE_DATABASE_URL", "postgresql://127.0.0.1:1/no-connection")
	old := stripe.GetBackendWithConfig(stripe.APIBackend, &stripe.BackendConfig{}).(*stripe.BackendImplementation).HTTPClient
	var requests countOfferTransport
	stripe.SetHTTPClient(&http.Client{Transport: &requests})
	t.Cleanup(func() { stripe.SetHTTPClient(old) })

	dir := "../../projects/posters/testdata"
	review := filepath.Join(dir, "signal-studies-editorial-01.json")
	quote := filepath.Join(dir, "editorial-test-offer.json")
	raw, err := os.ReadFile(quote)
	require.NoError(t, err)
	const packet = "8e343a7789b0994d4093682e0849842929e47709dfe4121157670649ed19d33d"
	link := fmt.Sprintf("https://studio.dropshippr-apps.workers.dev/collections/signal-studies?view=test-offer-file&packet=%s&offer=%x", packet, sha256.Sum256(raw))
	var out bytes.Buffer
	verify := posterVerifyTestOfferCommand()
	verify.SetOut(&out)
	verify.SetArgs([]string{quote, review, "--from", link})
	require.NoError(t, verify.Execute())
	got := new(v1.DigitalOffer)
	require.NoError(t, protojson.Unmarshal(out.Bytes(), got))
	require.Equal(t, "aud", got.Currency)
	require.Equal(t, int64(1200), got.AmountMinor)
	require.Equal(t, fmt.Sprintf("%x", sha256.Sum256(raw)), got.GetStudioOfferSha256().GetValue())

	for _, tc := range []struct {
		packet string
		flags  []string
		err    string
	}{
		{packet, []string{"--offer-file", quote, "--offer-from", link + "&extra=1"}, "download link"},
		{"wrong-packet", []string{"--offer-file", quote, "--offer-from", link}, "supplied packet digest"},
		{packet, []string{"--offer-file", quote}, "must all be set"},
		{packet, []string{"--offer-from", link}, "must all be set"},
		{packet, []string{"--offer-file=", "--offer-from="}, "open"},
	} {
		cmd := posterCheckoutCommand()
		cmd.SilenceUsage = true
		cmd.SetOut(&out)
		cmd.SetErr(&out)
		cmd.SetArgs(append([]string{t.TempDir(), "--packet", review, "--packet-sha256", tc.packet}, tc.flags...))
		require.ErrorContains(t, cmd.Execute(), tc.err)
	}
	require.Zero(t, int(requests), "the local verifier and rejected checkouts must not contact Stripe")
}

func TestPosterCheckoutCommandServesIssuedPrice(t *testing.T) {
	dsn, collection := os.Getenv("OMEGA_DIGITAL_ORDER_TEST_DSN"), os.Getenv("OMEGA_POSTER_TEST_COLLECTION")
	if dsn == "" || collection == "" {
		t.Skip("use the isolated PostgreSQL checkout suite with the Studio collection")
	}
	t.Setenv("OMEGA_POSTER_COMMERCE_DATABASE_URL", dsn)
	t.Setenv("OMEGA_POSTER_STRIPE_TEST_KEY", "sk_test_local")
	t.Setenv("OMEGA_POSTER_STRIPE_SIGNING_SECRET", "whsec_fixture")
	var reads atomic.Int32
	account := "acct_fixture_" + uuid.NewString()
	provider := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/v1/account" {
			t.Errorf("unexpected provider request %s %s", r.Method, r.URL.Path)
			http.NotFound(w, r)
			return
		}
		reads.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"id": account, "object": "account"})
	}))
	defer provider.Close()
	original := stripe.GetBackendWithConfig(stripe.APIBackend, &stripe.BackendConfig{}).(*stripe.BackendImplementation).HTTPClient
	target, err := url.Parse(provider.URL)
	require.NoError(t, err)
	stripe.SetHTTPClient(&http.Client{Transport: statementTestTransport{target, provider.Client().Transport}})
	t.Cleanup(func() { stripe.SetHTTPClient(original) })

	const dir = "../../projects/posters/testdata/"
	review := dir + "signal-studies-editorial-01.json"
	raw, err := os.ReadFile(dir + "editorial-test-offer.json")
	require.NoError(t, err)
	quote := new(v1.PosterTestOffer)
	require.NoError(t, protojson.Unmarshal(raw, quote))
	quote.PriceSource, quote.PriceRevision, quote.PriceRecordedAt = "seller-draft", 2, "2026-11-22T18:32:11Z"
	quote.Currency, quote.AmountMinor, quote.SellerDraftSha256 = "USD", 1949, fmt.Sprintf("%x", sha256.Sum256([]byte("secondary seller draft")))
	selected, err := protojson.Marshal(quote)
	require.NoError(t, err)
	file := filepath.Join(t.TempDir(), "selected.json")
	require.NoError(t, os.WriteFile(file, selected, 0600))
	link := fmt.Sprintf("https://studio.dropshippr-apps.workers.dev/collections/signal-studies?view=test-offer-file&packet=%s&offer=%x", quote.PacketSha256, sha256.Sum256(selected))
	for _, tc := range []struct {
		display string
		extra   []string
	}{{"AUD 12.00", nil}, {"USD 19.49", []string{"--offer-file", file, "--offer-from", link}}} {
		t.Run(tc.display, func(t *testing.T) {
			cmd := posterCheckoutCommand()
			out, writer := io.Pipe()
			ctx, cancel := context.WithTimeout(t.Context(), 12*time.Second)
			done := make(chan error, 1)
			t.Cleanup(func() { cancel(); _ = out.Close(); require.NoError(t, <-done) })
			cmd.SetArgs(append([]string{collection, "--listen", "127.0.0.1:0", "--packet", review, "--packet-sha256", quote.PacketSha256}, tc.extra...))
			cmd.SetOut(writer)
			go func() { err := cmd.ExecuteContext(ctx); _ = writer.CloseWithError(err); done <- err }()
			line, err := bufio.NewReader(out).ReadString('\n')
			require.NoError(t, err)
			origin, ok := strings.CutPrefix(strings.TrimSpace(line), "Private poster test checkout ")
			require.True(t, ok)
			client := http.Client{Timeout: 3 * time.Second}
			response, err := client.Get(origin)
			require.NoError(t, err)
			defer response.Body.Close()
			body, err := io.ReadAll(response.Body)
			require.NoError(t, err)
			require.Equal(t, 200, response.StatusCode)
			require.Contains(t, string(body), tc.display+" in test funds")
		})
	}
	require.EqualValues(t, 2, reads.Load())
}
