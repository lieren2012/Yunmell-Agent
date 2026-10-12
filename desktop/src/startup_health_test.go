package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestPrivateManagementHealthBypassesProxyWithoutGlobalEnvironmentChanges(t *testing.T) {
	t.Setenv("HTTP_PROXY", "http://127.0.0.1:7890")
	for _, raw := range []string{"http://10.31.3.82:6602/api/health", "http://192.168.1.7/api/health", "http://127.0.0.1:8088/api/health"} {
		request, _ := http.NewRequest(http.MethodGet, raw, nil)
		proxy, err := healthProxy(request)
		if err != nil || proxy != nil {
			t.Fatalf("private health target must be direct: %s", raw)
		}
	}
}

func TestHealthReadinessRequiresValidResponseAndRole(t *testing.T) {
	for _, test := range []struct {
		name, body, role string
		status           int
		ready            bool
	}{
		{"healthy control", `{"ok":true,"db":true}`, "control-plane", 200, true},
		{"uninitialised control", `{"ok":true,"db":false}`, "control-plane", 200, false},
		{"local setup wizard", `{"ok":true,"db":false}`, "local-runtime", 200, true},
		{"wrong HTML page", `<html>login</html>`, "control-plane", 200, false},
		{"missing health fields", `{}`, "local-runtime", 200, false},
		{"not ready", `{"ok":false,"db":true}`, "local-runtime", 200, false},
		{"not found", `{}`, "control-plane", 404, false},
		{"authentication error", `{}`, "control-plane", 401, false},
		{"gateway error", `{}`, "control-plane", 502, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(test.status)
				_, _ = w.Write([]byte(test.body))
			}))
			defer server.Close()
			ctx, cancel := context.WithTimeout(context.Background(), time.Second)
			defer cancel()
			result := probeStartupHealth(ctx, server.URL, test.role)
			if result.Ready != test.ready {
				t.Fatalf("unexpected readiness: %+v", result)
			}
			if result.HTTPStatus != test.status {
				t.Fatal(result)
			}
		})
	}
}

func TestHealthTimeoutBoundsOneNetworkRequest(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { <-r.Context().Done() }))
	defer server.Close()
	start := time.Now()
	_, err := waitStartupHealth(LocaleZH, server.URL, "control-plane", 100*time.Millisecond)
	if err == nil {
		t.Fatal("a stalled response must time out")
	}
	if time.Since(start) > time.Second {
		t.Fatal("health request ignored its startup deadline")
	}
}

func TestHealthAddressDoesNotLeakConnectionQuery(t *testing.T) {
	endpoint, err := healthEndpoint("http://10.31.3.82:6602/?token=sensitive&enterprise=company")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(endpoint.String(), "sensitive") || endpoint.RawQuery != "" {
		t.Fatal("diagnostics must not log connection query values")
	}
}
