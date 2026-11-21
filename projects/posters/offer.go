package posters

import (
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"html/template"
	"io/fs"

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
)

// TestOffer accepts the exact private packet exported by Studio. This binding
// describes a sandbox offer and never conveys permission for a public sale.
func TestOffer(collection fs.FS, raw []byte, expected string) (*v1.DigitalOffer, []byte, []byte, error) {
	sum := sha256.Sum256(raw)
	if hex.EncodeToString(sum[:]) != expected {
		return nil, nil, nil, errors.New("the packet digest differs from the Studio receipt")
	}
	type scope struct {
		BusinessID string `json:"businessId"`
		ProjectID  string `json:"projectId"`
		RecordID   string `json:"recordId"`
		Revision   int    `json:"recordRevision"`
	}
	var packet struct {
		Schema    string          `json:"schema"`
		Run       string          `json:"runId"`
		Candidate json.RawMessage `json:"candidate"`
		Review    struct {
			Artwork, Copy struct {
				Source scope `json:"source"`
			}
		} `json:"review"`
		Decision struct {
			Audience, Destination         string
			CheckoutEnabled, PublicLaunch *bool
			AdditionalSpend               *int
		} `json:"decision"`
	}
	if err := json.Unmarshal(raw, &packet); err != nil {
		return nil, nil, nil, err
	}
	art, copy, decision := packet.Review.Artwork.Source, packet.Review.Copy.Source, packet.Decision
	if packet.Schema != "omega.poster-review/v1" || packet.Run != "a8e14e74-1110-4000-8000-000000000101" ||
		art.BusinessID != StudioBusinessID || art.ProjectID != StudioProductID ||
		copy.BusinessID != art.BusinessID || copy.ProjectID != art.ProjectID || art.RecordID != "58ac9b0f-bdc6-56b9-8a1a-131ef87ce8fb" || copy.RecordID != "821ab426-0868-5525-814f-24acbe3025d5" || art.Revision != 1 || copy.Revision != 1 ||
		decision.Audience != "studio-owner" || decision.Destination != "/collections/signal-studies?view=store" || decision.CheckoutEnabled == nil || *decision.CheckoutEnabled ||
		decision.PublicLaunch == nil || *decision.PublicLaunch || decision.AdditionalSpend == nil || *decision.AdditionalSpend != 0 {
		return nil, nil, nil, errors.New("the packet does not identify this private poster edition")
	}
	candidate, err := Candidate(collection)
	if err != nil {
		return nil, nil, nil, err
	}
	selected := new(v1.PosterReleaseCandidate)
	if err = protojson.Unmarshal(packet.Candidate, selected); err != nil || !proto.Equal(selected, candidate) {
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
	return &v1.DigitalOffer{
		BusinessId: art.BusinessID, ProductId: art.ProjectID, Edition: candidate.Edition, PacketSha256: expected,
		ArchiveSha256: candidate.PrintPack.Sha256, ArchiveName: candidate.PrintPack.Name, AmountMinor: 1200, Currency: "aud", Licence: "private-test-download-v1",
	}, data, preview, nil
}
