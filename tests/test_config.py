from abm_daily_bot.config import Settings


def test_empty_optional_public_url_is_allowed() -> None:
    settings = Settings(public_base_url="")

    assert settings.public_base_url is None


def test_individual_odoo_mapping_overrides_test_default() -> None:
    settings = Settings(
        odoo_default_user_id=94,
        telegram_odoo_user_map={1001: 12, 1002: 13},
    )

    assert settings.odoo_user_id_for(1001) == 12
    assert settings.odoo_user_id_for(1002) == 13
    assert settings.odoo_user_id_for(9999) == 94


def test_project_scope_is_configurable() -> None:
    settings = Settings(
        odoo_project_ids=[1329, 1330, 1335, 1336],
        odoo_scope_label="PORTF-008 · Управление клубами",
    )

    assert settings.odoo_project_ids == [1329, 1330, 1335, 1336]
    assert settings.odoo_scope_label.startswith("PORTF-008")

