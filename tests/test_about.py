"""Tests for the About page (step 22): one page with About, Designer & game,
Reference, Contact and Support me, in the same format as TCsMusic."""
import pytest

from app import routes


@pytest.fixture
def about_settings(monkeypatch):
    """Give each test its own copy of the settings, so filling one in never leaks into another test."""
    links = dict(routes.ABOUT_LINKS)
    emailjs = dict(routes.ABOUT_EMAILJS)
    monkeypatch.setattr(routes, "ABOUT_LINKS", links)
    monkeypatch.setattr(routes, "ABOUT_EMAILJS", emailjs)
    return links, emailjs


def test_page_has_every_section_and_a_jump_nav(client):
    page = client.get("/about").get_data(as_text=True)
    for anchor in ("about", "designer", "reference", "contact", "support"):
        assert f'id="{anchor}"' in page
        assert f'href="#{anchor}"' in page
    assert 'id="algorithms"' in page and 'id="controls"' in page   # old footer links still land somewhere


def test_reference_tables_come_from_the_engine(client):
    page = client.get("/about").get_data(as_text=True)
    for name in ("Morph Ball", "Dash Boots", "Double Jump", "Grapple Beam", "Energy Tank"):
        assert name in page
    assert "Collectible" in page and "/api/maps/&lt;id&gt;/check" in page


def test_empty_settings_hide_the_form_and_the_tip_buttons(client, about_settings):
    page = client.get("/about").get_data(as_text=True)
    assert 'id="about-contact-form"' not in page and "emailjs" not in page
    assert "Contact details are coming soon." in page
    assert "Tip via PayPal" not in page and "Tip via GCash" not in page


def test_filled_settings_show_the_form_links_and_tips(client, about_settings):
    links, emailjs = about_settings
    emailjs.update(service="service_x", template="template_y", key="public_z")
    links.update(github="https://github.com/example/tcsmetroid", tip="https://paypal.me/example", gcash_qr=True)
    page = client.get("/about").get_data(as_text=True)
    assert 'id="about-contact-form"' in page and 'data-service="service_x"' in page
    assert "about.js" in page and "@emailjs/browser@4.4.1" in page
    assert "https://github.com/example/tcsmetroid" in page
    assert "Tip via PayPal" in page and "support-qr.png" in page


def test_header_and_footer_point_to_the_sections(client):
    page = client.get("/").get_data(as_text=True)
    for anchor in ("#about", "#reference", "#contact", "#support"):
        assert f"/about{anchor}" in page
    assert ">About</a>" in page and "How it works" not in page


def test_contact_script_is_served(client):
    js = client.get("/static/about.js").get_data(as_text=True)
    assert "emailjs.sendForm" in js and "about-contact-form" in js
