package main

import (
	"database/sql"

	"github.com/benebsworth/omega/internal/db"
)

// openVictoriaDB opens a lightweight, read-only-style sql.DB connection to
// Postgres and returns a VictoriaDB reader backed by it.
// The caller is responsible for closing the returned *sql.DB.
func openVictoriaDB() (*sql.DB, *db.VictoriaDB, error) {
	sqlDB, err := sql.Open("pgx", db.DatabaseURL())
	if err != nil {
		return nil, nil, err
	}
	if err := sqlDB.Ping(); err != nil {
		sqlDB.Close() //nolint:errcheck,gosec
		return nil, nil, err
	}
	return sqlDB, db.NewVictoria(sqlDB), nil
}
