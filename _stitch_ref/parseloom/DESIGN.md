---
name: ParseLoom
colors:
  surface: '#121414'
  surface-dim: '#121414'
  surface-bright: '#383939'
  surface-container-lowest: '#0c0f0e'
  surface-container-low: '#1a1c1c'
  surface-container: '#1e2020'
  surface-container-high: '#282a2a'
  surface-container-highest: '#333535'
  on-surface: '#e2e2e2'
  on-surface-variant: '#c8c5cd'
  inverse-surface: '#e2e2e2'
  inverse-on-surface: '#2f3130'
  outline: '#929097'
  outline-variant: '#47464c'
  surface-tint: '#c6c4df'
  primary: '#c6c4df'
  on-primary: '#2f2e43'
  primary-container: '#1a1a2e'
  on-primary-container: '#83829b'
  inverse-primary: '#5d5c74'
  secondary: '#cebdff'
  on-secondary: '#381385'
  secondary-container: '#4f319c'
  on-secondary-container: '#bea8ff'
  tertiary: '#bfc6dd'
  on-tertiary: '#293042'
  tertiary-container: '#141c2d'
  on-tertiary-container: '#7d8499'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e2e0fc'
  primary-fixed-dim: '#c6c4df'
  on-primary-fixed: '#1a1a2e'
  on-primary-fixed-variant: '#45455b'
  secondary-fixed: '#e8ddff'
  secondary-fixed-dim: '#cebdff'
  on-secondary-fixed: '#21005e'
  on-secondary-fixed-variant: '#4f319c'
  tertiary-fixed: '#dbe2fa'
  tertiary-fixed-dim: '#bfc6dd'
  on-tertiary-fixed: '#141b2c'
  on-tertiary-fixed-variant: '#3f4759'
  background: '#121414'
  on-background: '#e2e2e2'
  surface-variant: '#333535'
typography:
  headline-xl:
    fontFamily: Geist
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Geist
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-md:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 8px
  gutter: 16px
  margin-mobile: 20px
  margin-desktop: 40px
  grid-gap: 24px
---

## Brand & Style

The design system is engineered for a premium AI-driven experience, targeting HR tech and high-end recruitment sectors. The brand personality is authoritative yet visionary, combining the precision of data science with a sophisticated aesthetic. 

The visual style leans heavily into **Modern Glassmorphism** and **Bento-grid** layouts. It utilizes high-contrast interfaces where dark, deep surfaces are punctuated by ethereal glows and sharp typography. The emotional response should be one of "effortless intelligence"—where complex AI processing feels calm, curated, and high-value. Subtle staggered entrances and interactive soft-glow borders create a sense of life and responsiveness within the static grid.

## Colors

The palette is anchored in a sophisticated dark mode. The **Deep Navy (#1a1a2e)** serves as the primary structural color, providing a sense of depth and stability. **Muted Purple (#a78bfa)** is used as the primary action accent, signaling AI-enhanced features and primary interactions. **Soft Periwinkle (#e0e7ff)** acts as a secondary accent for highlighting data visualizations and secondary actions.

**Neutral Cream (#f5f5f4)** is reserved exclusively for high-contrast typography and critical details, ensuring maximum legibility against the dark backgrounds. Backgrounds should use a gradient transition from Deep Navy to a slightly lighter Slate to provide visual volume.

## Typography

The typography system utilizes **Geist** for its technical precision and modern character. It is optimized for high-density data and editorial-style layouts. For technical data points and AI-generated metadata, **JetBrains Mono** is introduced to provide a "coded" feel that reinforces the AI shortlisting narrative.

Headlines should utilize tighter letter spacing for a more impactful, "display" feel. Body text maintains generous line height to ensure readability within the bento-style containers. Use uppercase styling for labels and tags to create a distinct visual hierarchy against body copy.

## Layout & Spacing

This design system employs a **Bento-grid layout** with an emphasis on asymmetric card sizing. The structure is based on a 12-column fluid grid for desktop and a single-column stack for mobile. 

Spacing is rhythmic, using a base-8 unit. Bento cards should utilize a `24px` gap to allow the background glows and glassmorphism effects enough breathing room to be visible. On mobile, margins tighten to `20px`, and cards transition into a vertical stream, maintaining the same gap to preserve the "tiled" aesthetic. Elements within cards should follow a `16px` or `24px` padding rule depending on the card's visual weight.

## Elevation & Depth

Depth is achieved through **Glassmorphism** and **Soft Glow Borders** rather than traditional shadows. 
- **Surfaces:** Cards use a semi-transparent fill (`rgba(30, 41, 59, 0.7)`) with a `backdrop-filter: blur(12px)`.
- **Borders:** High-priority elements use a 1px border with a subtle linear gradient (from #a78bfa at 30% opacity to transparent).
- **Glows:** Active states or "AI-processing" states utilize a secondary glow effect—an outer shadow with a large spread and very low opacity using the accent color.
- **Layers:** Floating elements like tooltips or modals should have a higher blur value and a slightly lighter surface tint to denote physical elevation above the bento grid.

## Shapes

The design system uses a **Rounded** shape language to soften the technical nature of the AI tool. Standard bento cards and primary UI elements use a `0.5rem` (8px) radius. Larger container components or featured cards use `1rem` (16px) or `1.5rem` (24px) to create a clear visual distinction between the "shell" of the application and its contents. Buttons and input fields should remain consistent at the base `0.5rem` radius to maintain a professional, structured feel.

## Components

- **Buttons:** Primary buttons use a solid #a78bfa fill with dark navy text. Secondary buttons use a glass background with a periwinkle border. Apply a subtle "shimmer" animation on hover.
- **Bento Cards:** The foundational component. Cards must support varying aspect ratios. Each card should have a 1px inner border and a very subtle radial gradient highlight in the top-left corner.
- **Chips/Badges:** Use JetBrains Mono for the text. Use low-opacity fills of the accent colors (10-15%) with a high-opacity border of the same hue.
- **Input Fields:** Minimalist design with a bottom-only border that glows (Lavender) when focused. Placeholders should be in a muted slate.
- **Lists:** Candidate lists within cards should use zebra-striping with ultra-low opacity (2%) and hover states that trigger a slight scale-up effect (1.02x).
- **Interactive States:** Use "staggered entrances" for cards when a page loads. Transitions should be smooth (0.4s ease-out) to mimic the fluidity of modern web frameworks like Aceternity.