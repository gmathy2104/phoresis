# 3D Terrain View - Implementation Notes

## Overview

The 3D Terrain View is an alternative visualization mode for the electropherogram panel in the densitometry module. It renders the lane intensity profile as a Three.js terrain mesh with color-coded peaks by band type.

## Architecture

**Class**: `Chromatogram3DRenderer` (inline in `densitometry.html`)

**Dependencies**: Three.js (r160+), OrbitControls

**Location**: `gel_analyzer/templates/gel_analyzer/analyses/densitometry.html` (lines ~564-1020)

## Key Design Decisions

### On-Demand Rendering (Performance Fix)

The renderer uses **on-demand rendering** instead of a continuous 60fps `requestAnimationFrame` loop to avoid burning the GPU:

- `_renderFrame()`: Renders a single frame (no loop)
- `_startAnimating()`: Called on OrbitControls `start` event — begins animation loop
- `_stopAnimatingAfterDamping()`: Called on OrbitControls `end` event — continues for 600ms (for damping), then stops
- `_animateLoop()`: Only runs while `_isAnimating` is true

Single frames are also rendered after:
- `render()` (new terrain data loaded)
- `highlightBand()` (band selection)
- `onResize()` (container resize)

### Vertex Coloring: Closest-Center-Wins

When multiple bands' ±3σ Gaussian ranges overlap, the vertex color is determined by **which band center is closest** to the vertex position:

```javascript
_getVertexColor(yPos) {
    let bestBand = null;
    let bestDist = Infinity;
    for (const band of this.bands) {
        const sigma = band.densitometry?.peak_sigma || band.densitometry?.sigma || 15;
        const center = band.densitometry?.peak_center_y || band.position_y || band.y;
        if (!center) continue;
        const dist = Math.abs(yPos - center);
        if (dist <= sigma * 3 && dist < bestDist) {
            bestDist = dist;
            bestBand = band;
        }
    }
    if (bestBand) {
        const type = bestBand.band_type || 'OTHER';
        return this.bandColors[type] || this.bandColors.DEFAULT;
    }
    return this.bandColors.DEFAULT;
}
```

**Why**: The POI band often has a large sigma (e.g. 13.05 → 78px range) that overlaps neighboring OTHER bands. First-match-wins iteration (the original approach) would color those neighbors green. Closest-center-wins ensures each peak is colored by its own band type.

### Band Type Colors

| Band Type | Color | Hex |
|-----------|-------|-----|
| POI | Green | `#22C55E` |
| OTHER | Gray | `#9E9E9E` |
| MW_REFERENCE | Amber | `#FFC107` |
| Baseline (DEFAULT) | Blue | `#2196F3` |

Baseline = vertices not within ±3σ of any band center.

### Legend Overlay

An HTML overlay (`.dm-3d-legend`) is positioned absolutely within the 3D container. Uses `pointer-events: none` to not interfere with OrbitControls. Created in `_createLegend()`, cleaned up in `dispose()`.

CSS styles are in `densitometry.css` under the `/* 3D Legend */` section.

## 2D vs 3D Alignment

Both views use the **same profile data** (`profileData.y_positions` and `profileData.intensities`). Peak positions and heights match.

**Color boundary differences** (expected):
- **2D chart**: Each band is rendered as a separate SVG `<area>` element spanning its full ±3σ range. Overlapping areas are resolved by SVG z-order.
- **3D terrain**: Each vertex gets one color via closest-center-wins. No overlap ambiguity.

This means the green (POI) region may appear slightly different in width between the two views — this is correct behavior, not a bug.

### Example: Lane 84 (Lane 1)

POI band: center=496.1, σ=13.05, range=[456.9 – 535.3]

Three OTHER bands have centers inside POI's ±3σ range:
- OTHER center=463.5 (32.6px from POI) → gray in 3D
- OTHER center=500.0 (3.9px from POI) → gray in 3D
- OTHER center=530.0 (33.9px from POI) → gray in 3D

All correctly colored gray because their own centers are closer than the POI center.

## Terrain Construction

```
Scene dimensions: 20 units width × 6 units depth × max 8 units height
Depth segments: 30 (Gaussian falloff across Z for mountain cross-section)
Downsampling: >500 data points reduced to ~500 for performance
Shader: Custom ShaderMaterial with contour lines (white, 8 intervals)
```

The terrain maps profile Y positions to the X axis and intensity values to the Y (height) axis. The Z axis provides depth via Gaussian falloff to create the mountain appearance.

## Bug History

1. **Wrong property name** (fixed): `gaussian_sigma` → `peak_sigma` (API field name mismatch caused all sigmas to fall back to hardcoded 15)
2. **Adjacent peaks green** (fixed): First-match-wins iteration → closest-center-wins iteration
3. **GPU fan spinning** (fixed): Continuous 60fps render loop → on-demand rendering with damping support
