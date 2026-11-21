package posters

import (
	"archive/zip"
	"bytes"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"net/url"
	"path"
	"slices"
	"strings"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"google.golang.org/protobuf/proto"
)

// Read only the fields used to check Studio's MarketplaceDraft export. The
// verified result is the original protobuf JSON, including fields added by Studio.
type studioSellerDraft struct {
	Schema, Channel, State, Edition               string
	ReleasePacketSha256, ProposalPacketSha256     string
	SourceReleasePacketSha256, SourceListingTitle string
	Title, Description, ObservationTemplateSha256 string
	BuyerFile, ListingText, SellerNotes           *v1.PosterFile
	BuyerFileContents                             []*v1.PosterFile
	Gallery                                       []studioSellerPhoto
}

type studioSellerPhoto struct {
	File        *v1.PosterFile
	SourceFiles []*v1.PosterFile
}

func sellerDownloadSelection(link string) (packet, manifest string, err error) {
	invalid := errors.New("use the full Download seller ZIP link from the private Signal Studies draft")
	u, err := url.Parse(link)
	if err != nil || u.Scheme != "https" || u.Host != "studio.dropshippr-apps.workers.dev" ||
		u.User != nil || u.EscapedPath() != "/collections/signal-studies" || u.Fragment != "" {
		return "", "", invalid
	}
	q, err := url.ParseQuery(u.RawQuery)
	if err != nil || len(q["view"]) != 1 || q.Get("view") != "etsy-pack" || len(q["packet"]) != 1 || len(q["draft"]) != 1 {
		return "", "", invalid
	}
	packet, manifest = q.Get("packet"), q.Get("draft")
	for _, digest := range []string{packet, manifest} {
		if decoded, err := hex.DecodeString(digest); err != nil || len(decoded) != 32 || digest != strings.ToLower(digest) {
			return "", "", invalid
		}
	}
	return packet, manifest, nil
}

// VerifySellerPack checks two local exports against the selected hosted link.
// It makes no network requests and returns the original verified seller manifest.
func VerifySellerPack(files fs.FS, name string, review []byte, link string) ([]byte, error) {
	packet, manifest, err := sellerDownloadSelection(link)
	if err != nil {
		return nil, err
	}
	selected, err := reviewedCandidate(review, packet)
	if err != nil {
		return nil, err
	}
	_, pack, err := archive(files, name, "")
	if err != nil {
		return nil, err
	}
	_, raw, err := file(pack, "seller/draft.json", manifest)
	if err != nil {
		return nil, fmt.Errorf("Studio seller manifest: %w", err)
	}
	var draft studioSellerDraft
	if err := json.Unmarshal(raw, &draft); err != nil {
		return nil, err
	}
	if err := draft.checkSelection(selected, packet); err != nil {
		return nil, err
	}
	if err := draft.checkFiles(pack, selected); err != nil {
		return nil, err
	}
	return raw, nil
}

func (d *studioSellerDraft) checkSelection(selected *v1.PosterReleaseCandidate, packet string) error {
	if d.Schema != "omega.marketplace-draft/v1" || d.Channel != "Etsy" || selected.Edition != d.Edition ||
		d.SourceListingTitle != selected.ListingTitle || selected.PrintPack == nil ||
		d.BuyerFile.GetName() != "signal-studies.zip" || d.BuyerFile.GetSha256() != selected.PrintPack.Sha256 ||
		d.BuyerFile.GetBytes() != selected.PrintPack.Bytes || len(d.Gallery) != 4 ||
		!slices.EqualFunc(d.BuyerFileContents, selected.DeliveryFiles, func(a, b *v1.PosterFile) bool { return proto.Equal(a, b) }) {
		return errors.New("seller materials differ from the reviewed buyer edition")
	}
	switch d.Edition {
	case EditorialEdition:
		if d.SourceReleasePacketSha256 != "" || packet != editorialPacketSHA {
			return errors.New("the editorial materials identify a different release")
		}
	case CaptionEdition:
		if d.SourceReleasePacketSha256 != editorialPacketSHA || packet != captionPacketSHA {
			return errors.New("the caption materials identify a different source edition")
		}
	default:
		return errors.New("this edition has no Signal Studies seller materials")
	}
	if d.State == "offline-draft" && d.ReleasePacketSha256 == packet && d.ProposalPacketSha256 == "" {
		return nil
	}
	if d.Edition == CaptionEdition && d.State == "offline-proposal" && d.ProposalPacketSha256 == packet && d.ReleasePacketSha256 == "" {
		return nil
	}
	return errors.New("seller proposal or release status differs from the selected packet")
}

func checkedSellerFile(pack *zip.Reader, name string, ref *v1.PosterFile) ([]byte, error) {
	if ref.GetBytes() == 0 || len(ref.GetSha256()) != 64 {
		return nil, fmt.Errorf("missing file identity for %s", name)
	}
	actual, body, err := file(pack, name, ref.Sha256)
	if err != nil {
		return nil, err
	}
	if actual.Bytes != ref.Bytes {
		return nil, fmt.Errorf("%s differs from its recorded length", name)
	}
	return body, nil
}

func exactSellerMembers(pack *zip.Reader, expected map[string]bool) error {
	if len(pack.File) != len(expected) {
		return errors.New("ZIP member count differs from the edition")
	}
	for _, member := range pack.File {
		if !expected[member.Name] || !member.Mode().IsRegular() {
			return fmt.Errorf("unexpected or duplicate ZIP member %q", member.Name)
		}
		delete(expected, member.Name)
	}
	return nil
}

func (d *studioSellerDraft) checkFiles(pack *zip.Reader, selected *v1.PosterReleaseCandidate) error {
	const listing, notes, survey, buyer = "listing.txt", "seller/review.md", "seller/observations.csv", "buyer/signal-studies.zip"
	members := map[string]bool{"seller/draft.json": true, listing: true, notes: true, survey: true, buyer: true}
	delivery := make(map[string]*v1.PosterFile, len(selected.DeliveryFiles))
	for _, ref := range selected.DeliveryFiles {
		delivery[ref.Name] = ref
	}
	for _, image := range d.Gallery {
		name := image.File.GetName()
		if !fs.ValidPath(name) || path.Base(name) != name || path.Ext(name) != ".jpg" || len(image.SourceFiles) == 0 {
			return errors.New("a listing photo is missing its name or source sheets")
		}
		for _, source := range image.SourceFiles {
			if source == nil || !proto.Equal(source, delivery[source.GetName()]) {
				return fmt.Errorf("%s refers to a different buyer sheet", name)
			}
		}
		member := "previews/" + name
		if members[member] {
			return fmt.Errorf("duplicate listing photo %s", name)
		}
		members[member] = true
		if _, err := checkedSellerFile(pack, member, image.File); err != nil {
			return err
		}
	}
	if err := exactSellerMembers(pack, members); err != nil {
		return err
	}
	if d.ListingText.GetName() != listing || d.SellerNotes.GetName() != notes || len(d.ObservationTemplateSha256) != 64 {
		return errors.New("the seller listing, review or measurement template is missing")
	}
	text, err := checkedSellerFile(pack, listing, d.ListingText)
	if err != nil {
		return err
	}
	if string(text) != d.Title+"\n\n"+d.Description+"\n" {
		return errors.New("listing text differs from the seller copy")
	}
	if _, err := checkedSellerFile(pack, notes, d.SellerNotes); err != nil {
		return err
	}
	if _, _, err := file(pack, survey, d.ObservationTemplateSha256); err != nil {
		return err
	}
	bundle, err := checkedSellerFile(pack, buyer, d.BuyerFile)
	if err != nil {
		return err
	}
	sheets, err := zip.NewReader(bytes.NewReader(bundle), int64(len(bundle)))
	if err != nil {
		return err
	}
	names := make(map[string]bool, len(delivery))
	for name, ref := range delivery {
		names[name] = true
		if _, err := checkedSellerFile(sheets, name, ref); err != nil {
			return err
		}
	}
	return exactSellerMembers(sheets, names)
}
