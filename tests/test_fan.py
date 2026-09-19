"""The fan type: a central path plus nested uncertainty intervals.

A fan is one line and N fills, and each fill is between TWO curves. That is the
whole idea, and most of what is worth pinning follows from it: the fills must
not stack, the author's ordering must not matter, and an interval that does not
contain the one inside it is a data mistake no reader could see.
"""
from __future__ import annotations

import matplotlib
import pytest

matplotlib.use("Agg")

from econcharts.render import render, RenderError        # noqa: E402
from econcharts.spec import Spec, SpecError
from econcharts.theme import load_theme                  # noqa: E402
import matplotlib.colors as mcolors                      # noqa: E402
import numpy as np                                       # noqa: E402              # noqa: E402

_P = ["2024Q1", "2024Q2", "2024Q3", "2024Q4"]


def _fan(intervals, central=(3.0, 3.0, 3.0, 3.0)):
    return Spec(period=f"{_P[0]}:{_P[-1]}", series=[{
        "name": "I", "type": "fan", "data": dict(zip(_P, central)),
        "intervals": intervals}])


def _iv(conf, lo, hi):
    return {"conf": conf, "lo": dict(zip(_P, [lo] * 4)), "hi": dict(zip(_P, [hi] * 4))}


def _fill_heights(fig):
    """Vertical extent of each fill, in the order they were drawn."""
    out = []
    for coll in fig.axes[0].collections:
        ys = [v[1] for path in coll.get_paths() for v in path.vertices]
        out.append(max(ys) - min(ys))
    return out


def test_a_fan_is_one_line_and_a_ring_per_interval():
    """Bands are drawn as RINGS, so the count is not one artist per interval:
    every band but the innermost contributes two fills, above and below the next
    band in, and the innermost is a single solid one. 2 intervals -> 3 fills."""
    fig = render(_fan([_iv(90, 2.0, 4.0), _iv(60, 2.5, 3.5)]), size="slides_half")
    assert len(fig.axes[0].collections) == 3, "two rings for the outer band, one solid inner"
    # one Line2D, PCHIP-smoothed like any other line series
    assert len(fig.axes[0].lines) == 1, "the central path is still an ordinary line"


def test_intervals_are_drawn_widest_first_whatever_the_spec_order():
    """The author declares confidences, not draw order. Given inside-out, the
    fills must still come out outside-in or the wider one hides the rest."""
    fig = render(_fan([_iv(30, 2.9, 3.1), _iv(90, 2.0, 4.0), _iv(60, 2.5, 3.5)]),
                 size="slides_half")
    heights = _fill_heights(fig)
    assert heights == sorted(heights, reverse=True),         f"fills drawn inner-first and would be hidden: {heights}"


def test_an_interval_that_does_not_contain_the_next_is_refused():
    """A 90% band narrower than the 60% one is a mispointed column. Nothing on
    the chart would show it — the narrower fill simply vanishes underneath."""
    with pytest.raises(RenderError, match="does not contain"):
        render(_fan([_iv(90, 2.9, 3.1), _iv(60, 2.0, 4.0)]), size="slides_half")


def test_lo_above_hi_is_refused():
    with pytest.raises(RenderError, match="swapped"):
        render(_fan([_iv(90, 4.0, 2.0)]), size="slides_half")


def test_a_fan_needs_intervals_and_intervals_need_a_fan():
    with pytest.raises(SpecError, match="at least one entry in `intervals`"):
        Spec.from_dict({"series": [{"name": "I", "type": "fan", "data": [1, 2]}]})
    with pytest.raises(SpecError, match="only for fan series"):
        Spec.from_dict({"series": [{"name": "I", "type": "line", "data": [1, 2],
                                    "intervals": [_iv(90, 1, 3)]}]})


def test_conf_is_a_percentage_not_a_fraction():
    """0.9 is a legal 0.9% interval and is almost certainly meant as 90%, so it
    is refused with a message that says which."""
    with pytest.raises(SpecError, match="percentage, not a fraction"):
        Spec.from_dict({"series": [{"name": "I", "type": "fan", "data": [1, 2],
                                    "intervals": [_iv(0.9, 1, 3)]}]})


def test_the_fan_starts_where_its_intervals_do():
    """No forecast-origin concept: leading nulls leave the fills empty over
    history, which is the whole mechanism."""
    spec = Spec(period=f"{_P[0]}:{_P[-1]}", series=[{
        "name": "I", "type": "fan", "data": dict(zip(_P, [3.0] * 4)),
        "intervals": [{"conf": 90,
                       "lo": dict(zip(_P, [None, None, 2.0, 1.5])),
                       "hi": dict(zip(_P, [None, None, 4.0, 4.5]))}]}])
    fig = render(spec, size="slides_half")
    ax = fig.axes[0]
    fill_x = [v[0] for p in ax.collections[0].get_paths() for v in p.vertices]
    central_x = ax.lines[0].get_xdata()
    assert min(fill_x) > min(central_x),         "the fill must not cover the periods whose bounds are null"
    assert max(fill_x) == pytest.approx(max(central_x), rel=1e-6),         "but it must reach the end of the horizon"

def test_the_fills_can_take_a_colour_of_their_own():
    """A fan reads better when the bands recede from the central path rather
    than restating it, so `shade` picks a theme colour NAME for the fills."""
    from econcharts.theme import load_theme
    theme = load_theme("bbva")
    spec = _fan([_iv(90, 2.0, 4.0)])
    spec.series[0].shade = "lightblue"
    fig = render(spec, size="slides_half")
    fill = fig.axes[0].collections[0].get_facecolor()[0][:3]
    want = matplotlib.colors.to_rgb(theme.resolve_color("lightblue"))
    assert fill == pytest.approx(want, abs=1e-6), "the fill ignored `shade`"
    line = matplotlib.colors.to_rgb(fig.axes[0].lines[0].get_color())
    assert line != pytest.approx(want, abs=1e-6), "the central path must keep its own colour"


def test_shade_is_refused_on_anything_but_a_fan():
    with pytest.raises(SpecError, match="only for fan series"):
        Spec.from_dict({"series": [{"name": "I", "type": "line", "data": [1, 2],
                                    "shade": "lightblue"}]})


def test_the_fan_opens_from_the_last_point_without_an_interval():
    """Otherwise the bands begin at full width and the vertical edge reads as a
    step in the data rather than the start of a projection."""
    central = (3.0, 3.0, 3.0, 3.0)
    spec = Spec(period=f"{_P[0]}:{_P[-1]}", series=[{
        "name": "I", "type": "fan", "data": dict(zip(_P, central)),
        "intervals": [{"conf": 90,
                       "lo": dict(zip(_P, [None, None, 2.0, 1.5])),
                       "hi": dict(zip(_P, [None, None, 4.0, 4.5]))}]}])
    fig = render(spec, size="slides_half")
    verts = [v for p in fig.axes[0].collections[0].get_paths() for v in p.vertices]
    x0 = min(v[0] for v in verts)
    at_x0 = [v[1] for v in verts if v[0] == pytest.approx(x0, abs=1e-9)]
    assert max(at_x0) - min(at_x0) == pytest.approx(0.0, abs=1e-9), (
        f"the fan should open from a point on the central path, but starts "
        f"{max(at_x0) - min(at_x0):.3f} wide")


def _composite(fig):
    """Each fill composited over white, in draw order — what the eye actually sees.

    Independent per fill, NOT cumulative: bands are drawn as non-overlapping rings,
    so nothing sits on top of anything else and each one's colour is its own alpha
    over the page. This used to accumulate, which was right while the fills were
    nested and compounding and became wrong the moment they stopped.
    """
    import numpy as np
    out = []
    for coll in fig.axes[0].collections:
        rgba = coll.get_facecolor()[0]
        a = coll.get_alpha() if coll.get_alpha() is not None else rgba[3]
        over = np.ones(3) * (1 - a) + np.array(rgba[:3]) * a
        out.append(tuple(round(v * 255) for v in over))
    return out


def test_a_fan_spans_soft_to_strong_whatever_the_interval_count():
    """The ladder is the shading WITHIN one fan, so the two ends are fixed and
    only the spacing changes: two intervals and five both run soft -> strong, and
    a reader is not shown a different scale because the author declared a
    different number of bands."""
    from econcharts import charttypes, theme as theme_mod
    t = theme_mod.load_theme("bbva")
    soft = t.val("fan.strengths", {})["soft"]
    strong = t.val("fan.strengths", {})["strong"]
    for n in (2, 3, 4, 5):
        ramp = charttypes._fan_ramp(t, None, n)
        assert len(ramp) == n
        assert ramp[0] == pytest.approx(soft)
        assert ramp[-1] == pytest.approx(strong)
        assert ramp == sorted(ramp), "a fan must darken inward"


def test_a_lone_interval_has_no_ramp_so_shade_strength_decides():
    """One band cannot span a ladder, so it is the single case the spec still
    picks. This is what `shade_strength` is FOR once the ramp is automatic."""
    spec = _fan([_iv(90, 2.0, 4.0)])
    spec.series[0].shade = "lightblue"
    spec.series[0].shade_strength = "soft"
    soft = _composite(render(spec, size="slides_half"))[0]
    spec.series[0].shade_strength = "strong"
    strong = _composite(render(spec, size="slides_half"))[0]
    assert strong[0] < soft[0], f"strong must darken a lone band: {strong} vs {soft}"


def test_shade_strength_is_a_selection_from_the_theme():
    spec = _fan([_iv(90, 2.0, 4.0)])
    spec.series[0].shade = "lightblue"
    default = _composite(render(spec, size="slides_half"))[0]
    spec.series[0].shade_strength = "strong"
    strong = _composite(render(spec, size="slides_half"))[0]
    assert strong[0] < default[0], f"`strong` must darken the fill: {strong} vs {default}"


def test_an_unknown_strength_names_the_ones_that_exist():
    spec = _fan([_iv(90, 2.0, 4.0)])
    spec.series[0].shade_strength = "extremo"
    with pytest.raises(RenderError, match="soft"):
        render(spec, size="slides_half")


def test_shade_strength_is_refused_on_anything_but_a_fan():
    with pytest.raises(SpecError, match="only for fan series"):
        Spec.from_dict({"series": [{"name": "I", "type": "line", "data": [1, 2],
                                    "shade_strength": "strong"}]})


# --- the visibility of `soft` ------------------------------------------------
#
# `soft` is the faintest thing a chart ever draws, so it is the one strength set
# by measurement rather than taste. These pin that measurement. The golden image
# cannot: an alpha change from 0.18 to 0.30 -- two thirds darker -- scores RMS
# 5.38 against test_image_fan's tolerance of 20, so it sails through. That test
# guards layout and draw order; this one guards the shade.

def _srgb_to_lab(rgb):
    c = np.array(rgb, dtype=float) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805],
                  [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]])
    xyz = (m @ c) / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return 116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])


def _delta_e_2000(lab1, lab2):
    """CIEDE2000. Validated against the Sharma, Wu & Dalal (2005) blue-region
    pairs, which exist because CIE76 overstates blue differences ~2.7x -- and
    every shade colour in this theme is blue, so CIE76 is not an option here."""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    cb = (C1 + C2) / 2
    g = 0.5 * (1 - np.sqrt(cb ** 7 / (cb ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)

    def _h(ap, b):
        if ap == 0 and b == 0:
            return 0.0
        h = np.degrees(np.arctan2(b, ap))
        return h + 360 if h < 0 else h

    h1p, h2p = _h(a1p, b1), _h(a2p, b2)
    dLp, dCp = L2 - L1, C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp / 2))
    Lbp, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbp = (h1p + h2p + 360) / 2
    else:
        hbp = (h1p + h2p - 360) / 2
    T = (1 - 0.17 * np.cos(np.radians(hbp - 30)) + 0.24 * np.cos(np.radians(2 * hbp))
         + 0.32 * np.cos(np.radians(3 * hbp + 6)) - 0.20 * np.cos(np.radians(4 * hbp - 63)))
    dth = 30 * np.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cbp ** 7 / (Cbp ** 7 + 25.0 ** 7))
    SL = 1 + (0.015 * (Lbp - 50) ** 2) / np.sqrt(20 + (Lbp - 50) ** 2)
    SC = 1 + 0.045 * Cbp
    SH = 1 + 0.015 * Cbp * T
    RT = -np.sin(np.radians(2 * dth)) * Rc
    return float(np.sqrt((dLp / SL) ** 2 + (dCp / SC) ** 2 + (dHp / SH) ** 2
                         + RT * (dCp / SC) * (dHp / SH)))


def _over_white(hex_color, alpha):
    r, g, b = (255 * c for c in mcolors.to_rgb(hex_color))
    return tuple(255 - (255 - c) * alpha for c in (r, g, b))


def _delta_e_from_page(hex_color, alpha):
    """How far one fill at `alpha` sits from the white it lands on."""
    return _delta_e_2000(_srgb_to_lab(_over_white(hex_color, alpha)),
                         _srgb_to_lab((255, 255, 255)))


CLEARLY_VISIBLE = 5.0   # the standard interpretation scale's threshold


def test_delta_e_2000_matches_the_reference_pairs():
    """Guards the yardstick before anything is measured with it. These are the
    Sharma et al. pairs; CIE76 would score the third 9.18 instead of 3.44."""
    cases = [((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
             ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
             ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
             ((50.0, -1.3802, -84.2814), (50.0, 0.0, -82.7485), 1.0000)]
    for lab1, lab2, want in cases:
        assert _delta_e_2000(lab1, lab2) == pytest.approx(want, abs=1e-4)


def test_soft_is_clearly_visible_in_the_shade_colour_we_ship():
    """`soft` must clear the 'clearly visible' threshold, not merely be
    perceptible. At the old 0.12 lightblue reached only 4.5 and fell short."""
    t = load_theme("bbva")
    soft = t.val("fan.strengths", {})["soft"]
    got = _delta_e_from_page(t.resolve_color("lightblue"), soft)
    assert got >= CLEARLY_VISIBLE, f"lightblue at soft={soft} is only dE00 {got:.2f}"


def test_medium_is_the_midpoint_of_the_ladder():
    """Not a free third value. The ramp interpolates soft -> strong, so at three
    intervals it lands on the middle rung by construction; if `medium` were set
    anywhere else the name would describe a shade no fan ever draws."""
    s = load_theme("bbva").val("fan.strengths", {})
    assert s["medium"] == pytest.approx((s["soft"] + s["strong"]) / 2, abs=1e-9)


def test_each_ring_composites_at_exactly_its_named_alpha():
    """The point of drawing rings. A band's shade is the theme's rung and nothing
    else — not a function of how many intervals sit inside it. Under the previous
    nested fills the innermost of three reached 0.96 effective against a named
    0.65, so the ladder a reader saw was never the ladder the theme wrote down.

    Two intervals, so the fills are (outer ring above, outer ring below, inner
    solid) and the two outer ones must be the SAME colour as each other."""
    from econcharts import charttypes, theme as theme_mod
    t = theme_mod.load_theme("bbva")
    spec = _fan([_iv(90, 2.0, 4.0), _iv(60, 2.5, 3.5)])
    spec.series[0].shade = "lightblue"
    seen = _composite(render(spec, size="slides_half"))
    assert len(seen) == 3
    assert seen[0] == seen[1], "the two halves of one ring must match"

    ink = np.array([255 * c for c in mcolors.to_rgb(t.resolve_color("lightblue"))])
    white = np.array([255.0, 255.0, 255.0])
    for band, alpha in ((seen[0], 0.25), (seen[2], 0.65)):
        want = white + (ink - white) * alpha
        assert np.allclose(band, want, atol=1.5), (
            f"{band} is not alpha {alpha} over white ({want})")
