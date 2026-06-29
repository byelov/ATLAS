package main

// Tool-call repetition detector. Catches the structural-loop case the
// PC-207 lens scoring doesn't see: model calls the SAME (tool, args)
// pair multiple times in close succession (e.g. read_file('app.py')
// 4 times in 6 turns, or run_command('curl localhost:5000/...') three
// times after the server already returned the same error each time).
//
// This is complementary to the lens-as-PRM intervention in agent.go:
// lens scores GENERATED CONTENT semantically; this detector scores
// CALL SHAPES structurally. Together they cover most stuck patterns:
//   - lens catches "model produced low-quality content" (stub writes)
//   - this catches "model emitted the same tool call again" (read loops)

import (
	"crypto/sha1"
	"encoding/hex"
	"encoding/json"
	"fmt"
)

const (
	// toolRepeatWindow is the number of recent tool calls to remember.
	// 8 is enough to span a typical recon → action → verify → recon
	// pattern (4-6 turns) plus margin for re-tries, while staying small
	// enough that a long-ago repeated call doesn't keep firing
	// interventions on a different topic.
	toolRepeatWindow = 8

	// toolRepeatThreshold is the number of times the same call signature
	// must appear in the window before we intervene. 3 is the minimum
	// that's clearly a pattern (1 = normal, 2 = retry); 4+ would miss
	// the kind of stub-loop case where the model only got 3 attempts in
	// before something else broke the chain.
	toolRepeatThreshold = 3
)

// recordToolCall pushes a (tool_name, args) signature into ctx's
// rolling window and returns the corrective message + true when the
// same signature has appeared toolRepeatThreshold times within the
// last toolRepeatWindow entries. Returns ("", false) otherwise.
//
// Caller is responsible for resetting ctx.RecentToolCalls after acting
// on the corrective so we don't re-fire on the same crash on the next
// iteration.
func recordToolCall(ctx *AgentContext, toolName string, args json.RawMessage) (string, bool) {
	sig := toolCallSignature(toolName, args)
	ctx.RecentToolCalls = append(ctx.RecentToolCalls, sig)
	if len(ctx.RecentToolCalls) > toolRepeatWindow {
		ctx.RecentToolCalls = ctx.RecentToolCalls[len(ctx.RecentToolCalls)-toolRepeatWindow:]
	}

	count := 0
	for _, s := range ctx.RecentToolCalls {
		if s == sig {
			count++
		}
	}
	if count < toolRepeatThreshold {
		return "", false
	}
	return fmt.Sprintf(
		"⚠ Tool-call repetition detected: you've called `%s` with these exact arguments %d times in the last %d turns. "+
			"The same call won't produce a different result. Try a different approach: (a) use different arguments to "+
			"discover what's actually there (different path, broader regex, list_directory before read_file), "+
			"(b) try a sibling tool — find_file if a path is unclear, run_command if a tool is failing in a confusing "+
			"way, (c) declare done if you've already gathered enough information, or (d) ask the user for clarification "+
			"if the task is ambiguous.",
		toolName, count, toolRepeatWindow), true
}

// toolCallSignature computes a stable hash of a (tool_name, args)
// tuple. Re-marshals args through encoding/json to canonicalize key
// order and whitespace — important because the model sometimes emits
// the same logical call with slightly different JSON formatting that
// would defeat naive string-equality detection.
func toolCallSignature(toolName string, args json.RawMessage) string {
	var v interface{}
	canonical := []byte(args)
	if err := json.Unmarshal(args, &v); err == nil {
		if b, err := json.Marshal(v); err == nil {
			canonical = b
		}
	}
	h := sha1.Sum([]byte(toolName + "|" + string(canonical)))
	return hex.EncodeToString(h[:])
}
