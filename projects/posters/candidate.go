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

const (
	OriginalEdition  = "signal-studies-v0.1"
	EditorialEdition = "signal-studies-editorial-01"
	CaptionEdition   = "signal-studies-caption-01"
	launchPlanSHA    = "5ea3fd82e4b28e810171799a107f8047547963e1d4a439a5ea9612d360332d2e"
	originalPackSHA  = "1085e2cdf49cce6b566064312c0dc2d6a92b27ff67982d37861b0bb3a3d324ab"
	maxFileSize      = 2 << 20
)

type pinnedFile struct{ name, sha256 string }

type editionFiles struct {
	printPack, reviewPDF, preview, artwork pinnedFile
}

var editions = map[string]editionFiles{
	OriginalEdition: {
		printPack: pinnedFile{"signal-studies-print-candidate.zip", originalPackSHA},
		reviewPDF: pinnedFile{"signal-studies-review.pdf", "b8447580c80451ea37d8bb9b086b2b602d9d03f34f72bab3ded40902c4f17cdf"},
		preview:   pinnedFile{"print-1.png", "5e86a0ee4ccfabf9f7f0000fd599fb2416734b372559209863560ea0e00ca4fd"},
		artwork:   pinnedFile{"harmonic-sum-A4.pdf", "3dd35f9939eacbb0b279d551c3af259d0a5d60f8bdefe50b565f676c6c4ba17e"},
	},
	EditorialEdition: {
		printPack: pinnedFile{"reader-proof-01/signal-studies.zip", "6fcfc7df642b32152537ca62d7bb3b21eeadb233b2eb4172046949c5b38c099e"},
		reviewPDF: pinnedFile{"reader-proof-01/edition-preview.pdf", "622a6e6a62083c08a6f644caa0cabca5bd257cf7efa44834667f97bc0d5d13fa"},
		preview:   pinnedFile{"print-2.png", "7a5790747ac6b659688d6fa4420f294719475b2b7051e9846091a4b635cb1c5a"},
		artwork:   pinnedFile{"phase-portrait-A4.pdf", "d69b1d703cb561cf3295c63d34990a331512c65db8a7b56b0972370abc7932fb"},
	},
	CaptionEdition: {
		printPack: pinnedFile{"caption-01/signal-studies.zip", "9c6813f61fa1e98e19b741e6f368f0a7bfe8fbf2cfe285dfb2082a4789a2b8d8"},
		reviewPDF: pinnedFile{"caption-01/edition-preview.pdf", "21dd034c6c1b0953bc9a4cbd536f6e5e300bc0859c2146991d2dff0e289daf2c"},
		preview:   pinnedFile{"print-2.png", "7a5790747ac6b659688d6fa4420f294719475b2b7051e9846091a4b635cb1c5a"},
		artwork:   pinnedFile{"phase-portrait-A4.pdf", "d69b1d703cb561cf3295c63d34990a331512c65db8a7b56b0972370abc7932fb"},
	},
}

// WithCaptionFiles reads the two on-demand exports alongside the original
// collection. All other inputs continue to come from their issued locations.
func WithCaptionFiles(collection, downloads fs.FS) fs.FS {
	if downloads == nil {
		return collection
	}
	return captionCollection{collection, downloads}
}

type captionCollection struct{ collection, downloads fs.FS }

func (c captionCollection) Open(name string) (fs.File, error) {
	files := editions[CaptionEdition]
	if name == files.printPack.name || name == files.reviewPDF.name {
		return c.downloads.Open(strings.TrimPrefix(name, "caption-01/"))
	}
	return c.collection.Open(name)
}

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

// Candidate reproduces the original poster pilot's release candidate.
func Candidate(collection fs.FS) (*omegav1.PosterReleaseCandidate, error) {
	return CandidateForEdition(collection, OriginalEdition)
}

// CandidateForEdition verifies the selected release and derives its manifest
// from the collection files, preserving the delivery archive's member order.
func CandidateForEdition(collection fs.FS, edition string) (*omegav1.PosterReleaseCandidate, error) {
	files, ok := editions[edition]
	if !ok {
		return nil, fmt.Errorf("unknown poster edition %q", edition)
	}
	c := &omegav1.PosterReleaseCandidate{Edition: edition}
	var delivery, source *zip.Reader
	var err error
	c.PrintPack, delivery, err = archive(collection, files.printPack.name, files.printPack.sha256)
	if err != nil {
		return nil, err
	}
	c.DevelopmentKit, source, err = archive(collection, "signal-studies-development-kit.zip", "b94c205fd13ad83d1d81f70feb2f66327b8f3e9cee19840efa8473c34aed6aab")
	if err != nil {
		return nil, err
	}
	c.ReviewPdf, _, err = file(collection, files.reviewPDF.name, files.reviewPDF.sha256)
	if err != nil {
		return nil, err
	}
	c.ArtworkPreview, _, err = file(collection, files.preview.name, files.preview.sha256)
	if err != nil {
		return nil, err
	}
	for _, item := range delivery.File {
		ref, _, err := file(delivery, item.Name, "")
		if err != nil {
			return nil, err
		}
		c.DeliveryFiles = append(c.DeliveryFiles, ref)
		if ref.Name == files.artwork.name {
			c.SelectedArtwork = ref
		}
	}
	if c.GetSelectedArtwork().GetSha256() != files.artwork.sha256 {
		return nil, fmt.Errorf("the selected A4 artwork is missing or changed")
	}
	if edition == EditorialEdition || edition == CaptionEdition {
		// Studio's saved Phase portrait record selects the A4 member inside the
		// original Library ZIP. The corrected delivery must carry those bytes.
		original := editions[OriginalEdition].printPack
		_, library, err := archive(collection, original.name, original.sha256)
		if err != nil {
			return nil, err
		}
		if _, _, err := file(library, c.SelectedArtwork.Name, c.SelectedArtwork.Sha256); err != nil {
			return nil, err
		}
		var listing []byte
		c.ListingSource, listing, err = file(collection, "reader-proof-01/listing.txt", "9d7a1a18960e35886f2a4868f818cbcc0f47bdba6313e6d73d9c53f0b4c82768")
		if err != nil {
			return nil, err
		}
		c.ListingTitle, c.ListingDescription, ok = strings.Cut(strings.TrimSuffix(string(listing), "\n"), "\n\n")
		if !ok || c.ListingTitle == "" || c.ListingDescription == "" {
			return nil, fmt.Errorf("the editorial listing does not identify one title and description")
		}
		return c, nil
	}
	var plan []byte
	c.ListingSource, plan, err = file(source, "launch-plan.txt", launchPlanSHA)
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
