package posters

import (
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"html/template"
	"io/fs"
	"path"
	"strings"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

//go:embed checkout.html
var checkoutHTML string

var CheckoutPage = template.Must(template.New("poster-checkout").Parse(checkoutHTML))

const (
	StudioBusinessID = "business-d41cd8fc-2eab-48ac-a021-0b3790d02eee"
	StudioProductID  = "product-9d215b3a-5cd7-4a1b-9a22-81ffb5140e65"

	originalPacketSHA  = "18d06477efdfa9c34ebc6dfa08986457618faaf7afb32c0d2c8c38191c584afa"
	editorialPacketSHA = "8e343a7789b0994d4093682e0849842929e47709dfe4121157670649ed19d33d"
	captionPacketSHA   = "2a68ff21008e8554f9d4278a9a758c84d85526e69a08c593fc8c829bf7ec55b6"
)

type studioSource struct {
	BusinessID, ProjectID, RecordID, SubjectID string
	RecordRevision                             int
}

func sourceDigest(raw []byte) string {
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func (s studioSource) matches(recordID string) bool {
	return s.BusinessID == StudioBusinessID && s.ProjectID == StudioProductID && s.RecordID == recordID && s.RecordRevision == 1
}

// Studio's immutable exports bind the business, product, run, private
// destination and exact artwork and copy. A revision also binds its parent
// and the evidence for the change.
// The receipt supplies a separate digest for the operator's selected export.
func reviewedCandidate(raw []byte, expected string) (*v1.PosterReleaseCandidate, error) {
	if sourceDigest(raw) != expected {
		return nil, errors.New("the packet digest differs from the Studio receipt")
	}
	var edition, artID, copyID string
	switch expected {
	case originalPacketSHA:
		edition, artID, copyID = OriginalEdition, "58ac9b0f-bdc6-56b9-8a1a-131ef87ce8fb", "821ab426-0868-5525-814f-24acbe3025d5"
	case editorialPacketSHA:
		edition, artID, copyID = EditorialEdition, "3a227c6c-1432-59a6-80d8-5c4af20ec341", "28cb2421-131b-4bc6-92d6-4613e2cab765"
	case captionPacketSHA:
		edition, artID, copyID = CaptionEdition, "3a227c6c-1432-59a6-80d8-5c4af20ec341", "28cb2421-131b-4bc6-92d6-4613e2cab765"
	default:
		return nil, errors.New("the packet does not identify this private poster edition")
	}
	var packet struct {
		Schema, RunID string
		Candidate     json.RawMessage
		Review        struct {
			Artwork, Copy struct{ Source studioSource }
		}
		Decision struct {
			Audience, Destination         string
			CheckoutEnabled, PublicLaunch *bool
			AdditionalSpend               *int
		}
	}
	if err := json.Unmarshal(raw, &packet); err != nil {
		return nil, err
	}
	selected := new(v1.PosterReleaseCandidate)
	if err := protojson.Unmarshal(packet.Candidate, selected); err != nil {
		return nil, err
	}
	decision := packet.Decision
	subject := "signal-studies-" + strings.TrimSuffix(selected.GetSelectedArtwork().GetName(), "-A4.pdf")
	if selected.Edition != edition || packet.Schema != "omega.poster-review/v1" || packet.RunID != "a8e14e74-1110-4000-8000-000000000101" ||
		!packet.Review.Artwork.Source.matches(artID) || packet.Review.Artwork.Source.SubjectID != subject || !packet.Review.Copy.Source.matches(copyID) ||
		decision.Audience != "studio-owner" || decision.Destination != "/collections/signal-studies?view=store" ||
		decision.CheckoutEnabled == nil || *decision.CheckoutEnabled || decision.PublicLaunch == nil || *decision.PublicLaunch ||
		decision.AdditionalSpend == nil || *decision.AdditionalSpend != 0 {
		return nil, errors.New("the review sources or private destination differ from the selected edition")
	}
	return selected, nil
}

const testDownloadLicence = "private-test-download-v1"

func digitalOffer(candidate *v1.PosterReleaseCandidate, packet string) *v1.DigitalOffer {
	return &v1.DigitalOffer{
		BusinessId: StudioBusinessID, ProductId: StudioProductID, Edition: candidate.Edition, PacketSha256: packet,
		ArchiveSha256: candidate.PrintPack.Sha256, ArchiveName: path.Base(candidate.PrintPack.Name),
		AmountMinor: 1200, Currency: "aud", Licence: testDownloadLicence,
	}
}

// TestOffer accepts the exact private packet exported by Studio. This binding
// describes a sandbox offer and never conveys permission for a public sale.
func TestOffer(collection fs.FS, raw []byte, expected string) (*v1.DigitalOffer, []byte, []byte, error) {
	selected, err := reviewedCandidate(raw, expected)
	if err != nil {
		return nil, nil, nil, err
	}
	candidate, err := CandidateForEdition(collection, selected.Edition)
	if err != nil {
		return nil, nil, nil, err
	}
	if !proto.Equal(selected, candidate) {
		return nil, nil, nil, errors.New("the packet does not match the exact collection")
	}
	_, data, err := file(collection, candidate.PrintPack.Name, candidate.PrintPack.Sha256)
	if err != nil {
		return nil, nil, nil, err
	}
	_, preview, err := file(collection, candidate.ArtworkPreview.Name, candidate.ArtworkPreview.Sha256)
	if err != nil {
		return nil, nil, nil, err
	}
	return digitalOffer(candidate, expected), data, preview, nil
}
