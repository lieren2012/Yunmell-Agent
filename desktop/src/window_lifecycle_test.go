package main

import "testing"

func TestMainWindowClosePolicyHidesOnlyWhenEnabled(t *testing.T) {
	if got := mainWindowCloseBehaviorFor(Settings{MinimizeToTray: true}); got != mainWindowCloseToTray {
		t.Fatalf("close policy with tray enabled = %d, want close-to-tray", got)
	}
	if got := mainWindowCloseBehaviorFor(Settings{MinimizeToTray: false}); got != mainWindowQuitApplication {
		t.Fatalf("close policy with tray disabled = %d, want quit", got)
	}
}
