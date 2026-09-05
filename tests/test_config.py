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


def test_personal_invite_contains_odoo_user_and_role() -> None:
    settings = Settings(telegram_invite_codes={"private-code": {"odoo_user_id": 584, "role": "pm"}})

    assert settings.telegram_invite_codes["private-code"] == {
        "odoo_user_id": 584,
        "role": "pm",
    }


def test_bootstrap_invite_can_enable_explicit_recovery() -> None:
    settings = Settings(
        telegram_invite_codes={
            "recovery-code": {
                "odoo_user_id": 1382,
                "role": "pm",
                "allow_rebind": True,
            }
        }
    )

    assert settings.telegram_invite_codes["recovery-code"]["allow_rebind"] is True


def test_ai_and_blocker_privacy_have_safe_defaults() -> None:
    settings = Settings(ai_model="", yandex_ai_model="")

    assert settings.ai_model == "gpt-5-mini"
    assert settings.yandex_ai_model == "aliceai-llm"
    assert settings.ai_provider == "auto"
    assert settings.odoo_include_blocker_text is False
