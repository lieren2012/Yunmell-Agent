package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type updateTransport func(*http.Request) (*http.Response, error)

func (f updateTransport) RoundTrip(request *http.Request) (*http.Response, error) { return f(request) }
func testUpdateAsset(body []byte) clientReleaseAsset {
	return testUpdateAssetForVersion(body, "1.0.11")
}
func testUpdateAssetForVersion(body []byte, version string) clientReleaseAsset {
	digest := sha256.Sum256(body)
	name := "Yunmell-Agent-desktop-windows-amd64-" + version + ".exe"
	return clientReleaseAsset{Name: name, Size: int64(len(body)), Digest: "sha256:" + hex.EncodeToString(digest[:]), URL: "https://github.com/" + defaultUpdateRepository + "/releases/download/v" + version + "/" + name}
}
func testUpdater(t *testing.T, releases []clientRelease, body []byte) *clientUpdater {
	t.Helper()
	u := newClientUpdater("", "windows-amd64", t.TempDir(), nil)
	u.client.Transport = updateTransport(func(r *http.Request) (*http.Response, error) {
		data := body
		if r.URL.Host == "api.github.com" {
			data, _ = json.Marshal(releases)
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(string(data))), Header: make(http.Header), Request: r}, nil
	})
	return u
}
func TestClientUpdateSelectsOnlyConfiguredPlatformAndStableRelease(t *testing.T) {
	body := []byte("verified Yunmell installer")
	asset := testUpdateAsset(body)
	u := testUpdater(t, []clientRelease{{Tag: "v9.0.0", Draft: true}, {Tag: "v2.0.0b1", Prerelease: true}, {Tag: "v1.0.11", Assets: []clientReleaseAsset{asset}}}, body)
	if err := u.check(false); err != nil {
		t.Fatal(err)
	}
	if u.snapshot().LatestVersion != "1.0.11" {
		t.Fatal(u.snapshot())
	}
	if err := u.download(); err != nil {
		t.Fatal(err)
	}
	if u.snapshot().Stage != "ready" {
		t.Fatal(u.snapshot())
	}
	if err := verifyUpdateFile(u.path, asset); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(u.path, []byte("changed after verification"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := verifyUpdateFile(u.path, asset); err == nil {
		t.Fatal("installer changed after download must be rejected")
	}
}
func TestClientUpdateRejectsForeignReleaseAndMissingChecksum(t *testing.T) {
	for _, tamper := range []func(*clientReleaseAsset){func(a *clientReleaseAsset) { a.URL = "https://example.com/installer.exe" }, func(a *clientReleaseAsset) { a.Digest = "" }, func(a *clientReleaseAsset) { a.Name = "Octop-desktop-windows-amd64-1.0.11.exe" }} {
		a := testUpdateAsset([]byte("package"))
		tamper(&a)
		u := testUpdater(t, []clientRelease{{Tag: "v1.0.11", Assets: []clientReleaseAsset{a}}}, nil)
		if err := u.check(false); err == nil {
			t.Fatal("untrusted/unsigned release must be rejected")
		}
	}
}
func TestClientUpdateCorruptOrInterruptedDownloadPreservesLocalData(t *testing.T) {
	asset := testUpdateAsset([]byte("expected installer"))
	u := testUpdater(t, []clientRelease{{Tag: "v1.0.11", Assets: []clientReleaseAsset{asset}}}, []byte("bad"))
	old := filepath.Join(u.directory, "local-session.json")
	if err := os.WriteFile(old, []byte("local session"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := u.check(false); err != nil {
		t.Fatal(err)
	}
	if err := u.download(); err == nil {
		t.Fatal("corrupt/truncated download must fail")
	}
	if data, _ := os.ReadFile(old); string(data) != "local session" {
		t.Fatal("local data was changed")
	}
	if u.path != "" {
		t.Fatal("failed download must never produce a prepared installer")
	}
	u.client.Transport = updateTransport(func(*http.Request) (*http.Response, error) { return nil, errors.New("offline") })
	if err := u.check(false); err == nil {
		t.Fatal("offline source must report failure")
	}
}
func TestClientUpdateRequiresInstallConfirmation(t *testing.T) {
	a := &App{}
	if err := a.InstallClientUpdate(false); err == nil {
		t.Fatal("installation needs explicit confirmation")
	}
}
func TestClientUpdateFailedInstallerRestoresOldExecutable(t *testing.T) {
	dir := t.TempDir()
	exe := filepath.Join(dir, "Yunmell-Agent.exe")
	installer := filepath.Join(dir, "installer.exe")
	body := []byte("trusted installer")
	if err := os.WriteFile(exe, []byte("old executable"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(installer, body, 0o600); err != nil {
		t.Fatal(err)
	}
	plan := clientInstallPlan{Executable: exe, Installer: installer, Asset: testUpdateAsset(body), Result: filepath.Join(dir, "result.json")}
	previousWait, previousApply := waitClientExit, applyClientPackage
	t.Cleanup(func() { waitClientExit = previousWait; applyClientPackage = previousApply })
	waitClientExit = func(int, time.Duration) error { return nil }
	applyClientPackage = func(plan clientInstallPlan) error {
		_ = os.WriteFile(plan.Executable, []byte("partial install"), 0o700)
		return errors.New("installer failed")
	}
	if err := applyClientInstall(plan); err == nil {
		t.Fatal("installation must report failure")
	}
	if data, _ := os.ReadFile(exe); string(data) != "old executable" {
		t.Fatal("failed install did not restore old executable")
	}
}
func TestClientUpdaterRejectsDowngrades(t *testing.T) {
	u := testUpdater(t, []clientRelease{{Tag: "v1.0.9"}, {Tag: "v1.0.10b10", Prerelease: true}}, nil)
	if err := u.check(false); err != nil {
		t.Fatal(err)
	}
	if u.snapshot().HasUpdate {
		t.Fatal("older client must not be selected")
	}
	if err := u.download(); err == nil {
		t.Fatal("older release must not be downloaded for installation")
	}
}

func TestClientUpdaterKeepsCurrentPrereleaseTrackWhenStableOnly(t *testing.T) {
	// The installed client is 1.0.10b14. A stable-only check must not report the
	// older 1.0.9 tag as latest, and must still offer a real b15 upgrade.
	u := testUpdater(t, []clientRelease{
		{Tag: "v1.0.9"},
		{Tag: "v1.0.10b14", Prerelease: true},
	}, nil)
	if err := u.check(false); err != nil {
		t.Fatal(err)
	}
	if got := u.snapshot(); got.LatestVersion != "1.0.10b14" || got.HasUpdate {
		t.Fatalf("current pre-release was treated as a downgrade: %+v", got)
	}

	body := []byte("next Yunmell installer")
	asset := testUpdateAssetForVersion(body, "1.0.10b15")
	u = testUpdater(t, []clientRelease{
		{Tag: "v1.0.9"},
		{Tag: "v1.0.10b14", Prerelease: true},
		{Tag: "v1.0.10b15", Prerelease: true, Assets: []clientReleaseAsset{asset}},
	}, body)
	if err := u.check(false); err != nil {
		t.Fatal(err)
	}
	if got := u.snapshot(); got.LatestVersion != "1.0.10b15" || !got.HasUpdate {
		t.Fatalf("newer pre-release was not selected: %+v", got)
	}
}

func TestParallelInstallerDownloadChecksRangesAndHash(t *testing.T) {
	body := bytes.Repeat([]byte("yunmell"), (9<<20)/7)
	asset := testUpdateAsset(body)
	u := testUpdater(t, []clientRelease{{Tag: "v1.0.11", Assets: []clientReleaseAsset{asset}}}, nil)
	u.client.Transport = updateTransport(func(request *http.Request) (*http.Response, error) {
		if request.URL.Host == "api.github.com" {
			data, _ := json.Marshal([]clientRelease{{Tag: "v1.0.11", Assets: []clientReleaseAsset{asset}}})
			return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(data)), Header: make(http.Header)}, nil
		}
		var start, end int
		if _, err := fmt.Sscanf(request.Header.Get("Range"), "bytes=%d-%d", &start, &end); err != nil {
			return nil, err
		}
		return &http.Response{StatusCode: 206, Body: io.NopCloser(bytes.NewReader(body[start : end+1])), Header: http.Header{"Content-Range": {fmt.Sprintf("bytes %d-%d/%d", start, end, len(body))}}}, nil
	})
	if err := u.check(false); err != nil {
		t.Fatal(err)
	}
	if err := u.download(); err != nil {
		t.Fatal(err)
	}
	if err := verifyUpdateFile(u.path, asset); err != nil {
		t.Fatal(err)
	}
	if u.snapshot().Downloaded != asset.Size {
		t.Fatal("progress must cover the complete installer")
	}
}
