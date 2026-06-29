package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestFormatDemoModelLabel(t *testing.T) {
	tests := map[string]string{
		"orion-code-10b-it-Q4_K_M":                "Orion code 10B",
		"nova-7B-Q6_K":                            "Nova 7B",
		"/models/atlas-test-3.1-8B-Instruct.gguf": "Atlas test 3.1 8B",
		"": demoModelFallback,
	}
	for input, want := range tests {
		t.Run(input, func(t *testing.T) {
			if got := formatDemoModelLabel(input); got != want {
				t.Fatalf("formatDemoModelLabel(%q) = %q, want %q", input, got, want)
			}
		})
	}
}

func TestFetchDemoModelLabel(t *testing.T) {
	tests := []struct {
		name   string
		status int
		body   string
		want   string
	}{
		{"configured model", http.StatusOK, `{"object":"list","data":[{"id":"orion-code-10b-it-Q4_K_M"}]}`, "Orion code 10B"},
		{"empty list", http.StatusOK, `{"object":"list","data":[]}`, demoModelFallback},
		{"missing id", http.StatusOK, `{"object":"list","data":[{"id":""}]}`, demoModelFallback},
		{"malformed", http.StatusOK, `{`, demoModelFallback},
		{"upstream failure", http.StatusServiceUnavailable, `unavailable`, demoModelFallback},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/v1/models" {
					t.Errorf("path = %q, want /v1/models", r.URL.Path)
				}
				w.WriteHeader(tc.status)
				_, _ = w.Write([]byte(tc.body))
			}))
			defer srv.Close()
			if got := fetchDemoModelLabel(srv.URL); got != tc.want {
				t.Fatalf("label = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestDemoTitlesDescribeActualComparison(t *testing.T) {
	m := &demoModel{modelLabel: "Orion code 10B"}
	left := m.baselineTitle()
	right := m.atlasTitle()
	for _, title := range []string{left, right} {
		if !strings.Contains(title, "Orion code 10B") {
			t.Fatalf("title %q does not identify configured model", title)
		}
		if strings.Contains(title, "RAW 9B") || strings.Contains(title, "no V3 orchestration") {
			t.Fatalf("title retains misleading legacy wording: %q", title)
		}
	}
	if !strings.Contains(left, "BASE AGENT") || !strings.Contains(left, "V3 OFF") {
		t.Fatalf("baseline title is not explicit about comparison: %q", left)
	}
	if !strings.Contains(right, "ATLAS V3") {
		t.Fatalf("V3 title is not explicit: %q", right)
	}
}

func TestDemoTitleFallsBackWithoutMetadata(t *testing.T) {
	m := &demoModel{}
	if got := m.baselineTitle(); !strings.HasPrefix(got, demoModelFallback) {
		t.Fatalf("baseline title = %q, want neutral fallback", got)
	}
}

func TestDemoLiveAndOutputViewsUseResolvedTitles(t *testing.T) {
	rawChild := newTUIModel("http://unused")
	v3Child := newTUIModel("http://unused")
	m := &demoModel{
		modelLabel:  "Orion code 10B",
		prompt:      demoPrompt{Prompt: "build it"},
		promptShown: len("build it"),
		width:       180,
		height:      36,
		rawChild:    &rawChild,
		v3Child:     &v3Child,
		rawSandbox:  ".demo-base-test",
		v3Sandbox:   ".demo-v3-test",
		activePane:  "v3",
	}

	assertTitles := func(name, view string) {
		t.Helper()
		for _, want := range []string{"Orion code 10B", "BASE AGENT", "V3 OFF", "ATLAS V3"} {
			if !strings.Contains(view, want) {
				t.Fatalf("%s view missing %q", name, want)
			}
		}
		for _, stale := range []string{"RAW 9B", "no V3 orchestration"} {
			if strings.Contains(view, stale) {
				t.Fatalf("%s view contains stale label %q", name, stale)
			}
		}
	}

	assertTitles("live", m.View())
	m.outputMode = true
	assertTitles("output", m.View())
}
