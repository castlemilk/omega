package posters

import (
	"errors"
	"regexp"
	"strings"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

const (
	studioOfferURL = "https://studio.dropshippr-apps.workers.dev/collections/signal-studies?view=test-offer-file&packet="
	buyerWording   = "For personal printing and display only. Resale and redistribution of the digital files are excluded."
	aiDisclosure   = "Original code-generated curves and composition prepared with AI assistance for Gamma Systems."
)

// These identify Studio's issued, unmodified seller manifest and the review of
// the actual edition's PRINTING.txt and FONT-LICENCE.txt. The composed manifest
// changes when the owner saves terms or a price and is pinned by the offer URL.
var issuedSellerSources = map[string]struct{ baseDraft, wordingReview string }{
	EditorialEdition: {"d0c843b3375d619acbddbb22df74c286f2644d1d46cbd026d01948579aed66e4", "79a0979bcf41d50c86945aa018fcb339908977e6b177ad004e5e9f41e937f46a"},
	CaptionEdition:   {"84661c9ffb849c0d25ea66500830e53a7fa76cf8c889673175709db2de5a9538", "b85c75a7a2b0e345b9ba8c631afe7bb5da947574a1a2737a60be6766cf867154"},
}

var (
	offerDigest = regexp.MustCompile(`^[0-9a-f]{64}$`)
	// time.Parse accepts extra spellings, including a decimal comma and +24:00.
	offerTime = regexp.MustCompile(`^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]+)?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])$`)
)

func checkStudioPrice(q *v1.PosterTestOffer) error {
	switch q.Currency {
	case "AUD", "CAD", "EUR", "GBP", "USD":
	default:
		return errors.New("the test offer uses an unsupported currency")
	}
	if q.AmountMinor < 1 || q.AmountMinor > 99_999_999 || q.LaunchPlanSha256 != launchPlanSHA {
		return errors.New("the test amount or its source launch plan is invalid")
	}
	switch q.PriceSource {
	case "launch-plan":
		if q.AmountMinor != 1200 || q.Currency != "AUD" {
			return errors.New("the original launch plan proposes AUD 12.00")
		}
	case "seller-draft":
		if q.PriceRevision == 0 {
			return errors.New("a selected price needs a recorded seller revision")
		}
	default:
		return errors.New("unknown test price source")
	}
	if q.PriceRevision == 0 {
		if q.PriceRecordedAt != "" || q.MarketDay != "" || q.MarketSha256 != "" {
			return errors.New("the initial launch price cannot cite a saved choice")
		}
	} else if _, err := time.Parse(time.RFC3339, q.PriceRecordedAt); err != nil || !offerTime.MatchString(q.PriceRecordedAt) {
		return errors.New("the saved price revision needs its recorded time")
	}
	if q.MarketDay != "" || q.MarketSha256 != "" {
		if _, err := time.Parse(time.DateOnly, q.MarketDay); err != nil || !offerDigest.MatchString(q.MarketSha256) {
			return errors.New("the market source needs its UTC day and SHA-256")
		}
	}
	return nil
}

// VerifyTestOffer reads the owner's two local downloads. Its trust anchor is
// the separately copied Studio download URL, which commits to both byte streams.
func VerifyTestOffer(raw, review []byte, link string) (*v1.DigitalOffer, error) {
	packet, digest := sourceDigest(review), sourceDigest(raw)
	if link != studioOfferURL+packet+"&offer="+digest {
		return nil, errors.New("the offer, review packet or exact Studio offer download link differs")
	}
	candidate, err := reviewedCandidate(review, packet)
	if err != nil {
		return nil, err
	}
	q := new(v1.PosterTestOffer)
	if err := protojson.Unmarshal(raw, q); err != nil {
		return nil, err
	}
	return checkStudioTestOffer(q, candidate, packet, digest)
}

func checkStudioTestOffer(q *v1.PosterTestOffer, candidate *v1.PosterReleaseCandidate, packet, digest string) (*v1.DigitalOffer, error) {
	known, ok := issuedSellerSources[candidate.Edition]
	if !ok || q.Schema != "omega.poster-test-offer/v1" || q.Environment != "stripe-test" ||
		q.BusinessId != StudioBusinessID || q.ProductId != StudioProductID || q.PacketSha256 != packet ||
		q.Edition != candidate.Edition || q.Licence != testDownloadLicence || q.BaseSellerDraftSha256 != known.baseDraft ||
		!offerDigest.MatchString(q.SellerDraftSha256) {
		return nil, errors.New("the test environment, private edition, seller source or licence differs")
	}
	var pdfs uint32
	var guide, font string
	for _, file := range candidate.DeliveryFiles {
		switch file.Name {
		case "PRINTING.txt":
			guide = file.Sha256
		case "FONT-LICENCE.txt":
			font = file.Sha256
		default:
			if strings.HasSuffix(file.Name, ".pdf") {
				pdfs++
			}
		}
	}
	if q.ArchiveName != "signal-studies.zip" || q.ArchiveSha256 != candidate.PrintPack.Sha256 ||
		q.ArchiveBytes != candidate.PrintPack.Bytes || pdfs != 6 || q.PrintPdfCount != pdfs ||
		guide == "" || q.GuideSha256 != guide || font == "" || q.FontNoticeSha256 != font {
		return nil, errors.New("the buyer ZIP, six print PDFs, guide or font notice differs from the review packet")
	}
	if q.WordingRevision != 0 || q.BuyerWording != "" || q.AiDisclosure != "" || q.WordingReviewSha256 != "" {
		if q.WordingRevision == 0 || q.BuyerWording != buyerWording || q.AiDisclosure != aiDisclosure || q.WordingReviewSha256 != known.wordingReview {
			return nil, errors.New("the selected seller wording or AI disclosure differs from this edition's wording review")
		}
	}
	composed := q.PriceSource == "seller-draft" || q.WordingRevision > 0
	if composed == (q.SellerDraftSha256 == known.baseDraft) {
		return nil, errors.New("the seller draft checksum contradicts the selected price or wording")
	}
	if err := checkStudioPrice(q); err != nil {
		return nil, err
	}
	offer := digitalOffer(candidate, packet)
	offer.AmountMinor, offer.Currency = q.AmountMinor, strings.ToLower(q.Currency)
	offer.ArchiveName, offer.StudioOfferSha256 = q.ArchiveName, wrapperspb.String(digest)
	return offer, nil
}
