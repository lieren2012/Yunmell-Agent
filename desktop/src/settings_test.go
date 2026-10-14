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

func TestDefaultSettingsUsePublicHTTPSControlPlane(t *testing.T) {
	if got := defaultSettings().ControlPlaneURL; got != "https://agent-oc.yun.cab" {
		t.Fatalf("default control plane URL = %q", got)
	}
}

func TestLoadSettingsMigratesLegacyDefaultButPreservesCustomAddress(t *testing.T) {
	temp := t.TempDir()
	t.Setenv("OCTOP_HOME", temp)
	if err := os.WriteFile(filepath.Join(temp, "desktop-settings.json"), []byte(`{"controlPlaneUrl":"https://6602-b3-agent.yun.cab"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	if got := loadSettings().ControlPlaneURL; got != "https://agent-oc.yun.cab" {
		t.Fatalf("migrated control plane URL = %q", got)
	}
	if err := os.WriteFile(filepath.Join(temp, "desktop-settings.json"), []byte(`{"controlPlaneUrl":"https://custom.example.com"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	if got := loadSettings().ControlPlaneURL; got != "https://custom.example.com" {
		t.Fatalf("custom control plane URL = %q", got)
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

func TestRetryReloadsSavedConnectionWithoutDroppingOtherSettings(t *testing.T) {
	t.Setenv("OCTOP_HOME", t.TempDir())
	store := &settingsStore{cur: Settings{ControlPlaneURL: "http://127.0.0.1:1"}}
	if err := os.WriteFile(settingsPath(), []byte(`{"controlPlaneUrl":"http://10.31.3.82:6602","port":16689,"locale":"zh","includePrerelease":true}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := store.reload(); err != nil {
		t.Fatal(err)
	}
	if store.get().ControlPlaneURL != "http://10.31.3.82:6602" || store.get().Port != 16689 || !store.get().IncludePrerelease {
		t.Fatal("saved connection/settings were not reloaded")
	}
	if err := os.WriteFile(settingsPath(), []byte(`not valid JSON`), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := store.reload(); err == nil {
		t.Fatal("invalid settings must not silently reset the connection")
	}
	if store.get().ControlPlaneURL != "http://10.31.3.82:6602" {
		t.Fatal("invalid settings replaced working configuration")
	}
}
