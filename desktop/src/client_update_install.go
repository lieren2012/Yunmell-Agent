package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

type clientInstallPlan struct {
	ParentPID   int                `json:"parentPID"`
	Executable  string             `json:"executable"`
	Installer   string             `json:"installer"`
	Asset       clientReleaseAsset `json:"asset"`
	Version     string             `json:"version"`
	Home        string             `json:"home"`
	Result      string             `json:"result"`
	UpdatesOnly bool               `json:"updatesOnly"`
}
type clientInstallResult struct {
	Version string `json:"version"`
	Success bool   `json:"success"`
	Error   string `json:"error"`
}

var applyClientPackage = installClientPackage
var waitClientExit = waitForClientExit

func copyUpdateFile(source, destination string, mode os.FileMode) error {
	src, err := os.Open(source)
	if err != nil {
		return err
	}
	defer src.Close()
	dst, err := os.OpenFile(destination, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	_, err = io.Copy(dst, src)
	if err == nil {
		err = dst.Sync()
	}
	closeErr := dst.Close()
	if err != nil {
		return err
	}
	return closeErr
}

func (a *App) InstallClientUpdate(confirmed bool) error {
	if !confirmed {
		return fmt.Errorf("save your work and confirm installation first")
	}
	u := a.updater
	u.mu.Lock()
	ready := u.state.Stage == "ready"
	path := u.path
	asset := u.asset
	version := u.state.LatestVersion
	if ready {
		u.state.Stage = "installing"
	}
	u.mu.Unlock()
	if !ready {
		return fmt.Errorf("download and verify the client installer first")
	}
	// Every pre-install error retains the existing program and permits a retry.
	succeeded := false
	defer func() {
		if !succeeded {
			u.publish(func(s *ClientUpdateStatus) {
				if s.Stage == "installing" {
					s.Stage = "ready"
				}
			})
		}
	}()
	if err := verifyUpdateFile(path, asset); err != nil {
		u.fail(err)
		return err
	}
	executable, err := os.Executable()
	if err != nil {
		return err
	}
	plan := clientInstallPlan{ParentPID: os.Getpid(), Executable: executable, Installer: path, Asset: asset, Version: version, Home: octopHome()}
	plan.UpdatesOnly = len(os.Args) == 2 && os.Args[1] == "--client-updates"
	directory, err := os.MkdirTemp(u.directory, "install-")
	if err != nil {
		return err
	}
	plan.Result = filepath.Join(directory, "result.json")
	planPath := filepath.Join(directory, "plan.json")
	data, err := json.Marshal(plan)
	if err != nil {
		return err
	}
	if err = os.WriteFile(planPath, data, 0o600); err != nil {
		return err
	}
	helper := filepath.Join(directory, filepath.Base(executable))
	if err = copyUpdateFile(executable, helper, 0o700); err != nil {
		return err
	}
	if err = launchClientInstallerHelper(helper, planPath); err != nil {
		u.fail(err)
		return err
	}
	// An unprivileged watcher retains the original user's token and environment.
	// The elevated Windows installer helper never relaunches the app as admin.
	watcher := exec.Command(helper, "--restart-after-client-update", planPath)
	hideUpdateHelper(watcher)
	if err = watcher.Start(); err != nil {
		u.fail(err)
		return err
	}
	u.publish(func(s *ClientUpdateStatus) { s.Stage = "installing" })
	a.requestQuit()
	succeeded = true
	return nil
}

func loadClientInstallPlan(path string) (clientInstallPlan, error) {
	var plan clientInstallPlan
	data, err := os.ReadFile(path)
	if err != nil {
		return plan, err
	}
	if err = json.Unmarshal(data, &plan); err != nil {
		return plan, err
	}
	if plan.ParentPID <= 0 || !filepath.IsAbs(plan.Executable) || !filepath.IsAbs(plan.Installer) || !filepath.IsAbs(plan.Home) || !filepath.IsAbs(plan.Result) || !pep440RE.MatchString(plan.Version) {
		return plan, fmt.Errorf("invalid client install plan")
	}
	return plan, nil
}

func writeClientInstallResult(plan clientInstallPlan, result clientInstallResult) {
	data, _ := json.Marshal(result)
	tmp := plan.Result + ".new"
	if os.WriteFile(tmp, data, 0o600) == nil {
		_ = os.Rename(tmp, plan.Result)
	}
}

func applyClientInstall(plan clientInstallPlan) error {
	if err := waitClientExit(plan.ParentPID, 90*time.Second); err != nil {
		return err
	}
	if err := verifyUpdateFile(plan.Installer, plan.Asset); err != nil {
		return err
	}
	backup := filepath.Join(filepath.Dir(plan.Result), "previous-client")
	if err := copyUpdateFile(plan.Executable, backup, 0o700); err != nil {
		return fmt.Errorf("cannot preserve the current client: %w", err)
	}
	if err := applyClientPackage(plan); err != nil {
		if rollbackErr := rollbackClientPackage(plan, backup); rollbackErr != nil {
			return fmt.Errorf("update failed (%v); rollback failed (%v); backup: %s", err, rollbackErr, backup)
		}
		return fmt.Errorf("update failed; the previous client was restored: %w", err)
	}
	return nil
}

func verifyInstalledClient(executable, version string) error {
	cmd := exec.Command(executable, "--client-version")
	hideUpdateHelper(cmd)
	output, err := cmd.Output()
	if err != nil {
		return fmt.Errorf("updated client cannot start: %w", err)
	}
	if strings.TrimSpace(string(output)) != version {
		return fmt.Errorf("installed version does not match the verified release")
	}
	return nil
}

func restartAfterClientUpdate(plan clientInstallPlan) error {
	deadline := time.Now().Add(20 * time.Minute)
	for time.Now().Before(deadline) {
		data, err := os.ReadFile(plan.Result)
		if err == nil {
			var result clientInstallResult
			if err = json.Unmarshal(data, &result); err != nil {
				return err
			}
			// Abort paths (e.g. the parent never exited) must not spawn a duplicate.
			if err = waitForClientExit(plan.ParentPID, time.Second); err != nil {
				return err
			}
			_ = os.Setenv("OCTOP_HOME", plan.Home)
			last := filepath.Join(plan.Home, "updates", "last-install.json")
			if err = os.WriteFile(last, data, 0o600); err != nil {
				return err
			}
			args := []string{}
			if plan.UpdatesOnly {
				args = append(args, "--client-updates")
			}
			cmd := exec.Command(plan.Executable, args...)
			hideUpdateHelper(cmd)
			return cmd.Start()
		}
		time.Sleep(500 * time.Millisecond)
	}
	return fmt.Errorf("client installer did not finish; previous program and data remain available")
}

func handleClientUpdateCommand() bool {
	if len(os.Args) == 2 && os.Args[1] == "--client-version" {
		fmt.Println(clientVersion)
		return true
	}
	if len(os.Args) != 3 {
		return false
	}
	switch os.Args[1] {
	case "--apply-client-update":
		plan, err := loadClientInstallPlan(os.Args[2])
		if err != nil {
			return true
		}
		err = applyClientInstall(plan)
		result := clientInstallResult{Version: plan.Version, Success: err == nil}
		if err != nil {
			result.Error = err.Error()
		}
		writeClientInstallResult(plan, result)
		return true
	case "--restart-after-client-update":
		plan, err := loadClientInstallPlan(os.Args[2])
		if err == nil {
			_ = restartAfterClientUpdate(plan)
		}
		return true
	}
	return false
}
