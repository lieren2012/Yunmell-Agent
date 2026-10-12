package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type StartupHealth struct {
	Target        string `json:"target"`
	Role          string `json:"role"`
	Route         string `json:"route"`
	HTTPStatus    int    `json:"httpStatus"`
	Ready         bool   `json:"ready"`
	DatabaseReady bool   `json:"databaseReady"`
	Version       string `json:"version,omitempty"`
	Detail        string `json:"detail"`
}

func privateHealthHost(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	address := net.ParseIP(host)
	return address != nil && (address.IsPrivate() || address.IsLoopback() || address.IsLinkLocalUnicast())
}

func healthProxy(request *http.Request) (*url.URL, error) {
	// Go's standard NO_PROXY does not bypass RFC1918 addresses by default.
	// Management/loopback health probes are read-only internal traffic; leave
	// model providers and GitHub downloads on their existing proxy policy.
	if privateHealthHost(request.URL.Hostname()) {
		return nil, nil
	}
	return http.ProxyFromEnvironment(request)
}

func healthEndpoint(base string) (*url.URL, error) {
	parsed, err := url.Parse(strings.TrimSpace(base))
	if err != nil || parsed.Host == "" || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.User != nil {
		return nil, fmt.Errorf("管理端地址须为 http(s) 地址，不包含账号或密码")
	}
	parsed.Path = strings.TrimRight(parsed.Path, "/") + "/api/health"
	parsed.RawPath = ""
	parsed.RawQuery = ""
	parsed.Fragment = ""
	return parsed, nil
}

func probeStartupHealth(ctx context.Context, base, role string) StartupHealth {
	result := StartupHealth{Role: role, Route: "direct"}
	endpoint, err := healthEndpoint(base)
	if err != nil {
		result.Detail = err.Error()
		return result
	}
	result.Target = endpoint.String()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint.String(), nil)
	if err != nil {
		result.Detail = "无法创建健康检查请求"
		return result
	}
	if proxy, proxyErr := healthProxy(request); proxyErr != nil {
		result.Detail = "代理配置无效"
		return result
	} else if proxy != nil {
		result.Route = "environment-proxy"
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = healthProxy
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	response, err := client.Do(request)
	if err != nil {
		if ctx.Err() != nil {
			result.Detail = "健康检查超时；请检查地址、端口和连接路径"
		} else {
			result.Detail = "连接失败；请检查地址、端口及 HTTPS 证书"
		}
		return result
	}
	defer response.Body.Close()
	result.HTTPStatus = response.StatusCode
	if response.StatusCode != http.StatusOK {
		result.Detail = fmt.Sprintf("健康检查返回 HTTP %d", response.StatusCode)
		if result.Route == "environment-proxy" {
			result.Detail += "（经环境代理返回，不能据此认定管理端故障）"
		}
		return result
	}
	var payload struct {
		OK      *bool  `json:"ok"`
		DB      *bool  `json:"db"`
		Version string `json:"version"`
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, 64*1024))
	if err != nil || json.Unmarshal(body, &payload) != nil || payload.OK == nil {
		result.Detail = "收到 HTTP 200，但响应不是有效的健康检查 JSON"
		return result
	}
	result.Version = payload.Version
	result.DatabaseReady = payload.DB != nil && *payload.DB
	if !*payload.OK {
		result.Detail = "服务报告 ok=false"
		return result
	}
	if role == "control-plane" && !result.DatabaseReady {
		result.Detail = "企业管理端数据库未就绪（db=false 或缺失）；请先完成管理端初始化"
		return result
	}
	result.Ready = true
	result.Detail = "健康检查通过"
	if privateHealthHost(endpoint.Hostname()) {
		result.Detail += "（内网/本机直连，已绕过环境代理）"
	}
	return result
}

func waitStartupHealth(locale Locale, base, role string, timeout time.Duration) (StartupHealth, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	var result StartupHealth
	for {
		attempt, stop := context.WithTimeout(ctx, 5*time.Second)
		result = probeStartupHealth(attempt, base, role)
		stop()
		if result.Target == "" {
			return result, fmt.Errorf("%s：%s", healthRoleName(role), result.Detail)
		}
		if result.Ready {
			return result, nil
		}
		// Bad URL, authentication/redirect/wrong path responses cannot become
		// ready by waiting. Return an actionable diagnosis immediately.
		if result.HTTPStatus >= 300 && result.HTTPStatus < 500 {
			return result, fmt.Errorf("%s：%s", healthRoleName(role), result.Detail)
		}
		select {
		case <-ctx.Done():
			address := strings.TrimSuffix(result.Target, "/api/health")
			legacy := formatHealthWaitError(locale, address, timeout, fmt.Errorf("%s", result.Detail), result.HTTPStatus)
			return result, fmt.Errorf("%s：%s\n%s", healthRoleName(role), legacy, result.Detail)
		case <-time.After(250 * time.Millisecond):
		}
	}
}
func healthRoleName(role string) string {
	if role == "control-plane" {
		return "企业管理端"
	}
	return "本机运行时"
}
