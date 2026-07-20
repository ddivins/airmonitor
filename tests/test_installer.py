from __future__ import annotations

from pathlib import Path
import os
import subprocess


ROOT = Path(__file__).parents[1]
INSTALLER = ROOT / "tools" / "install.sh"
UPDATER = ROOT / "tools" / "update.sh"
CONFIG_EXAMPLE = ROOT / "config" / "install.conf.example"


def test_installer_is_executable_and_valid_bash() -> None:
    assert os.access(INSTALLER, os.X_OK)
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)


def test_installer_help_documents_supported_modes() -> None:
    result = subprocess.run(
        ["bash", str(INSTALLER), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--config FILE" in result.stdout
    assert "--core" in result.stdout
    assert "--full" in result.stdout
    assert "--migrate-from USER@HOST" in result.stdout
    assert "--non-interactive" in result.stdout


def test_installer_preserves_secrets_and_gates_public_routing() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'if ! sudo test -e "$destination"' in text
    assert 'mode=0600' in text
    assert 'permissions" == "600"' in text
    assert 'certificate_exists "$DOMAIN"' in text
    assert 'INSTALL_STATUS_PAGE=0' in text
    assert 'RUN_DOCTOR=0' in text


def test_installer_checks_hardware_before_running_update() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "EXPECTED_CP2105_SERIAL" in text
    assert text.index("validate_cp2105\n") < text.index("run_update\n")


def test_migration_protects_database_consistency_and_destination_files() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    migration = text[text.index("migrate_from_old_host()") : text.index("install_config_templates()")]
    assert 'systemctl stop airmonitor.target grafana-server' in migration
    assert 'systemctl start airmonitor.target grafana-server' in migration
    assert 'backup_existing "$DATA_DIR/airmonitor.sqlite3"' in migration
    assert "etc/letsencrypt" not in migration


def test_updater_can_explicitly_skip_status_page_provisioning() -> None:
    text = UPDATER.read_text(encoding="utf-8")
    assert 'INSTALL_STATUS_PAGE="${INSTALL_STATUS_PAGE:-auto}"' in text
    assert '[[ "$INSTALL_STATUS_PAGE" == "1" ]]' in text
    assert '[[ "$INSTALL_STATUS_PAGE" == "auto" ]]' in text
    assert 'RUN_DOCTOR="${RUN_DOCTOR:-1}"' in text
    assert '[[ "$RUN_DOCTOR" == "1"' in text


def test_installer_supports_config_file_and_remembers_previous_answers() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "load_conf_file() {" in text
    assert 'load_conf_file "$STATE_CONF"' in text
    assert 'load_conf_file "$CONFIG_FILE"' in text
    assert "save_config() {" in text
    assert 'STATE_CONF="$CONFIG_DIR/install.conf"' in text
    # loaded config, then --config file, then explicit flags, in that order
    assert text.index('load_conf_file "$STATE_CONF"') < text.index('load_conf_file "$CONFIG_FILE"')
    assert text.index('load_conf_file "$CONFIG_FILE"') < text.index('[[ -n "$FLAG_MODE" ]] && MODE="$FLAG_MODE"')


def test_installer_prompts_only_when_interactive_and_unconfigured() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'prompt_for_missing_config() {' in text
    assert '[[ "$NON_INTERACTIVE" == "false" && -t 0 ]] || return 0' in text


def test_installer_requires_domain_and_cert_email_for_full_mode() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'fail "MODE=full requires DOMAIN' in text
    assert 'fail "MODE=full requires CERT_EMAIL' in text


def test_installer_never_persists_migrate_from() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    save_config = text[text.index("save_config() {") : text.index("prompt_for_missing_config() {")]
    assert "printf 'MIGRATE_FROM=\\n'" in save_config


def test_install_conf_example_documents_all_recognized_keys() -> None:
    installer_text = INSTALLER.read_text(encoding="utf-8")
    example_text = CONFIG_EXAMPLE.read_text(encoding="utf-8")
    for key in ("MODE", "DOMAIN", "CERT_EMAIL", "CERTBOT_CLOUDFLARE_CREDENTIALS", "MIGRATE_FROM", "LEGACY_GRAFANA_REDIRECT"):
        assert f"{key}=" in example_text
        assert key in installer_text
    assert "example" not in example_text
