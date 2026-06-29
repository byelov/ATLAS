package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// resolveWorkspacePath translates an approved host path and verifies that the
// result stays inside the configured workspace. It checks both the lexical path
// and the nearest existing ancestor so symlinks cannot escape the workspace.
func resolveWorkspacePath(ctx *AgentContext, path string) (string, error) {
	resolved := resolveAgentPath(ctx, path)
	root, err := filepath.Abs(ctx.WorkingDir)
	if err != nil {
		return "", fmt.Errorf("resolve workspace root: %w", err)
	}
	candidate, err := filepath.Abs(resolved)
	if err != nil {
		return "", fmt.Errorf("resolve path: %w", err)
	}
	if !pathWithin(root, candidate) {
		return "", fmt.Errorf("path %q is outside the workspace", path)
	}

	realRoot, err := filepath.EvalSymlinks(root)
	if err != nil {
		return "", fmt.Errorf("resolve workspace root symlinks: %w", err)
	}
	existing := candidate
	for {
		if _, statErr := os.Lstat(existing); statErr == nil {
			break
		} else if !os.IsNotExist(statErr) {
			return "", fmt.Errorf("inspect path %q: %w", path, statErr)
		}
		parent := filepath.Dir(existing)
		if parent == existing {
			return "", fmt.Errorf("path %q has no existing workspace ancestor", path)
		}
		existing = parent
	}
	realExisting, err := filepath.EvalSymlinks(existing)
	if err != nil {
		return "", fmt.Errorf("resolve path symlinks: %w", err)
	}
	if !pathWithin(realRoot, realExisting) {
		return "", fmt.Errorf("path %q escapes the workspace through a symlink", path)
	}
	return candidate, nil
}

func pathWithin(root, candidate string) bool {
	rel, err := filepath.Rel(filepath.Clean(root), filepath.Clean(candidate))
	return err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}

// validateToolWorkspacePaths applies workspace containment before any tool
// handler can touch the filesystem. It is used by both the agent loop and the
// shared dispatcher so parallel and direct dispatch paths follow one policy.
func validateToolWorkspacePaths(name string, args json.RawMessage, ctx *AgentContext) string {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(args, &fields); err != nil {
		return ""
	}
	keys := map[string][]string{
		"read_file":      {"path"},
		"outline_file":   {"path"},
		"write_file":     {"path"},
		"edit_file":      {"path"},
		"ast_edit":       {"path"},
		"delete_file":    {"path"},
		"move_file":      {"source", "destination"},
		"search_files":   {"path"},
		"find_file":      {"path"},
		"list_directory": {"path"},
		"run_command":    {"cwd"},
		"run_background": {"cwd"},
	}
	for _, key := range keys[name] {
		raw, ok := fields[key]
		if !ok {
			continue
		}
		var value string
		if json.Unmarshal(raw, &value) != nil || strings.TrimSpace(value) == "" {
			continue
		}
		if _, err := resolveWorkspacePath(ctx, value); err != nil {
			return fmt.Sprintf("%s: %v", name, err)
		}
	}
	return ""
}
