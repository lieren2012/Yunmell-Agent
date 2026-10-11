package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadSettingsMigratesLegacyPreventSleepMac(t *testing.T) {
	temp := t.TempDir()
	t.Setenv("OCTOP_HOME", temp)
	if err := os.WriteFile(
		filepath.Join(temp, "desktop-settings.json"),
		[]byte(`{"preventSleepMac":true}`),
		0o644,
	); err != nil {
		t.Fatal(err)
	}

	if !loadSettings().PreventSleep {
		t.Fatal("legacy preventSleepMac should migrate to preventSleep")
	}
}

func TestNormalizeControlPlaneURL(t *testing.T) {
	got, err := normalizeControlPlaneURL("  https://control.example.com///  ")
	if err != nil {
		t.Fatal(err)
	}
	if got != "https://control.example.com" {
		t.Fatalf("normalized control plane URL = %q", got)
	}
}

func TestNormalizeControlPlaneURLRejectsNonHTTP(t *testing.T) {
	if _, err := normalizeControlPlaneURL("file:///tmp/control"); err == nil {
		t.Fatal("expected non-http control plane URL to be rejected")
	}
}

func TestSettingsSavePersistsControlPlaneURL(t *testing.T) {
	temp := t.TempDir()
	t.Setenv("OCTOP_HOME", temp)
	store := &settingsStore{cur: defaultSettings()}
	err := store.save(Settings{Locale: LocaleZH, ControlPlaneURL: "https://control.example.com/"})
	if err != nil {
		t.Fatal(err)
	}
	if store.get().ControlPlaneURL != "https://control.example.com" {
		t.Fatalf("saved control plane URL = %q", store.get().ControlPlaneURL)
	}
	loaded := loadSettings()
	if loaded.ControlPlaneURL != "https://control.example.com" {
		t.Fatalf("loaded control plane URL = %q", loaded.ControlPlaneURL)
	}
}
