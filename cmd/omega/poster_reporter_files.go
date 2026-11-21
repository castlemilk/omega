//go:build unix

package main

import (
	"bytes"
	"crypto/ed25519"
	"crypto/rand"
	"database/sql"
	"errors"
	"io"
	"io/fs"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"syscall"

	"github.com/benebsworth/omega/internal/commerce"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/stdlib"
)

func reporterDirectory(path string, create bool) error {
	if create {
		if err := os.MkdirAll(path, 0700); err != nil {
			return errors.New("could not create the private reporter directory")
		}
	}
	info, err := os.Lstat(path)
	if err != nil || !info.IsDir() || !privateReporterMode(info, 0700) {
		return errors.New("the reporter directory must belong to the current user and have mode 0700")
	}
	return nil
}

func privateReporterMode(info fs.FileInfo, mode fs.FileMode) bool {
	stat, ok := info.Sys().(*syscall.Stat_t)
	return ok && int64(stat.Uid) == int64(os.Geteuid()) && info.Mode().Perm() == mode
}

func reporterPrivateFile(path string, limit int64) ([]byte, error) {
	f, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0) // #nosec G304 -- owner-selected source, validated on the open descriptor
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return nil, fs.ErrNotExist
		}
		return nil, errors.New("could not open the private reporter file")
	}
	defer func() { _ = f.Close() }()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() || !privateReporterMode(info, 0600) {
		return nil, errors.New("reporter files must be regular files owned by the current user with mode 0600")
	}
	data, err := io.ReadAll(io.LimitReader(f, limit+1))
	if err != nil || int64(len(data)) > limit {
		return nil, errors.New("invalid private reporter file")
	}
	return data, nil
}

func reporterKey(dir string, create bool) (ed25519.PrivateKey, error) {
	if err := reporterDirectory(dir, create); err != nil {
		return nil, err
	}
	path := filepath.Join(dir, "signing.seed")
	seed, err := reporterPrivateFile(path, ed25519.SeedSize)
	if create && errors.Is(err, fs.ErrNotExist) {
		if err := createReporterSeed(dir, path); err != nil {
			return nil, err
		}
		seed, err = reporterPrivateFile(path, ed25519.SeedSize)
	}
	if err != nil || len(seed) != ed25519.SeedSize {
		return nil, errors.New("the private signing seed is missing, unreadable or invalid")
	}
	return ed25519.NewKeyFromSeed(seed), nil
}

func createReporterSeed(dir, path string) error {
	_, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return errors.New("could not generate the reporter signing key")
	}
	temp, err := os.CreateTemp(dir, ".signing-*")
	if err != nil {
		return errors.New("could not create the private signing seed")
	}
	defer func() { _ = os.Remove(temp.Name()) }()
	_, writeErr := temp.Write(private.Seed())
	syncErr := temp.Sync()
	closeErr := temp.Close()
	if errors.Join(writeErr, syncErr, closeErr) != nil {
		return errors.New("could not save the private signing seed")
	}
	// Linking publishes a complete file without replacing an existing key,
	// even if a second init finishes first.
	if err := os.Link(temp.Name(), path); err != nil && !errors.Is(err, fs.ErrExist) {
		return errors.New("could not publish the private signing seed")
	}
	return nil
}

func reporterConnection(path string) (*commerce.StripeTest, *sql.DB, error) {
	data, err := reporterPrivateFile(path, 16*1024)
	if err != nil {
		return nil, nil, errors.New("could not read the owner's mode-0600 reporter credentials file")
	}
	values := make(map[string]string)
	for _, line := range strings.Split(strings.TrimSuffix(string(data), "\n"), "\n") {
		name, value, ok := strings.Cut(strings.TrimSuffix(line, "\r"), "=")
		if !ok || value == "" || values[name] != "" || (name != "OMEGA_POSTER_STRIPE_TEST_KEY" && name != "OMEGA_POSTER_COMMERCE_DATABASE_URL") {
			return nil, nil, errors.New("the reporter credentials file needs exactly the test key and local database URL")
		}
		values[name] = value
	}
	if len(values) != 2 || bytes.IndexByte(data, 0) >= 0 {
		return nil, nil, errors.New("the reporter credentials file needs exactly the test key and local database URL")
	}
	gateway, err := commerce.NewStripeTest(values["OMEGA_POSTER_STRIPE_TEST_KEY"])
	if err != nil {
		return nil, nil, errors.New("the reporter requires the isolated Stripe test credential")
	}
	dsn := values["OMEGA_POSTER_COMMERCE_DATABASE_URL"]
	target, err := url.Parse(dsn)
	if err != nil || (target.Scheme != "postgres" && target.Scheme != "postgresql") || !reporterLoopback(target.Hostname()) ||
		target.User.Username() == "" || strings.TrimPrefix(target.Path, "/") == "" {
		return nil, nil, errors.New("the reporter requires an explicit local PostgreSQL user and database")
	}
	cfg, err := pgx.ParseConfig(dsn)
	if err != nil || !reporterLoopback(cfg.Host) {
		return nil, nil, errors.New("could not read the local reporter database configuration")
	}
	for _, fallback := range cfg.Fallbacks {
		if !reporterLoopback(fallback.Host) {
			return nil, nil, errors.New("the reporter database must remain on loopback")
		}
	}
	cfg.RuntimeParams["default_transaction_read_only"] = "on"
	return gateway, stdlib.OpenDB(*cfg), nil
}

func reporterLoopback(host string) bool {
	return host == "localhost" || net.ParseIP(host).IsLoopback()
}
