package posters

import (
	"archive/zip"
	"bytes"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"strings"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"google.golang.org/protobuf/encoding/protojson"
)

const (
	launchURL         = "https://studio.dropshippr-apps.workers.dev/collections/signal-studies?view=launch-review-pack&packet="
	launchManifest    = "launch-review.json"
	launchPacket      = "edition/packet.json"
	launchIssue       = "edition/private-issue.json"
	launchOffer       = "offer/test-offer.json"
	launchSeller      = "seller/seller-kit.zip"
	launchDestination = "/collections/signal-studies?view=store"
	maxLaunchZIP      = 4 << 20
)

var launchFileLimits = map[string]int64{
	"START-HERE.md": 64 << 10, launchManifest: 64 << 10, launchPacket: 1 << 20,
	launchIssue: 4096, launchOffer: 64 << 10, launchSeller: maxFileSize,
}

func launchFiles(fsys fs.FS, name string) (map[string][]byte, error) {
	f, err := fsys.Open(name)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() <= 0 || info.Size() > maxLaunchZIP {
		return nil, errors.New("select a regular Studio review ZIP of up to 4 MiB")
	}
	raw, err := io.ReadAll(io.LimitReader(f, maxLaunchZIP+1))
	if err != nil {
		return nil, err
	}
	if int64(len(raw)) != info.Size() {
		return nil, errors.New("the review ZIP size changed")
	}
	pack, err := zip.NewReader(bytes.NewReader(raw), int64(len(raw)))
	if err != nil {
		return nil, err
	}
	if len(pack.File) != len(launchFileLimits) {
		return nil, errors.New("the launch review must contain exactly six files")
	}
	out := make(map[string][]byte, len(pack.File))
	for _, member := range pack.File {
		limit, ok := launchFileLimits[member.Name]
		if !ok || !member.Mode().IsRegular() || out[member.Name] != nil || member.Flags&1 != 0 ||
			member.UncompressedSize64 == 0 || member.UncompressedSize64 > uint64(limit) {
			return nil, errors.New("unexpected, duplicate, encrypted or oversized review ZIP member")
		}
		reader, err := member.Open()
		if err != nil {
			return nil, err
		}
		body, err := io.ReadAll(io.LimitReader(reader, limit+1))
		closeErr := reader.Close()
		if err != nil || closeErr != nil || uint64(len(body)) != member.UncompressedSize64 {
			return nil, fmt.Errorf("could not verify review member %s", member.Name)
		}
		out[member.Name] = body
	}
	return out, nil
}

func checkLaunchFiles(review *v1.ChannelLaunchReview, files map[string][]byte) error {
	if len(review.Files) != len(launchFileLimits)-1 {
		return errors.New("the manifest must identify all five companion files")
	}
	seen := make(map[string]bool, len(review.Files))
	for _, ref := range review.Files {
		raw, ok := files[ref.GetName()]
		if !ok || ref.Name == launchManifest || seen[ref.Name] || uint64(ref.Bytes) != uint64(len(raw)) || ref.Sha256 != sourceDigest(raw) {
			return errors.New("a launch manifest file is missing, repeated or differs from its recorded bytes and SHA-256")
		}
		seen[ref.Name] = true
	}
	return nil
}

func checkLaunchGates(review *v1.ChannelLaunchReview) error {
	const prepared = v1.LaunchReviewGateState_LAUNCH_REVIEW_GATE_STATE_PREPARED
	const decide = v1.LaunchReviewGateState_LAUNCH_REVIEW_GATE_STATE_NEEDS_DECISION
	const evidence = v1.LaunchReviewGateState_LAUNCH_REVIEW_GATE_STATE_NEEDS_EVIDENCE
	expected := map[string]v1.LaunchReviewGateState{
		"materials": prepared, "measurement": prepared, "offer-price": decide, "buyer-wording": decide,
		"paper-proof": evidence, "distribution-rights": decide, "shop-and-fees": decide, "buyer-support": decide, "publication": decide,
	}
	if review.PriceSource == "seller-draft" {
		expected["offer-price"] = prepared
	}
	switch review.WordingState {
	case "selected":
		expected["buyer-wording"] = prepared
	case "held", "awaiting":
	default:
		return errors.New("unknown owner wording state")
	}
	for _, gate := range review.Gates {
		want, ok := expected[gate.GetId()]
		if !ok || gate.State != want || strings.TrimSpace(gate.Title) == "" || strings.TrimSpace(gate.Detail) == "" {
			return errors.New("a private preparation gate is duplicated, contradictory or incomplete")
		}
		delete(expected, gate.Id)
	}
	if len(expected) != 0 {
		return errors.New("the private launch review is missing a required gate")
	}
	return nil
}

// VerifyLaunchReview checks the locally selected, pinned package and all nested
// artwork without extracting anything. Its packet and offer can be passed on to
// the collection verifier and the existing private checkout.
func VerifyLaunchReview(fsys fs.FS, name, link string) (*v1.VerifiedChannelLaunchReview, []byte, error) {
	files, err := launchFiles(fsys, name)
	if err != nil {
		return nil, nil, err
	}
	raw, packetRaw, quoteRaw := files[launchManifest], files[launchPacket], files[launchOffer]
	packet, manifest, offerSHA := sourceDigest(packetRaw), sourceDigest(raw), sourceDigest(quoteRaw)
	if link != launchURL+packet+"&review="+manifest {
		return nil, nil, errors.New("the exact Studio launch review link, packet or manifest checksum differs")
	}
	review := new(v1.ChannelLaunchReview)
	if err := protojson.Unmarshal(raw, review); err != nil {
		return nil, nil, err
	}
	if err := checkLaunchFiles(review, files); err != nil {
		return nil, nil, err
	}
	if review.Schema != "omega.channel-launch-review/v1" || review.BusinessId != StudioBusinessID || review.ProductId != StudioProductID ||
		review.Channel != "Etsy" || review.Action != "prepare-offline-listing" || review.PrivateDestination != launchDestination {
		return nil, nil, errors.New("the review does not identify this private Etsy preparation")
	}
	if err := checkLaunchGates(review); err != nil {
		return nil, nil, err
	}
	issue := new(v1.LaunchReviewPrivateIssue)
	if err := protojson.Unmarshal(files[launchIssue], issue); err != nil {
		return nil, nil, err
	}
	issuedAt, err := time.Parse(time.RFC3339, issue.RecordedAt)
	if err != nil || !offerTime.MatchString(issue.RecordedAt) || !strings.HasSuffix(issue.RecordedAt, "Z") ||
		issue.ListingId != OriginalEdition || issue.Destination != launchDestination || issue.PacketSha256 != packet ||
		(issue.Trigger != "scheduled" && issue.Trigger != "owner-requested") {
		return nil, nil, errors.New("the private issue receipt differs from the listing, packet, destination or issuance")
	}
	candidate, err := reviewedCandidate(packetRaw, packet)
	if err != nil {
		return nil, nil, err
	}
	q := new(v1.PosterTestOffer)
	if err := protojson.Unmarshal(quoteRaw, q); err != nil {
		return nil, nil, err
	}
	offer, err := checkStudioTestOffer(q, candidate, packet, offerSHA)
	if err != nil {
		return nil, nil, err
	}
	if review.Edition != offer.Edition || review.AmountMinor != q.AmountMinor || review.Currency != q.Currency ||
		review.PriceSource != q.PriceSource || (review.WordingState == "selected") != (q.WordingRevision > 0) ||
		review.SellerDraftSha256 != q.SellerDraftSha256 || review.BuyerArchiveSha256 != q.ArchiveSha256 {
		return nil, nil, errors.New("the launch manifest disagrees with the selected test offer or buyer ZIP")
	}
	if q.PriceRevision > 0 {
		recorded, _ := time.Parse(time.RFC3339, q.PriceRecordedAt) // Validated by checkStudioTestOffer.
		if recorded.Before(issuedAt) {
			return nil, nil, errors.New("the saved price predates the private issue receipt")
		}
	}
	seller := files[launchSeller]
	pack, err := zip.NewReader(bytes.NewReader(seller), int64(len(seller)))
	if err != nil {
		return nil, nil, err
	}
	draftRaw, draft, err := readSellerPack(pack, candidate, packet, q.SellerDraftSha256)
	if err != nil {
		return nil, nil, err
	}
	if err := checkLaunchSeller(draftRaw, draft, candidate, q, issuedAt); err != nil {
		return nil, nil, err
	}
	return &v1.VerifiedChannelLaunchReview{ReviewSha256: manifest, PacketSha256: packet, OfferSha256: offerSHA,
		Review: review, Offer: offer, PrivateIssue: issue}, packetRaw, nil
}
