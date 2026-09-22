"""The own-feed demonstration has a hard length limit.

Submission item 3 allows a maximum of 2-3 minutes. The full platform tour runs
twenty, which is the wrong artifact for that requirement: a reviewer with a
three-minute budget should not have to find the relevant ninety seconds inside
it. These tests pin the limit and the four things the recording must show.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "demo"))

import record_own_feed as own


def test_the_limit_matches_the_challenge():
    assert own.HARD_LIMIT_S == 180.0, "the challenge allows 2-3 minutes"


def test_the_planned_beats_fit_inside_the_limit():
    """Planned dwell plus a generous allowance for actions must still fit."""
    class _Page:
        def __getattr__(self, _):
            return lambda *a, **k: None

    beats = own.build(_Page(), "GJ18X6705")
    dwell = sum(b.dwell_s for b in beats)
    # Each beat's action costs real time too; the recorded take measured 2m32s
    # against 116s of dwell, so roughly 40s of headroom is the honest margin.
    assert dwell < own.HARD_LIMIT_S, dwell
    assert own.HARD_LIMIT_S - dwell >= 40, (
        f"only {own.HARD_LIMIT_S - dwell:.0f}s of headroom for the actions; "
        "a recording that runs over gets cut off, not shortened")


def test_it_shows_the_four_things_the_challenge_asks_for():
    class _Page:
        def __getattr__(self, _):
            return lambda *a, **k: None

    titles = " ".join(b.title.lower() for b in own.build(_Page(), "X"))
    assert "onboarding" in titles           # 1. onboarding
    assert "detection" in titles            # 2. AI detection and analytics
    assert "watchlist" in titles            # 3. watchlist correlation
    assert "alert" in titles                # 4. the alert it fired


def test_onboarding_is_driven_through_the_portal_not_a_background_fetch():
    """The demo must onboard for real, and be seen to.

    This asserted `method: 'POST'`, which pinned the old approach: the
    recorder called /registry/cameras/import from page.evaluate. The
    onboarding happened and the recording showed nothing — a page reload and a
    new row, with no visible cause. Model 1's named deliverable is a
    *demonstration* of manual and bulk onboarding, and an invisible fetch
    demonstrates nothing.

    Worse, it hid a failure. The recording signed in as SUPERVISOR, which does
    not hold `admin:write`, so the fetch returned 403 and nothing said so.
    Driving the real form is what surfaced it: the panel printed
    `PERMISSION_DENIED` into the frame.
    """
    src = (ROOT / "tools" / "demo" / "record_own_feed.py").read_text()
    assert "#ob-camera-id" in src, "the recorder does not fill the onboarding form"
    assert "#btn-ob-submit" in src, "the recorder never commits the onboarding"
    assert "#btn-ob-dry" in src, (
        "the recorder does not validate first, which is the step that shows "
        "the dry run writes nothing")
    # Check the code, not the prose: the docstring explains the old approach
    # by name, and an earlier version of this assertion flagged its own
    # explanation.
    body = src.split("def onboard()", 1)[1].split("def registry_gaps", 1)[0]
    body = body.split('"""', 2)[-1]          # drop the docstring
    assert "fetch(" not in body, (
        "onboarding is back to a background fetch the recording cannot show")


def test_the_recording_carries_a_token_that_can_actually_onboard():
    """One token cannot film both halves, and the platform is right about that.

    ADMIN holds no search permission and SUPERVISOR holds no admin:write,
    because running the estate and investigating people are different jobs.
    The film signs in as the administrator to onboard, then hands over.
    """
    src = (ROOT / "tools" / "demo" / "record_own_feed.py").read_text()
    assert "--admin-token-file" in src
    assert "admin:write" in src, (
        "nothing explains why a second token is needed, so the next person "
        "will remove it")
    # and it must warn rather than silently film a refusal
    assert "PERMISSION_DENIED" in src


def test_an_overlong_recording_is_refused_not_shipped():
    src = (ROOT / "tools" / "demo" / "record_own_feed.py").read_text()
    assert "HARD_LIMIT_S" in src
    assert "raise SystemExit" in src.split("if secs > HARD_LIMIT_S:", 1)[1][:300]
