package main

import (
	"os"
	"path/filepath"
	"testing"
)

// TestMain points the user cache dir at a throwaway directory for the whole
// package. os.UserCacheDir honors $XDG_CACHE_HOME only on Linux; on macOS it
// is $HOME/Library/Caches, so without overriding HOME the chat and session
// tests write into the real ~/Library/Caches/atlas-tui/sessions.
func TestMain(m *testing.M) {
	home, err := os.MkdirTemp("", "atlas-tui-test-home-")
	if err != nil {
		panic(err)
	}
	os.Setenv("HOME", home)
	os.Setenv("XDG_CACHE_HOME", filepath.Join(home, ".cache"))
	code := m.Run()
	os.RemoveAll(home)
	os.Exit(code)
}
