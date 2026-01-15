#!/usr/bin/env python3
"""
Download Microsoft Core Fonts for Docker image caching.
This script downloads the fonts that ttf-mscorefonts-installer would download.
"""

import urllib.request
import os
import sys

# Font files and their download URLs from reliable sources
# These are the actual font files (TTF) that we need
FONTS = {
    # Arial family
    'arial.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/arial.ttf',
    'arialbd.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/arialbd.ttf',
    'arialbi.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/arialbi.ttf',
    'ariali.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/ariali.ttf',
    'ariblk.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/ariblk.ttf',
    
    # Comic Sans MS
    'comic.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/comic.ttf',
    'comicbd.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/comicbd.ttf',
    
    # Courier New
    'cour.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/cour.ttf',
    'courbd.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/courbd.ttf',
    'courbi.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/courbi.ttf',
    'couri.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/couri.ttf',
    
    # Georgia
    'georgia.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/georgia.ttf',
    'georgiab.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/georgiab.ttf',
    'georgiai.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/georgiai.ttf',
    'georgiaz.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/georgiaz.ttf',
    
    # Impact
    'impact.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/impact.ttf',
    
    # Times New Roman
    'times.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/times.ttf',
    'timesbd.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/timesbd.ttf',
    'timesbi.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/timesbi.ttf',
    'timesi.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/timesi.ttf',
    
    # Trebuchet MS
    'trebuc.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/trebuc.ttf',
    'trebucbd.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/trebucbd.ttf',
    'trebucbi.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/trebucbi.ttf',
    'trebucit.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/trebucit.ttf',
    
    # Verdana
    'verdana.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/verdana.ttf',
    'verdanab.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/verdanab.ttf',
    'verdanai.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/verdanai.ttf',
    'verdanaz.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/verdanaz.ttf',
    
    # Andale Mono
    'andlso.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/andlso.ttf',
    
    # Webdings
    'webdings.ttf': 'https://github.com/Luxianze/Microsoft-Core-Fonts/raw/main/webdings.ttf',
}

def download_font(font_name, url):
    """Download a single font file."""
    try:
        print(f"Downloading {font_name}...", end=' ', flush=True)
        urllib.request.urlretrieve(url, font_name)
        size = os.path.getsize(font_name)
        print(f"✓ ({size:,} bytes)")
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

def main():
    """Download all Microsoft Core Fonts."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    print(f"Downloading {len(FONTS)} Microsoft Core Fonts to {script_dir}...\n")
    
    success_count = 0
    for font_name, url in FONTS.items():
        if download_font(font_name, url):
            success_count += 1
    
    print(f"\n{'='*60}")
    print(f"Downloaded {success_count}/{len(FONTS)} fonts successfully")
    
    if success_count < len(FONTS):
        print("Warning: Some fonts failed to download. You may need to download them manually.")
        sys.exit(1)
    else:
        print("All fonts downloaded successfully!")
        sys.exit(0)

if __name__ == '__main__':
    main()
