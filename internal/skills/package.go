package skills

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

const manifestFileName = "SKILL.json"

// maxDecompressBytes caps extraction size to guard against decompression bombs.
const maxDecompressBytes = 100 * 1024 * 1024 // 100 MiB

// Package creates a .skill ZIP archive at outputPath containing the SKILL.json
// manifest plus all files found under sourceDir.
func Package(skill Skill, sourceDir string, outputPath string) error {
	if err := Validate(skill); err != nil {
		return fmt.Errorf("skills: invalid skill: %w", err)
	}

	buf := new(bytes.Buffer)
	zw := zip.NewWriter(buf)

	// Write manifest.
	manifest := manifestFromSkill(skill)
	manifestData, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return fmt.Errorf("skills: marshal manifest: %w", err)
	}
	mw, err := zw.Create(manifestFileName)
	if err != nil {
		return fmt.Errorf("skills: create manifest entry: %w", err)
	}
	if _, err := mw.Write(manifestData); err != nil {
		return fmt.Errorf("skills: write manifest: %w", err)
	}

	// Walk sourceDir and add files.
	if sourceDir != "" {
		if err := filepath.WalkDir(sourceDir, func(path string, d os.DirEntry, walkErr error) error {
			if walkErr != nil {
				return walkErr
			}
			if d.IsDir() {
				return nil
			}
			rel, err := filepath.Rel(sourceDir, path)
			if err != nil {
				return err
			}
			fw, err := zw.Create(rel)
			if err != nil {
				return fmt.Errorf("skills: create zip entry %q: %w", rel, err)
			}
			f, err := os.Open(path) //nolint:gosec // path is derived from WalkDir under a caller-supplied directory
			if err != nil {
				return fmt.Errorf("skills: open %q: %w", path, err)
			}
			_, copyErr := io.Copy(fw, f)
			if closeErr := f.Close(); closeErr != nil && copyErr == nil {
				copyErr = fmt.Errorf("skills: close %q: %w", path, closeErr)
			}
			if copyErr != nil {
				return fmt.Errorf("skills: copy %q: %w", rel, copyErr)
			}
			return nil
		}); err != nil {
			return fmt.Errorf("skills: walk source dir: %w", err)
		}
	}

	if err := zw.Close(); err != nil {
		return fmt.Errorf("skills: close zip writer: %w", err)
	}
	if err := os.WriteFile(outputPath, buf.Bytes(), 0o600); err != nil {
		return fmt.Errorf("skills: write archive %q: %w", outputPath, err)
	}
	return nil
}

// Unpackage extracts a .skill archive to targetDir and returns the parsed Skill.
func Unpackage(archivePath string, targetDir string) (*Skill, error) {
	zr, err := zip.OpenReader(archivePath) //nolint:gosec // path is validated by caller
	if err != nil {
		return nil, fmt.Errorf("skills: open archive %q: %w", archivePath, err)
	}
	defer func() { _ = zr.Close() }()

	var skill *Skill
	for _, f := range zr.File {
		if err := extractFile(f, targetDir); err != nil {
			return nil, err
		}
		if f.Name == manifestFileName {
			s, err := parseManifestFile(f)
			if err != nil {
				return nil, err
			}
			skill = s
		}
	}
	if skill == nil {
		return nil, fmt.Errorf("skills: archive %q missing %s", archivePath, manifestFileName)
	}
	return skill, nil
}

// ReadManifest reads only the manifest from a .skill archive without extracting.
func ReadManifest(archivePath string) (*SkillManifest, error) {
	zr, err := zip.OpenReader(archivePath) //nolint:gosec // path is validated by caller
	if err != nil {
		return nil, fmt.Errorf("skills: open archive %q: %w", archivePath, err)
	}
	defer func() { _ = zr.Close() }()

	for _, f := range zr.File {
		if f.Name != manifestFileName {
			continue
		}
		rc, err := f.Open()
		if err != nil {
			return nil, fmt.Errorf("skills: open manifest entry: %w", err)
		}
		var m SkillManifest
		decodeErr := json.NewDecoder(rc).Decode(&m)
		if closeErr := rc.Close(); closeErr != nil && decodeErr == nil {
			decodeErr = fmt.Errorf("skills: close manifest reader: %w", closeErr)
		}
		if decodeErr != nil {
			return nil, fmt.Errorf("skills: decode manifest: %w", decodeErr)
		}
		return &m, nil
	}
	return nil, fmt.Errorf("skills: %s not found in %q", manifestFileName, archivePath)
}

// extractFile writes a single zip entry to targetDir, preserving relative path.
func extractFile(f *zip.File, targetDir string) error {
	dest := filepath.Join(targetDir, filepath.Clean(f.Name))
	if f.FileInfo().IsDir() {
		return os.MkdirAll(dest, 0o750)
	}
	if err := os.MkdirAll(filepath.Dir(dest), 0o750); err != nil {
		return fmt.Errorf("skills: mkdir for %q: %w", dest, err)
	}
	rc, err := f.Open()
	if err != nil {
		return fmt.Errorf("skills: open zip entry %q: %w", f.Name, err)
	}
	out, err := os.Create(dest) //nolint:gosec // dest is constructed via filepath.Join + Clean
	if err != nil {
		_ = rc.Close()
		return fmt.Errorf("skills: create %q: %w", dest, err)
	}
	_, copyErr := io.Copy(out, io.LimitReader(rc, maxDecompressBytes))
	if closeErr := out.Close(); closeErr != nil && copyErr == nil {
		copyErr = fmt.Errorf("skills: close output %q: %w", dest, closeErr)
	}
	if closeErr := rc.Close(); closeErr != nil && copyErr == nil {
		copyErr = fmt.Errorf("skills: close zip entry %q: %w", f.Name, closeErr)
	}
	if copyErr != nil {
		return fmt.Errorf("skills: write %q: %w", dest, copyErr)
	}
	return nil
}

// parseManifestFile reads and parses a manifest from an open zip.File.
func parseManifestFile(f *zip.File) (*Skill, error) {
	rc, err := f.Open()
	if err != nil {
		return nil, fmt.Errorf("skills: open manifest entry: %w", err)
	}
	var m SkillManifest
	decodeErr := json.NewDecoder(rc).Decode(&m)
	if closeErr := rc.Close(); closeErr != nil && decodeErr == nil {
		decodeErr = fmt.Errorf("skills: close manifest reader: %w", closeErr)
	}
	if decodeErr != nil {
		return nil, fmt.Errorf("skills: decode manifest: %w", decodeErr)
	}
	return &Skill{
		Name:         m.Name,
		Version:      m.Version,
		Description:  m.Description,
		Author:       m.Author,
		Dependencies: m.Dependencies,
		EntryPoint:   m.EntryPoint,
	}, nil
}
