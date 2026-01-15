# Microsoft Core Fonts

This directory contains pre-downloaded Microsoft Core Fonts to speed up Docker builds.

## Why?

The `ttf-mscorefonts-installer` package downloads fonts from Microsoft's servers during Docker builds, which takes 15+ minutes. By pre-downloading and caching these fonts, Docker builds are much faster (2-3 minutes instead of 15+).

## Fonts Included

24 Microsoft Core Fonts:
- Arial (regular, bold, italic, bold italic)
- Comic Sans MS (regular, bold)
- Georgia (regular, bold, italic, bold italic)
- Impact
- Times New Roman (regular, bold, italic, bold italic)
- Trebuchet MS (regular, bold, italic, bold italic)
- Verdana (regular, bold, italic, bold italic)
- Webdings

## Missing Fonts

The following fonts are not included (less commonly used in resumes):
- Arial Black
- Courier New (all variants)
- Andale Mono

If you need these fonts, you can download them manually and add them to this directory.

## Updating Fonts

If you need to update or add fonts:

1. Download the font files (`.ttf` format)
2. Place them in this directory
3. The Dockerfiles will automatically copy them to `/usr/share/fonts/truetype/msttcorefonts/` in the container

## Docker Layer Caching

The fonts are copied in a separate Docker layer, so they're only re-downloaded/copied if:
- The `backend/fonts/` directory changes
- The Docker cache is cleared

This means most builds will skip the font installation step entirely, making builds very fast.
