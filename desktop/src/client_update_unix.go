//go:build !windows

package main

import (
	"archive/tar"
	"compress/gzip"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"
)

func hideUpdateHelper(cmd *exec.Cmd) {}
func launchClientInstallerHelper(helper, plan string) error {
	return exec.Command(helper, "--apply-client-update", plan).Start()
}
func waitForClientExit(pid int, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		err := syscall.Kill(pid, 0)
		if err == syscall.ESRCH {
			return nil
		}
		if err != nil {
			return err
		}
		time.Sleep(250 * time.Millisecond)
	}
	return fmt.Errorf("the running client did not exit; installation cancelled")
}
func macClientBundle(executable string) string {
	for path := filepath.Dir(executable); path != filepath.Dir(path); path = filepath.Dir(path) {
		if strings.HasSuffix(path, ".app") {
			return path
		}
	}
	return ""
}
func installClientPackage(plan clientInstallPlan) error {
	if runtime.GOOS == "darwin" {
		bundle := macClientBundle(plan.Executable)
		if bundle == "" {
			return fmt.Errorf("the installed client is not an application bundle")
		}
		mount := filepath.Join(filepath.Dir(plan.Result), "mount")
		if err := os.MkdirAll(mount, 0o700); err != nil {
			return err
		}
		if err := exec.Command("hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", mount, plan.Installer).Run(); err != nil {
			return err
		}
		defer exec.Command("hdiutil", "detach", mount).Run()
		next := bundle + ".update-new-" + safeVersion(plan.Version)
		previous := bundle + ".update-previous-" + safeVersion(clientVersion)
		if _, err := os.Stat(next); !os.IsNotExist(err) {
			return fmt.Errorf("a staged app update already exists")
		}
		if _, err := os.Stat(previous); !os.IsNotExist(err) {
			return fmt.Errorf("a previous app backup already exists")
		}
		if err := exec.Command("ditto", filepath.Join(mount, "Yunmell-Agent.app"), next).Run(); err != nil {
			return err
		}
		defer os.RemoveAll(next)
		if err := verifyInstalledClient(filepath.Join(next, "Contents", "MacOS", "Yunmell-Agent"), plan.Version); err != nil {
			return err
		}
		if err := os.Rename(bundle, previous); err != nil {
			return err
		}
		if err := os.Rename(next, bundle); err != nil {
			_ = os.Rename(previous, bundle)
			return err
		}
		return nil
	}
	f, err := os.Open(plan.Installer)
	if err != nil {
		return err
	}
	defer f.Close()
	gz, err := gzip.NewReader(f)
	if err != nil {
		return err
	}
	defer gz.Close()
	reader := tar.NewReader(gz)
	for {
		header, err := reader.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
		if header.Name != "Yunmell-Agent" || header.Typeflag != tar.TypeReg {
			continue
		}
		if header.Size <= 0 || header.Size > 1<<30 {
			return fmt.Errorf("invalid client binary size")
		}
		next, err := os.CreateTemp(filepath.Dir(plan.Executable), ".yunmell-update-")
		if err != nil {
			return err
		}
		name := next.Name()
		defer os.Remove(name)
		_, err = io.CopyN(next, reader, header.Size)
		next.Close()
		if err != nil {
			return err
		}
		if err = os.Chmod(name, 0o755); err != nil {
			return err
		}
		if err = verifyInstalledClient(name, plan.Version); err != nil {
			return err
		}
		return os.Rename(name, plan.Executable)
	}
	return fmt.Errorf("client package contains no Yunmell executable")
}
func rollbackClientPackage(plan clientInstallPlan, backup string) error {
	if runtime.GOOS == "darwin" {
		bundle := macClientBundle(plan.Executable)
		previous := bundle + ".update-previous-" + safeVersion(clientVersion)
		if bundle != "" {
			if _, err := os.Stat(previous); err == nil {
				return os.Rename(previous, bundle)
			}
		}
	}
	return copyUpdateFile(backup, plan.Executable, 0o700)
}
