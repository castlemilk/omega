package posters

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"strings"
	"testing"
	"testing/fstest"

	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
)

// These files are the exact wire bytes emitted by Studio's prepareSelection.
// Keep the original field order and absence of a trailing newline.
func TestReviewedStudioSelections(t *testing.T) {
	for _, tc := range []struct {
		edition, digest, lead, artworkID, copyID string
	}{
		{OriginalEdition, originalPacketSHA, "harmonic-sum", "58ac9b0f-bdc6-56b9-8a1a-131ef87ce8fb", "821ab426-0868-5525-814f-24acbe3025d5"},
		{EditorialEdition, editorialPacketSHA, "phase-portrait", "3a227c6c-1432-59a6-80d8-5c4af20ec341", "28cb2421-131b-4bc6-92d6-4613e2cab765"},
		{CaptionEdition, captionPacketSHA, "phase-portrait", "3a227c6c-1432-59a6-80d8-5c4af20ec341", "28cb2421-131b-4bc6-92d6-4613e2cab765"},
	} {
		t.Run(tc.edition, func(t *testing.T) {
			raw, err := os.ReadFile("testdata/" + tc.edition + ".json")
			require.NoError(t, err)
			selected, err := reviewedCandidate(raw, tc.digest)
			require.NoError(t, err)
			require.Equal(t, tc.edition, selected.Edition)
			require.Len(t, selected.DeliveryFiles, 8)
			require.Equal(t, tc.lead+"-A4.pdf", selected.SelectedArtwork.Name)

			// Audit which sources and decision the pinned packet actually binds.
			var packet map[string]any
			require.NoError(t, json.Unmarshal(raw, &packet))
			fields := map[string]any{
				"schema": "omega.poster-review/v1", "runId": "a8e14e74-1110-4000-8000-000000000101",
				"decision": map[string]any{"audience": "studio-owner", "destination": "/collections/signal-studies?view=store",
					"checkoutEnabled": false, "publicLaunch": false, "additionalSpend": float64(0)},
				"review.artwork.source": map[string]any{"businessId": StudioBusinessID, "projectId": StudioProductID,
					"recordId": tc.artworkID, "recordRevision": float64(1), "subjectId": "signal-studies-" + tc.lead},
				"review.artwork.asset.id":            tc.lead + "-a4",
				"review.artwork.asset.libraryFileId": "libfile_6e770951dac08191a33b72affdb1f607",
				"review.artwork.asset.sha256":        originalPackSHA,
				"review.artwork.asset.archiveMember": map[string]any{"name": selected.SelectedArtwork.Name, "sha256": selected.SelectedArtwork.Sha256},
				"review.copy.source": map[string]any{"businessId": StudioBusinessID, "projectId": StudioProductID,
					"recordId": tc.copyID, "recordRevision": float64(1)},
				"review.copy.title": selected.ListingTitle, "review.copy.content.text": selected.ListingDescription,
				"review.copy.content.parentRecordId": nil,
			}
			if tc.edition == EditorialEdition {
				parent := "821ab426-0868-5525-814f-24acbe3025d5"
				fields["review.copy.content.parentRecordId"] = parent
				fields["experiment.copyParent"] = parent
				fields["experiment.previousPacketSha256"] = originalPacketSHA
				fields["experiment.cycle"] = float64(2)
				fields["experiment.changedVariable"] = "editorial-revision"
				fields["experiment.leadPrint"] = tc.lead
				fields["experiment.editorial.source"] = "ai-reader"
				fields["experiment.editorial.storefrontRecordId"] = "308dff0a-4599-4242-9520-b8c21dc80f38"
				fields["experiment.editorial.storefrontRevision"] = float64(1)
				fields["experiment.editorial.copyRecordId"] = tc.copyID
				fields["experiment.editorial.copyRevision"] = float64(1)
				require.Len(t, strings.Split(selected.ListingDescription, "\n\n"), 3)
			} else if tc.edition == CaptionEdition {
				fields["review.copy.content.parentRecordId"] = "821ab426-0868-5525-814f-24acbe3025d5"
				fields["experiment.cycle"] = float64(3)
				fields["experiment.previousPacketSha256"] = editorialPacketSHA
				fields["experiment.changedVariable"] = "scientific-caption"
				fields["experiment.revisedCaption"] = "A parallel projection of a calculated field."
				fields["experiment.captionProof.sha256"] = "3cac88cf702522085c26e1742be5fba5dbe6f60bd2868a0cabcdd83258a1b988"
			} else {
				require.NotContains(t, packet, "experiment")
			}
			for name, want := range fields {
				var value any = packet
				for _, key := range strings.Split(name, ".") {
					scope, ok := value.(map[string]any)
					require.True(t, ok, name)
					require.Contains(t, scope, key, name)
					value = scope[key]
				}
				require.Equal(t, want, value, name)
			}

			for _, change := range [][2]string{
				{`"publicLaunch":false`, `"publicLaunch":true`}, {tc.copyID, tc.artworkID},
				{tc.artworkID, tc.copyID}, {tc.edition, "substituted-edition"},
			} {
				changed := bytes.Replace(raw, []byte(change[0]), []byte(change[1]), 1)
				require.NotEqual(t, raw, changed)
				require.True(t, json.Valid(changed))
				_, _, _, err := TestOffer(fstest.MapFS{}, changed, tc.digest)
				require.ErrorContains(t, err, "packet digest")
				_, _, _, err = TestOffer(fstest.MapFS{}, changed, fmt.Sprintf("%x", sha256.Sum256(changed)))
				require.ErrorContains(t, err, "private poster edition")
			}
		})
	}
}

func TestCandidatesFromStudioCollection(t *testing.T) {
	dir := os.Getenv("OMEGA_POSTER_TEST_COLLECTION")
	if dir == "" {
		t.Skip("set OMEGA_POSTER_TEST_COLLECTION to the Studio Signal Studies files")
	}
	var collection fs.FS = os.DirFS(dir)
	type selection struct{ edition, packetDigest string }
	cases := []selection{
		{OriginalEdition, originalPacketSHA}, {EditorialEdition, editorialPacketSHA},
	}
	if downloads := os.Getenv("OMEGA_POSTER_CAPTION_FILES"); downloads != "" {
		collection = WithCaptionFiles(collection, os.DirFS(downloads))
		cases = append(cases, selection{CaptionEdition, captionPacketSHA})
	}
	for _, tc := range cases {
		t.Run(tc.edition, func(t *testing.T) {
			raw, err := os.ReadFile("testdata/" + tc.edition + ".json")
			require.NoError(t, err)
			selected, err := reviewedCandidate(raw, tc.packetDigest)
			require.NoError(t, err)
			got, err := CandidateForEdition(collection, tc.edition)
			require.NoError(t, err)
			require.True(t, proto.Equal(got, selected))
			if tc.edition == OriginalEdition {
				def, err := Candidate(collection)
				require.NoError(t, err)
				require.True(t, proto.Equal(def, got))
				return
			}
			listing, err := fs.ReadFile(collection, got.ListingSource.Name)
			require.NoError(t, err)
			require.Equal(t, got.ListingTitle+"\n\n"+got.ListingDescription+"\n", string(listing))
			files := fstest.MapFS{}
			originalPack := editions[OriginalEdition].printPack.name
			for _, name := range []string{got.PrintPack.Name, got.ReviewPdf.Name, got.DevelopmentKit.Name, got.ArtworkPreview.Name, originalPack} {
				contents, err := fs.ReadFile(collection, name)
				require.NoError(t, err)
				files[name] = &fstest.MapFile{Data: contents}
			}
			files[got.ListingSource.Name] = &fstest.MapFile{Data: bytes.ReplaceAll(listing, []byte("\n\n"), []byte(" "))}
			_, _, _, err = TestOffer(files, raw, tc.packetDigest)
			require.ErrorContains(t, err, got.ListingSource.Name+" does not match")
			files[got.ListingSource.Name] = &fstest.MapFile{Data: listing}
			files[originalPack] = files[got.PrintPack.Name]
			_, _, _, err = TestOffer(files, raw, tc.packetDigest)
			require.ErrorContains(t, err, originalPack+" does not match")
		})
	}
}
