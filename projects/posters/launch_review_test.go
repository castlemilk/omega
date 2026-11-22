package posters

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"io"
	"io/fs"
	"maps"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"testing/fstest"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

func testLaunchGate(id string, state v1.LaunchReviewGateState) *v1.LaunchReviewGate {
	return &v1.LaunchReviewGate{Id: id, State: state, Title: id, Detail: "Recorded for private review."}
}

func testLaunchWire(t *testing.T, value proto.Message) []byte {
	t.Helper()
	body, err := protojson.Marshal(value)
	require.NoError(t, err)
	return body
}

func launchFixture(t *testing.T) (map[string][]byte, *v1.ChannelLaunchReview) {
	t.Helper()
	raw, packet, q := studioQuoteFixture(t)
	files := map[string][]byte{
		"START-HERE.md": []byte("Private preparation for Etsy.\n"), launchPacket: packet, launchOffer: raw, launchSeller: []byte("placeholder seller ZIP"),
		launchIssue: testLaunchWire(t, &v1.LaunchReviewPrivateIssue{ListingId: OriginalEdition, Destination: launchDestination, PacketSha256: editorialPacketSHA, RecordedAt: "2026-11-21T05:15:53.692Z", Trigger: "scheduled"}),
	}
	r := &v1.ChannelLaunchReview{Schema: "omega.channel-launch-review/v1", BusinessId: StudioBusinessID, ProductId: StudioProductID, Edition: EditorialEdition,
		Channel: "Etsy", Action: "prepare-offline-listing", PrivateDestination: launchDestination, AmountMinor: q.AmountMinor, Currency: q.Currency,
		SellerDraftSha256: q.SellerDraftSha256, BuyerArchiveSha256: q.ArchiveSha256, PriceSource: q.PriceSource, WordingState: "awaiting"}
	for _, id := range []string{"materials", "measurement", "buyer-wording", "offer-price", "distribution-rights", "shop-and-fees", "buyer-support", "publication", "paper-proof"} {
		state := v1.LaunchReviewGateState_LAUNCH_REVIEW_GATE_STATE_NEEDS_DECISION
		if id == "paper-proof" {
			state = v1.LaunchReviewGateState_LAUNCH_REVIEW_GATE_STATE_NEEDS_EVIDENCE
		}
		if id == "materials" || id == "measurement" {
			state = v1.LaunchReviewGateState_LAUNCH_REVIEW_GATE_STATE_PREPARED
		}
		r.Gates = append(r.Gates, testLaunchGate(id, state))
	}
	resealLaunch(t, files, r)
	return files, r
}

func resealLaunch(t *testing.T, files map[string][]byte, r *v1.ChannelLaunchReview) {
	t.Helper()
	r.Files = nil
	for _, name := range []string{"START-HERE.md", launchPacket, launchIssue, launchOffer, launchSeller} {
		body := files[name]
		r.Files = append(r.Files, &v1.LaunchReviewFile{Name: name, Bytes: uint32(len(body)), Sha256: sourceDigest(body)})
	}
	files[launchManifest] = testLaunchWire(t, r)
}

func launchFixtureURL(files map[string][]byte) string {
	return launchURL + sourceDigest(files[launchPacket]) + "&review=" + sourceDigest(files[launchManifest])
}

func inspectLaunchBytes(raw []byte, link string) (*v1.VerifiedChannelLaunchReview, error) {
	files := fstest.MapFS{"review.zip": &fstest.MapFile{Data: raw}}
	result, _, err := VerifyLaunchReview(files, "review.zip", link)
	return result, err
}

func TestLaunchReviewRequiresExactMembersAndLink(t *testing.T) {
	files, _ := launchFixture(t)
	link := launchFixtureURL(files)
	raw := sellerTestZip(t, files, "")
	for _, wrong := range []string{"", link + "#page", link + "&extra=1", link + "&packet=" + editorialPacketSHA,
		strings.Replace(link, "https:", "http:", 1), strings.Replace(link, ".dev/", ".dev:443/", 1),
		strings.Replace(link, "//studio.", "//owner@studio.", 1), strings.Replace(link, "&review=", "&offer=", 1), strings.Replace(link, "launch-review-pack", "etsy-pack", 1)} {
		_, err := inspectLaunchBytes(raw, wrong)
		require.ErrorContains(t, err, "exact Studio")
	}
	t.Run("duplicate", func(t *testing.T) {
		_, err := inspectLaunchBytes(sellerTestZip(t, files, launchOffer), link)
		require.ErrorContains(t, err, "six files")
	})
	for _, name := range []string{"../packet.json", "/packet.json", "edition/", "edition\\packet.json"} {
		changed := maps.Clone(files)
		delete(changed, launchPacket)
		changed[name] = []byte("other")
		if strings.HasSuffix(name, "/") {
			changed[name] = nil
		}
		_, err := inspectLaunchBytes(sellerTestZip(t, changed, ""), link)
		require.Error(t, err)
	}
	t.Run("reference size and hash", func(t *testing.T) {
		changed := maps.Clone(files)
		changed["START-HERE.md"] = []byte("different note")
		_, err := inspectLaunchBytes(sellerTestZip(t, changed, ""), link)
		require.ErrorContains(t, err, "recorded bytes")
	})
	t.Run("bounded expansion", func(t *testing.T) {
		changed := maps.Clone(files)
		changed["START-HERE.md"] = bytes.Repeat([]byte{'z'}, (64<<10)+1)
		_, err := inspectLaunchBytes(sellerTestZip(t, changed, ""), link)
		require.ErrorContains(t, err, "oversized")
		_, err = inspectLaunchBytes(make([]byte, maxLaunchZIP+1), link)
		require.ErrorContains(t, err, "4 MiB")
	})
	t.Run("symbolic link", func(t *testing.T) {
		var buf bytes.Buffer
		out := zip.NewWriter(&buf)
		for name, body := range files {
			h := &zip.FileHeader{Name: name, Method: zip.Store}
			if name == launchPacket {
				h.SetMode(fs.ModeSymlink | 0777)
			}
			f, e := out.CreateHeader(h)
			require.NoError(t, e)
			_, e = f.Write(body)
			require.NoError(t, e)
		}
		require.NoError(t, out.Close())
		_, err := inspectLaunchBytes(buf.Bytes(), link)
		require.ErrorContains(t, err, "unexpected")
	})
}

func TestLaunchReviewRejectsRepinnedContradictions(t *testing.T) {
	for _, tc := range []struct {
		name, want string
		change     func(*v1.ChannelLaunchReview)
	}{
		{"other business", "private Etsy", func(r *v1.ChannelLaunchReview) { r.BusinessId = "different" }},
		{"public action", "private Etsy", func(r *v1.ChannelLaunchReview) { r.Action = "publish" }},
		{"public store", "private Etsy", func(r *v1.ChannelLaunchReview) { r.PrivateDestination = "/checkout" }},
		{"unearned publication", "preparation gate", func(r *v1.ChannelLaunchReview) {
			r.Gates[7].State = v1.LaunchReviewGateState_LAUNCH_REVIEW_GATE_STATE_PREPARED
		}},
		{"paper proof absent", "preparation gate", func(r *v1.ChannelLaunchReview) {
			r.Gates[8].State = v1.LaunchReviewGateState_LAUNCH_REVIEW_GATE_STATE_PREPARED
		}},
		{"wording unselected", "preparation gate", func(r *v1.ChannelLaunchReview) { r.WordingState = "selected" }},
		{"duplicate gate", "preparation gate", func(r *v1.ChannelLaunchReview) { r.Gates[0] = r.Gates[1] }},
		{"missing gate", "missing a required", func(r *v1.ChannelLaunchReview) { r.Gates = r.Gates[:8] }},
		{"gate missing detail", "preparation gate", func(r *v1.ChannelLaunchReview) { r.Gates[2].Detail = " " }},
		{"invented wording state", "wording state", func(r *v1.ChannelLaunchReview) { r.WordingState = "published" }},
		{"duplicate reference", "manifest file", func(r *v1.ChannelLaunchReview) { r.Files[0] = r.Files[1] }},
		{"hash without size", "manifest file", func(r *v1.ChannelLaunchReview) { r.Files[2].Bytes++ }},
		{"receipt missing", "all five", func(r *v1.ChannelLaunchReview) { r.Files = r.Files[:4] }},
		{"wrong total", "selected test offer", func(r *v1.ChannelLaunchReview) { r.AmountMinor++ }},
		{"wrong currency", "selected test offer", func(r *v1.ChannelLaunchReview) { r.Currency = "USD" }},
		{"wrong buyer ZIP", "selected test offer", func(r *v1.ChannelLaunchReview) { r.BuyerArchiveSha256 = originalPackSHA }},
		{"wrong seller digest", "selected test offer", func(r *v1.ChannelLaunchReview) { r.SellerDraftSha256 = originalPackSHA }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			files, r := launchFixture(t)
			tc.change(r)
			files[launchManifest] = testLaunchWire(t, r)
			_, err := inspectLaunchBytes(sellerTestZip(t, files, ""), launchFixtureURL(files))
			require.ErrorContains(t, err, tc.want)
		})
	}
	for _, change := range []func(*v1.LaunchReviewPrivateIssue){
		func(s *v1.LaunchReviewPrivateIssue) { s.PacketSha256 = captionPacketSHA },
		func(s *v1.LaunchReviewPrivateIssue) { s.ListingId = EditorialEdition },
		func(s *v1.LaunchReviewPrivateIssue) { s.Destination = "/public" },
		func(s *v1.LaunchReviewPrivateIssue) { s.Trigger = "automatic-publication" },
		func(s *v1.LaunchReviewPrivateIssue) { s.RecordedAt = "2026-02-31T12:00:00Z" },
	} {
		files, r := launchFixture(t)
		issue := new(v1.LaunchReviewPrivateIssue)
		require.NoError(t, protojson.Unmarshal(files[launchIssue], issue))
		change(issue)
		files[launchIssue] = testLaunchWire(t, issue)
		resealLaunch(t, files, r)
		_, err := inspectLaunchBytes(sellerTestZip(t, files, ""), launchFixtureURL(files))
		require.ErrorContains(t, err, "issue receipt")
	}
}

func unpackLaunchTestZip(t *testing.T, raw []byte) map[string][]byte {
	t.Helper()
	z, err := zip.NewReader(bytes.NewReader(raw), int64(len(raw)))
	require.NoError(t, err)
	m := map[string][]byte{}
	for _, f := range z.File {
		r, err := f.Open()
		require.NoError(t, err)
		m[f.Name], err = io.ReadAll(r)
		require.NoError(t, err)
		require.NoError(t, r.Close())
	}
	return m
}

func TestIssuedLaunchReviewAndSellerDecision(t *testing.T) {
	dir := os.Getenv("OMEGA_POSTER_LAUNCH_REVIEWS")
	if dir == "" {
		t.Skip("set OMEGA_POSTER_LAUNCH_REVIEWS for the exact issued Studio packages")
	}
	for _, label := range []string{"current", "revised"} {
		t.Run(label, func(t *testing.T) {
			body, err := os.ReadFile(filepath.Join(dir, label+".zip"))
			require.NoError(t, err)
			link, err := os.ReadFile(filepath.Join(dir, label+"-from.txt"))
			require.NoError(t, err)
			v, err := inspectLaunchBytes(body, strings.TrimSpace(string(link)))
			require.NoError(t, err)
			parts := unpackLaunchTestZip(t, body)
			require.Equal(t, sourceDigest(parts[launchManifest]), v.ReviewSha256)
			require.Equal(t, sourceDigest(parts[launchOffer]), v.Offer.StudioOfferSha256.Value)
			seller := unpackLaunchTestZip(t, parts[launchSeller])
			require.Equal(t, v.Review.BuyerArchiveSha256, sourceDigest(seller["buyer/signal-studies.zip"]))
			// Re-pin all envelopes to the modified seller draft. Rejection must
			// still follow from the underlying edition or seller decision.
			inspectSeller := func(t *testing.T, nested map[string][]byte, d map[string]any) error {
				t.Helper()
				files := maps.Clone(parts)
				body, err := json.Marshal(d)
				require.NoError(t, err)
				nested["seller/draft.json"] = body
				q := new(v1.PosterTestOffer)
				require.NoError(t, protojson.Unmarshal(files[launchOffer], q))
				q.SellerDraftSha256 = sourceDigest(body)
				files[launchOffer] = testLaunchWire(t, q)
				files[launchSeller] = sellerTestZip(t, nested, "")
				r := proto.CloneOf(v.Review)
				r.SellerDraftSha256 = q.SellerDraftSha256
				resealLaunch(t, files, r)
				_, err = inspectLaunchBytes(sellerTestZip(t, files, ""), launchFixtureURL(files))
				return err
			}
			for _, tc := range []struct {
				name   string
				change func(map[string]any)
			}{
				{"seller price", func(d map[string]any) { d["approvedPriceMinor"] = "1280" }},
				{"seller currency", func(d map[string]any) { d["approvedCurrency"] = "invalid" }},
				{"contradictory price description", func(d map[string]any) { d["priceHypothesis"] = "The saved price is AUD 2.00." }},
				{"measurement source", func(d map[string]any) { d["observationTemplateSha256"] = originalPackSHA }},
				{"contradictory wording", func(d map[string]any) { d["buyerTerms"] = map[string]any{"disclosure": "Changed"} }},
				{"inconsistent decision checksum", func(d map[string]any) {
					decision, _ := d["priceDecision"].(map[string]any)
					if decision == nil {
						decision = map[string]any{}
						d["priceDecision"] = decision
					}
					decision["decisionSha256"] = originalPackSHA
				}},
			} {
				t.Run(tc.name, func(t *testing.T) {
					var d map[string]any
					require.NoError(t, json.Unmarshal(seller["seller/draft.json"], &d))
					tc.change(d)
					require.Error(t, inspectSeller(t, maps.Clone(seller), d))
				})
			}
			if v.Review.PriceSource == "seller-draft" {
				for _, tc := range []struct{ member, want string }{
					{"previews/01-set.jpg", "seller photographs"},
					{"seller/review.md", "preparation notes"},
					{"buyer/signal-studies.zip", "reviewed buyer edition"},
				} {
					t.Run("repinned "+tc.member, func(t *testing.T) {
						var d map[string]any
						nested := maps.Clone(seller)
						require.NoError(t, json.Unmarshal(nested["seller/draft.json"], &d))
						var ref map[string]any
						switch tc.member {
						case "previews/01-set.jpg":
							ref = d["gallery"].([]any)[0].(map[string]any)["file"].(map[string]any)
						case "seller/review.md":
							ref = d["sellerNotes"].(map[string]any)
						default:
							ref = d["buyerFile"].(map[string]any)
						}
						nested[tc.member] = []byte("different edition or price")
						ref["bytes"], ref["sha256"] = len(nested[tc.member]), sourceDigest(nested[tc.member])
						require.ErrorContains(t, inspectSeller(t, nested, d), tc.want)
					})
				}
			}
		})
	}
}
