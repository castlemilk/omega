package posters

import (
	"bytes"
	"os"
	"strings"
	"testing"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

func studioQuoteFixture(t *testing.T) ([]byte, []byte, *v1.PosterTestOffer) {
	t.Helper()
	raw, err := os.ReadFile("testdata/editorial-test-offer.json")
	require.NoError(t, err)
	review, err := os.ReadFile("testdata/" + EditorialEdition + ".json")
	require.NoError(t, err)
	q := new(v1.PosterTestOffer)
	require.NoError(t, protojson.Unmarshal(raw, q))
	return raw, review, q
}

func checkedQuote(t *testing.T, q *v1.PosterTestOffer, review []byte) (*v1.DigitalOffer, error) {
	t.Helper()
	raw, err := protojson.Marshal(q)
	require.NoError(t, err)
	return VerifyTestOffer(raw, review, studioOfferURL+sourceDigest(review)+"&offer="+sourceDigest(raw))
}

func TestStudioOfferPinnedBytesAndPrivateScope(t *testing.T) {
	raw, review, _ := studioQuoteFixture(t)
	link := studioOfferURL + editorialPacketSHA + "&offer=" + sourceDigest(raw)
	verified, err := VerifyTestOffer(raw, review, link)
	require.NoError(t, err)
	require.Equal(t, sourceDigest(raw), verified.StudioOfferSha256.Value)
	require.Equal(t, int64(1200), verified.AmountMinor)
	require.Equal(t, "aud", verified.Currency)
	for _, wrong := range []string{
		strings.Replace(link, "https://", "http://", 1), strings.Replace(link, "studio.", "other.", 1),
		strings.Replace(link, ".dev/", ".dev:443/", 1), strings.Replace(link, "//studio.", "//user@studio.", 1),
		strings.Replace(link, "test-offer-file", "store", 1), strings.Replace(link, "&offer=", "&offer=x&offer=", 1),
		strings.Replace(link, "packet=", "packet=&packet=", 1), link + "&extra=1", link + "#", link + "\n",
		strings.Replace(link, "packet", "%70acket", 1), strings.Replace(link, editorialPacketSHA, captionPacketSHA, 1),
	} {
		_, err = VerifyTestOffer(raw, review, wrong)
		require.Error(t, err, wrong)
	}
	_, err = VerifyTestOffer(bytes.TrimSpace(raw), review, link)
	require.Error(t, err)
	_, err = VerifyTestOffer(raw, append(bytes.Clone(review), '\n'), link)
	require.Error(t, err)
	malformed := []byte(`{"schema":"omega.poster-test-offer/v1","schema":"different"}`)
	_, err = VerifyTestOffer(malformed, review, studioOfferURL+editorialPacketSHA+"&offer="+sourceDigest(malformed))
	require.Error(t, err)
}

func TestStudioOfferSelectedPriceAndWording(t *testing.T) {
	_, review, base := studioQuoteFixture(t)
	base.PriceSource, base.PriceRevision, base.PriceRecordedAt = "seller-draft", 3, "2026-11-22T16:08:20.315Z"
	base.MarketDay, base.MarketSha256 = "2026-11-20", sourceDigest([]byte("saved market report"))
	base.WordingRevision, base.WordingReviewSha256 = 2, issuedSellerSources[EditorialEdition].wordingReview
	base.BuyerWording, base.AiDisclosure = buyerWording, aiDisclosure
	base.SellerDraftSha256 = sourceDigest([]byte("composed seller draft"))
	for _, tc := range []struct {
		currency string
		amount   int64
	}{
		{"CAD", 1}, {"EUR", 33}, {"GBP", 2205}, {"USD", 99_999_999}, {"AUD", 1575},
	} {
		base.Currency, base.AmountMinor = tc.currency, tc.amount
		offer, err := checkedQuote(t, base, review)
		require.NoError(t, err)
		require.Equal(t, strings.ToLower(tc.currency), offer.Currency)
		require.Equal(t, tc.amount, offer.AmountMinor)
		require.Equal(t, "private-test-download-v1", offer.Licence)
	}
	base.PriceSource, base.AmountMinor = "launch-plan", 1200
	restored, err := checkedQuote(t, base, review)
	require.NoError(t, err)
	original, _, _ := studioQuoteFixture(t)
	require.NotEqual(t, sourceDigest(original), restored.StudioOfferSha256.Value)

	caption, err := os.ReadFile("testdata/" + CaptionEdition + ".json")
	require.NoError(t, err)
	_, err = checkedQuote(t, base, caption)
	require.Error(t, err)
	selected, err := reviewedCandidate(caption, captionPacketSHA)
	require.NoError(t, err)
	base.PacketSha256, base.Edition, base.BaseSellerDraftSha256 = captionPacketSHA, CaptionEdition, issuedSellerSources[CaptionEdition].baseDraft
	base.ArchiveBytes, base.ArchiveSha256 = selected.PrintPack.Bytes, selected.PrintPack.Sha256
	for _, f := range selected.DeliveryFiles {
		if f.Name == "PRINTING.txt" {
			base.GuideSha256 = f.Sha256
		}
	}
	_, err = checkedQuote(t, base, caption)
	require.ErrorContains(t, err, "wording review")
	base.WordingReviewSha256 = issuedSellerSources[CaptionEdition].wordingReview
	verified, err := checkedQuote(t, base, caption)
	require.NoError(t, err)
	require.Equal(t, CaptionEdition, verified.Edition)
}

func TestStudioOfferRejectsRehashedContradictions(t *testing.T) {
	_, review, base := studioQuoteFixture(t)
	for name, change := range map[string]func(*v1.PosterTestOffer){
		"schema":                    func(q *v1.PosterTestOffer) { q.Schema = "unknown" },
		"live scope":                func(q *v1.PosterTestOffer) { q.Environment = "stripe-live" },
		"business":                  func(q *v1.PosterTestOffer) { q.BusinessId = "foreign" },
		"product":                   func(q *v1.PosterTestOffer) { q.ProductId = "another" },
		"edition":                   func(q *v1.PosterTestOffer) { q.Edition = CaptionEdition },
		"packet":                    func(q *v1.PosterTestOffer) { q.PacketSha256 = captionPacketSHA },
		"base seller draft":         func(q *v1.PosterTestOffer) { q.BaseSellerDraftSha256 = issuedSellerSources[CaptionEdition].baseDraft },
		"initial seller":            func(q *v1.PosterTestOffer) { q.SellerDraftSha256 = sourceDigest([]byte("wrong draft")) },
		"invalid seller digest":     func(q *v1.PosterTestOffer) { q.SellerDraftSha256 = "" },
		"archive name":              func(q *v1.PosterTestOffer) { q.ArchiveName = "buyer/signal-studies.zip" },
		"archive":                   func(q *v1.PosterTestOffer) { q.ArchiveSha256 = editions[CaptionEdition].printPack.sha256 },
		"archive length":            func(q *v1.PosterTestOffer) { q.ArchiveBytes++ },
		"extra PDF":                 func(q *v1.PosterTestOffer) { q.PrintPdfCount++ },
		"font":                      func(q *v1.PosterTestOffer) { q.FontNoticeSha256 = q.GuideSha256 },
		"guide":                     func(q *v1.PosterTestOffer) { q.GuideSha256 = "" },
		"public licence":            func(q *v1.PosterTestOffer) { q.Licence = "retail" },
		"foreign launch plan":       func(q *v1.PosterTestOffer) { q.LaunchPlanSha256 = q.ArchiveSha256 },
		"unknown source":            func(q *v1.PosterTestOffer) { q.PriceSource = "market-price" },
		"zero":                      func(q *v1.PosterTestOffer) { q.AmountMinor = 0 },
		"negative":                  func(q *v1.PosterTestOffer) { q.AmountMinor = -1 },
		"too large":                 func(q *v1.PosterTestOffer) { q.AmountMinor = 100_000_000 },
		"currency":                  func(q *v1.PosterTestOffer) { q.Currency = "JPY" },
		"case":                      func(q *v1.PosterTestOffer) { q.Currency = "aud" },
		"launch price":              func(q *v1.PosterTestOffer) { q.AmountMinor++ },
		"launch currency":           func(q *v1.PosterTestOffer) { q.Currency = "EUR" },
		"unsaved seller choice":     func(q *v1.PosterTestOffer) { q.PriceSource = "seller-draft" },
		"undated revision":          func(q *v1.PosterTestOffer) { q.PriceRevision = 1 },
		"invalid saved date":        func(q *v1.PosterTestOffer) { q.PriceRevision = 1; q.PriceRecordedAt = "2026-02-30T09:31:00Z" },
		"invalid offset":            func(q *v1.PosterTestOffer) { q.PriceRevision = 1; q.PriceRecordedAt = "2026-02-01T09:31:00+24:00" },
		"initial date":              func(q *v1.PosterTestOffer) { q.PriceRecordedAt = "2026-11-21T09:31:00Z" },
		"market for unsaved choice": func(q *v1.PosterTestOffer) { q.MarketDay = "2026-11-21"; q.MarketSha256 = q.ArchiveSha256 },
		"missing market report": func(q *v1.PosterTestOffer) {
			q.PriceRevision = 1
			q.PriceRecordedAt = "2026-11-21T09:31:00Z"
			q.MarketDay = "2026-11-21"
		},
		"invalid market day": func(q *v1.PosterTestOffer) {
			q.PriceRevision = 1
			q.PriceRecordedAt = "2026-11-21T09:31:00Z"
			q.MarketDay = "2026-02-30"
			q.MarketSha256 = q.ArchiveSha256
		},
		"unselected buyer language": func(q *v1.PosterTestOffer) { q.BuyerWording = buyerWording },
		"missing AI disclosure": func(q *v1.PosterTestOffer) {
			q.WordingRevision = 1
			q.WordingReviewSha256 = issuedSellerSources[EditorialEdition].wordingReview
			q.BuyerWording = buyerWording
		},
		"unchanged draft with selected wording": func(q *v1.PosterTestOffer) {
			q.WordingRevision, q.WordingReviewSha256 = 1, issuedSellerSources[EditorialEdition].wordingReview
			q.BuyerWording, q.AiDisclosure = buyerWording, aiDisclosure
		},
		"modified AI disclosure": func(q *v1.PosterTestOffer) {
			q.WordingRevision = 1
			q.WordingReviewSha256 = issuedSellerSources[EditorialEdition].wordingReview
			q.BuyerWording = buyerWording
			q.AiDisclosure = "Issued without AI."
		},
	} {
		t.Run(name, func(t *testing.T) {
			q := proto.CloneOf(base)
			change(q)
			_, err := checkedQuote(t, q, review)
			require.Error(t, err)
		})
	}
}
