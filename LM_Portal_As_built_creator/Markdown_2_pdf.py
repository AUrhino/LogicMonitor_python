#!/usr/bin/env python3
"""Convert Markdown to PDF locally with free open-source Python tools.

Written by Ryan Gillan
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

__version__ = "1.04"


PDF_CSS = """
@page {
  size: a4 portrait;
  margin: 16mm 14mm 18mm 14mm;
  @frame footer_frame {
    -pdf-frame-content: footer_content;
    left: 14mm;
    right: 14mm;
    bottom: 5mm;
    height: 6mm;
  }
}
body { font-family: Helvetica, Arial, sans-serif; color: #172033; font-size: 9pt; line-height: 1.35; }
h1, h2, h3, h4, h5, h6 { color: #143a5e; -pdf-keep-with-next: true; }
h1 { font-size: 22pt; border-bottom: 2px solid #2b6f9f; padding-bottom: 5px; }
h2 { font-size: 16pt; border-bottom: 1px solid #b9cad8; padding-bottom: 3px; margin-top: 14px; }
h3 { font-size: 12pt; margin-top: 11px; }
h4 { font-size: 10pt; }
p { margin: 5px 0 7px; }
a { color: #0969a8; text-decoration: none; }
blockquote { border-left: 4px solid #7ea7c4; background-color: #f2f7fa; padding: 7px 10px; }
code { font-family: Courier; background-color: #eef2f5; font-size: 8pt; }
pre { font-family: Courier; background-color: #eef2f5; border: 1px solid #d2dbe2; padding: 8px; font-size: 7.5pt; white-space: pre-wrap; }
table { border-collapse: collapse; width: 100%; margin: 7px 0 11px; font-size: 7.5pt; }
th, td { border: 0.5px solid #aebdca; padding: 4px; vertical-align: top; }
th { background-color: #dbe8f1; color: #173f5f; font-weight: bold; }
img { max-width: 100%; }
#footer_content { color: #64748b; font-size: 7.5pt; text-align: center; }
"""


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Convert rendered Markdown to PDF locally using xhtml2pdf.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python Markdown_2_pdf.py customer_As_Built.md
  python Markdown_2_pdf.py customer_As_Built.md customer_As_Built.pdf
  python Markdown_2_pdf.py customer_As_Built.md --output ./pdf/customer.pdf
  python Markdown_2_pdf.py customer_As_Built.md --debug

Free local dependencies:
  python -m pip install --upgrade markdown xhtml2pdf
""",
    )
    result.add_argument("source", nargs="?", help="Source Markdown file")
    result.add_argument("output_positional", nargs="?", help="Optional output PDF file")
    result.add_argument("--output", "-o", help="Output PDF file (defaults beside source)")
    result.add_argument(
        "--debug",
        action="store_true",
        help="Show diagnostics and save the intermediate HTML file",
    )
    result.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return result


def debug(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[DEBUG] {message}", flush=True)


def ensure_dependencies() -> None:
    missing = [
        package
        for package in ("markdown", "xhtml2pdf")
        if importlib.util.find_spec(package) is None
    ]
    if missing:
        raise RuntimeError(
            "Missing local PDF dependencies: "
            + ", ".join(missing)
            + ". Run: python -m pip install --upgrade markdown xhtml2pdf"
        )


def resource_path(uri: str, source_dir: Path) -> str:
    """Resolve local Markdown images for xhtml2pdf."""
    parsed = urlparse(uri)
    if parsed.scheme in {"http", "https", "data"}:
        return uri
    if parsed.scheme == "file":
        return unquote(parsed.path)
    candidate = Path(unquote(parsed.path))
    if not candidate.is_absolute():
        candidate = source_dir / candidate
    return str(candidate.resolve())


def convert(source: Path, output: Path, debug_enabled: bool = False) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Markdown source file not found: {source}")
    if source.suffix.lower() not in {".md", ".markdown"}:
        raise ValueError(f"Source must be a Markdown file: {source}")
    ensure_dependencies()
    if output.suffix.lower() != ".pdf":
        output = output.with_suffix(".pdf")
    output.parent.mkdir(parents=True, exist_ok=True)

    import markdown  # type: ignore
    from xhtml2pdf import pisa  # type: ignore

    markdown_text = source.read_text(encoding="utf-8")
    body = markdown.markdown(
        markdown_text,
        extensions=["extra", "sane_lists", "toc"],
        output_format="html5",
    )
    title = html.escape(source.stem.replace("_", " "))
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>{PDF_CSS}</style>
</head>
<body>
{body}
<div id="footer_content">Page <pdf:pagenumber> of <pdf:pagecount></div>
</body>
</html>
"""

    debug(debug_enabled, f"Source: {source}")
    debug(debug_enabled, f"Output: {output}")
    debug(debug_enabled, "Engine: Python-Markdown + xhtml2pdf")
    debug(debug_enabled, f"Rendered HTML characters: {len(document)}")
    if debug_enabled:
        html_path = output.with_suffix(".debug.html")
        html_path.write_text(document, encoding="utf-8")
        debug(debug_enabled, f"Intermediate HTML: {html_path}")

    with output.open("wb") as pdf_file:
        status = pisa.CreatePDF(
            src=document,
            dest=pdf_file,
            encoding="utf-8",
            link_callback=lambda uri, _rel: resource_path(uri, source.parent),
        )
    if status.err:
        output.unlink(missing_ok=True)
        raise RuntimeError(f"xhtml2pdf reported {status.err} rendering error(s)")
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("PDF renderer completed without creating a valid PDF")
    debug(debug_enabled, f"PDF size: {output.stat().st_size} bytes")
    print(f"Created PDF: {output}")


def main() -> int:
    args_parser = parser()
    if len(sys.argv) == 1:
        args_parser.print_help()
        return 0
    args = args_parser.parse_args()
    if not args.source:
        args_parser.error("a source Markdown file is required")
    if args.output and args.output_positional:
        args_parser.error("use either positional output or --output, not both")

    source = Path(args.source).expanduser().resolve()
    output_arg = args.output or args.output_positional
    output = (
        Path(output_arg).expanduser().resolve()
        if output_arg
        else source.with_suffix(".pdf")
    )
    try:
        convert(source, output, args.debug)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
