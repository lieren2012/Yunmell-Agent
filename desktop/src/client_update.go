package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
)

// This is the shell version, independent of the Python runtime and upstream baseline.
const clientVersion = "1.0.10b8"
const defaultUpdateRepository = "lieren2012/Yunmell-Agent"

type ClientUpdateStatus struct {
	CurrentVersion string `json:"currentVersion"`
	LatestVersion  string `json:"latestVersion"`
	ReleaseNotes   string `json:"releaseNotes"`
	Source         string `json:"source"`
	HasUpdate      bool   `json:"hasUpdate"`
	Prerelease     bool   `json:"prerelease"`
	Stage          string `json:"stage"`
	Downloaded     int64  `json:"downloaded"`
	Total          int64  `json:"total"`
	Error          string `json:"error"`
	LastInstall    string `json:"lastInstall"`
}

type clientReleaseAsset struct {
	Name   string `json:"name"`
	URL    string `json:"browser_download_url"`
	Digest string `json:"digest"`
	Size   int64  `json:"size"`
}
type clientRelease struct {
	Tag        string               `json:"tag_name"`
	Notes      string               `json:"body"`
	Draft      bool                 `json:"draft"`
	Prerelease bool                 `json:"prerelease"`
	Assets     []clientReleaseAsset `json:"assets"`
}
type clientUpdater struct {
	mu         sync.Mutex
	state      ClientUpdateStatus
	asset      clientReleaseAsset
	path       string
	repository string
	platform   string
	directory  string
	client     *http.Client
	emit       func(ClientUpdateStatus)
}

var repositoryPattern = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)

func newClientUpdater(repository, platform, directory string, emit func(ClientUpdateStatus)) *clientUpdater {
	if repository == "" {
		repository = defaultUpdateRepository
	}
	u := &clientUpdater{repository: repository, platform: platform, directory: directory, emit: emit,
		state: ClientUpdateStatus{CurrentVersion: clientVersion, Stage: "idle", Source: "https://github.com/" + repository + "/releases"}}
	u.client = &http.Client{Timeout: 30 * time.Minute, CheckRedirect: func(req *http.Request, via []*http.Request) error {
		if len(via) >= 5 {
			return fmt.Errorf("too many download redirects")
		}
		return trustedUpdateURL(req.URL)
	}}
	if data, err := os.ReadFile(filepath.Join(directory, "last-install.json")); err == nil {
		var result clientInstallResult
		if json.Unmarshal(data, &result) == nil {
			if result.Success {
				u.state.LastInstall = "上次安装完成：" + result.Version
			} else {
				u.state.LastInstall = result.Error
			}
		}
	}
	return u
}

func trustedUpdateURL(parsed *url.URL) error {
	if parsed.Scheme != "https" || parsed.User != nil || parsed.Port() != "" {
		return fmt.Errorf("update source must use HTTPS without embedded credentials")
	}
	switch parsed.Hostname() {
	case "api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com":
		return nil
	default:
		return fmt.Errorf("untrusted update download host")
	}
}

func (u *clientUpdater) snapshot() ClientUpdateStatus {
	u.mu.Lock()
	defer u.mu.Unlock()
	return u.state
}
func (u *clientUpdater) publish(change func(*ClientUpdateStatus)) {
	u.mu.Lock()
	change(&u.state)
	state := u.state
	u.mu.Unlock()
	if u.emit != nil {
		u.emit(state)
	}
}
func (u *clientUpdater) fail(err error) {
	u.publish(func(s *ClientUpdateStatus) { s.Stage = "error"; s.Error = err.Error() })
}

func (u *clientUpdater) begin(stage string) error {
	u.mu.Lock()
	switch u.state.Stage {
	case "checking", "downloading", "installing":
		u.mu.Unlock()
		return fmt.Errorf("a client update operation is already running")
	}
	u.state.Stage = stage
	u.state.Error = ""
	state := u.state
	u.mu.Unlock()
	if u.emit != nil {
		u.emit(state)
	}
	return nil
}

func (u *clientUpdater) get(raw string) (*http.Response, error) {
	return u.getRange(context.Background(), raw, "")
}

func (u *clientUpdater) getRange(ctx context.Context, raw, rangeHeader string) (*http.Response, error) {
	parsed, err := url.Parse(raw)
	if err != nil {
		return nil, err
	}
	if err = trustedUpdateURL(parsed); err != nil {
		return nil, err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, raw, nil)
	if err != nil {
		return nil, err
	}
	request.Header.Set("User-Agent", "Yunmell-Agent/"+clientVersion)
	if rangeHeader != "" {
		request.Header.Set("Range", rangeHeader)
	}
	client := u.client
	if parsed.Hostname() == "api.github.com" || strings.HasSuffix(parsed.Path, ".sha256") {
		copy := *client
		copy.Timeout = 20 * time.Second
		client = &copy
	}
	resp, err := client.Do(request)
	if err != nil {
		return nil, fmt.Errorf("cannot reach the client update source: %w", err)
	}
	if (rangeHeader == "" && resp.StatusCode != http.StatusOK) || (rangeHeader != "" && resp.StatusCode != http.StatusPartialContent) {
		resp.Body.Close()
		return nil, fmt.Errorf("client update source returned HTTP %d", resp.StatusCode)
	}
	return resp, nil
}

func (u *clientUpdater) check(includePrerelease bool) error {
	if err := u.begin("checking"); err != nil {
		return err
	}
	err := u.checkRelease(includePrerelease)
	if err != nil {
		u.fail(err)
	}
	return err
}
func (u *clientUpdater) checkRelease(includePrerelease bool) error {
	if !repositoryPattern.MatchString(u.repository) {
		return fmt.Errorf("invalid GitHub update repository")
	}
	resp, err := u.get("https://api.github.com/repos/" + u.repository + "/releases?per_page=100")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	var releases []clientRelease
	if err = json.NewDecoder(io.LimitReader(resp.Body, 4<<20)).Decode(&releases); err != nil {
		return fmt.Errorf("invalid client release metadata")
	}
	var chosen *clientRelease
	for i := range releases {
		r := &releases[i]
		version := strings.TrimPrefix(r.Tag, "v")
		if r.Draft || !pep440RE.MatchString(version) {
			continue
		}
		pre := r.Prerelease || clientVersionIsPrerelease(version)
		if !includePrerelease && pre {
			continue
		}
		if chosen == nil || compareVersions(r.Tag, chosen.Tag) > 0 {
			chosen = r
		}
	}
	if chosen == nil {
		return fmt.Errorf("no published client release in the selected channel")
	}
	version := strings.TrimPrefix(chosen.Tag, "v")
	hasUpdate := compareVersions(version, clientVersion) > 0
	asset := clientReleaseAsset{}
	if hasUpdate {
		ext := ".exe"
		if strings.HasPrefix(u.platform, "darwin-") {
			ext = ".dmg"
		}
		if strings.HasPrefix(u.platform, "linux-") {
			ext = ".tar.gz"
		}
		name := "Yunmell-Agent-desktop-" + u.platform + "-" + version + ext
		for _, candidate := range chosen.Assets {
			if candidate.Name == name {
				asset = candidate
				break
			}
		}
		if asset.Name == "" {
			return fmt.Errorf("this release has no client installer for %s", u.platform)
		}
		if asset.Size <= 0 || asset.Size > 1<<30 {
			return fmt.Errorf("invalid installer size")
		}
		expected := "https://github.com/" + u.repository + "/releases/download/" + chosen.Tag + "/" + name
		if asset.URL != expected {
			return fmt.Errorf("installer does not belong to the configured Yunmell release")
		}
		if _, err := parseSHA256(asset.Digest); err != nil {
			checksumURL := expected + ".sha256"
			found := false
			for _, item := range chosen.Assets {
				if item.Name == name+".sha256" && item.URL == checksumURL {
					found = true
				}
			}
			if !found {
				return fmt.Errorf("release is missing a trusted SHA-256 checksum")
			}
			checksum, err := u.get(checksumURL)
			if err != nil {
				return err
			}
			body, readErr := io.ReadAll(io.LimitReader(checksum.Body, 512))
			checksum.Body.Close()
			if readErr != nil {
				return readErr
			}
			fields := strings.Fields(string(body))
			if len(fields) != 2 || fields[1] != name {
				return fmt.Errorf("invalid installer checksum file")
			}
			asset.Digest = "sha256:" + fields[0]
			if _, err = parseSHA256(asset.Digest); err != nil {
				return err
			}
		}
	}
	u.mu.Lock()
	u.asset = asset
	u.path = ""
	u.mu.Unlock()
	u.publish(func(s *ClientUpdateStatus) {
		s.LatestVersion = version
		s.ReleaseNotes = chosen.Notes
		s.Prerelease = chosen.Prerelease || clientVersionIsPrerelease(version)
		s.HasUpdate = hasUpdate
		s.Stage = "checked"
		s.Downloaded = 0
		s.Total = asset.Size
	})
	return nil
}

func clientVersionIsPrerelease(version string) bool {
	key := parseVersion(version)
	return key.pre[0] < 1 || key.dev[0] < 1
}

func parseSHA256(digest string) (string, error) {
	if !strings.HasPrefix(digest, "sha256:") {
		return "", fmt.Errorf("release is missing SHA-256 integrity metadata")
	}
	hash := strings.ToLower(strings.TrimPrefix(digest, "sha256:"))
	decoded, err := hex.DecodeString(hash)
	if err != nil || len(decoded) != sha256.Size {
		return "", fmt.Errorf("invalid SHA-256 integrity metadata")
	}
	return hash, nil
}
func verifyUpdateFile(path string, asset clientReleaseAsset) error {
	expected, err := parseSHA256(asset.Digest)
	if err != nil {
		return err
	}
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	h := sha256.New()
	count, err := io.Copy(h, f)
	if err != nil {
		return err
	}
	if count != asset.Size || hex.EncodeToString(h.Sum(nil)) != expected {
		return fmt.Errorf("installer integrity check failed; the installed client was not changed")
	}
	return nil
}

func (u *clientUpdater) download() error {
	u.mu.Lock()
	if !u.state.HasUpdate || u.asset.Name == "" {
		u.mu.Unlock()
		return fmt.Errorf("check for a newer client release first")
	}
	u.mu.Unlock()
	if err := u.begin("downloading"); err != nil {
		return err
	}
	err := u.downloadAsset()
	if err != nil {
		u.fail(err)
	}
	return err
}
func (u *clientUpdater) downloadAsset() error {
	u.mu.Lock()
	asset := u.asset
	u.mu.Unlock()
	if err := os.MkdirAll(u.directory, 0o700); err != nil {
		return err
	}
	f, err := os.CreateTemp(u.directory, "installer-*.part")
	if err != nil {
		return err
	}
	part := f.Name()
	defer os.Remove(part)
	if asset.Size >= 8<<20 {
		if err := u.downloadRanges(f, asset); err != nil {
			f.Close()
			return err
		}
		if err := f.Close(); err != nil {
			return err
		}
		if err := verifyUpdateFile(part, asset); err != nil {
			return err
		}
		return u.finishDownload(part, asset)
	}
	resp, err := u.get(asset.URL)
	if err != nil {
		f.Close()
		return err
	}
	defer resp.Body.Close()
	h := sha256.New()
	writer := io.MultiWriter(f, h)
	buf := make([]byte, 128*1024)
	var total int64
	last := time.Time{}
	for {
		n, readErr := resp.Body.Read(buf)
		if n > 0 {
			total += int64(n)
			if total > asset.Size {
				f.Close()
				return fmt.Errorf("installer exceeds declared size")
			}
			if _, err = writer.Write(buf[:n]); err != nil {
				f.Close()
				return err
			}
		}
		if time.Since(last) > 250*time.Millisecond {
			u.publish(func(s *ClientUpdateStatus) { s.Downloaded = total })
			last = time.Now()
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			f.Close()
			return fmt.Errorf("installer download interrupted: %w", readErr)
		}
	}
	if err = f.Close(); err != nil {
		return err
	}
	expected, err := parseSHA256(asset.Digest)
	if err != nil {
		return err
	}
	if total != asset.Size || hex.EncodeToString(h.Sum(nil)) != expected {
		return fmt.Errorf("installer integrity check failed; the installed client was not changed")
	}
	return u.finishDownload(part, asset)
}

func (u *clientUpdater) finishDownload(part string, asset clientReleaseAsset) error {
	final := filepath.Join(u.directory, asset.Name)
	// Re-downloads replace only a previous verified installer, never the running app.
	if err := os.Remove(final); err != nil && !os.IsNotExist(err) {
		return err
	}
	if err := os.Rename(part, final); err != nil {
		return err
	}
	u.mu.Lock()
	u.path = final
	u.mu.Unlock()
	u.publish(func(s *ClientUpdateStatus) { s.Stage = "ready"; s.Downloaded = asset.Size })
	return nil
}

// GitHub supports byte ranges. Bounded concurrency prevents a slow CDN
// connection from stretching a large client update into an hours-long download.
func (u *clientUpdater) downloadRanges(file *os.File, asset clientReleaseAsset) error {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	const chunk = int64(4 << 20)
	jobs := make(chan int64, (asset.Size+chunk-1)/chunk)
	for offset := int64(0); offset < asset.Size; offset += chunk {
		jobs <- offset
	}
	close(jobs)
	errors := make(chan error, 1)
	var group sync.WaitGroup
	for worker := 0; worker < 8; worker++ {
		group.Add(1)
		go func() {
			defer group.Done()
			for offset := range jobs {
				if ctx.Err() != nil {
					return
				}
				length := min(chunk, asset.Size-offset)
				resp, err := u.getRange(ctx, asset.URL, fmt.Sprintf("bytes=%d-%d", offset, offset+length-1))
				if err == nil {
					expectedRange := fmt.Sprintf("bytes %d-%d/%d", offset, offset+length-1, asset.Size)
					if resp.Header.Get("Content-Range") != expectedRange {
						err = fmt.Errorf("installer range does not match release metadata")
					}
					if err == nil {
						var body []byte
						body, err = io.ReadAll(io.LimitReader(resp.Body, length+1))
						if err == nil && int64(len(body)) != length {
							err = fmt.Errorf("installer range download was incomplete")
						}
						if err == nil {
							_, err = file.WriteAt(body, offset)
						}
					}
					resp.Body.Close()
				}
				if err != nil {
					select {
					case errors <- err:
					default:
					}
					cancel()
					return
				}
				u.publish(func(s *ClientUpdateStatus) { s.Downloaded += length })
			}
		}()
	}
	group.Wait()
	select {
	case err := <-errors:
		return err
	default:
		return file.Sync()
	}
}

func (a *App) GetClientUpdateStatus() ClientUpdateStatus { return a.updater.snapshot() }
func (a *App) CheckClientUpdate(includePrerelease bool) error {
	s := a.store.get()
	s.IncludePrerelease = includePrerelease
	if err := a.store.save(s); err != nil {
		return err
	}
	go func() { _ = a.updater.check(includePrerelease) }()
	return nil
}
func (a *App) DownloadClientUpdate() error { go func() { _ = a.updater.download() }(); return nil }
func (a *App) ShowClientUpdates() {
	if a.updateWindow != nil {
		a.updateWindow.Show()
		// Hidden windows initialise WebView2 on their first Show. Focusing before
		// the controller is ready can terminate the application on Windows.
	}
}
func (a *App) HideClientUpdates() {
	if a.updateWindow != nil {
		a.updateWindow.Hide()
	}
}
