from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_grafana_is_configured_under_appliance_subpath() -> None:
    installer = (ROOT / "tools" / "install-grafana.sh").read_text(encoding="utf-8")
    updater = (ROOT / "tools" / "update.sh").read_text(encoding="utf-8")
    assert "GRAFANA_ROOT_URL:-http://localhost:3000/" in installer
    assert "GF_SERVER_SERVE_FROM_SUB_PATH=true" in installer
    assert "serve_from_sub_path = true" in installer
    # "Main Org." is Grafana's own out-of-the-box default organization name,
    # not something AirMonitor creates -- anything else (e.g. the earlier
    # "AirMonitor" default) never matches a real org on a fresh install, and
    # Grafana silently falls back to requiring login instead of erroring.
    assert "GRAFANA_ANONYMOUS_ORG_NAME:-Main Org." in installer
    assert "GF_USERS_HOME_PAGE=/" in installer
    assert "GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH" not in installer
    assert "UPDATE preferences SET home_dashboard_id = 0" in installer
    assert "no Grafana organization named" in installer
    assert "[[ -x /usr/sbin/grafana ]]" in updater
    assert "[[ -x /usr/sbin/grafana-cli ]]" in updater
    assert 'GRAFANA_DOMAIN="$DOMAIN"' in updater
    assert 'GRAFANA_ROOT_URL="${DOMAIN:+https://$DOMAIN/grafana/}"' in updater
    assert 'GRAFANA_ANONYMOUS_ORG_NAME="$GRAFANA_ANONYMOUS_ORG_NAME"' in updater


def test_grafana_installer_sets_db_permissions_before_validating_sql() -> None:
    """A migrated or already-populated database exists by the time this
    script runs, so the airmonitor-data group/chgrp setup must happen before
    the validate-db step reads it -- otherwise this only ever worked on a
    from-scratch host (no DB yet, so validation was skipped) or a host
    that had already run this once before. Also: usermod -aG never affects
    an already-running process, so validate-db must read as root (sudo)
    rather than rely on this invocation's own group membership."""

    installer = (ROOT / "tools" / "install-grafana.sh").read_text(encoding="utf-8")
    permissions_pos = installer.index("Configuring AirMonitor DB permissions")
    validate_pos = installer.index("Validating dashboard SQL against")
    assert permissions_pos < validate_pos
    assert 'sudo python3 "$DASHBOARD_GENERATOR" --validate-db "$DB_FILE"' in installer
    assert "SUDO_USER" not in installer
    assert 'sudo usermod -aG "$DATA_GROUP" "$(id -un)"' in installer
    assert installer.count("Configuring AirMonitor DB permissions") == 1


def test_install_sh_carries_grafana_org_name_through_migration() -> None:
    """--migrate-from copies the old host's install.conf, then immediately
    re-saves this run's resolved config over it. If GRAFANA_ANONYMOUS_ORG_NAME
    isn't a known key on both sides of that round trip, a migrated appliance
    silently loses it and reproduces the anonymous-Grafana-requires-login bug
    on the new host."""

    installer = (ROOT / "tools" / "install.sh").read_text(encoding="utf-8")
    assert 'GRAFANA_ANONYMOUS_ORG_NAME=""' in installer
    assert "MIGRATE_FROM|LEGACY_GRAFANA_REDIRECT|GRAFANA_ANONYMOUS_ORG_NAME)" in installer
    assert "printf 'GRAFANA_ANONYMOUS_ORG_NAME=%s\\n' \"$GRAFANA_ANONYMOUS_ORG_NAME\"" in installer


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


def test_nginx_routes_alerts_page_and_api_not_the_catchall() -> None:
    """The trailing `location / { return 301 /grafana... }` catch-all means any
    new page needs an explicit location block, or it silently 301s to Grafana
    instead of loading."""

    config = (ROOT / "nginx" / "airmonitor.conf.template").read_text(encoding="utf-8")
    assert "location = /alerts {" in config
    assert "proxy_pass http://127.0.0.1:8080/alerts.html;" in config
    assert "location = /alerts-api {" in config
    assert "proxy_pass http://127.0.0.1:8080/api/alerts;" in config
    assert "location = /update-api {" in config
    assert "proxy_pass http://127.0.0.1:8080/api/update;" in config


def test_nginx_injects_airmonitor_banner_into_grafana_pages() -> None:
    """Grafana's own pages (e.g. /grafana/dashboards) can't take a custom
    dashboard panel, so the logo banner is injected at the nginx layer
    instead, before Grafana's #reactRoot mount point so it survives every
    client-side route change. Applied to both the login page's own location
    block and the main prefix location, since the exact-match /grafana/login
    block serves that page's HTML and the prefix block never sees it."""

    config = (ROOT / "nginx" / "airmonitor.conf.template").read_text(encoding="utf-8")
    assert config.count('sub_filter \'</head>\' \'<link rel="stylesheet" href="/status-assets/grafana-banner.css?v=2"></head>\';') == 2
    assert config.count("sub_filter '<div id=\"reactRoot\"></div>'") == 2
    for label in ("Home", "Live", "Prints", "Compare", "Alerts"):
        assert f">{label}</a>" in config
    assert 'proxy_set_header Accept-Encoding "";' in config


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


def test_landing_page_groups_readings_and_keeps_diagnostics_progressive() -> None:
    root = ROOT / "src" / "airmonitor" / "status_static"
    html = (root / "index.html").read_text(encoding="utf-8")
    css = (root / "style.css").read_text(encoding="utf-8")
    script = (root / "app.js").read_text(encoding="utf-8")

    assert 'class="reading-group"' in html
    assert 'class="reading-group particulate-group"' in html
    assert 'id="system-details"' in html
    assert 'id="voc-age"' in html
    assert 'id="pm25-age"' in html
    assert "renderReadingFreshness" in script
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_airmonitor_login_submits_to_grafana_then_returns_home() -> None:
    script = (ROOT / "src" / "airmonitor" / "status_static" / "login.js").read_text(encoding="utf-8")
    assert 'fetch("/grafana/login"' in script
    assert 'window.location.replace("/")' in script
