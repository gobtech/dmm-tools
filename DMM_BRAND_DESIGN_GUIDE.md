# DMM (Dorado Music Marketing) - Complete Brand Design Guide

> Extracted from https://www.dmusicmarketing.com/ (Squarespace Henson/Tremont Template v7)
> Site ID: 590102829de4bb02e43309fd | Template ID: 56d9c12107eaa07660adbcad

---

## 1. COLOR PALETTE

### Primary Colors
| Role | Hex | RGB | Usage |
|------|-----|-----|-------|
| Primary Black | `#000000` | rgb(0,0,0) | Primary text, strong emphasis, hover states |
| Near-Black | `#0a0a0a` | rgb(10,10,10) | Default body text color |
| Dark Charcoal | `#111111` | rgb(17,17,17) | Deep backgrounds, heavy text |
| Charcoal | `#222222` | rgb(34,34,34) | Headings (blog titles), dark overlays |
| Dark Gray | `#3e3e3e` | rgb(62,62,62) | Buttons, secondary text, link hover |
| White | `#ffffff` | rgb(255,255,255) | Primary background, button text, light overlays |

### Secondary / Neutral Grays
| Role | Hex | RGB | Usage |
|------|-----|-----|-------|
| Medium-Dark Gray | `#444444` | rgb(68,68,68) | Borders, secondary elements |
| Gray | `#797979` | rgb(121,121,121) | Visited links, tertiary text |
| Medium Gray | `#8f8f8f` | rgb(143,143,143) | Pagination icons (stroke) |
| Muted Gray | `#919191` | rgb(145,145,145) | Blog item titles, secondary headings |
| Soft Gray | `#999999` | rgb(153,153,153) | Meta text, image captions, excerpts |
| Light Gray | `#b4b4b4` | rgb(180,180,180) | Decorative borders |
| Border Gray | `#cccccc` | rgb(204,204,204) | Form borders |
| Subtle Gray | `#d0d0d0` | rgb(208,208,208) | Light borders |
| Pale Gray | `#dddddd` | rgb(221,221,221) | Very light borders |
| Whisper Gray | `#e3e3e3` | rgb(227,227,227) | Hairline borders |
| Light Border | `#e4e4e4` | rgb(228,228,228) | Section dividers |
| Off-White | `#e9e9e9` | rgb(233,233,233) | Subtle backgrounds |
| Lighter Gray | `#ededed` | rgb(237,237,237) | Background accents |
| Soft White | `#eeeeee` | rgb(238,238,238) | Light backgrounds |
| Near-White | `#f6f6f6` | rgb(246,246,246) | Panel backgrounds, lightbox overlays |
| Form Background | `#fafafa` | rgb(250,250,250) | Input field backgrounds |

### Accent Colors
| Role | Hex | RGB | Usage |
|------|-----|-----|-------|
| Coral Red | `#f0523d` | rgb(240,82,61) | Warning/accent, interactive elements |
| Alert Red | `#ce2c30` | rgb(206,44,48) | Errors, alerts |
| Dark Red | `#ab2121` | rgb(171,33,33) | Pagination label color, strong emphasis |
| Error Red | `#cc3b3b` | rgb(204,59,59) | Form validation errors |
| Deep Red | `#bd0000` | rgb(189,0,0) | Dark error states |
| Soft Red | `#e99292` | rgb(233,146,146) | Light error backgrounds |
| Separator Red | `rgba(255,36,36,0.6)` | -- | Blog list separator lines |

### Primary Button | `#272727` | rgb(39,39,39) | Primary form button background |

### Overlay / Transparency Values
```
rgba(0,0,0,0.04)   - Subtle shadow border
rgba(0,0,0,0.05)   - Very light overlay
rgba(0,0,0,0.1)    - Light overlay
rgba(0,0,0,0.22)   - Modal shadow
rgba(0,0,0,0.24)   - Social icon shadow
rgba(0,0,0,0.4)    - Medium dark overlay (gradient midpoint)
rgba(0,0,0,0.7)    - Info overlay (gallery/index)
rgba(0,0,0,0.75)   - Dark radial gradient center
rgba(0,0,0,0.9)    - Very dark overlay (gradient base)
rgba(0,0,0,0.98)   - Near-opaque overlay

rgba(255,255,255,0.04) - Subtle white inset
rgba(255,255,255,0.15) - Light white overlay
rgba(255,255,255,0.7)  - Medium white overlay
rgba(255,255,255,0.9)  - Strong white overlay
rgba(255,255,255,0.96) - Near-opaque white
rgba(255,255,255,1.0)  - Solid white (arrows, indicators)

rgba(246,246,246,0.98) - Light panel overlay
rgba(128,128,128,0.15) - Gray transparency
rgba(153,153,153,0.5)  - Muted gray overlay
rgba(10,10,10,0.5)     - Blog link hover state
rgba(0,0,0,0.5)        - Read-more link hover
rgba(254,254,254,0.9)  - Off-white overlay
```

---

## 2. TYPOGRAPHY

### Font Stack Hierarchy

#### Primary Fonts
| Role | Font Family | Fallbacks |
|------|-----------|-----------|
| **Headings (Primary)** | `adobe-garamond-pro` | (serif, elegant) |
| **Headings (Secondary)** | `Raleway` | sans-serif |
| **Body / UI Text** | `"Helvetica Neue"` | `Helvetica, Arial, sans-serif` |
| **Meta / Captions** | `Roboto` | sans-serif |
| **Excerpts / Small Text** | `Lato` | sans-serif |
| **System UI** | `Clarkson` | `"Helvetica Neue", Helvetica, Arial, sans-serif` |
| **Icons** | `squarespace-ui-font` | -- |

#### Font Pairing Strategy
- **Headings**: `adobe-garamond-pro` (elegant serif) or `Raleway` (clean geometric sans-serif)
- **Body text**: `"Helvetica Neue"` system stack
- **UI/Meta labels**: `Roboto` (geometric, clean)
- **Detail text/excerpts**: `Lato` (humanist sans-serif)

### Font Sizes
| Token | Size | Usage |
|-------|------|-------|
| `xs` | `8px` | Pagination labels, smallest text |
| `sm` | `11px` | Meta labels, social buttons, button text |
| `base-sm` | `12px` | Blog meta, small body text, captions |
| `base-md` | `13px` | Secondary body text |
| `base` | `14px` | Default body text |
| `md` | `16px` | Larger body text |
| `lg` | `21px` | Blog list item titles |
| `xl` | `22px` | Blog list titles, subheadings |
| `2xl` | `26px` | Secondary headings |
| `3xl` | `31px` | Blog item titles (Raleway context) |
| `4xl` | `32px` | Major headings |
| `5xl` | `35px` | Large headings |
| `6xl` | `43px` | Hero/blog item titles (`adobe-garamond-pro`) |

### Font Weights
| Weight | Value | Usage |
|--------|-------|-------|
| Thin | `100` | Pagination labels (Roboto) |
| Regular | `400` | Body text, excerpts |
| Medium | `500` | Blog list item titles (Raleway), UI buttons |
| Semi-Bold | `600` | Social button labels, heading emphasis (Raleway) |
| Bold | `700` | Headings, blog item titles, meta labels, strong text |

### Line Heights
```
0.5em  - Compact/tight
1.0em  - Single line (headings)
1.3em  - Tight heading line-height
1.4em  - Comfortable heading line-height
1.5em  - Blog list item titles
1.6em  - Default body text / excerpts / pagination
1.65em - Comfortable reading
1.7em  - Spacious body text (excerpts)
22px   - Fixed line-height for specific elements
```

### Letter Spacing
```
-.01em  - Tight (large headings)
0em     - Normal
.01em   - Slight tracking
.05em   - Light tracking
.06em   - Moderate tracking
.1em    - Wide tracking (display text)
.5px    - Button text uppercase tracking
```

### Text Transform
- Buttons: `text-transform: uppercase`
- Navigation: Based on template settings
- Headings: `text-transform: none` (default)

### Heading Styles (Specific)

```css
/* Hero / Major Heading (adobe-garamond-pro) */
h1.major-heading {
  font-family: adobe-garamond-pro;
  font-size: 43px;
  font-weight: 400;
  line-height: 1.3em;
  letter-spacing: 0em;
  color: #222;
}

/* Section Heading (Raleway) */
h2.section-heading {
  font-family: Raleway;
  font-weight: 600;
  font-size: 31px;
  letter-spacing: -.01em;
  line-height: 1.3em;
  color: #919191;
}

/* Subsection Heading (Raleway) */
h3.subsection-heading {
  font-family: Raleway;
  font-weight: 500;
  font-size: 21px;
  line-height: 1.5em;
  color: #919191;
}

/* Meta Heading (Roboto) */
h4.meta-heading {
  font-family: Roboto;
  font-weight: 700;
  font-size: 11px;
  color: #0a0a0a;
}

/* Body Text (Helvetica Neue) */
p.body-text {
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-weight: 400;
  font-size: 14px;
  line-height: 1.6em;
  color: #0a0a0a;
}

/* Excerpt / Detail Text (Lato) */
p.excerpt-text {
  font-family: Lato;
  font-weight: 700;
  font-size: 12px;
  line-height: 1.7em;
  color: #999;
}
```

---

## 3. LOGO

### Logo Image
- **URL**: `https://images.squarespace-cdn.com/content/v1/590102829de4bb02e43309fd/1503502770341-VCOKSUOU944GCVSODOI7/DMM-final-logo-extended.png`
- **Format**: PNG with transparency
- **Alt text**: "dmusicmarketing"
- **Filename**: `DMM-final-logo-extended.png`
- **Logo Image ID**: `599da1b2f14aa14676343c4f`
- **Upload date**: August 23, 2017 (timestamp 1503502770341)

### Logo Description
The logo file is named "DMM-final-logo-extended" suggesting:
- **Abbreviation**: DMM (Dorado Music Marketing / D Music Marketing)
- **Format**: Extended/horizontal layout (wide format, not stacked)
- **Type**: Final approved version
- **Positioning**: Top-left corner of header (per Henson template default)

### Logo Usage
- Placed in the site header with a link to homepage (`/`)
- Available with `?format=original` suffix for full-resolution version
- Served via Squarespace CDN

---

## 4. DESIGN LANGUAGE

### Theme: Clean Minimalist with Professional Edge

#### Light vs Dark
- **Primary theme**: Light/White background with dark text
- **Overlay capability**: Semi-transparent dark overlays (`rgba(0,0,0,0.7)`) on index/gallery images
- **Not a dark theme** - uses white (#fff) as primary background, near-black (#0a0a0a) as primary text

#### Overall Mood
- **Minimalist**: Content-first approach, no decorative clutter
- **Professional**: Clean typography, restrained color palette
- **Sophisticated**: Use of elegant serif font (`adobe-garamond-pro`) alongside clean sans-serifs
- **Understated**: Letting content (music industry work) speak for itself

#### Design Era
- **Modern/Contemporary**: Sans-serif dominant UI, generous whitespace
- **Not overly trendy**: Avoids extreme gradients, neon, or heavy animations
- **Timeless**: Classic serif/sans-serif pairing, monochromatic palette

#### Design Density
- **Spacious**: Generous outer padding (level 3 of 10)
- **Breathing room**: 17px block padding, 34px spacing between elements
- **Full-bleed imagery**: Gallery/index images go edge-to-edge

---

## 5. UI PATTERNS

### Buttons

```css
/* Primary Button */
.button-primary {
  background: #3e3e3e;
  color: #fff;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-size: 11px;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: background 0.15s ease-out;
}
.button-primary:hover {
  background-color: #000;
}

/* Form Submit Button */
.button-submit {
  background: #272727;
  color: #fff;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-size: 11px;
  font-weight: 500;
}

/* Social Button (border style) */
.button-social {
  background: linear-gradient(#555, #222);
  width: 55px;
  padding: 1px 6px 0 2px;
  border-radius: 3px;
  box-shadow: inset rgba(255,255,255,0.04);
}
.button-social:hover {
  background: linear-gradient(#666, #222);
}

/* Social Icon (inline/circular) */
.social-icon-circle {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #999;
  transition: background 0.15s ease-out;
}
.social-icon-circle:hover {
  background: #222;
}

/* Read More Link */
.read-more-link {
  font-family: Lato;
  font-weight: 700;
  color: #000;
  text-decoration: none;
}
.read-more-link:hover {
  color: rgba(0,0,0,0.5);
}
```

### Border Radius Values
```
2px   - Form inputs
3px   - Small buttons, social button wrappers
4px   - Cards, panels
5px   - Dropdown lists
14px  - Rounded elements
50%   - Circular icons/avatars
```

### Spacing System

#### Block Spacing
```
Padding (vertical): 17px top, 17px bottom (per block)
Padding (horizontal): 17px left, 17px right (per column)
Row margins: -17px left, -17px right (offset)
```

#### Site Outer Padding
```
Level 3 (of configurable range) - moderate breathing room
Header outer padding: Level 1 (tighter)
```

#### Content Spacing
```
Blog list spacing: 34px between items
Gallery gutter: 12px between images
Blog separator margin-bottom: 34px
Header element spacing: 0px (tight)
Index menu description spacing: Level 3
Index menu padding: Level 1
```

### Navigation
```
Position: Right-aligned
Style: Standard (not hamburger on desktop)
Page title position: Center
Social icons: Right side (with nav)
Cart link: Hidden
Ajax loading: Enabled (smooth page transitions)
```

### Grid System
```
Blog list columns: 4
Product list items per row: 3
Related products items per row: 3
Column widths: 8.33%, 16.67%, 25%, 33.33%, 50%, 66.67%, 75%, 83.33%, 100%
Max-widths: 250px, 304px, 350px, 500px, 640px, 800px
```

### Shadows
```css
/* Modal / Popup Shadow */
box-shadow: 0 4px 33px rgba(0,0,0,0.22), 0 0 0 1px rgba(0,0,0,0.04);

/* Social Button Inset */
box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
```

### Links
```css
/* Default Link */
a {
  color: #0a0a0a;
  text-decoration: none;
  transition: color 0.15s ease-out;
}
a:hover {
  color: rgba(10,10,10,0.5);
}

/* Meta Link */
a.meta {
  color: #0a0a0a;
  text-decoration: none;
}
a.meta:hover {
  color: rgba(10,10,10,0.5);
  text-decoration: underline;
}
```

### Separators
```css
/* Blog List Separator */
.separator {
  background-color: rgba(255, 36, 36, 0.6);
  height: 1px;
  margin-bottom: 34px;
}
```

---

## 6. IMAGERY STYLE

### Gallery Settings
```
Style: Stacked (default for this site)
Image aspect ratios:
  - Grid: 1:1 Square
  - Stacked: 16:9 Widescreen
  - Gallery default: 3:2 standard, 4:3 general
Full-width first landscape: true
Image captions: Show on Hover/Tap
Caption indicator position: Bottom Left
Image zoom factor: 2.5x (on product images)
```

### Image Overlays
```css
/* Dark overlay for hero/gallery */
.image-overlay-dark {
  background: rgba(0, 0, 0, 0.7);
}

/* Gradient overlay */
.image-overlay-gradient {
  background: linear-gradient(
    0deg,
    rgba(0,0,0,0.9) 0%,
    rgba(0,0,0,0.4) 33%,
    rgba(0,0,0,0) 100%
  );
}

/* Radial vignette overlay */
.image-overlay-vignette {
  background: radial-gradient(
    circle at 50% 25%,
    rgba(0,0,0,0.75),
    #000
  );
}
```

### Photo Treatments
- Full-bleed/edge-to-edge display
- Dark semi-transparent overlays for text readability
- No heavy filters or color treatments
- Clean, professional photography style
- Hover effects: Fade behavior for product/gallery lists
- Index descriptions hidden on hover

### Index/Landing Page
- Slideshow capability (currently disabled)
- Slideshow delay: 3.5 seconds when active
- Index inactive on load: true (hover-activated)
- Touch slideshow: enabled for mobile

---

## 7. BRAND IDENTITY CUES

### Personality Traits
| Trait | Evidence |
|-------|----------|
| **Professional** | Clean Helvetica Neue body text, restrained color palette, structured layout |
| **Sophisticated** | Adobe Garamond Pro serif headings, monochromatic scheme, minimal design |
| **Music Industry Insider** | Understated luxury, no flashy colors - lets the work speak |
| **Latin American Connection** | Founded by ex-UMG/EMI executives, country set to Mexico |
| **Boutique/Specialist** | Small, focused service offering; personal touch implied |
| **International** | English-language site targeting global music industry for LATAM services |

### Brand Voice
- Tagline: "integrated marketing + strategy in Latin America"
- Tone: Professional, confident, knowledgeable
- Use of "+" instead of "&" in tagline - modern/tech-influenced
- Lowercase brand name: "dmusicmarketing" - approachable, not corporate

### Visual Identity Summary
- **NOT luxury/gold/glamorous** - it's understated professional
- **NOT edgy/punk/rebellious** - it's clean and trustworthy
- **NOT corporate/blue/stiff** - it's creative industry professional
- **IS**: Minimalist, monochromatic, sophisticated, content-first, music-industry professional

### Key Brand Design Rules
1. **Monochromatic first**: Grayscale as primary palette (#000 to #fff)
2. **Serif + Sans-serif pairing**: Elegant serif headings with clean sans-serif body
3. **Whitespace is key**: Generous padding, breathing room
4. **Content-forward**: Typography and text content dominate over decorative elements
5. **Subtle interactions**: 0.15s ease-out transitions, fade effects, opacity changes
6. **Red as accent only**: Red tones (#ab2121, rgba(255,36,36,0.6)) used sparingly for separators/emphasis

---

## 8. ANIMATION & TRANSITIONS

```css
/* Standard transition (most common) */
transition: all 0.15s ease-out;

/* Color transition */
transition: color 0.15s ease-out;

/* Common timing values */
0.1s ease-in-out   /* Quick micro-interactions */
0.15s ease-out      /* Standard hover effects */
0.2s                /* Short transitions */
0.25s               /* Medium transitions */
0.3s ease-in-out    /* Standard transitions */
0.4s                /* Comfortable transitions */
0.5s ease-in-out    /* Slow transitions, page loads */
1.5s                /* Long animations */
2s                  /* Very long animations */

/* Loading spinner */
@keyframes sqs-spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

/* Font loading animation */
@keyframes fonts-loading {
  0%, 99% { color: transparent; }
}
html.wf-loading * {
  animation: fonts-loading 3s;
}

/* Gallery transition */
transition-type: cards (500ms duration)

/* Index slideshow delay */
3.5 seconds between slides

/* Hover behaviors */
Product list: Fade on hover
Gallery captions: Show on Hover/Tap
Index descriptions: Hide on hover
```

---

## 9. RESPONSIVE BREAKPOINTS

```css
/* Mobile (small) */
@media (max-width: 432px) { }

/* Mobile (medium) */
@media (max-width: 480px) { }

/* Tablet / Template breakpoint */
@media (max-width: 640px) { }

/* Desktop starts */
@media (min-width: 433px) { }
@media (min-width: 481px) { }
@media (min-width: 640px) { }

/* High-DPI displays */
@media (min-resolution: 1.5dppx) { }
```

---

## 10. SOCIAL MEDIA PRESENCE

| Platform | Handle/URL |
|----------|-----------|
| Facebook | https://www.facebook.com/dmusicmarketinglatam/ |
| Instagram | http://instagram.com/dmusicmarketing |
| Spotify | https://open.spotify.com/user/dmusicmarketing |
| Email | press@dmusicmarketing.com |

---

## 11. CONTENT STRUCTURE

### Pages
1. **Home** (`/`) - Landing/index page with hero content
2. **About** (`/about`) - Company story, team background, "Why Latin America?" section
3. **Services** (`/services`) - Service offerings list
4. **Clients** (`/clients`) - Client list and testimonials (gallery collection type)
5. **Connect** (`/connect`) - Contact form and newsletter signup

### Services Offered
Radio Promo, Effective PR, Brand Campaigns, TV, Social Media, Street Campaigns, Showcases, Magazine Covers, Syncing, Marketing Consultancy

### Notable Clients
Beggars Group, Secretly Group, Sony Music Group, ATO Records, Domino, Epitaph, Giant Music, Sub Pop, Secret City Records, WARP Records, ANTI-

### Artists Mentioned
Sharon Van Etten, Kongos, Interpol, Arctic Monkeys, Placebo, Garbage, Nick Cave, Bjork, Coldplay, Robbie Williams, Major Lazer, Petit Biscuit, Katy Perry

---

## 12. CSS DESIGN TOKENS (For Implementation)

```css
:root {
  /* Primary Colors */
  --color-black: #000000;
  --color-near-black: #0a0a0a;
  --color-dark: #111111;
  --color-charcoal: #222222;
  --color-dark-gray: #3e3e3e;
  --color-button-primary: #272727;
  --color-white: #ffffff;

  /* Neutral Grays */
  --color-gray-700: #444444;
  --color-gray-600: #797979;
  --color-gray-550: #8f8f8f;
  --color-gray-500: #919191;
  --color-gray-400: #999999;
  --color-gray-350: #b4b4b4;
  --color-gray-300: #cccccc;
  --color-gray-250: #d0d0d0;
  --color-gray-200: #e3e3e3;
  --color-gray-150: #ededed;
  --color-gray-100: #f6f6f6;
  --color-gray-50: #fafafa;

  /* Accent Colors */
  --color-accent-coral: #f0523d;
  --color-accent-red: #ce2c30;
  --color-accent-dark-red: #ab2121;
  --color-accent-error: #cc3b3b;
  --color-accent-separator: rgba(255, 36, 36, 0.6);

  /* Typography */
  --font-heading-serif: 'adobe-garamond-pro', Georgia, 'Times New Roman', serif;
  --font-heading-sans: 'Raleway', 'Helvetica Neue', Helvetica, Arial, sans-serif;
  --font-body: 'Helvetica Neue', Helvetica, Arial, sans-serif;
  --font-meta: 'Roboto', 'Helvetica Neue', Helvetica, Arial, sans-serif;
  --font-detail: 'Lato', 'Helvetica Neue', Helvetica, Arial, sans-serif;
  --font-system: 'Clarkson', 'Helvetica Neue', Helvetica, Arial, sans-serif;

  /* Font Sizes */
  --text-xs: 8px;
  --text-sm: 11px;
  --text-base-sm: 12px;
  --text-base: 14px;
  --text-md: 16px;
  --text-lg: 21px;
  --text-xl: 22px;
  --text-2xl: 26px;
  --text-3xl: 31px;
  --text-4xl: 32px;
  --text-5xl: 35px;
  --text-6xl: 43px;

  /* Font Weights */
  --weight-thin: 100;
  --weight-regular: 400;
  --weight-medium: 500;
  --weight-semibold: 600;
  --weight-bold: 700;

  /* Line Heights */
  --leading-tight: 1em;
  --leading-snug: 1.3em;
  --leading-normal: 1.5em;
  --leading-relaxed: 1.6em;
  --leading-loose: 1.7em;

  /* Letter Spacing */
  --tracking-tight: -0.01em;
  --tracking-normal: 0em;
  --tracking-wide: 0.05em;
  --tracking-wider: 0.1em;
  --tracking-button: 0.5px;

  /* Spacing */
  --space-block: 17px;
  --space-list: 34px;
  --space-gallery-gutter: 12px;
  --space-separator-margin: 34px;

  /* Border Radius */
  --radius-sm: 2px;
  --radius-md: 3px;
  --radius-lg: 4px;
  --radius-xl: 5px;
  --radius-2xl: 14px;
  --radius-full: 50%;

  /* Shadows */
  --shadow-modal: 0 4px 33px rgba(0,0,0,0.22), 0 0 0 1px rgba(0,0,0,0.04);
  --shadow-inset-light: inset 0 1px 0 rgba(255,255,255,0.04);

  /* Transitions */
  --transition-fast: 0.15s ease-out;
  --transition-normal: 0.3s ease-in-out;
  --transition-slow: 0.5s ease-in-out;

  /* Overlays */
  --overlay-light: rgba(0,0,0,0.1);
  --overlay-medium: rgba(0,0,0,0.4);
  --overlay-dark: rgba(0,0,0,0.7);
  --overlay-heavy: rgba(0,0,0,0.9);

  /* Breakpoints */
  --bp-mobile-sm: 432px;
  --bp-mobile: 480px;
  --bp-tablet: 640px;
}
```

---

## 13. QUICK REFERENCE - RECREATING THE BRAND

### Essential Design Rules
1. **Background**: White (`#fff`) - clean, open
2. **Primary text**: Near-black (`#0a0a0a`) - not pure black for readability
3. **Headings**: Use `adobe-garamond-pro` or `Raleway` in gray tones (`#222` or `#919191`)
4. **Body**: `"Helvetica Neue"` at 14px, 400 weight, 1.6em line-height
5. **Buttons**: Dark charcoal (`#3e3e3e`), white text, uppercase, small (11px)
6. **Hover**: Darken to `#000` for buttons; fade to 50% opacity for text links
7. **Accents**: Muted reds used sparingly - only for separators and emphasis
8. **Spacing**: 17px as base unit (block padding)
9. **Transitions**: 0.15s ease-out for hover states
10. **Layout**: Content-centered, right-aligned navigation, generous whitespace
