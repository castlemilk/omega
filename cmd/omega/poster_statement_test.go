package main

import (
	"bytes"
	"crypto/sha256"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/commerce"
	"github.com/benebsworth/omega/projects/posters"
	"github.com/google/uuid"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/stripe/stripe-go/v87"
	"google.golang.org/protobuf/proto"
)

func TestPosterStatementCommand(t *testing.T) {
	dsn := os.Getenv("OMEGA_DIGITAL_ORDER_TEST_DSN")
	if dsn == "" {
		t.Skip("run make test-digital-orders for the CLI and PostgreSQL integration")
	}
	ctx := t.Context()
	day := time.Now().UTC().AddDate(0, 0, -1).Truncate(24 * time.Hour)
	account, id := "acct_fixture_"+uuid.NewString(), uuid.NewString()
	archive := []byte("private fixture archive")
	offer := &v1.DigitalOffer{BusinessId: posters.StudioBusinessID, ProductId: posters.StudioProductID, Edition: posters.EditorialEdition,
		PacketSha256: strings.Repeat("1", 64), ArchiveSha256: fmt.Sprintf("%x", sha256.Sum256(archive)), ArchiveName: "signal-studies.zip",
		AmountMinor: 1200, Currency: "aud", Licence: "private-test-download-v1"}
	if dir := os.Getenv("OMEGA_POSTER_TEST_COLLECTION"); dir != "" {
		raw, err := os.ReadFile("../../projects/posters/testdata/" + posters.EditorialEdition + ".json")
		require.NoError(t, err)
		offer, archive, _, err = posters.TestOffer(os.DirFS(dir), raw, "8e343a7789b0994d4093682e0849842929e47709dfe4121157670649ed19d33d")
		require.NoError(t, err)
	}
	definition, err := proto.MarshalOptions{Deterministic: true}.Marshal(offer)
	require.NoError(t, err)
	key := fmt.Sprintf("%x", sha256.Sum256(definition))
	type obj = map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		var response any
		switch r.URL.Path {
		case "/v1/account":
			response = obj{"id": account, "object": "account"}
		case "/v1/checkout/sessions/cs_test_statement":
			assert.Equal(t, "payment_intent.latest_charge.balance_transaction", r.URL.Query().Get("expand[0]"))
			meta := obj{"omega_order": id, "omega_offer": key}
			balance := obj{"id": "txn_stmt_charge", "object": "balance_transaction", "source": "ch_stmt", "type": "charge",
				"amount": 850, "currency": "usd", "fee": 34, "net": 816, "status": "pending", "created": day.Unix()}
			charge := obj{"id": "ch_stmt", "amount_captured": 1200, "amount_refunded": 300, "paid": true,
				"captured": true, "currency": "aud", "payment_intent": "pi_stmt", "balance_transaction": balance}
			intent := obj{"id": "pi_stmt", "amount": 1200, "amount_received": 1200, "status": "succeeded",
				"currency": "aud", "metadata": meta, "latest_charge": charge}
			response = obj{"id": "cs_test_statement", "mode": "payment", "client_reference_id": id, "metadata": meta,
				"amount_total": 1200, "status": "complete", "payment_status": "paid", "currency": "aud", "payment_intent": intent}
		case "/v1/refunds":
			assert.Equal(t, "ch_stmt", r.URL.Query().Get("charge"))
			assert.Equal(t, "data.balance_transaction", r.URL.Query().Get("expand[0]"))
			balance := obj{"id": "txn_stmt_refund", "object": "balance_transaction", "source": "re_stmt", "type": "refund",
				"amount": -200, "currency": "usd", "fee": 0, "net": -200, "status": "available", "created": day.Unix() + 1}
			refund := obj{"id": "re_stmt", "object": "refund", "charge": "ch_stmt", "amount": 300,
				"status": "succeeded", "currency": "aud", "balance_transaction": balance}
			response = obj{"object": "list", "data": []obj{refund}, "has_more": false}
		default:
			t.Errorf("unexpected Stripe request %s", r.URL.Path)
			w.WriteHeader(http.StatusForbidden)
			response = obj{"error": obj{"type": "permission_error", "message": "direct balance access denied"}}
		}
		_ = json.NewEncoder(w).Encode(response)
	}))
	defer server.Close()
	original := stripe.GetBackendWithConfig(stripe.APIBackend, &stripe.BackendConfig{}).(*stripe.BackendImplementation).HTTPClient
	target, err := url.Parse(server.URL)
	require.NoError(t, err)
	stripe.SetHTTPClient(&http.Client{Transport: statementTestTransport{target, server.Client().Transport}})
	t.Cleanup(func() { stripe.SetHTTPClient(original) })
	t.Setenv("OMEGA_POSTER_STRIPE_TEST_KEY", "sk_test_fixture")
	t.Setenv("OMEGA_POSTER_COMMERCE_DATABASE_URL", dsn)
	gateway, err := commerce.NewStripeTest("sk_test_fixture")
	require.NoError(t, err)
	db, err := sql.Open("pgx", dsn)
	require.NoError(t, err)
	defer func() { _ = db.Close() }()
	_, err = commerce.Open(ctx, db, account, "http://127.0.0.1", "whsec_fixture", gateway, offer, archive)
	require.NoError(t, err)
	var storedKey string
	err = db.QueryRowContext(ctx, `INSERT INTO omega_digital_orders(connection_id,id,buyer_hash,offer_key,created_at,session_id)
		SELECT connection_id,$2,'private'::bytea,offer_key,$3,'cs_test_statement' FROM omega_digital_offers WHERE connection_id=$1 RETURNING offer_key`,
		account+"/"+offer.BusinessId, id, day).Scan(&storedKey)
	require.NoError(t, err)
	require.Equal(t, key, storedKey)
	var out bytes.Buffer
	origOut := rootCmd.OutOrStdout()
	rootCmd.SetOut(&out)
	t.Cleanup(func() { rootCmd.SetOut(origOut); rootCmd.SetArgs(nil) })
	rootCmd.SetArgs([]string{"posters", "test-statement", "--from", day.Format(time.DateOnly), "--through", day.Format(time.DateOnly)})
	require.NoError(t, rootCmd.Execute())
	var statement map[string]any
	require.NoError(t, json.Unmarshal(out.Bytes(), &statement))
	require.Equal(t, "complete", statement["coverage"])
	require.Equal(t, "omega.commerce-statement/v1", statement["schema"])
	require.Equal(t, true, statement["testMode"])
	rows := statement["orders"].([]any)
	require.Len(t, rows, 1)
	row := rows[0].(map[string]any)
	require.Equal(t, id, row["orderId"])
	require.Equal(t, "1200", row["capturedMinor"])
	require.Equal(t, "300", row["refundedMinor"])
	require.Equal(t, true, row["balanceComplete"])
	require.Len(t, row["movements"], 2)
	require.NotContains(t, row, "disputeStatus")
	require.Equal(t, float64(0), row["unresolvedEvents"])
	require.Equal(t, float64(0), row["downloadsIssued"])
	if os.Getenv("OMEGA_PRINT_TEST_STATEMENT") == "1" {
		var compact bytes.Buffer
		require.NoError(t, json.Compact(&compact, out.Bytes()))
		t.Log("CLI fixture statement", compact.String())
	}
}

// All SDK traffic for the normal CLI command stays inside the test server.
type statementTestTransport struct {
	target    *url.URL
	transport http.RoundTripper
}

func (s statementTestTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	r := request.Clone(request.Context())
	r.URL.Scheme, r.URL.Host = s.target.Scheme, s.target.Host
	return s.transport.RoundTrip(r)
}
