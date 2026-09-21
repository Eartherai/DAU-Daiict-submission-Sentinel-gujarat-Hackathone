# UI — WHAT THE SCREENSHOT WAS ACTUALLY SHOWING

Three real defects, found by measuring the running app rather than restyling.

## 1. The video filled only part of each tile

The tile `.frame` is a **flex row** holding two children: the JPEG preview
`<img>` and, once WHEP negotiates, the `<video>`. As flex siblings they shared
the row:

```
frame  480px
  img    459px at x=-84   <- overflowing past the left edge
  video  300px at x=375   <- squeezed into what was left
```

`width: 100%` cannot win that argument, because flex shrink is applied
afterwards. This is exactly the half-filled tiles with dead space beside them.

**Fix.** Take the video out of flow and let it cover the frame, and hide the
still whenever a video exists — declaratively, with `:has(video)`, so it cannot
desynchronise from the media lifecycle the way a JS show/hide can.

Measured after: `frame 480x258`, `video 480x258`, still `display: none`.

## 2. The status line said "0 live sessions" while eight tiles played

`liveProgress()` counted `.frame[data-state="live"]`. That attribute is set by
the media lifecycle and does not always reach `live` on the direct plane, so
the wall reported zero while video was visibly playing. A status line that
disagrees with the screen is worse than no status line.

Now counted from what the browser is actually decoding
(`readyState >= 2 && videoWidth > 0`). Reads **8 live sessions**, matching the
eight tiles on screen.

## 3. The control strip collapsed into a column below ~1400px

`.live-head` is a nowrap row: status on the left, controls on the right. At
1920 that holds. At 1024 the status text takes the width it wants and starves
the control strip to **108px wide x 641px tall** — its buttons stack into a
column down the side and the wall is squeezed to an 86px sliver underneath.
That is the broken header in the screenshot.

**Fix.** Let the head wrap, give the control strip its own full-width row, and
cap the status text so it can never starve a sibling again. The masthead is
also fitted to the 34px command band; it was 61px and overflowing to `top:-14`,
which is why the brand text looked doubled.

Measured at 1024x768 after: grid **77.1%** of the viewport, video **74.4%**,
tiles filling their frames, status truthful.

## A regression I introduced and backed out

My first attempt set `flex-wrap: nowrap` on `.live-head` to stop the status
wrapping. That turned the entire control strip into a vertical column and
pushed the wall off-screen — the same failure I was trying to fix, caused from
the other direction. Reverted, and replaced with wrapping plus a text cap.

## Not a first-principles redesign

This round fixed what was broken. A genuine ground-up redesign still wants:

- the `cameraId -> TileController` model (§41), so tiles own their media and
  nothing queries the whole DOM per update
- a repaint that preserves `<video>` nodes across wall-size changes (§40)
- the alert rail (§51), target inspector (§52) and map panel (§53)
- keyboard navigation and focus order (§63)
- the regression matrix across 12/16/25/30 x Grid/Focus/Two-up/Dense/Tab (§65)

The black tiles that remain are not layout: they are WHEP sessions the grid has
not served, which is the concurrency budget described in
`CLAUDE_LIVE_ANPR.md`, not a CSS problem.
