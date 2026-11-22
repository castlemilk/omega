package main

import (
	"bytes"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/stretchr/testify/require"
	"github.com/stripe/stripe-go/v87"
	"google.golang.org/protobuf/encoding/protojson"
)

func TestLaunchReviewCLIRejectsMixedOrIncompleteSources(t *testing.T) {
	original := stripe.GetBackendWithConfig(stripe.APIBackend, &stripe.BackendConfig{}).(*stripe.BackendImplementation).HTTPClient
	var requests countOfferTransport
	stripe.SetHTTPClient(&http.Client{Transport: &requests})
	t.Cleanup(func() { stripe.SetHTTPClient(original) })
	t.Setenv("OMEGA_POSTER_STRIPE_TEST_KEY", "sk_test_fixture")
	t.Setenv("OMEGA_POSTER_COMMERCE_DATABASE_URL", "postgresql://127.0.0.1:1/unavailable")
	launch := []string{"--launch-review", "case.zip", "--launch-review-from", "not-a-source"}
	cases := [][]string{{}, {"--launch-review", "case.zip"}, {"--launch-review-from", "source"},
		append(append([]string{}, launch...), "--packet", "a", "--packet-sha256", "b"),
		append(append([]string{}, launch...), "--offer-file", "a", "--offer-from", "b"), launch}
	for _, args := range cases {
		cmd := posterCheckoutCommand()
		cmd.SetArgs(append([]string{t.TempDir()}, args...))
		var out bytes.Buffer
		cmd.SetOut(&out)
		cmd.SetErr(&out)
		cmd.SilenceUsage = true
		require.Error(t, cmd.Execute())
	}
	require.Zero(t, requests)
}

func TestVerifyLaunchReviewCommandPrintsExactIssuerHash(t *testing.T) {
	dir := os.Getenv("OMEGA_POSTER_LAUNCH_REVIEWS")
	if dir == "" {
		t.Skip("set OMEGA_POSTER_LAUNCH_REVIEWS for the issued package")
	}
	zip := filepath.Join(dir, "current.zip")
	url, err := os.ReadFile(filepath.Join(dir, "current-from.txt"))
	require.NoError(t, err)
	cmd := posterVerifyLaunchReviewCommand()
	var out bytes.Buffer
	cmd.SetOut(&out)
	cmd.SetArgs([]string{zip, "--from", strings.TrimSpace(string(url))})
	require.NoError(t, cmd.Execute())
	receipt := new(v1.VerifiedChannelLaunchReview)
	require.NoError(t, protojson.Unmarshal(out.Bytes(), receipt))
	require.True(t, strings.HasSuffix(strings.TrimSpace(string(url)), "&review="+receipt.ReviewSha256))
	require.Equal(t, "prepare-offline-listing", receipt.Review.Action)
	require.Equal(t, receipt.OfferSha256, receipt.Offer.StudioOfferSha256.Value)
	t.Setenv("OMEGA_POSTER_STRIPE_TEST_KEY", "")
	checkout := posterCheckoutCommand()
	checkout.SilenceUsage = true
	checkout.SetOut(&out)
	checkout.SetErr(&out)
	checkout.SetArgs([]string{t.TempDir(), "--launch-review", zip, "--launch-review-from", strings.TrimSpace(string(url)) + "&extra=1"})
	require.ErrorContains(t, checkout.Execute(), "exact Studio launch review link")
}
