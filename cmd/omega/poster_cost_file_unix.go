//go:build unix

package main

import (
	"errors"
	"os"

	"golang.org/x/sys/unix"
)

func openPrivateDataFile(path string, flags int, mode os.FileMode) (*os.File, error) {
	file, err := os.OpenFile(path, flags|unix.O_NOFOLLOW|unix.O_NONBLOCK, mode)
	if err != nil {
		return nil, err
	}
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() || !privateReporterMode(info, 0600) {
		_ = file.Close()
		return nil, errors.New("the data file must be a regular, owner-only file with mode 0600")
	}
	return file, nil
}
