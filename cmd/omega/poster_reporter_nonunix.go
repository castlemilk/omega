//go:build !unix

package main

import (
	"crypto/ed25519"
	"database/sql"
	"errors"

	"github.com/benebsworth/omega/internal/commerce"
)

func reporterKey(string, bool) (ed25519.PrivateKey, error) {
	return nil, errors.New("the reporter requires a Unix user with private file permissions")
}

func reporterConnection(string) (*commerce.StripeTest, *sql.DB, error) {
	return nil, nil, errors.New("the reporter requires a Unix user with private file permissions")
}
