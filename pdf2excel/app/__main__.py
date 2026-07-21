"""Entry point.

    python -m app                                  # launch the GUI
    python -m app convert input.pdf -o out.xlsx    # headless OCR + export
    python -m app export input.pdf -o out.xlsx     # export from the session
    python -m app inspect input.pdf

``convert`` also writes the session file (input.pdf.p2x) page by page,
so a headless overnight OCR run can be reviewed in the GUI afterwards —
and a crash mid-batch keeps every completed page.
"""

from __future__ import annotations

import argparse
import sys
import time

from app.config import PipelineConfig
from app.pipeline import pdf_loader
from app.pipeline.engines import available_engines
from app.pipeline.runner import process_pdf


def _parse_pages(spec: str) -> tuple[int, int]:
    if "-" in spec:
        a, b = spec.split("-", 1)
        return int(a), int(b)
    n = int(spec)
    return n, n


def cmd_inspect(args) -> int:
    info = pdf_loader.inspect_pdf(args.pdf)
    print(f"file:        {info.path}")
    print(f"pages:       {info.n_pages}")
    print(f"creator:     {info.creator or '-'}")
    print(f"producer:    {info.producer or '-'}")
    print(f"text chars:  {info.text_chars}")
    print(f"scanned:     {'no — has a text layer' if info.has_text_layer else 'yes (image-only, OCR required)'}")
    print(f"engines:     {available_engines()}")
    return 0


def cmd_convert(args) -> int:
    config = PipelineConfig(
        dpi=args.dpi,
        engine=args.engine,
        rotation="auto" if args.rotation == "auto" else int(args.rotation),
        page_range=_parse_pages(args.pages) if args.pages else None,
        output_layout=args.layout,
    )

    info = pdf_loader.inspect_pdf(args.pdf)
    if info.has_text_layer:
        print("warning: this PDF already has a text layer — it is likely a "
              "native (non-scanned) document. OCR will still run; the GUI "
              "offers a direct-parse path for such files.", file=sys.stderr)

    store = None
    if not args.no_session:
        from app.session import SessionStore
        try:
            store = SessionStore.for_pdf(args.pdf)
            if not config.page_range:
                store.clear_pages()  # full re-run replaces the session
            store.save_config(config)
        except Exception as exc:
            print(f"warning: session persistence disabled ({exc})",
                  file=sys.stderr)
            store = None

    t0 = time.time()

    def progress(done: int, total: int, msg: str) -> None:
        print(f"[{done}/{total}] {msg}", flush=True)

    pages = process_pdf(args.pdf, config, progress=progress,
                        on_page=store.save_page if store else None)
    if store:
        store.close()

    from app.export.excel import export_workbook
    export_workbook(pages, args.output, config)

    errors = [p for p in pages if p.error]
    print(f"done: {len(pages)} page(s) -> {args.output} "
          f"in {time.time() - t0:.1f}s"
          + (f" ({len(errors)} page(s) with errors)" if errors else ""))
    for p in errors:
        print(f"  page {p.page_number}: {p.error}", file=sys.stderr)
    return 1 if errors else 0


def cmd_export(args) -> int:
    """Export from the session file without re-running OCR."""
    from app.session import SessionStore
    if not SessionStore.exists_for_pdf(args.pdf):
        print(f"error: no session file found at "
              f"{SessionStore.path_for_pdf(args.pdf)!r} — run "
              f"'convert' (or the GUI) first.", file=sys.stderr)
        return 1
    with SessionStore.for_pdf(args.pdf) as store:
        results = store.load_pages()
        config = store.load_config() or PipelineConfig()

    if not results:
        print("error: the session contains no extracted pages.",
              file=sys.stderr)
        return 1

    pages = [results[k] for k in sorted(results)]
    if args.reviewed_only:
        pages = [p for p in pages if p.reviewed]
        if not pages:
            print("error: --reviewed-only, but no page is marked reviewed.",
                  file=sys.stderr)
            return 1
    else:
        unreviewed = sum(1 for p in pages if not p.reviewed and not p.error)
        if unreviewed:
            print(f"warning: {unreviewed} page(s) have not been reviewed — "
                  "OCR output should be human-checked before finance use.",
                  file=sys.stderr)

    config.output_layout = args.layout
    config.export_raw_columns = not args.no_raw

    from app.export.excel import export_workbook
    export_workbook(pages, args.output, config)
    print(f"exported {len(pages)} page(s) -> {args.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app",
        description="Offline scanned-PDF → Excel converter (id-ID finance documents).")
    sub = parser.add_subparsers(dest="command")

    p_inspect = sub.add_parser("inspect", help="show PDF info and scanned/native detection")
    p_inspect.add_argument("pdf")
    p_inspect.set_defaults(func=cmd_inspect)

    p_conv = sub.add_parser("convert", help="OCR a PDF and export to .xlsx")
    p_conv.add_argument("pdf")
    p_conv.add_argument("-o", "--output", required=True, help="output .xlsx path")
    p_conv.add_argument("--dpi", type=int, default=300)
    p_conv.add_argument("--engine", default="rapidocr",
                        choices=["rapidocr", "paddle-ppstructure"])
    p_conv.add_argument("--rotation", default="auto",
                        choices=["auto", "0", "90", "180", "270"],
                        help="auto-detect (default) or force a rotation")
    p_conv.add_argument("--pages", help="page or range, 1-based, e.g. 3 or 1-5")
    p_conv.add_argument("--layout", default="sheet_per_page",
                        choices=["sheet_per_page", "merged_by_label"])
    p_conv.add_argument("--no-session", action="store_true",
                        help="do not write a resumable session file")
    p_conv.set_defaults(func=cmd_convert)

    p_exp = sub.add_parser(
        "export", help="export the saved session (input.pdf.p2x) to .xlsx "
                       "without re-running OCR")
    p_exp.add_argument("pdf")
    p_exp.add_argument("-o", "--output", required=True, help="output .xlsx path")
    p_exp.add_argument("--layout", default="sheet_per_page",
                       choices=["sheet_per_page", "merged_by_label"])
    p_exp.add_argument("--no-raw", action="store_true",
                       help="omit the hidden raw-OCR audit columns")
    p_exp.add_argument("--reviewed-only", action="store_true",
                       help="export only pages marked reviewed")
    p_exp.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    if not args.command:
        try:
            from app.gui.main_window import main as gui_main
        except ImportError as exc:
            print(f"GUI unavailable ({exc}).\n"
                  f"Install the GUI dependency with: pip install PySide6\n",
                  file=sys.stderr)
            parser.print_help()
            return 1
        return gui_main()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
