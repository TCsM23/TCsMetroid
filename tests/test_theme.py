"""Tests for light/dark mode and the brand look (step 20)."""


def test_theme_is_chosen_in_the_head_before_the_page_draws(client):
    page = client.get("/").get_data(as_text=True)
    head = page.split("</head>")[0]
    assert "tcsmetroid-theme" in head and "prefers-color-scheme: light" in head
    assert 'classList.add("is-motion")' in head          # motion starts before the first paint too
    assert '<meta name="color-scheme" content="dark light">' in head


def test_header_has_a_theme_switch(client):
    page = client.get("/about").get_data(as_text=True)
    assert 'class="base-header-theme"' in page and 'class="is-moon"' in page and 'class="is-sun"' in page


def test_stylesheet_has_both_palettes_from_the_moodboard(client):
    css = client.get("/static/style.css").get_data(as_text=True).lower()
    assert ':root[data-theme="light"]' in css
    for colour in ("#050309", "#f1fb67", "#f73600", "#00e3ff"):
        assert colour in css
    assert "orbitron" in css and "roboto" in css and "hk modular" in css


def test_no_smooth_scroll_on_page_load(client):
    css = client.get("/static/style.css").get_data(as_text=True)
    assert "scroll-behavior: smooth" not in css


def test_thumbnails_use_theme_classes(client):
    page = client.get("/").get_data(as_text=True)
    assert 'class="minimap-room is-start"' in page and 'class="minimap-room is-boss"' in page
