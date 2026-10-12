package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

type StartupStatus struct {
	Busy         bool          `json:"busy"`
	Phase        string        `json:"phase"`
	Message      string        `json:"message"`
	ControlPlane StartupHealth `json:"controlPlane"`
	LocalRuntime StartupHealth `json:"localRuntime"`
}

func (a *App) updateStartup(change func(*StartupStatus)) {
	a.startupMu.Lock()
	change(&a.startup)
	state := a.startup
	// Only role, endpoint, HTTP code and readiness are recorded. Response
	// bodies, proxy credentials, login passwords and tokens are never logged.
	if data, err := json.MarshalIndent(state, "", "  "); err == nil {
		if os.MkdirAll(octopHome(), 0o700) == nil {
			_ = os.WriteFile(filepath.Join(octopHome(), "desktop-startup.json"), data, 0o600)
		}
	}
	a.startupMu.Unlock()
	if a.app != nil {
		a.app.Event.Emit("desktop:startup", state)
	}
}
func (a *App) GetStartupStatus() StartupStatus {
	a.startupMu.Lock()
	defer a.startupMu.Unlock()
	return a.startup
}
func (a *App) startupFailed(message string) {
	a.updateStartup(func(s *StartupStatus) { s.Phase = "error"; s.Message = message })
}
func (a *App) RetryStartup() error {
	if a.GetStartupStatus().Busy {
		return fmt.Errorf("启动检查正在进行，请稍候")
	}
	if a.window != nil {
		a.window.SetURL("/")
	}
	go a.boot()
	return nil
}
func (a *App) ShowConnectionSettings() {
	if a.settingsWindow != nil {
		a.settingsWindow.Show()
	}
}

func handleStartupDiagnosis() bool {
	if len(os.Args) != 2 || os.Args[1] != "--startup-diagnose" {
		return false
	}
	settings := loadSettings()
	state := StartupStatus{Phase: "diagnosis"}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	if settings.ControlPlaneURL != "" {
		state.ControlPlane = probeStartupHealth(ctx, settings.ControlPlaneURL, "control-plane")
	}
	cancel()
	ctx, cancel = context.WithTimeout(context.Background(), time.Second)
	state.LocalRuntime = probeStartupHealth(ctx, dashboardURL(settings.Port), "local-runtime")
	cancel()
	legacyHTTPStatus := 0
	if endpoint, err := healthEndpoint(settings.ControlPlaneURL); err == nil {
		// Compare with the former proxy-based request without logging the proxy
		// URL, response body, credentials or environment contents.
		client := &http.Client{Timeout: 10 * time.Second}
		if response, err := client.Get(endpoint.String()); err == nil {
			legacyHTTPStatus = response.StatusCode
			response.Body.Close()
		}
	}
	result := struct {
		ClientVersion string `json:"clientVersion"`
		StartupStatus
		LegacyProxyHTTPStatus int `json:"legacyProxyHTTPStatus"`
	}{clientVersion, state, legacyHTTPStatus}
	data, _ := json.MarshalIndent(result, "", "  ")
	fmt.Println(string(data))
	return true
}
