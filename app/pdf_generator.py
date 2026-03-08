import io
import fitz


def _wrap_text(text: str, font: str, fontsize: float, max_width: float) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            test = f"{current} {word}"
            tw = fitz.get_text_length(test, fontname=font, fontsize=fontsize)
            if tw <= max_width:
                current = test
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _set_metadata(doc, title: str, author: str = ""):
    """Set PDF metadata for ATS compatibility."""
    doc.set_metadata({
        "title": title,
        "author": author,
        "subject": title,
        "creator": "CareerPulse",
        "producer": "CareerPulse",
    })


def generate_resume_pdf(resume_text: str, name: str = "") -> bytes:
    """Generate an ATS-optimized resume PDF from plain text.

    ATS best practices:
    - Real selectable text (not images)
    - Standard fonts (Helvetica/Helvetica-Bold)
    - Single-column layout, no tables
    - PDF metadata set (title, author)
    - Simple top-to-bottom reading order
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # Letter size

    # Extract name from first non-empty line for metadata
    first_line = ""
    for line in resume_text.split("\n"):
        if line.strip():
            first_line = line.strip()
            break
    doc_name = name or first_line
    _set_metadata(doc, f"Resume - {doc_name}", doc_name)

    margin_x = 54
    margin_top = 54
    max_width = 612 - 2 * margin_x
    y = margin_top

    body_font = "helv"
    bold_font = "hebo"
    body_size = 10.5
    heading_size = 11.5
    name_size = 14
    line_height = body_size * 1.5
    heading_line_height = heading_size * 1.8

    is_first_line = True

    for raw_line in resume_text.split("\n"):
        line = raw_line.strip()

        # First non-empty line is the name — render larger and bold
        if is_first_line and line:
            is_first_line = False
            if y > 740:
                page = doc.new_page(width=612, height=792)
                y = margin_top
            page.insert_text(
                fitz.Point(margin_x, y),
                line,
                fontname=bold_font,
                fontsize=name_size,
                color=(0.05, 0.05, 0.05),
            )
            y += name_size * 1.8
            continue

        if is_first_line:
            continue

        # Detect section headings (all caps lines or lines ending with colon)
        is_heading = (
            (line == line.upper() and len(line) > 2 and line.replace(" ", "").replace("&", "").replace("/", "").isalpha())
            or (line.endswith(":") and len(line) < 60 and not line.startswith("-"))
        )

        if is_heading:
            y += 8  # extra space before heading
            if y > 740:
                page = doc.new_page(width=612, height=792)
                y = margin_top

            page.insert_text(
                fitz.Point(margin_x, y),
                line,
                fontname=bold_font,
                fontsize=heading_size,
                color=(0.1, 0.1, 0.1),
            )
            # Full-width separator under heading
            page.draw_line(
                fitz.Point(margin_x, y + 4),
                fitz.Point(612 - margin_x, y + 4),
                color=(0.75, 0.75, 0.75),
                width=0.5,
            )
            y += heading_line_height
            continue

        if not line:
            y += line_height * 0.4
            continue

        # Detect sub-headings (job title lines with | or dates)
        is_subheading = (
            "|" in line
            or (any(c.isdigit() for c in line) and ("-" in line or "–" in line) and len(line) < 120)
        )

        font = bold_font if is_subheading else body_font
        size = body_size if not is_subheading else body_size + 0.5

        # Word-wrap body text
        wrapped = _wrap_text(line, font, size, max_width)
        for wl in wrapped:
            if y > 750:
                page = doc.new_page(width=612, height=792)
                y = margin_top
            page.insert_text(
                fitz.Point(margin_x, y),
                wl,
                fontname=font,
                fontsize=size,
                color=(0.12, 0.12, 0.12),
            )
            y += line_height

    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def generate_cover_letter_pdf(cover_letter: str, company: str = "",
                               position: str = "") -> bytes:
    """Generate an ATS-optimized cover letter PDF."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)

    title = "Cover Letter"
    if position and company:
        title = f"Cover Letter - {position} at {company}"
    elif position:
        title = f"Cover Letter - {position}"

    _set_metadata(doc, title)

    margin_x = 72
    max_width = 612 - 2 * margin_x
    y = 72

    body_font = "helv"
    bold_font = "hebo"
    body_size = 11
    line_height = body_size * 1.6

    # Title
    page.insert_text(
        fitz.Point(margin_x, y),
        title,
        fontname=bold_font,
        fontsize=13,
        color=(0.1, 0.1, 0.1),
    )
    y += 28

    # Separator line
    page.draw_line(
        fitz.Point(margin_x, y - 6),
        fitz.Point(612 - margin_x, y - 6),
        color=(0.8, 0.8, 0.8),
        width=0.5,
    )
    y += 4

    # Body
    for raw_line in cover_letter.split("\n"):
        line = raw_line.strip()
        if not line:
            y += line_height * 0.6
            continue

        # Detect greeting/closing lines for bold
        is_greeting = (
            line.startswith("Dear ") or line.startswith("Sincerely")
            or line.startswith("Best regards") or line.startswith("Regards")
        )
        font = bold_font if is_greeting else body_font

        wrapped = _wrap_text(line, font, body_size, max_width)
        for wl in wrapped:
            if y > 740:
                page = doc.new_page(width=612, height=792)
                y = 72
            page.insert_text(
                fitz.Point(margin_x, y),
                wl,
                fontname=font,
                fontsize=body_size,
                color=(0.12, 0.12, 0.12),
            )
            y += line_height

    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()
