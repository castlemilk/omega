// Package posters prepares the Signal Studies digital poster business.
package posters

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"strings"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"google.golang.org/protobuf/encoding/protojson"
)

const maxFileSize = 2 << 20

func file(fsys fs.FS, name, expected string) (*omegav1.PosterFile, []byte, error) {
	f, err := fsys.Open(name)
	if err != nil {
		return nil, nil, err
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, maxFileSize+1))
	if err != nil {
		return nil, nil, err
	}
	digest := sha256.Sum256(data)
	hash := hex.EncodeToString(digest[:])
	if len(data) == 0 || len(data) > maxFileSize || (expected != "" && hash != expected) {
		return nil, nil, fmt.Errorf("%s does not match the selected edition", name)
	}
	return &omegav1.PosterFile{Name: name, Sha256: hash, Bytes: uint32(len(data))}, data, nil
}

func archive(fsys fs.FS, name, hash string) (*omegav1.PosterFile, *zip.Reader, error) {
	ref, data, err := file(fsys, name, hash)
	if err != nil {
		return nil, nil, err
	}
	z, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	return ref, z, err
}

// Candidate reads the edition's original files. The pinned input choices
// are the five byte selections in Studio's supervised poster pilot charter.
func Candidate(collection fs.FS) (*omegav1.PosterReleaseCandidate, error) {
	c := &omegav1.PosterReleaseCandidate{Edition: "signal-studies-v0.1"}
	var delivery, source *zip.Reader
	var err error
	c.PrintPack, delivery, err = archive(collection, "signal-studies-print-candidate.zip", "1085e2cdf49cce6b566064312c0dc2d6a92b27ff67982d37861b0bb3a3d324ab")
	if err != nil {
		return nil, err
	}
	c.DevelopmentKit, source, err = archive(collection, "signal-studies-development-kit.zip", "b94c205fd13ad83d1d81f70feb2f66327b8f3e9cee19840efa8473c34aed6aab")
	if err != nil {
		return nil, err
	}
	c.ReviewPdf, _, err = file(collection, "signal-studies-review.pdf", "b8447580c80451ea37d8bb9b086b2b602d9d03f34f72bab3ded40902c4f17cdf")
	if err != nil {
		return nil, err
	}
	c.ArtworkPreview, _, err = file(collection, "print-1.png", "5e86a0ee4ccfabf9f7f0000fd599fb2416734b372559209863560ea0e00ca4fd")
	if err != nil {
		return nil, err
	}
	for _, item := range delivery.File {
		ref, _, err := file(delivery, item.Name, "")
		if err != nil {
			return nil, err
		}
		c.DeliveryFiles = append(c.DeliveryFiles, ref)
		if ref.Name == "harmonic-sum-A4.pdf" {
			c.SelectedArtwork = ref
		}
	}
	if c.GetSelectedArtwork().GetSha256() != "3dd35f9939eacbb0b279d551c3af259d0a5d60f8bdefe50b565f676c6c4ba17e" {
		return nil, fmt.Errorf("the selected A4 artwork is missing or changed")
	}
	var plan []byte
	c.ListingSource, plan, err = file(source, "launch-plan.txt", "5ea3fd82e4b28e810171799a107f8047547963e1d4a439a5ea9612d360332d2e")
	if err != nil {
		return nil, err
	}
	_, listing, titleFound := strings.Cut(string(plan), "Proposed listing title:\n")
	title, descriptionAndPlan, descriptionFound := strings.Cut(listing, "\n\nDraft description:\n")
	description, _, endFound := strings.Cut(descriptionAndPlan, "\n\nPrice hypothesis:")
	if !titleFound || !descriptionFound || !endFound || strings.TrimSpace(title) == "" || strings.TrimSpace(description) == "" {
		return nil, fmt.Errorf("the launch plan does not identify one listing title and description")
	}
	c.ListingTitle = strings.TrimSpace(title)
	c.ListingDescription = strings.Join(strings.Fields(description), " ")
	return c, nil
}

// StableJSON canonicalizes protobuf JSON whitespace and field ordering so the
// same bytes identify a candidate across independent builds and languages.
func StableJSON(candidate *omegav1.PosterReleaseCandidate) ([]byte, error) {
	raw, err := protojson.Marshal(candidate)
	if err != nil {
		return nil, err
	}
	var value map[string]any
	if err := json.Unmarshal(raw, &value); err != nil {
		return nil, err
	}
	return json.MarshalIndent(value, "", "  ")
}
