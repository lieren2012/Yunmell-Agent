//go:build windows

package main

import (
	"context"
	"fmt"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
)

func hideUpdateHelper(cmd *exec.Cmd) { hideConsole(cmd) }

func launchClientInstallerHelper(helper, plan string) error {
	verb, _ := windows.UTF16PtrFromString("runas")
	file, _ := windows.UTF16PtrFromString(helper)
	args, _ := windows.UTF16PtrFromString("--apply-client-update " + syscall.EscapeArg(plan))
	proc := windows.NewLazySystemDLL("shell32.dll").NewProc("ShellExecuteW")
	result, _, _ := proc.Call(0, uintptr(unsafe.Pointer(verb)), uintptr(unsafe.Pointer(file)), uintptr(unsafe.Pointer(args)), 0, 0)
	if result <= 32 {
		return fmt.Errorf("installer permission was cancelled or unavailable; the current client is unchanged")
	}
	return nil
}

func waitForClientExit(pid int, timeout time.Duration) error {
	handle, err := windows.OpenProcess(windows.SYNCHRONIZE, false, uint32(pid))
	if err == windows.ERROR_INVALID_PARAMETER {
		return nil
	}
	if err != nil {
		return fmt.Errorf("cannot wait for the running client: %w", err)
	}
	defer windows.CloseHandle(handle)
	result, err := windows.WaitForSingleObject(handle, uint32(timeout.Milliseconds()))
	if err != nil {
		return err
	}
	if result != windows.WAIT_OBJECT_0 {
		return fmt.Errorf("the running client did not exit; installation cancelled")
	}
	return nil
}

func installClientPackage(plan clientInstallPlan) error {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, plan.Installer, "/S", "/D="+filepath.Dir(plan.Executable))
	hideUpdateHelper(cmd)
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("Windows installer failed: %w", err)
	}
	return verifyInstalledClient(plan.Executable, plan.Version)
}
func rollbackClientPackage(plan clientInstallPlan, backup string) error {
	return copyUpdateFile(backup, plan.Executable, 0o700)
}
