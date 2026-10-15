"""Tests for the motion layer (step 19): every page loads it, and each page picks its background."""
import pytest


@pytest.mark.parametrize("url, background", [
    ("/", "constellation"), ("/about", "constellation"), ("/maps/1", "constellation"),
    ("/maps/1/designer", "grid"), ("/sandbox", "grid"), ("/maps/1/edit", "grid"),
    ("/maps/1/play", "warp"), ("/sandbox/play", "warp"),
])
def test_page_picks_its_background(client, url, background):
    page = client.get(url).get_data(as_text=True)
    assert f'data-bg="{background}"' in page
    assert 'id="base-bg-canvas"' in page and "motion.js" in page


def test_header_has_a_menu_button_for_small_screens(client):
    page = client.get("/").get_data(as_text=True)
    assert 'class="base-header-menu"' in page and 'aria-controls="base-header-nav"' in page
    assert 'id="base-header-nav"' in page


def test_motion_script_and_styles_are_served(client):
    js = client.get("/static/motion.js").get_data(as_text=True)
    css = client.get("/static/style.css").get_data(as_text=True)
    for name in ("drawConstellation", "drawGrid", "drawWarp", "IntersectionObserver", "prefers-reduced-motion"):
        assert name in js
    assert "is-leaving" in css and "is-leaving" in js and "prefers-reduced-motion" in css
    assert "@view-transition" not in css   # replaced by our own fade (see step 21)
