from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_grafana_is_configured_under_appliance_subpath() -> None:
    installer = (ROOT / "tools" / "install-grafana.sh").read_text(encoding="utf-8")
    updater = (ROOT / "tools" / "update.sh").read_text(encoding="utf-8")
    assert "GRAFANA_ROOT_URL:-http://localhost:3000/" in installer
    assert "GF_SERVER_SERVE_FROM_SUB_PATH=true" in installer
    assert "serve_from_sub_path = true" in installer
    assert "GRAFANA_ANONYMOUS_ORG_NAME:-AirMonitor" in installer
    assert "GF_USERS_HOME_PAGE=/" in installer
    assert "GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH" not in installer
    assert "UPDATE preferences SET home_dashboard_id = 0" in installer
    assert "[[ -x /usr/sbin/grafana ]]" in updater
    assert "[[ -x /usr/sbin/grafana-cli ]]" in updater
    assert 'GRAFANA_DOMAIN="$DOMAIN"' in updater
    assert 'GRAFANA_ROOT_URL="${DOMAIN:+https://$DOMAIN/grafana/}"' in updater


def test_nginx_routes_grafana_and_shared_session_on_one_origin() -> None:
    config = (ROOT / "nginx" / "airmonitor.conf.template").read_text(encoding="utf-8")
    assert "location /grafana/" in config
    assert "location = /sign-in" in config
    assert "proxy_cookie_path /grafana" in config
    assert '\"redirectUrl\":\"/grafana/\"' in config
    assert '\"redirectUrl\":\"/\"' in config
    assert "__DOMAIN__" in config
    assert "example" not in config


def test_legacy_grafana_subdomain_is_optional_and_templated() -> None:
    config = (ROOT / "nginx" / "airmonitor-legacy-grafana.conf.template").read_text(encoding="utf-8")
    assert "server_name grafana.__DOMAIN__;" in config
    assert "return 301 https://__DOMAIN__/grafana$request_uri;" in config
    installer = (ROOT / "tools" / "install.sh").read_text(encoding="utf-8")
    assert '[[ "$LEGACY_GRAFANA_REDIRECT" == "true" ]]' in installer
    status_page = (ROOT / "tools" / "install-status-page.sh").read_text(encoding="utf-8")
    assert 'LEGACY_GRAFANA_REDIRECT="${LEGACY_GRAFANA_REDIRECT:-false}"' in status_page


def test_nginx_routes_public_exports_to_bounded_export_service() -> None:
    config = (ROOT / "nginx" / "airmonitor.conf.template").read_text(encoding="utf-8")
    assert "location /exports/" in config
    assert "proxy_pass http://127.0.0.1:8081/" in config
    assert "proxy_read_timeout 180s" in config


def test_export_page_is_light_theme_and_mobile_responsive() -> None:
    css = (ROOT / "src" / "airmonitor" / "export_static" / "export.css").read_text(encoding="utf-8")
    assert "color-scheme: light" in css
    assert "@media (max-width:720px)" in css
    assert ".download-grid" in css


def test_landing_page_uses_same_origin_grafana_links() -> None:
    for name in ("index.html", "app.js"):
        content = (ROOT / "src" / "airmonitor" / "status_static" / name).read_text(encoding="utf-8")
        assert 'href="/grafana/' in content
        assert "https://grafana.airmonitor.example.com" not in content
        assert 'href="/sign-in"' in content


def test_airmonitor_login_submits_to_grafana_then_returns_home() -> None:
    script = (ROOT / "src" / "airmonitor" / "status_static" / "login.js").read_text(encoding="utf-8")
    assert 'fetch("/grafana/login"' in script
    assert 'window.location.replace("/")' in script
