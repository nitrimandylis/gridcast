# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** gridcast
**Generated:** 2026-09-02 (ui-ux-pro-max search, then reconciled with the locked token sheet)
**Category:** Analytics / scorecard app, static HTML + CSS, no build step
**Design Dials:** Density 8/10 (Dense / Dashboard)

---

## The one rule that outranks this file

`site/tokens.css` is **locked**. Every colour, font and radius comes through a
name in that file: warm near-black paper, cream ink (never white), the two-red
accent pair, Archivo split by width (wdth 62 caps for display, 100 for body),
Geist Mono for every machine-written number and label. The catalog palette and
font pairing this search returned (blue/amber, Fira) were **rejected**; only
the style layer below was kept. Do not reintroduce them.

## Style layer (what the search contributed)

**Style:** Data-Dense Dashboard

**Keywords:** data tables, KPI stat rows, minimal padding, grid layout,
space-efficient, maximum data visibility

**Key effects:** row highlighting on hover, hover tooltips on matrix cells,
smooth filter/toggle transitions, quiet loading states

**Landing pattern:** dropped on purpose. gridcast is an app, not a funnel.
No hero-video sections, no CTA strategy, no logo walls.

## Density mapping (dial 8/10 onto the locked space ladder)

The dense 2-32px scale maps onto tokens that already exist. Components use
the small end of the ladder; the big end (`--space-4xl`, `--space-5xl`,
`--void`) belongs to page rhythm on the home page only, never inside a
component.

| Dense role | Token | Value |
|------------|-------|-------|
| Tight gaps | `--space-3xs` | 2px |
| Icon/inline gaps | `--space-2xs` | 4px |
| Cell padding, standard | `--space-xs` | 8px |
| Row padding | `--space-sm` | 12px |
| Card padding | `--space-md` / `--space-lg` | 16 / 24px |
| Between components | `--space-xl` | 36px |
| Section margins | `--space-2xl` | 48px |

Shadows: none. This theme separates surfaces with the paper ladder
(`--color-paper` through `--color-paper-4`) and hairline rules, not shadows.

## Component conventions

- Cards: `--color-paper-3` on `--color-paper`, 1px `--color-rule` border,
  `--radius-card`, padding `--space-md`/`--space-lg`. Hover raises to
  `--color-paper-4`, never translates or scales.
- Tables/ledger: mono (`--font-data`) numerals, `--space-xs`/`--space-sm` cell
  padding, hairline row rules, full-row hover highlight, sticky first column
  where rows are wide.
- Labels: `--text-xs` mono uppercase, `--color-muted`.
- Buttons: pill radius, accent fill uses `--color-accent` with
  `--color-accent-ink`; accent text uses `--color-accent-text`. Never swap
  the two reds.
- Focus: visible ring in `--color-focus` on every interactive element.

## Anti-patterns (do NOT use)

- Ornate design, decorative gradients, glassmorphism
- Shadows for depth (paper ladder + rules instead)
- Emojis as icons (inline SVG only)
- Layout-shifting hovers (scale/translate that moves neighbours)
- Instant state changes (transitions 150-300ms, `--dur-*` tokens)
- Invisible focus states
- Raw hex in components (tokens only)

## Pre-delivery checklist

- [ ] All colour and type through `tokens.css` names, zero raw hex in style.css components
- [ ] Text contrast 4.5:1 minimum (`--color-dim` is large-type only)
- [ ] `cursor: pointer` + visible focus on all interactive elements
- [ ] Hover states with 150-300ms transitions
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive at 375 / 768 / 1024 / 1440, no horizontal scroll except intentional matrix scroll wrappers
- [ ] No content hidden behind the sticky nav
