//go:build unix

package main

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/sys/unix"
)

// Each component is opened relative to its already-open parent. Neither a
// supplied symlink nor a concurrent directory rename can redirect the writer.
func openSettlementEvidenceDir(path string) (*os.File, error) {
	absolute, err := filepath.Abs(path)
	if err != nil {
		return nil, fmt.Errorf("resolve settlement evidence directory: %w", err)
	}
	const flags = unix.O_RDONLY | unix.O_CLOEXEC | unix.O_DIRECTORY | unix.O_NOFOLLOW
	fd, err := unix.Open("/", flags, 0)
	if err != nil {
		return nil, fmt.Errorf("open settlement evidence path: %w", err)
	}
	for _, part := range strings.Split(strings.TrimPrefix(absolute, "/"), "/") {
		if part == "" {
			continue
		}
		next, openErr := unix.Openat(fd, part, flags, 0)
		if errors.Is(openErr, fs.ErrNotExist) {
			openErr = unix.Mkdirat(fd, part, 0700)
			if openErr == nil || errors.Is(openErr, fs.ErrExist) {
				next, openErr = unix.Openat(fd, part, flags, 0)
			}
		}
		_ = unix.Close(fd)
		if openErr != nil {
			return nil, fmt.Errorf("open settlement evidence directory %q without following symlinks: %w", absolute, openErr)
		}
		fd = next
	}
	dir := os.NewFile(uintptr(fd), absolute)
	info, err := dir.Stat()
	if err != nil || !info.IsDir() || !privateReporterMode(info, 0700) {
		_ = dir.Close()
		return nil, errors.New("the settlement evidence directory must be owned by the current user with mode 0700")
	}
	return dir, nil
}

// Link a complete private file into place without replacing an existing
// statement. Verify the published or pre-existing file through its descriptor.
func saveSettlementStatement(dir *os.File, digest string, body []byte) error {
	if fmt.Sprintf("%x", sha256.Sum256(body)) != digest {
		return errors.New("the settlement statement does not match its evidence digest")
	}
	fd := int(dir.Fd())
	temp := ".statement-" + rand.Text()
	const flags = unix.O_WRONLY | unix.O_CREAT | unix.O_EXCL | unix.O_CLOEXEC | unix.O_NOFOLLOW
	fileFD, err := unix.Openat(fd, temp, flags, 0600)
	if err != nil {
		return fmt.Errorf("create private settlement evidence: %w", err)
	}
	defer func() { _ = unix.Unlinkat(fd, temp, 0) }()
	file := os.NewFile(uintptr(fileFD), temp)
	_, writeErr := file.Write(body)
	if err := errors.Join(writeErr, file.Sync(), file.Close()); err != nil {
		return fmt.Errorf("save settlement statement bytes: %w", err)
	}
	name := digest + ".json"
	if err := unix.Linkat(fd, temp, fd, name, 0); err != nil && !errors.Is(err, fs.ErrExist) {
		return fmt.Errorf("publish settlement evidence %s: %w", name, err)
	}
	savedFD, err := unix.Openat(fd, name, unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW|unix.O_NONBLOCK, 0)
	if err != nil {
		return fmt.Errorf("open settlement evidence %s without following symlinks: %w", name, err)
	}
	saved := os.NewFile(uintptr(savedFD), name)
	defer func() { _ = saved.Close() }()
	info, err := saved.Stat()
	if err != nil || !info.Mode().IsRegular() || !privateReporterMode(info, 0600) {
		return fmt.Errorf("settlement evidence %s must be a regular file owned by the current user with mode 0600", name)
	}
	data, err := io.ReadAll(io.LimitReader(saved, int64(len(body))+1))
	if err != nil || !bytes.Equal(data, body) {
		return fmt.Errorf("the existing settlement evidence %s does not match the observed statement", name)
	}
	if err := dir.Sync(); err != nil {
		return fmt.Errorf("sync settlement evidence directory: %w", err)
	}
	return nil
}
