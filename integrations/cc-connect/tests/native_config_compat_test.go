package config

import (
	"bytes"
	"os"
	"testing"
)

func TestAIADNativeConfigCompatibility(t *testing.T) {
	legacyPath := os.Getenv("AIAD_NATIVE_CONFIG_FIXTURE_LEGACY")
	currentPath := os.Getenv("AIAD_NATIVE_CONFIG_FIXTURE_CURRENT")
	if legacyPath == "" || currentPath == "" {
		t.Fatal("AIAD native configuration fixture paths are required")
	}
	legacyBytes, err := os.ReadFile(legacyPath)
	if err != nil {
		t.Fatalf("read legacy fixture: %v", err)
	}
	currentBytes, err := os.ReadFile(currentPath)
	if err != nil {
		t.Fatalf("read current fixture: %v", err)
	}
	if !bytes.Equal(legacyBytes, currentBytes) {
		t.Fatal("legacy and current renderer TOML bytes differ")
	}

	t.Setenv("AIAD_CC_CONNECT_MANAGEMENT_TOKEN", "synthetic-management-token")
	t.Setenv("AIAD_TELEGRAM_CLAUDE_BOT_TOKEN", "synthetic-claude-token")
	t.Setenv("AIAD_TELEGRAM_CODEX_BOT_TOKEN", "synthetic-codex-token")
	for _, fixture := range []struct {
		name string
		path string
	}{
		{name: "legacy-v1", path: legacyPath},
		{name: "current-v2", path: currentPath},
	} {
		t.Run(fixture.name, func(t *testing.T) {
			cfg, err := Load(fixture.path)
			if err != nil {
				t.Fatalf("Load: %v", err)
			}
			if cfg.Management.Enabled == nil || !*cfg.Management.Enabled {
				t.Fatal("management API was not enabled")
			}
			if cfg.Management.Port != 59020 || cfg.Management.Token != "synthetic-management-token" {
				t.Fatalf("management config = %#v", cfg.Management)
			}
			if len(cfg.Projects) != 2 {
				t.Fatalf("project count = %d, want 2", len(cfg.Projects))
			}
			wantTypes := []string{"claudecode", "codex"}
			wantTokens := []string{"synthetic-claude-token", "synthetic-codex-token"}
			for index, project := range cfg.Projects {
				if project.Agent.Type != wantTypes[index] {
					t.Fatalf("project %d agent type = %q", index, project.Agent.Type)
				}
				if project.AdminFrom != "123456789" || len(project.Platforms) != 1 {
					t.Fatalf("project %d governance config = %#v", index, project)
				}
				if got := project.Platforms[0].Options["token"]; got != wantTokens[index] {
					t.Fatalf("project %d token = %#v", index, got)
				}
				if got := project.Platforms[0].Options["allow_from"]; got != "123456789" {
					t.Fatalf("project %d allow_from = %#v", index, got)
				}
			}
		})
	}
}
