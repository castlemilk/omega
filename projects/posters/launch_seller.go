package posters

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
)

// Studio hashes the compact unsigned OfferPriceDecision in protobuf field order.
// Amounts are strings in protobuf JSON, including those in the nested seller draft.
type launchPriceDecision struct {
	Revision       uint32 `json:"revision,omitempty"`
	RecordedAt     string `json:"recordedAt,omitempty"`
	RestoreWorking bool   `json:"restoreWorking,omitempty"`
	Currency       string `json:"currency,omitempty"`
	AmountMinor    string `json:"amountMinor,omitempty"`
	MarketDay      string `json:"marketDay,omitempty"`
	MarketSHA      string `json:"marketSha256,omitempty"`
	BaseDraftSHA   string `json:"baseDraftSha256,omitempty"`
	PacketSHA      string `json:"packetSha256,omitempty"`
	DecisionSHA    string `json:"decisionSha256,omitempty"`
}

type launchBuyerTerms struct {
	BaseDraftSha256, ReviewSha256, RecordedAt, GuideSha256, FontNoticeSha256, BuyerWording, Disclosure string
	DecisionRevision                                                                                   uint32
}

// Seller manifests are an external Studio format with additional metadata.
// Check duplicate keys before decoding the fields this consumer understands.
func checkSellerJSON(d *json.Decoder, depth int) error {
	if depth > 32 {
		return errors.New("seller metadata is nested too deeply")
	}
	token, err := d.Token()
	if err != nil {
		return err
	}
	switch token {
	case json.Delim('{'):
		keys := make(map[string]bool)
		for d.More() {
			k, err := d.Token()
			if err != nil {
				return err
			}
			name, ok := k.(string)
			name = strings.ToLower(name) // encoding/json matches struct fields case-insensitively.
			if !ok || keys[name] {
				return errors.New("the seller manifest repeats a field")
			}
			keys[name] = true
			if err := checkSellerJSON(d, depth+1); err != nil {
				return err
			}
		}
	case json.Delim('['):
		for d.More() {
			if err := checkSellerJSON(d, depth+1); err != nil {
				return err
			}
		}
	default:
		return nil
	}
	_, err = d.Token()
	return err
}

func checkLaunchSeller(raw []byte, draft *studioSellerDraft, candidate *v1.PosterReleaseCandidate, q *v1.PosterTestOffer, issued time.Time) error {
	d := json.NewDecoder(bytes.NewReader(raw))
	if err := checkSellerJSON(d, 0); err != nil {
		return err
	}
	if _, err := d.Token(); err != io.EOF {
		return errors.New("unexpected trailing seller data")
	}
	var facts struct {
		ApprovedCurrency, ApprovedPriceMinor, SourceLaunchPlanSha256, PriceHypothesis string
		PriceDecision                                                                 *launchPriceDecision
		BuyerTerms                                                                    *launchBuyerTerms
	}
	if err := json.Unmarshal(raw, &facts); err != nil {
		return err
	}
	if draft.State != "offline-draft" || draft.ReleasePacketSha256 != q.PacketSha256 || draft.ProposalPacketSha256 != "" ||
		draft.Title != "Signal Studies Printable Maths Posters, Set of Three in A4 and A3" ||
		facts.SourceLaunchPlanSha256 != q.LaunchPlanSha256 || draft.ObservationTemplateSha256 != "3b6cb6ddc9ce639705bf59ed8c03069f36373b50ba94b5db9b26e570734789f4" {
		return errors.New("the seller kit is not the issued private Etsy draft with its original measurement template")
	}
	// Independent identity of the four issued photographs and their ordered
	// source sheets. readSellerPack separately checks each file's actual bytes.
	var gallery []string
	for _, photo := range draft.Gallery {
		gallery = append(gallery, photo.File.Name, photo.File.Sha256)
		for _, source := range photo.SourceFiles {
			gallery = append(gallery, source.Name, source.Sha256)
		}
	}
	wantGallery := "17620a248ac608ad9d23dbd0a0e9130f9e5ba5fed2a028bfcdb424cef10e2d7f"
	if candidate.Edition == CaptionEdition {
		wantGallery = "0814f54b4d2fd35036485cf4b05a8357c3e85cad5121b9c4444386ac0edb78ef"
	}
	if sourceDigest([]byte(strings.Join(gallery, "\n"))) != wantGallery {
		return errors.New("the seller photographs or their source sheets differ from this edition")
	}
	description := "Print a set of three mathematical studies in ivory, navy and copper.\n\n" + candidate.ListingDescription
	terms := facts.BuyerTerms
	if q.WordingRevision == 0 {
		if terms != nil {
			return errors.New("the seller kit includes unselected buyer wording")
		}
	} else {
		if terms == nil || terms.BaseDraftSha256 != q.BaseSellerDraftSha256 || terms.ReviewSha256 != q.WordingReviewSha256 ||
			terms.DecisionRevision != q.WordingRevision || terms.GuideSha256 != q.GuideSha256 || terms.FontNoticeSha256 != q.FontNoticeSha256 ||
			terms.BuyerWording != q.BuyerWording || terms.Disclosure != q.AiDisclosure {
			return errors.New("the seller wording or AI disclosure differs from the selected test offer")
		}
		t, err := time.Parse(time.RFC3339, terms.RecordedAt)
		if err != nil || !offerTime.MatchString(terms.RecordedAt) || t.Before(issued) {
			return errors.New("the selected seller wording has an invalid decision time")
		}
		description += "\n\n" + q.BuyerWording + "\n\n" + q.AiDisclosure
	}
	if draft.Description != description {
		return errors.New("the buyer-facing seller listing differs from the reviewed wording")
	}
	// Both price paragraphs in the downloadable owner's notes are generated
	// from this decision. Check them as well as the machine-readable amount.
	header := "Private working files for the shop owner. The shop and selling price are undecided."
	hypothesis := "AUD 12 for the complete set, proposed in the original launch plan. The selling price is undecided."
	if q.PriceSource == "seller-draft" {
		price := fmt.Sprintf("%s %d.%02d", q.Currency, q.AmountMinor/100, q.AmountMinor%100)
		header = "Private working files for the shop owner. Saved draft price: " + price + ". The shop and publication still need a decision."
		hypothesis = "The original launch plan proposes AUD 12 for the set. The saved private draft price is " + price + "."
	}
	if facts.PriceHypothesis != hypothesis || !strings.HasPrefix(draft.reviewText, "# Signal Studies · Seller preparation for Etsy\n\n"+header+"\n\n") ||
		!strings.Contains(draft.reviewText, "\n\n"+hypothesis+"\n\n") {
		return errors.New("the seller's price description or preparation notes differ from the quoted price")
	}
	p := facts.PriceDecision
	if q.PriceSource == "launch-plan" {
		if p != nil || facts.ApprovedCurrency != "" || facts.ApprovedPriceMinor != "" {
			return errors.New("the working-price offer includes a contradictory saved seller price")
		}
		return nil
	}
	minor := strconv.FormatInt(q.AmountMinor, 10)
	if p == nil || p.RestoreWorking || facts.ApprovedCurrency != q.Currency || facts.ApprovedPriceMinor != minor ||
		p.Currency != q.Currency || p.AmountMinor != minor || p.Revision != q.PriceRevision || p.RecordedAt != q.PriceRecordedAt ||
		p.MarketDay != q.MarketDay || p.MarketSHA != q.MarketSha256 || p.BaseDraftSHA != q.BaseSellerDraftSha256 || p.PacketSHA != q.PacketSha256 {
		return errors.New("the seller kit's recorded price, currency or decision differs from the quoted offer")
	}
	digest := p.DecisionSHA
	p.DecisionSHA = ""
	unsigned, err := json.Marshal(p)
	if err != nil || digest != sourceDigest(unsigned) {
		return errors.New("the saved seller price decision checksum differs")
	}
	return nil
}
