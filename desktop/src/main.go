package main

import (
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/wailsapp/wails/v3/pkg/application"
	"github.com/wailsapp/wails/v3/pkg/events"
)

//go:embed assets/*
var assets embed.FS

const trayDoubleClick = 400 * time.Millisecond

// App is the Wails service bound to the shell UI.
type App struct {
	app              *application.App
	window           *application.WebviewWindow
	settingsWindow   *application.WebviewWindow
	connectionWindow *application.WebviewWindow
	updateWindow     *application.WebviewWindow
	updater          *clientUpdater
	bootMu           sync.Mutex
	startupMu        sync.Mutex
	startup          StartupStatus
	store            *settingsStore
	sleep            *sleepGuard
	cmd              *exec.Cmd
	mu               sync.Mutex
	quitting         bool

	trayClickMu    sync.Mutex
	lastTrayClick  time.Time
	trayClickTimer *time.Timer
}

func (a *App) ServiceName() string { return "desktop" }

func (a *App) ServiceStartup(context.Context, application.ServiceOptions) error { return nil }

func (a *App) ServiceShutdown() error {
	a.sleep.stop()
	a.mu.Lock()
	cmd := a.cmd
	a.cmd = nil
	a.mu.Unlock()
	stopOctop(cmd)
	return nil
}

func (a *App) GetSettings() Settings {
	_ = a.store.reload()
	return a.store.get()
}

func (a *App) GetSettingsStatus() (Settings, error) {
	s := a.store.get()
	if a.app == nil {
		return s, nil
	}
	status, err := a.app.Autostart.Status()
	if err != nil {
		return s, fmt.Errorf("read autostart status: %w", err)
	}
	if s.Autostart != status.Enabled {
		s.Autostart = status.Enabled
		if err := a.store.save(s); err != nil {
			return s, err
		}
	}
	return s, nil
}

func (a *App) SaveSettings(next Settings) (Settings, error) {
	cur, err := a.GetSettingsStatus()
	if err != nil {
		return cur, err
	}
	autostart, err := a.setAutostart(next.Autostart)
	if err != nil {
		return cur, err
	}
	if err := a.sleep.set(next.PreventSleep); err != nil {
		if _, rollbackErr := a.setAutostart(cur.Autostart); rollbackErr != nil {
			log.Printf("rollback autostart after sleep prevention failure: %v", rollbackErr)
		}
		return cur, err
	}
	next.Autostart = autostart
	if err := a.store.save(next); err != nil {
		return cur, err
	}
	saved := a.store.get()
	a.applyDashboardPrefs(saved)
	return saved, nil
}

func (a *App) ShowMain() {
	a.showWindow()
}

func (a *App) HideSettings() {
	if a.connectionWindow != nil {
		a.connectionWindow.Hide()
	}
	if a.settingsWindow == nil {
		return
	}
	a.settingsWindow.Hide()
}

func (a *App) Quit() {
	a.requestQuit()
}

type mainWindowCloseBehavior uint8

const (
	mainWindowCloseToTray mainWindowCloseBehavior = iota
	mainWindowQuitApplication
)

func mainWindowCloseBehaviorFor(s Settings) mainWindowCloseBehavior {
	if s.MinimizeToTray {
		return mainWindowCloseToTray
	}
	return mainWindowQuitApplication
}

// closeMainWindow applies the user's close policy. Window minimisation is
// deliberately not handled here: it must remain a native minimise so the
// window keeps its taskbar button. The flag name is kept for settings-file
// compatibility, but it now means "hide on close".
func (a *App) closeMainWindow() {
	if a.store != nil && mainWindowCloseBehaviorFor(a.store.get()) == mainWindowCloseToTray {
		a.hideToTray()
		return
	}
	a.requestQuit()
}

func (a *App) setAutostart(on bool) (bool, error) {
	if a.app == nil {
		return false, fmt.Errorf("autostart is unavailable before the application starts")
	}
	if on {
		if err := a.app.Autostart.Enable(); err != nil {
			return false, fmt.Errorf("enable autostart: %w", err)
		}
	} else if err := a.app.Autostart.Disable(); err != nil {
		return false, fmt.Errorf("disable autostart: %w", err)
	}
	status, err := a.app.Autostart.Status()
	if err != nil {
		return false, fmt.Errorf("read autostart status: %w", err)
	}
	if status.Enabled != on {
		return status.Enabled, fmt.Errorf("autostart state did not update")
	}
	return status.Enabled, nil
}

func (a *App) applyDashboardPrefs(s Settings) {
	if a.window == nil {
		return
	}
	js := fmt.Sprintf(
		`(function(){try{localStorage.setItem('octop:ui-locale',%s);}catch(e){}})();`,
		jsonString(string(s.Locale)),
	)
	a.window.ExecJS(js)
}

func jsonString(s string) string {
	b, _ := json.Marshal(s)
	return string(b)
}

func (a *App) setStatus(msg string) {
	a.updateStartup(func(s *StartupStatus) { s.Message = msg })
	if a.app == nil {
		return
	}
	a.app.Event.Emit("desktop:status", msg)
}

func (a *App) boot() {
	if !a.bootMu.TryLock() {
		return
	}
	defer a.bootMu.Unlock()
	a.updateStartup(func(s *StartupStatus) { *s = StartupStatus{Busy: true, Phase: "control-plane"} })
	defer a.updateStartup(func(s *StartupStatus) { s.Busy = false })
	locale := LocaleEN
	if a.store != nil {
		locale = a.store.get().Locale
	}
	// OCTOP_DESKTOP_URL is retained for the development shell, where Wails is
	// intentionally pointed at an already-running Octop instance. A packaged
	// desktop release uses ControlPlaneURL only as the management-service
	// connection; the message/runtime dashboard remains local.
	if devURL := strings.TrimSpace(os.Getenv("OCTOP_DESKTOP_URL")); devURL != "" {
		parsed, err := url.Parse(devURL)
		if err != nil || (parsed.Hostname() != "localhost" && (net.ParseIP(parsed.Hostname()) == nil || !net.ParseIP(parsed.Hostname()).IsLoopback())) {
			a.startupFailed("OCTOP_DESKTOP_URL 仅可指向本机开发工作台。企业管理地址请填写在控制面设置中。")
			return
		}
		a.setStatus(desktopText(locale, copyStatusConnecting))
		if err := waitHealth(locale, devURL, 60*time.Second); err != nil {
			a.startupFailed(err.Error())
			return
		}
		a.showDashboard(devURL)
		return
	}
	s := a.store.get()
	if controlPlaneURL := strings.TrimSpace(s.ControlPlaneURL); controlPlaneURL != "" {
		// The management service carries identity and policy only.  Probe it in
		// the background so a slow/offline control plane never prevents the
		// local runtime and its pages from starting.
		go func(address string, lang Locale) {
			health, err := waitStartupHealth(lang, address, "control-plane", 8*time.Second)
			a.updateStartup(func(state *StartupStatus) {
				state.ControlPlane = health
				if err != nil && state.Phase == "ready" {
					state.Message = "企业管理端暂时离线，本地运行时仍可用"
				}
			})
		}(controlPlaneURL, locale)
	}
	a.updateStartup(func(state *StartupStatus) { state.Phase = "local-runtime" })
	base := dashboardURL(s.Port)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	existing := probeStartupHealth(ctx, base, "local-runtime")
	cancel()
	a.updateStartup(func(state *StartupStatus) { state.LocalRuntime = existing })
	if existing.Ready {
		a.mu.Lock()
		owned := a.cmd != nil
		a.mu.Unlock()
		if !owned {
			a.startupFailed(fmt.Sprintf("企业管理端检查通过；本机端口 %d 已有旧版或独立运行时。请关闭旧云迈客户端后重试，不要删除数据目录。", s.Port))
			return
		}
		a.updateStartup(func(state *StartupStatus) { state.LocalRuntime = existing; state.Phase = "ready" })
		a.showDashboard(base)
		return
	}
	if existing.HTTPStatus != 0 {
		a.startupFailed(fmt.Sprintf("本机端口 %d 已有服务，但健康响应不符合云迈运行时协议：%s。请检查端口占用。", s.Port, existing.Detail))
		return
	}
	a.setStatus(desktopText(locale, copyStatusCheckingRuntime))
	if err := ensurePortable(locale, a.setStatus); err != nil {
		a.startupFailed(err.Error())
		return
	}
	root := portableDir()
	a.mu.Lock()
	stopOctop(a.cmd)
	cmd, err := startOctop(root, s.Port)
	a.cmd = cmd
	a.mu.Unlock()
	if err != nil {
		a.startupFailed(err.Error())
		return
	}
	a.setStatus(desktopText(locale, copyStatusStartingService))
	health, err := waitStartupHealth(locale, base, "local-runtime", 45*time.Second)
	a.updateStartup(func(state *StartupStatus) { state.LocalRuntime = health })
	if err != nil {
		a.startupFailed(err.Error())
		return
	}
	a.updateStartup(func(state *StartupStatus) { state.Phase = "ready" })
	a.showDashboard(base)
}

func (a *App) showDashboard(base string) {
	if a.window == nil {
		return
	}
	a.window.SetURL(base)
	a.scheduleDragOverlay()
	s := a.store.get()
	go func() {
		time.Sleep(800 * time.Millisecond)
		a.applyDashboardPrefs(s)
	}()
	a.setStatus(desktopText(s.Locale, copyStatusReady))
}

func (a *App) hideToTray() {
	if a.window == nil {
		return
	}
	a.window.Hide()
}

func (a *App) showWindow() {
	if a.window == nil {
		return
	}
	if a.window.IsMinimised() {
		a.window.UnMinimise()
	}
	a.window.Show()
	a.window.Focus()
}

func (a *App) toggleMainWindow() {
	if a.window == nil {
		return
	}
	if a.window.IsVisible() && !a.window.IsMinimised() {
		a.hideToTray()
		return
	}
	a.showWindow()
}

func (a *App) onTrayLeftClick() {
	a.trayClickMu.Lock()
	defer a.trayClickMu.Unlock()
	if a.trayClickTimer != nil {
		a.trayClickTimer.Stop()
		a.trayClickTimer = nil
	}
	now := time.Now()
	if !a.lastTrayClick.IsZero() && now.Sub(a.lastTrayClick) < trayDoubleClick {
		a.lastTrayClick = time.Time{}
		go a.toggleMainWindow()
		return
	}
	a.lastTrayClick = now
	a.trayClickTimer = time.AfterFunc(trayDoubleClick, func() {
		a.trayClickMu.Lock()
		a.trayClickTimer = nil
		a.trayClickMu.Unlock()
		a.showWindow()
	})
}

func (a *App) installDragOverlay() {
	if a.window == nil {
		return
	}
	a.window.ExecJS(dragOverlayJS())
}

func (a *App) scheduleDragOverlay() {
	go func() {
		for range 40 {
			time.Sleep(250 * time.Millisecond)
			a.installDragOverlay()
			a.installExternalLinks()
		}
	}()
}

func (a *App) requestQuit() {
	a.mu.Lock()
	a.quitting = true
	a.mu.Unlock()
	if a.app != nil {
		a.app.Quit()
	}
}

func main() {
	if handleStartupDiagnosis() {
		return
	}
	if handleClientUpdateCommand() {
		return
	}
	updatesOnly := len(os.Args) == 2 && os.Args[1] == "--client-updates"
	store := &settingsStore{cur: loadSettings()}
	api := &App{
		store: store,
		sleep: &sleepGuard{},
	}

	app := application.New(application.Options{
		Name:        "云迈智能体",
		Description: "云迈智能体桌面客户端",
		Services: []application.Service{
			application.NewService(api),
		},
		Assets: application.AssetOptions{
			Handler: application.BundledAssetFileServer(assets),
		},
		Windows: application.WindowsOptions{
			DisableQuitOnLastWindowClosed: true,
		},
		Linux: application.LinuxOptions{
			DisableQuitOnLastWindowClosed: true,
		},
		Mac: application.MacOptions{
			ApplicationShouldTerminateAfterLastWindowClosed: false,
		},
	})
	api.app = app
	repository := store.get().UpdateRepository
	if value := strings.TrimSpace(os.Getenv("YUNMELL_UPDATE_REPO")); value != "" {
		repository = value
	}
	api.updater = newClientUpdater(repository, greenPlat(), filepath.Join(octopHome(), "updates"), func(status ClientUpdateStatus) { app.Event.Emit("desktop:client-update", status) })
	attachOpenURLEventListener(app, api.OpenExternal)
	app.Event.OnApplicationEvent(events.Common.ApplicationStarted, func(_ *application.ApplicationEvent) {
		applyAppIcon(app)
	})

	win := app.Window.NewWithOptions(application.WebviewWindowOptions{
		Title:                "云迈智能体",
		Width:                1200,
		Height:               800,
		URL:                  "/",
		Hidden:               updatesOnly,
		Frameless:            true,
		AllowSimpleEventEmit: true,
		BackgroundColour:     application.NewRGB(247, 248, 250),
	})
	api.window = win
	app.Event.On("desktop:toggle-maximise", func(_ *application.CustomEvent) {
		win.ToggleMaximise()
	})
	app.Event.On("desktop:minimise", func(_ *application.CustomEvent) {
		win.Minimise()
	})
	app.Event.On("desktop:close", func(_ *application.CustomEvent) {
		api.closeMainWindow()
	})
	installDragOverlay := func(_ *application.WindowEvent) { api.scheduleDragOverlay() }
	win.OnWindowEvent(events.Mac.WebViewDidFinishNavigation, installDragOverlay)
	win.OnWindowEvent(events.Windows.WebViewNavigationCompleted, installDragOverlay)
	win.OnWindowEvent(events.Linux.WindowLoadFinished, installDragOverlay)
	settingsWin := app.Window.NewWithOptions(application.WebviewWindowOptions{
		Title:            "云迈智能体设置",
		Width:            settingsWindowWidth,
		Height:           settingsWindowOuterHeight(),
		URL:              "/?settings=1",
		Hidden:           true,
		Frameless:        true,
		AlwaysOnTop:      true,
		DisableResize:    true,
		BackgroundColour: application.NewRGB(255, 255, 255),
		Windows: application.WindowsWindow{
			HiddenOnTaskbar: true,
		},
	})
	api.settingsWindow = settingsWin
	updatesWin := app.Window.NewWithOptions(application.WebviewWindowOptions{
		Title: "云迈客户端更新", Width: 560, Height: 620,
		URL: "/updates.html", Hidden: true, BackgroundColour: application.NewRGB(255, 255, 255),
	})
	api.updateWindow = updatesWin
	updatesWin.RegisterHook(events.Common.WindowClosing, func(event *application.WindowEvent) { event.Cancel(); updatesWin.Hide() })
	app.Event.On("desktop:show-updates", func(_ *application.CustomEvent) { api.ShowClientUpdates() })
	app.Event.RegisterApplicationEventHook(events.Mac.ApplicationShouldHandleReopen, func(event *application.ApplicationEvent) {
		event.Cancel()
		restoreMainAfterDockClick(api.window, api.settingsWindow)
	})

	win.RegisterHook(events.Common.WindowClosing, func(e *application.WindowEvent) {
		api.mu.Lock()
		quit := api.quitting
		api.mu.Unlock()
		if quit {
			return
		}
		if api.store != nil && mainWindowCloseBehaviorFor(api.store.get()) == mainWindowCloseToTray {
			e.Cancel()
			api.hideToTray()
			return
		}
		// The close event is already on the native UI thread. Let the native
		// close continue and request application shutdown asynchronously; this
		// avoids re-entering Wails' window-close hook synchronously.
		api.mu.Lock()
		api.quitting = true
		api.mu.Unlock()
		go func() {
			if api.app != nil {
				api.app.Quit()
			}
		}()
	})
	settingsWin.RegisterHook(events.Common.WindowClosing, func(e *application.WindowEvent) {
		e.Cancel()
		settingsWin.Hide()
	})
	settingsWin.OnWindowEvent(events.Common.WindowLostFocus, func(_ *application.WindowEvent) {
		settingsWin.Hide()
	})

	tray := app.SystemTray.New()
	applyTrayIcon(tray)
	tray.SetTooltip("云迈智能体")
	tray.AttachWindow(settingsWin).WindowOffset(6)
	showSettings := func() { tray.ShowWindow() }
	trayMenu := app.NewMenu()
	trayMenu.Add("显示云迈智能体").OnClick(func(_ *application.Context) { api.showWindow() })
	trayMenu.Add("设置").OnClick(func(_ *application.Context) { showSettings() })
	trayMenu.AddSeparator()
	trayMenu.Add("退出").OnClick(func(_ *application.Context) { api.requestQuit() })
	tray.SetMenu(trayMenu)
	if trayLeftClickShowsSettings(runtime.GOOS) {
		tray.OnClick(showSettings)
	} else {
		tray.OnClick(func() { api.onTrayLeftClick() })
	}
	// On Windows/Linux the context menu contains explicit Show/Quit actions;
	// keep the left click focused on restoring the main window.
	tray.OnRightClick(tray.OpenMenu)

	if !updatesOnly {
		if _, err := api.setAutostart(store.get().Autostart); err != nil {
			log.Printf("sync autostart: %v", err)
		}
		if err := api.sleep.set(store.get().PreventSleep); err != nil {
			log.Printf("enable sleep prevention: %v", err)
		}
	}

	api.scheduleDragOverlay()
	if !updatesOnly {
		go api.boot()
	}
	go func() {
		time.Sleep(time.Second)
		if updatesOnly {
			api.ShowClientUpdates()
		}
		if err := api.updater.check(store.get().IncludePrerelease); err == nil && api.updater.snapshot().HasUpdate {
			api.ShowClientUpdates()
		}
	}()

	if err := app.Run(); err != nil {
		log.Fatal(err)
	}
}
