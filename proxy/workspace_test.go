package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestResolveWorkspacePathRejectsTraversalAndAbsolutePaths(t *testing.T) {
	root := t.TempDir()
	ctx := &AgentContext{WorkingDir: root}
	for _, input := range []string{"../outside.txt", "/etc/passwd"} {
		if _, err := resolveWorkspacePath(ctx, input); err == nil {
			t.Errorf("resolveWorkspacePath(%q) succeeded, want rejection", input)
		}
	}
}

func TestResolveWorkspacePathAllowsHostPathTranslation(t *testing.T) {
	root := t.TempDir()
	ctx := &AgentContext{WorkingDir: root, HostWorkingDir: "/Users/test/project"}
	got, err := resolveWorkspacePath(ctx, "/Users/test/project/src/main.go")
	if err != nil {
		t.Fatalf("resolveWorkspacePath: %v", err)
	}
	want := filepath.Join(root, "src", "main.go")
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

func TestResolveWorkspacePathRejectsSymlinkEscape(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(root, "escape")); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	ctx := &AgentContext{WorkingDir: root}
	if _, err := resolveWorkspacePath(ctx, "escape/file.txt"); err == nil {
		t.Fatal("symlink escape succeeded, want rejection")
	}
}

func TestExecuteToolCallRejectsWorkspaceEscape(t *testing.T) {
	root := t.TempDir()
	ctx := &AgentContext{WorkingDir: root}
	res := executeToolCall("read_file", json.RawMessage(`{"path":"../secret"}`), ctx)
	if res.Success || !strings.Contains(res.Error, "outside the workspace") {
		t.Fatalf("result = %+v, want workspace rejection", res)
	}
}
