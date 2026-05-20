import json
import os
import pickle
import threading
import time
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SESSION_LOCK = threading.Lock()

SC_HOST = os.getenv("SC_HOST", "").rstrip("/")
SC_USERNAME = os.getenv("SC_USERNAME", "")
SC_PASSWORD = os.getenv("SC_PASSWORD", "")
SC_VERIFY_SSL = os.getenv("SC_VERIFY_SSL", "false").lower() in ("true", "1", "yes")

SESSION_FILE = os.getenv("SC_SESSION_FILE", "/config/session/scale_session.p")
SESSION_MAX_AGE_SECONDS = int(os.getenv("SC_SESSION_MAX_AGE_SECONDS", "43200"))


def _normalize_host(host: str) -> str:
    host = host.rstrip("/")
    if host.endswith("/rest/v1"):
        return host[:-len("/rest/v1")]
    return host


BASE_HOST = _normalize_host(SC_HOST)
BASE_API_URL = f"{BASE_HOST}/rest/v1"


def _session_path():
    return Path(SESSION_FILE)


def _session_is_fresh(path: Path) -> bool:
    if not path.exists():
        return False

    age = time.time() - path.stat().st_mtime
    return age < SESSION_MAX_AGE_SECONDS


def _save_headers(headers: dict):
    path = _session_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "wb") as f:
        pickle.dump(headers, f)

    os.replace(tmp_path, path)


def _load_headers() -> dict:
    with open(_session_path(), "rb") as f:
        return pickle.load(f)


def login() -> dict:
    if not BASE_HOST:
        raise RuntimeError("SC_HOST is not set")

    if not SC_USERNAME:
        raise RuntimeError("SC_USERNAME is not set")

    if not SC_PASSWORD:
        raise RuntimeError("SC_PASSWORD is not set")

    headers = {
        "Content-Type": "application/json"
    }

    payload = {
        "username": SC_USERNAME,
        "password": SC_PASSWORD,
        "useOIDC": False
    }

    response = requests.post(
        f"{BASE_API_URL}/login",
        headers=headers,
        data=json.dumps(payload),
        verify=SC_VERIFY_SSL,
        timeout=30
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Scale login failed: HTTP {response.status_code}: {response.text[:500]}"
        )

    session_id = response.cookies.get("sessionID")

    if not session_id:
        raise RuntimeError("Scale login succeeded, but no sessionID cookie was returned")

    headers["Cookie"] = f"sessionID={session_id}"

    _save_headers(headers)

    print("[SESSION] New Scale API session created and saved.")
    return headers


def logout():
    path = _session_path()

    if not path.exists():
        return

    try:
        headers = _load_headers()

        response = requests.post(
            f"{BASE_API_URL}/logout",
            headers=headers,
            verify=SC_VERIFY_SSL,
            timeout=30
        )

        print(f"[SESSION] Scale logout returned HTTP {response.status_code}")

    except Exception as e:
        print(f"[SESSION] Logout failed, continuing anyway: {e}")

    try:
        path.unlink()
        print("[SESSION] Old Scale API session file removed.")
    except FileNotFoundError:
        pass


def get_headers(force_refresh: bool = False) -> dict:
    with SESSION_LOCK:
        path = _session_path()

        if not force_refresh and _session_is_fresh(path):
            try:
                print("[SESSION] Using cached Scale API session.")
                return _load_headers()
            except Exception as e:
                print(f"[SESSION] Failed to load cached session, regenerating: {e}")

        if path.exists():
            print("[SESSION] Cached session is stale or invalid. Refreshing.")
            logout()

        return login()


def request(method: str, url: str, **kwargs):
    """
    Scale API request wrapper.

    Reuses cached session headers.
    If Scale returns 401 or 403, refreshes session once and retries.
    """
    extra_headers = kwargs.pop("headers", None) or {}
    timeout = kwargs.pop("timeout", 30)

    session_headers = get_headers()
    headers = dict(session_headers)
    headers.update(extra_headers)

    response = requests.request(
        method,
        url,
        headers=headers,
        verify=SC_VERIFY_SSL,
        timeout=timeout,
        **kwargs
    )

    if response.status_code in (401, 403):
        print(f"[SESSION] Scale API returned HTTP {response.status_code}. Refreshing session and retrying once.")

        session_headers = get_headers(force_refresh=True)
        headers = dict(session_headers)
        headers.update(extra_headers)

        response = requests.request(
            method,
            url,
            headers=headers,
            verify=SC_VERIFY_SSL,
            timeout=timeout,
            **kwargs
        )

    return response


def get(url: str, **kwargs):
    return request("GET", url, **kwargs)


def post(url: str, **kwargs):
    return request("POST", url, **kwargs)


def put(url: str, **kwargs):
    return request("PUT", url, **kwargs)


def delete(url: str, **kwargs):
    return request("DELETE", url, **kwargs)