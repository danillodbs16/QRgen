import io
import re
import zipfile

import pandas as pd
import qrcode
import streamlit as st

from PIL import Image, ImageColor, ImageDraw, ImageFont
from qrcode.constants import (
    ERROR_CORRECT_L,
    ERROR_CORRECT_M,
    ERROR_CORRECT_Q,
    ERROR_CORRECT_H,
)


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="QR Code Generator",
    page_icon="🔳",
    layout="wide",
)

st.title("🔳 QR Code Generator")

st.caption(
    "Generate customized QR codes from URLs or text. "
    "Customize colors, logos, dimensions and export settings."
    " This app is for educational purposes only."
)


# ============================================================
# CONSTANTS
# ============================================================

ERROR_LEVELS = {
    "L (~7%)": ERROR_CORRECT_L,
    "M (~15%)": ERROR_CORRECT_M,
    "Q (~25%)": ERROR_CORRECT_Q,
    "H (~30%)": ERROR_CORRECT_H,
}

STYLES = [
    "Square",
    "Rounded",
    "Circle",
    "Dots (small)",
    "Diamond",
    "Vertical bars",
    "Horizontal bars",
]

# Each module is drawn at this many pixels, then the whole image is
# resized to the requested size (gives smooth shapes).
RENDER_BOX = 24

FONT_CANDIDATES = [
    "DejaVuSans.ttf",
    "arial.ttf",
    "Arial.ttf",
    "Helvetica.ttc",
    "LiberationSans-Regular.ttf",
]


# ============================================================
# SESSION STATE
# ============================================================

DEFAULTS = {
    "applied_foreground": "#000000",
    "applied_background": "#FFFFFF",
    "foreground_picker": "#000000",
    "background_picker": "#FFFFFF",
    "terms_accepted": False,
    "agree_noncommercial": False,
    "agree_personal_data": False,
    "agree_content": False,
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# CALLBACKS
# ============================================================

def apply_foreground():
    st.session_state.applied_foreground = st.session_state.foreground_picker


def apply_background():
    st.session_state.applied_background = st.session_state.background_picker


def accept_terms():
    st.session_state.terms_accepted = True


def revoke_terms():
    st.session_state.terms_accepted = False
    st.session_state.agree_noncommercial = False
    st.session_state.agree_personal_data = False
    st.session_state.agree_content = False


# ============================================================
# HELPERS
# ============================================================

def load_font(size):
    """Load a TrueType font, falling back to Pillow's default font."""
    for name in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue

    try:
        # Pillow >= 10.1 supports a size argument
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def draw_qr_pattern(draw, x, y, box_size, foreground, style="Square"):
    """Draw a single QR module at (x, y)."""
    fg = ImageColor.getrgb(foreground)
    cx = x + box_size / 2
    cy = y + box_size / 2

    if style == "Square":
        draw.rectangle(
            (x, y, x + box_size - 1, y + box_size - 1),
            fill=fg,
        )

    elif style == "Rounded":
        radius = max(1, box_size // 4)
        draw.rounded_rectangle(
            (x, y, x + box_size - 1, y + box_size - 1),
            radius=radius,
            fill=fg,
        )

    elif style == "Circle":
        draw.ellipse(
            (x, y, x + box_size - 1, y + box_size - 1),
            fill=fg,
        )

    elif style == "Diamond":
        draw.polygon(
            [
                (cx, y),
                (x + box_size - 1, cy),
                (cx, y + box_size - 1),
                (x, cy),
            ],
            fill=fg,
        )

    elif style == "Dots (small)":
        inset = box_size * 0.18
        draw.ellipse(
            (x + inset, y + inset, x + box_size - 1 - inset, y + box_size - 1 - inset),
            fill=fg,
        )

    elif style == "Vertical bars":
        inset = box_size * 0.15
        draw.rounded_rectangle(
            (x + inset, y, x + box_size - 1 - inset, y + box_size - 1),
            radius=max(1, int(box_size * 0.2)),
            fill=fg,
        )

    elif style == "Horizontal bars":
        inset = box_size * 0.15
        draw.rounded_rectangle(
            (x, y + inset, x + box_size - 1, y + box_size - 1 - inset),
            radius=max(1, int(box_size * 0.2)),
            fill=fg,
        )

    else:
        draw.rectangle(
            (x, y, x + box_size - 1, y + box_size - 1),
            fill=fg,
        )


def is_finder_module(row, col, size):
    """True if the module belongs to one of the three finder patterns."""
    in_top = row < 7
    in_bottom = row >= size - 7
    in_left = col < 7
    in_right = col >= size - 7

    return (in_top and in_left) or (in_top and in_right) or (in_bottom and in_left)


def wrap_text(draw, text, font, max_width):
    """Wrap text into lines that fit max_width."""
    lines = []

    for paragraph in str(text).splitlines() or [""]:
        words = paragraph.split(" ")
        current = ""

        for word in words:
            candidate = word if not current else f"{current} {word}"
            width = draw.textlength(candidate, font=font)

            if width <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word

        lines.append(current)

    return lines


def generate_qr(
    data,
    foreground,
    background,
    style,
    error_level,
    border,
    size,
    logo_file=None,
    logo_ratio=0.2,
    caption=None,
    caption_size=28,
    caption_color="#000000",
    style_finders=True,
):
    """Create a QR code image and return it as a PIL image (RGB)."""
    if not str(data).strip():
        raise ValueError("The QR content is empty.")

    # Logos cover part of the code, so force the highest error correction
    if logo_file is not None:
        error_level = ERROR_CORRECT_H

    qr = qrcode.QRCode(
        version=None,
        error_correction=error_level,
        box_size=1,
        border=0,
    )
    qr.add_data(str(data))
    qr.make(fit=True)

    matrix = qr.get_matrix()
    modules = len(matrix)
    total_modules = modules + 2 * border

    img_px = total_modules * RENDER_BOX
    bg_rgb = ImageColor.getrgb(background)

    image = Image.new("RGB", (img_px, img_px), bg_rgb)
    draw = ImageDraw.Draw(image)

    for r, row in enumerate(matrix):
        for c, filled in enumerate(row):
            if not filled:
                continue

            x = (c + border) * RENDER_BOX
            y = (r + border) * RENDER_BOX

            module_style = style

            # Optionally keep the three corner squares blocky for easier scanning
            if not style_finders and is_finder_module(r, c, modules):
                module_style = "Square"

            draw_qr_pattern(draw, x, y, RENDER_BOX, foreground, module_style)

    # Logo in the center
    if logo_file is not None:
        logo_file.seek(0)
        logo = Image.open(logo_file).convert("RGBA")

        logo_side = int(img_px * logo_ratio)
        logo.thumbnail((logo_side, logo_side), Image.LANCZOS)

        pad = max(4, logo_side // 12)
        plate_w = logo.width + 2 * pad
        plate_h = logo.height + 2 * pad

        plate = Image.new("RGBA", (plate_w, plate_h), bg_rgb + (255,))
        plate.paste(logo, (pad, pad), logo)

        pos = ((img_px - plate_w) // 2, (img_px - plate_h) // 2)
        image.paste(plate.convert("RGB"), pos)

    # Resize to the requested output size
    image = image.resize((size, size), Image.LANCZOS)

    # Caption text below the QR code
    if caption and str(caption).strip():
        font = load_font(caption_size)
        measure = ImageDraw.Draw(image)

        margin = max(10, size // 40)
        lines = wrap_text(measure, caption, font, size - 2 * margin)

        line_height = int(caption_size * 1.3)
        text_height = line_height * len(lines) + margin

        canvas = Image.new("RGB", (size, size + text_height), bg_rgb)
        canvas.paste(image, (0, 0))

        text_draw = ImageDraw.Draw(canvas)
        y = size

        for line in lines:
            width = text_draw.textlength(line, font=font)
            text_draw.text(
                ((size - width) / 2, y),
                line,
                font=font,
                fill=ImageColor.getrgb(caption_color),
            )
            y += line_height

        image = canvas

    return image


def image_to_bytes(image, fmt):
    """Serialize a PIL image to bytes in the given format."""
    buffer = io.BytesIO()
    fmt = fmt.upper()

    if fmt == "JPEG":
        image.convert("RGB").save(buffer, format="JPEG", quality=95)
    else:
        image.save(buffer, format=fmt)

    return buffer.getvalue()


def safe_filename(text, fallback="qr"):
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text)).strip("_")
    return (name[:60] or fallback)


# ============================================================
# TERMS OF USE (the app is locked until they are accepted)
# ============================================================

TERMS_OF_USE = """
**Please read these terms carefully before using the QR Code Generator.**

**1. Non-commercial use only**

This app is provided for personal, educational and other non-commercial
purposes. You may not use it, or the QR codes it produces, as part of a paid
product or service, for resale, or for any commercial promotion or advertising
campaign.

**2. Personal data**

Whatever you type, paste or upload (links, text, CSV files, logos) is processed
to generate your QR code. You acknowledge that you are aware of this and that you
are solely responsible for the information you choose to share. Do not include
sensitive personal data (yours or anyone else's) such as ID numbers, passwords,
financial details or health information. Do not include personal data of third
parties without their consent.

**3. QR codes are not private**

A QR code is not encrypted. Anyone who scans it, or who obtains the image, can
read its full content. Do not encode anything you would not want to be public.

**4. Prohibited content**

You must not use this app to create QR codes that link to or contain content that:
- is illegal, or promotes illegal activities;
- is malicious or deceptive, including phishing, scams, malware or fake login pages;
- is hateful, discriminatory, harassing, threatening or violent;
- is sexually explicit or exploits or endangers minors;
- infringes intellectual property, privacy or other rights of third parties;
- impersonates a person, company or institution.

**5. Logos and images**

If you upload a logo or image, you confirm that you own it or have the right to
use it.

**6. No warranty**

The app is provided "as is", without warranties of any kind. Always test your QR
code with several devices before printing or distributing it. Customizations such
as colors, module styles and logos can reduce scannability.

**7. Limitation of liability**

To the maximum extent permitted by law, the provider of this app is not liable for
any damage resulting from its use, from the content you encode, or from how
third parties use the QR codes you create.

**8. Changes and restrictions**

These terms may change at any time. Access may be restricted if the app is used
in breach of these terms.
"""

if not st.session_state.terms_accepted:

    st.subheader("📜 Terms of Use")

    with st.container(border=True, height=420):
        st.markdown(TERMS_OF_USE)

    st.checkbox(
        "I will use this app for **non-commercial purposes only**.",
        key="agree_noncommercial",
    )

    st.checkbox(
        "I am aware that the **links, text and files I provide are processed "
        "and may contain personal data**, and I am responsible for what I share.",
        key="agree_personal_data",
    )

    st.checkbox(
        "I will **not use the app for inappropriate, illegal or deceptive content**, "
        "and I have read and accept the terms above.",
        key="agree_content",
    )

    all_checked = (
        st.session_state.agree_noncommercial
        and st.session_state.agree_personal_data
        and st.session_state.agree_content
    )

    st.button(
        "Accept and continue",
        type="primary",
        disabled=not all_checked,
        on_click=accept_terms,
    )

    if not all_checked:
        st.info("Tick all three boxes to unlock the QR generator.")

    st.stop()


# ============================================================
# SIDEBAR / SETTINGS
# ============================================================

with st.sidebar:

    st.header("⚙️ Settings")

    style = st.selectbox("Module style", STYLES)

    style_finders = st.checkbox(
        "Apply style to the corner squares",
        value=True,
        help="Turn this off to keep the three corner squares blocky, "
        "which makes the code easier to scan.",
    )

    error_label = st.selectbox("Error correction", list(ERROR_LEVELS), index=1)
    error_level = ERROR_LEVELS[error_label]

    size = st.slider("Image size (px)", 200, 1500, 500, step=50)
    border = st.slider("Border (modules)", 0, 10, 4)

    st.subheader("🎨 Colors")

    fg_col, fg_btn = st.columns([3, 2])
    with fg_col:
        st.color_picker("Foreground", key="foreground_picker")
    with fg_btn:
        st.write("")
        st.write("")
        st.button("Apply", key="apply_fg", on_click=apply_foreground)

    bg_col, bg_btn = st.columns([3, 2])
    with bg_col:
        st.color_picker("Background", key="background_picker")
    with bg_btn:
        st.write("")
        st.write("")
        st.button("Apply", key="apply_bg", on_click=apply_background)

    st.caption(
        f"Applied: foreground `{st.session_state.applied_foreground}` · "
        f"background `{st.session_state.applied_background}`"
    )

    st.subheader("🖼️ Logo")

    logo_file = st.file_uploader(
        "Logo (optional)",
        type=["png", "jpg", "jpeg", "webp"],
    )

    logo_ratio = st.slider("Logo size (% of QR)", 10, 30, 20) / 100

    st.subheader("🔤 Text")

    caption_size = st.slider("Text size", 12, 80, 28)
    caption_color = st.color_picker("Text color", "#000000")

    st.subheader("💾 Export")

    export_format = st.selectbox("Format", ["PNG", "JPEG", "WEBP"])

    st.divider()

    st.button("📜 Review terms of use", on_click=revoke_terms)


foreground = st.session_state.applied_foreground
background = st.session_state.applied_background

if foreground.lower() == background.lower():
    st.warning("Foreground and background colors are identical; the QR will not be readable.")


# ============================================================
# MAIN AREA
# ============================================================

mode = st.radio("Mode", ["Single", "Batch (CSV)"], horizontal=True)

extension = export_format.lower().replace("jpeg", "jpg")

if mode == "Single":

    left, right = st.columns(2)

    with left:
        data = st.text_area(
            "QR content (URL or text)",
            value="https://example.com",
            height=120,
        )

        caption = st.text_input("Text under the QR (optional)")

    with right:
        try:
            image = generate_qr(
                data=data,
                foreground=foreground,
                background=background,
                style=style,
                style_finders=style_finders,
                error_level=error_level,
                border=border,
                size=size,
                logo_file=logo_file,
                logo_ratio=logo_ratio,
                caption=caption,
                caption_size=caption_size,
                caption_color=caption_color,
            )

            st.image(image, caption="Preview")

            st.download_button(
                "⬇️ Download QR",
                data=image_to_bytes(image, export_format),
                file_name=f"qr.{extension}",
                mime=f"image/{'jpeg' if extension == 'jpg' else extension}",
            )

        except Exception as exc:
            st.error(f"QR generation failed: {exc}")

else:

    st.write(
        "Upload a CSV file. Each row becomes one QR code, "
        "and all codes are delivered in a ZIP file."
    )

    csv_file = st.file_uploader("CSV file", type=["csv"])

    if csv_file is not None:

        try:
            df = pd.read_csv(csv_file)
        except Exception as exc:
            st.error(f"Could not read the CSV: {exc}")
            df = None

        if df is not None and not df.empty:

            st.dataframe(df.head(10), use_container_width=True)

            columns = list(df.columns)

            c1, c2 = st.columns(2)

            with c1:
                data_col = st.selectbox("Column with QR content", columns)

            with c2:
                caption_col = st.selectbox(
                    "Column with text under the QR",
                    ["(none)"] + columns,
                )

            if st.button("Generate batch", type="primary"):

                zip_buffer = io.BytesIO()
                previews = []
                errors = []

                progress = st.progress(0.0)
                total = len(df)

                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:

                    for i, row in df.iterrows():

                        value = row[data_col]

                        if pd.isna(value) or not str(value).strip():
                            errors.append(f"Row {i + 1}: empty content")
                            continue

                        caption = None
                        if caption_col != "(none)" and not pd.isna(row[caption_col]):
                            caption = str(row[caption_col])

                        try:
                            image = generate_qr(
                                data=value,
                                foreground=foreground,
                                background=background,
                                style=style,
                                style_finders=style_finders,
                                error_level=error_level,
                                border=border,
                                size=size,
                                logo_file=logo_file,
                                logo_ratio=logo_ratio,
                                caption=caption,
                                caption_size=caption_size,
                                caption_color=caption_color,
                            )
                        except Exception as exc:
                            errors.append(f"Row {i + 1}: {exc}")
                            continue

                        name = f"{i + 1:04d}_{safe_filename(caption or value)}.{extension}"
                        zf.writestr(name, image_to_bytes(image, export_format))

                        if len(previews) < 6:
                            previews.append((image, name))

                        progress.progress((i + 1) / total)

                progress.empty()

                if previews:
                    st.success(f"Generated {len(previews)} preview(s) shown below; ZIP contains all valid rows.")

                    cols = st.columns(3)
                    for idx, (img, name) in enumerate(previews):
                        cols[idx % 3].image(img, caption=name)

                    st.download_button(
                        "⬇️ Download ZIP",
                        data=zip_buffer.getvalue(),
                        file_name="qr_codes.zip",
                        mime="application/zip",
                    )

                for message in errors:
                    st.warning(message)

        elif df is not None:
            st.warning("The CSV file is empty.")
