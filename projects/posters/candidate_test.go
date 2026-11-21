package posters

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"fmt"
	"testing"
	"testing/fstest"
)

func TestCandidateRejectsChangedPackage(t *testing.T) {
	_, err := Candidate(fstest.MapFS{"signal-studies-print-candidate.zip": {Data: []byte("substitute edition")}})
	if err == nil {
		t.Fatal("candidate accepted a substitute delivery file")
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
