from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_grafana_is_configured_under_appliance_subpath() -> None:
    installer = (ROOT / "tools" / "install-grafana.sh").read_text(encoding="utf-8")
    assert "https://airmonitor.example.com/grafana/" in installer
    assert "GF_SERVER_SERVE_FROM_SUB_PATH=true" in installer
    assert "serve_from_sub_path = true" in installer
    assert 'GRAFANA_ANONYMOUS_ORG_NAME:-Example Org' in installer


def test_nginx_routes_grafana_and_shared_session_on_one_origin() -> None:
    config = (ROOT / "nginx" / "airmonitor.conf").read_text(encoding="utf-8")
    assert "location /grafana/" in config
    assert "proxy_cookie_path /grafana" in config
    assert "https://airmonitor.example.com/grafana$request_uri" in config


def test_landing_page_uses_same_origin_grafana_links() -> None:
    for name in ("index.html", "app.js"):
        content = (ROOT / "src" / "airmonitor" / "status_static" / name).read_text(encoding="utf-8")
        assert 'href="/grafana/' in content
        assert "https://grafana.airmonitor.example.com" not in content
        assert "/grafana/login?redirectTo=%2F" in content
