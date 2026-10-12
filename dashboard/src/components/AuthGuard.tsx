import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Spin } from "antd";
import {
  AUTH_TOKEN_CHANGED_EVENT,
  AUTH_TOKEN_STORAGE_KEY,
  clearAuthToken,
  getAuthToken,
} from "../api/request";
import { authApi, type OctopUser } from "../api/modules/auth";
import { applyUserLocale } from "../utils/locale";
import { isNetworkFetchError } from "../utils/networkError";
import { CurrentUserProvider } from "../hooks/useCurrentUser";
import BootOfflinePanel from "./BootOfflinePanel";

interface AuthGuardProps {
  children: React.ReactNode;
}

/**
 * Gate every protected route on (a) the initial admin existing and
 * (b) a valid JWT in localStorage. Octop always requires auth — there is
 * no "password protection disabled" mode like finnie had.
 *
 * Always wait for ``/api/setup/status`` (and ``/auth/me`` when a token
 * exists) before mounting children. Optimistic shell render with a stale
 * token would fire ``/api/agents`` / capabilities / update probes and get
 * 503'd by setup lockdown on first boot.
 *
 * When unauthenticated we must NOT render children: MainLayout / AgentProvider
 * would fire authenticated APIs, trip the 401 interceptor, and race the
 * navigate back to ``/login``.
 *
 * When the backend is unreachable (offline / Failed to fetch), show an
 * explicit offline panel with Retry instead of mounting a blank shell.
 *
 * Auth is checked on mount and on explicit offline retry only. Do not put
 * ``navigate`` in the effect deps: under ``BrowserRouter``, React Router's
 * navigate identity changes with the location, which would re-run the gate
 * on every sidebar click and flash a full-page spinner.
 */
export default function AuthGuard({ children }: AuthGuardProps) {
  const navigate = useNavigate();
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  const [checking, setChecking] = useState(true);
  const [authed, setAuthed] = useState(false);
  const [user, setUser] = useState<OctopUser | null>(null);
  const [offline, setOffline] = useState(false);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      setOffline(false);
      try {
        const status = await authApi.getAuthStatus();
        if (status.connection_required) {
          clearAuthToken();
          if (!cancelled) navigateRef.current("/connection", { replace: true });
          return;
        }

        // No admin yet → push to setup wizard; drop any leftover JWT from a
        // previous install so background prefetch cannot stampede lockdown.
        if (status.setup_required) {
          clearAuthToken();
          if (!cancelled) navigateRef.current("/setup", { replace: true });
          return;
        }

        // Setup done. Need a token.
        const token = getAuthToken();
        if (!token) {
          if (!cancelled) {
            setAuthed(false);
            // Stay on the spinner until navigation away completes — do not
            // flip ``checking`` off or children would mount and 401→/login.
            navigateRef.current("/login", { replace: true });
          }
          return;
        }

        // Validate the token by hitting /auth/me. On 401 the request.ts
        // interceptor already kicks the user back to /login, so we just
        // need to swallow the throw here.
        try {
          const me = await authApi.me();
          await applyUserLocale(me.locale);
          if (!cancelled) {
            setUser(me);
            setAuthed(true);
            setChecking(false);
          }
        } catch (err) {
          if (cancelled) return;
          if (isNetworkFetchError(err)) {
            setOffline(true);
            setChecking(false);
            setAuthed(false);
            return;
          }
          setAuthed(false);
          navigateRef.current("/login", { replace: true });
        }
      } catch (err) {
        if (cancelled) return;
        // Backend unreachable (or setup/status otherwise failed) — do not
        // mount MainLayout with a null user (that produced a blank white
        // shell with no recovery action).
        void err;
        setOffline(true);
        setChecking(false);
        setAuthed(false);
      }
    };

    void check();
    return () => {
      cancelled = true;
    };
  }, [retryKey]);

  // A remembered token is shared by tabs on the same origin. If another tab
  // logs in as a different account (or logs out), this tab must not keep
  // rendering its old /auth/me projection while requests use the new token.
  // Drop the protected tree and make the user explicitly log in again.
  useEffect(() => {
    const invalidateAndLogin = () => {
      setUser(null);
      setAuthed(false);
      setChecking(true);
      // Cancel an in-flight check that could otherwise commit the old user
      // projection after this tab has observed the cross-tab token change.
      setRetryKey((key) => key + 1);
      navigateRef.current("/login", { replace: true });
    };

    const onStorage = (event: StorageEvent) => {
      if (event.key !== AUTH_TOKEN_STORAGE_KEY) return;
      if (event.newValue === event.oldValue) return;
      invalidateAndLogin();
    };

    const onAuthChanged = (event: Event) => {
      // Token renewal is a same-document ``set`` and keeps the same user;
      // dropping the whole shell on every sliding renewal would interrupt
      // active streams. Fresh login happens on the public route, while a
      // clear (logout/401) must force the normal gate re-check here.
      const reason = (event as CustomEvent<{ reason?: string }>).detail?.reason;
      if (reason === "renew") return;
      setUser(null);
      setAuthed(false);
      setChecking(true);
      setRetryKey((key) => key + 1);
    };

    window.addEventListener("storage", onStorage);
    window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, onAuthChanged);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, onAuthChanged);
    };
  }, []);

  if (offline) {
    return (
      <BootOfflinePanel
        onRetry={() => {
          setChecking(true);
          setAuthed(false);
          setOffline(false);
          setRetryKey((k) => k + 1);
        }}
      />
    );
  }

  if (checking || !authed) {
    return (
      <div
        style={{
          height: "100dvh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--fn-bg-layout)",
        }}
      >
        <Spin size="large" />
      </div>
    );
  }

  return (
    <CurrentUserProvider user={user} setUser={setUser}>
      {user?.deployment?.model_error && <Alert type="warning" message={user.deployment.model_error} showIcon />}
      {children}
    </CurrentUserProvider>
  );
}
