from abm_daily_bot.services.odoo_client import html_to_text


def test_html_to_text_extracts_odoo_chatter_content() -> None:
    assert html_to_text("<p>Готово: <strong>проверил API</strong></p>") == (
        "Готово: проверил API"
    )

