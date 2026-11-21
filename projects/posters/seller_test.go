package posters

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"fmt"
	"slices"
	"strings"
	"testing"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/stretchr/testify/require"
)

func sellerTestZip(t *testing.T, files map[string][]byte, duplicate string) []byte {
	t.Helper()
	var buf bytes.Buffer
	w := zip.NewWriter(&buf)
	write := func(name string) {
		out, err := w.Create(name)
		require.NoError(t, err)
		_, err = out.Write(files[name])
		require.NoError(t, err)
	}
	for name := range files {
		write(name)
	}
	if duplicate != "" {
		write(duplicate)
	}
	require.NoError(t, w.Close())
	return buf.Bytes()
}

func TestSellerDownloadSelection(t *testing.T) {
	const base = "https://studio.dropshippr-apps.workers.dev/collections/signal-studies?view=etsy-pack&packet="
	digest := strings.Repeat("a", 64)
	link := base + editorialPacketSHA + "&draft=" + digest
	p, d, err := sellerDownloadSelection(link)
	require.NoError(t, err)
	require.Equal(t, editorialPacketSHA, p)
	require.Equal(t, digest, d)
	for _, bad := range []string{link + "&draft=" + digest, strings.Replace(link, "https:", "http:", 1),
		strings.Replace(link, "studio.dropshippr-apps.workers.dev", "example.org", 1),
		strings.Replace(link, "etsy-pack", "etsy-draft", 1), base + editorialPacketSHA, link[:len(link)-1]} {
		_, _, err := sellerDownloadSelection(bad)
		require.Error(t, err)
	}
}

func TestSellerMaterials(t *testing.T) {
	ref := func(name string, data []byte) *v1.PosterFile {
		return &v1.PosterFile{Name: name, Sha256: fmt.Sprintf("%x", sha256.Sum256(data)), Bytes: uint32(len(data))}
	}
	sheet := []byte("Wave field A4 fixture")
	member := ref("wave-field-A4.pdf", sheet)
	buyer := sellerTestZip(t, map[string][]byte{member.Name: sheet}, "")
	files := map[string][]byte{
		"seller/draft.json": []byte("{}"), "buyer/signal-studies.zip": buyer,
		"listing.txt": []byte("Signal Studies\n\nPrint all three.\n"), "seller/review.md": []byte("Private review"),
		"seller/observations.csv": []byte("observed_at\n"),
	}
	selected := &v1.PosterReleaseCandidate{Edition: CaptionEdition, ListingTitle: "Signal Studies",
		PrintPack: ref("caption-01/signal-studies.zip", buyer), DeliveryFiles: []*v1.PosterFile{member}}
	draft := studioSellerDraft{Schema: "omega.marketplace-draft/v1", Channel: "Etsy", Edition: CaptionEdition,
		State: "offline-proposal", ProposalPacketSha256: captionPacketSHA, SourceReleasePacketSha256: editorialPacketSHA,
		SourceListingTitle: selected.ListingTitle, Title: "Signal Studies", Description: "Print all three.",
		BuyerFile: ref("signal-studies.zip", buyer), BuyerFileContents: selected.DeliveryFiles,
		ListingText: ref("listing.txt", files["listing.txt"]), SellerNotes: ref("seller/review.md", files["seller/review.md"]),
		ObservationTemplateSha256: ref("", files["seller/observations.csv"]).Sha256}
	for _, name := range []string{"01-set.jpg", "02-phase-portrait.jpg", "03-harmonic-sum.jpg", "04-wave-field.jpg"} {
		data := []byte("fixture for " + name)
		files["previews/"+name] = data
		draft.Gallery = append(draft.Gallery, studioSellerPhoto{ref(name, data), []*v1.PosterFile{member}})
	}
	validate := func(d studioSellerDraft, duplicate string) error {
		body := sellerTestZip(t, files, duplicate)
		pack, err := zip.NewReader(bytes.NewReader(body), int64(len(body)))
		require.NoError(t, err)
		return d.checkFiles(pack, selected)
	}
	require.NoError(t, draft.checkSelection(selected, captionPacketSHA))
	require.NoError(t, validate(draft, ""))
	issued := draft
	issued.State, issued.ReleasePacketSha256, issued.ProposalPacketSha256 = "offline-draft", captionPacketSHA, ""
	require.NoError(t, issued.checkSelection(selected, captionPacketSHA))
	issued.State = "offline-proposal"
	require.Error(t, issued.checkSelection(selected, captionPacketSHA))
	require.Error(t, draft.checkSelection(selected, editorialPacketSHA))
	editorial := draft
	editorial.Edition, editorial.State = EditorialEdition, "offline-draft"
	editorial.ReleasePacketSha256, editorial.ProposalPacketSha256, editorial.SourceReleasePacketSha256 = editorialPacketSHA, "", ""
	editorialCandidate := &v1.PosterReleaseCandidate{Edition: EditorialEdition, ListingTitle: selected.ListingTitle,
		PrintPack: selected.PrintPack, DeliveryFiles: selected.DeliveryFiles}
	require.NoError(t, editorial.checkSelection(editorialCandidate, editorialPacketSHA))
	editorial.SourceReleasePacketSha256 = captionPacketSHA
	require.Error(t, editorial.checkSelection(editorialCandidate, editorialPacketSHA))

	require.Error(t, validate(draft, "previews/01-set.jpg"))
	otherArt := draft
	otherArt.Gallery = slices.Clone(draft.Gallery)
	otherArt.Gallery[0].SourceFiles = []*v1.PosterFile{ref(member.Name, []byte("earlier caption"))}
	require.Error(t, validate(otherArt, ""))
	for _, name := range []string{"previews/04-wave-field.jpg", "buyer/signal-studies.zip", "listing.txt", "seller/review.md", "seller/observations.csv"} {
		original := files[name]
		files[name] = []byte("different edition")
		require.Error(t, validate(draft, ""), name)
		files[name] = original
	}
}
