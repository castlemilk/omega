//go:build !unix

package main

import (
	"crypto/ed25519"
	"database/sql"
	"errors"
	"os"

	"github.com/benebsworth/omega/internal/commerce"
)

func reporterKey(string, bool) (ed25519.PrivateKey, error) {
	return nil, errors.New("the reporter requires a Unix user with private file permissions")
}

func reporterConnection(string) (*commerce.StripeTest, *sql.DB, error) {
	return nil, nil, errors.New("the reporter requires a Unix user with private file permissions")
}

func openSettlementEvidenceDir(string) (*os.File, error) {
	return nil, errors.New("settlement evidence files require Unix private file permissions")
}

func saveSettlementStatement(*os.File, string, []byte) error {
	return errors.New("settlement evidence files require Unix private file permissions")
}

func openPrivateDataFile(string, int, os.FileMode) (*os.File, error) {
	return nil, errors.New("the local data file requires Unix private file permissions")
}
