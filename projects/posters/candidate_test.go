package posters

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"fmt"
	"strings"
	"testing"
	"testing/fstest"
)

func TestCandidateRejectsChangedPackage(t *testing.T) {
	_, err := Candidate(fstest.MapFS{"signal-studies-print-candidate.zip": {Data: []byte("substitute edition")}})
	if err == nil {
		t.Fatal("candidate accepted a substitute delivery file")
	}
	_, err = CandidateForEdition(fstest.MapFS{"reader-proof-01/signal-studies.zip": {Data: []byte("substitute edition")}}, EditorialEdition)
	if err == nil || !strings.Contains(err.Error(), "reader-proof-01/signal-studies.zip does not match") {
		t.Fatalf("editorial candidate did not reject changed delivery: %v", err)
	}
	_, err = CandidateForEdition(fstest.MapFS{}, "unregistered")
	if err == nil || !strings.Contains(err.Error(), "unknown poster edition") {
		t.Fatalf("unregistered edition: %v", err)
	}
}

func TestCheckoutRequiresPrivateStudioPacket(t *testing.T) {
	raw := []byte(`{"schema":"omega.poster-review/v1","decision":{"checkoutEnabled":true,"publicLaunch":true}}`)
	digest := fmt.Sprintf("%x", sha256.Sum256(raw))
	_, _, _, err := TestOffer(fstest.MapFS{}, raw, digest)
	if err == nil || !strings.Contains(err.Error(), "private poster edition") {
		t.Fatalf("invalid decision: %v", err)
	}
	_, _, _, err = TestOffer(fstest.MapFS{}, append(raw, ' '), digest)
	if err == nil || !strings.Contains(err.Error(), "packet digest") {
		t.Fatalf("changed packet: %v", err)
	}
}

func TestArchiveChecksContainerAndMember(t *testing.T) {
	var buf bytes.Buffer
	writer := zip.NewWriter(&buf)
	member, err := writer.Create("poster.pdf")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := member.Write([]byte("selected artwork")); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	inputs := fstest.MapFS{"pack.zip": {Data: buf.Bytes()}}
	ref, members, err := archive(inputs, "pack.zip", fmt.Sprintf("%x", sha256.Sum256(buf.Bytes())))
	if err != nil || int(ref.GetBytes()) != buf.Len() {
		t.Fatalf("archive: %v, %v", ref, err)
	}
	if _, _, err := file(members, "poster.pdf", fmt.Sprintf("%x", sha256.Sum256([]byte("selected artwork")))); err != nil {
		t.Fatal(err)
	}
	if _, _, err := file(members, "poster.pdf", ref.Sha256); err == nil {
		t.Fatal("member accepted the container digest")
	}
}
