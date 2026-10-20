# D.Ai PDF: a native reader and editor

> Written on 2026-10-19 after "build a native PDF reader and editor feature".
> The name "D.Ai PDF" is descriptive, like "D.Ai OCR": no new brand, nothing new to check for trademarks.
>
> **Decided (19 October 2026, "from now on you decide"):** the name is D.Ai PDF; qpdfview leaves the image once
> stage 1 is the default viewer; signatures are verify-only until a signing library is in Debian; Diamond only when
> asked. **Status: stages 1, 2 and 3a built** (§10–§13). Compression (3b) and stage 4 not started.

## 10. Stage 1: what was built

- `apps/dai-pdf`: `sandbox.py` (the bubblewrap command line: `--unshare-all`, the file read-only as
  `/tmp/document.pdf`, no home, `--clearenv`, `prlimit --data=1.5G --cpu=120`), `helper.py` (runs inside: Qt PDF
  renders, extracts text and link rectangles; pikepdf inspects), `findings.py` (what the file wants),
  `reader.py` (the window's side: a deadline on every request, a helper that died is started again, a page that
  killed it is reported as undrawable), `text.py` (Hebrew made readable, search), `gui.py` (the window and its
  dialogs), `cli.py` (`dai-pdf FILE`, `info`, `text`, `check`).
- **A lesson from building it:** an address-space limit (`prlimit --as`) kills PDFium at startup, because it
  reserves enormous address ranges it never touches. `--data` (writable memory) is enforced: a 7000-pixel page
  under 160 MB fails as "could not draw", the helper survives, and the next page draws (tested).
- **Links:** a GoToR action comes out of Qt as a `file:` address; the window refuses every scheme but
  `http`, `https` and `mailto`, and those only after a dialog that shows the whole address.
- **Tests:** 36 (findings on every kind of active content; helper and reader directly and inside the real sandbox
  with the memory limit; Hebrew mirroring; the window: file bar, zoom, rotation, search highlights, link
  policy, passwords, errors, copy, print to a file, outline, thumbnails; Raz's audit in Hebrew and English in
  three themes; the command line). CI installs `python3-pyqt6.qtpdf python3-pikepdf bubblewrap`.
- **Image:** `python3-pyqt6.qtpdf`, `python3-pikepdf`, `bubblewrap` added, `qpdfview` removed;
  `application/pdf=dai-pdf.desktop`; a VM check opens a file that wants things, proves the helper's command line
  is bubblewrap's, and that `dai-pdf check` lists and refuses.
- **Not yet:** text selection by dragging (copy is per page), a window-open timer for docs/HARDWARE.md, the
  screenshot in CI, and everything in stages 2–4.

## 11. Stage 2a: pages and forms (what was built)

- **Editing never touches the file until Save, and never in the window.** `edit.py` runs as a one-shot helper
  under bubblewrap (`sandbox.edit_argv`): every input bound read-only under `/tmp/in`, an empty folder the window
  made bound writable as `/tmp/out`, one JSON request on stdin, one answer on stdout, the result moved to where
  the person asked only after the helper finished cleanly (mode 0600). The window shows a **plan**: which source
  page is at each position and how it is turned; "Save as…" asks the editor to build that file.
- **Pages:** turn, move up and down, remove (never the last one), insert every page of another PDF (opened in
  its own sandbox, with its own password if it has one), merge and split from the command line. Undo and redo
  (Ctrl+Z, Ctrl+Shift+Z) over the plan and the form. A "•" in the title and a question before closing when there
  are unsaved changes.
- **Forms:** the Form tab lists the fields (text, multi-line, check box, radio group, drop-down; read-only ones
  disabled; required ones marked), filled in place; values go in with pikepdf (`/V`, `/AS`, `NeedAppearances`,
  appearance streams regenerated) and "Flatten when saving" bakes them in (`flatten_annotations`). XFA forms are
  shown with the stage 1 notice and are not editable.
- **Command line:** `merge`, `split` (a range, or one file per page), `rotate`, `delete`, `fields`, `fill
  --set name=value [--flatten]`, all `-o OUT`, all through the same sandboxed editor.
- **Tests:** 49 for D.Ai PDF now (the editor directly and inside bubblewrap; pages, passwords, bad requests that
  write nothing, fields listed, filled, flattened; the window: edit, undo, redo, thumbnails of turned pages, save
  and reopen, the form tab, the close question; Raz's audit with the Form tab open, touch and narrow passes).
  The VM check merges, turns and lists fields from the shell.
- **Not yet (stage 2b):** annotations (highlight, note, free text, drawing, stamps and signatures as pictures),
  and dragging pages in the thumbnail list (the buttons move them for now).

## 12. Stage 2b: marks (what was built)

- **Tools** above the pages: highlight, underline, strike through, note, text, stamp, and a colour swatch. A
  drag on a page makes the mark; it is drawn over the page at once and listed in the Marks tab (remove, go to);
  undo and redo cover it; a mark belongs to its source page, so it follows the page when pages move.
- **In the file** (`edit.py`, in the sandbox): highlight, underline and strike-through become real annotations
  (`/Highlight`, `/Underline`, `/StrikeOut` with quad points and a colour), a note becomes a `/Text` annotation
  with its contents, and every viewer draws them (D.Ai PDF's own helper renders with Qt's Annotations flag now).
  Free text and stamps are drawn **into the page as pictures**: the text is rendered by Qt at 288 dpi, so Hebrew
  is shaped and placed right to left in every viewer; the price is that such text is not selectable. A stamp is a
  PNG or JPEG the person chose (a signature, a logo), decoded by Qt inside the sandbox, bound read-only like the
  PDFs, with its transparency kept (an SMask).
- **A page's own /Rotate is honoured:** the mark lands where it was drawn on screen (the inverse of the
  mapping the helper uses for links), and a new turn from the plan is applied only after the marks are placed.
- **Tests:** 52 for D.Ai PDF (every kind in the file with its rectangle and colour; the turned page; a stamp
  inside bubblewrap; bad kinds, pages and pictures refused with nothing written; the window: drawing with a tool,
  the overlay, the list, marks following a moved page, undo, save and the saved annotations; Raz's audit with
  the Marks tab in the touch and narrow passes).
- **Not yet:** freehand drawing and shapes, editing a mark after it is placed (remove and draw again for now),
  selectable text with an embedded Hebrew font (**requires a check** of font subsetting with pikepdf).

## 13. Stage 3a: clean and search (what was built)

- **Redaction that truly removes:** a black box on a page makes that page a picture (300 dpi, drawn by Qt in the
  sandbox, the box painted on it); whatever was under the box, and every hidden layer of that page, is gone.
  The page keeps its size on paper. The price is said plainly in the window: the page's text becomes a
  picture (add OCR to make it searchable again).
- **A text layer for scans (OCR):** Tesseract, inside the same sandbox, in the person's language and English
  (eight languages on the image); pages without text get Tesseract's picture page with invisible text
  (`--all` for every page). Nothing is sent anywhere; no Ghostscript, no ocrmypdf.
- **Remove metadata:** the Info dictionary, XMP and PieceInfo of the file and its pages.
- **Pages as pictures:** every page of the plan as a PNG at a chosen resolution, with its turns.
- **Command line:** `ocr`, `strip`, `redact --page N --box L,T,W,H`, `export --dir FOLDER`.
- **Tests:** the picture page's pixels (black under the box, white elsewhere, text gone, the turned page's
  size), the metadata gone, OCR finding the words on a scan and leaving a text page alone (skipped where
  Tesseract is absent; CI installs it), export sizes and modes, the commands. The VM check redacts, strips,
  OCRs and exports with the real tools on the image.
- **A lesson:** Qt draws a PDF page over nothing; a picture of a page needs white paper under it first, or it
  comes out black (and Tesseract reads nothing).
- **Not yet:** compression with a size preview (3b), PDF/A.

## 0. Why, and what "native" means here

- Today the image ships **qpdfview**: a good viewer, but it is not D.Ai's (no D.Ai themes, no Hebrew-first
  interface, no sandbox, no editing, no Diamond).
- **Native:** a PyQt6 window like every other D.Ai app, drawn by Qt (C++), rendering through Qt PDF (PDFium,
  C++), editing through qpdf (C++) with its Python binding. No browser engine, no Electron, no web view.
  Everything runs on this computer; nothing is sent anywhere.
- **Different from other viewers:**
  1. **Every PDF opens in a sandbox.** PDF is one of the most common ways to attack a computer. The page images
     are drawn by a helper process in bubblewrap (no network, the file read-only, nothing else of yours), the
     same way Diamond Chat re-draws pictures. The window never parses the PDF itself.
  2. **What the file wants to do is shown, never done.** JavaScript, launch actions, form submission to a URL,
     and embedded files are listed in a bar at the top; none of them runs. Links show where they go and ask.
  3. **Hebrew that works:** right-to-left interface, Hebrew search and copy, Hebrew text in annotations and
     forms, OCR in D.Ai's eight languages to make a scanned PDF searchable.
  4. **Honest editing:** what a PDF really allows (pages, forms, annotations, redaction that removes, metadata,
     OCR, compression, signatures), explained plainly, with undo. Rewriting paragraphs in a finished PDF is not
     something any tool does well, and D.Ai does not pretend to.
  5. **Diamond, only when asked:** "summarize", "what does this form want from me", "translate this page",
     through the local model. Off by default on the Lite profile.

## 1. Scope

| Stage | What | Size |
|---|---|---|
| **1. Reader** | Open, pages, zoom, fit, rotate view, search (with Hebrew), copy text, outline, thumbnails, print, metadata, password-protected files, the sandbox helper, the "this file wants to" bar, link policy, D.Ai themes, keyboard and screen reader, default handler for `application/pdf` | Medium |
| **2. Pages and forms** | Reorder, rotate, delete, extract, insert from another PDF, merge, split; fill forms (text, check boxes, choices) and save; flatten forms; annotations: highlight, underline, strike, note, free text (Hebrew), freehand, shapes, stamp a picture (a drawn or scanned signature); undo and redo | Medium |
| **3. Clean and search** | OCR layer for scanned PDFs (ocrmypdf, Tesseract, eight languages); redaction that truly removes; remove metadata before sharing; compress (images down-sampled, with a preview of the size); export pages as pictures; PDF/A conversion where ocrmypdf can | Medium |
| **4. Trust** | Show existing digital signatures and whether they verify; sign with a certificate (**requires a check**: pyHanko is not in Debian 13, see §5); Diamond: summarize and explain, translate a page | Medium |

Out of scope, said plainly: editing the running text of an existing PDF (reflowing paragraphs), XFA forms
(PDFium in Qt does not render them; the file is shown with a notice), 3D and multimedia, DRM-protected files.

## 2. Threat model (short)

| Asset | Threat | Control |
|---|---|---|
| The computer | A crafted PDF exploits the renderer (PDFium, qpdf, fonts) | Rendering and parsing in a bubblewrap helper: no network, read-only file, its own `/tmp`, no home, seccomp from the Chat picture sandbox; the window gets PNG bytes only. qpdf parsing for editing runs in the same kind of helper. Debian security updates for `qt6-pdf`, `qpdf`, `libfreetype` |
| The computer | JavaScript, `Launch`, `GoToR`, `URI` and `SubmitForm` actions | Never executed. Listed in the file bar. A link opens only after a click and a confirmation showing the full target; `file:` and `Launch` are never opened |
| The computer | Embedded files (attachments) that are executables or malware | Listed with name, size and type; saved only to a chosen folder with the executable bit off; scanned with ClamAV when installed (Diamond Chat's `scan.py` is reused); never opened directly |
| Privacy | Metadata and hidden content leak when sharing (author, tool, dates, deleted-but-present objects, hidden layers) | "Prepare for sharing": remove metadata, flatten, and a true redaction that rasterizes the redacted page area and drops the underlying text objects |
| Privacy | The file leaves the computer | No network in the app or its helpers (it inherits the default-deny firewall and has no network code). Diamond runs on the local socket |
| Integrity | Editing corrupts the document | Edits are written to a new file next to the original until "Save"; the original is kept until the save succeeds and verifies (qpdf `--check`); undo history in memory |
| Availability | A huge or recursive PDF freezes the window | The helper has a time limit (per page) and a memory limit (`prlimit`); the window shows "this page could not be drawn" and goes on |

Not covered: a bug in bubblewrap or the kernel itself; a PDF that is itself legitimate but misleading (phishing
in the text: the Chat phishing checks can be run on links in stage 4 if wanted).

## 3. Architecture

```
dai-pdf (PyQt6 window, dai_style, dai_i18n)
 ├─ document.py    model: pages, outline, metadata, "what it wants" findings, undo stack
 ├─ render.py      talks to the helper: page N at DPI D -> PNG bytes; a small cache (a few pages, LRU)
 ├─ helper.py      runs INSIDE bubblewrap: QPdfDocument (python3-pyqt6.qtpdf) renders; pikepdf inspects;
 │                 one request per line on stdin, length-prefixed PNG on stdout; time and memory limits
 ├─ edit.py        pikepdf operations (pages, forms, annotations, metadata, flatten, redact, compress)
 ├─ ocr.py         ocrmypdf as a subprocess (languages from dai_i18n, like dai-ocr)
 ├─ sandbox.py     shared with Diamond Chat's pictures.py (bwrap arguments, limits); moved to dai-i18n/dai_sandbox
 ├─ gui.py         the window: pages view, side panel (thumbnails, outline, search, annotations, attachments),
 │                 the file bar, tools, forms, dialogs; RTL for Hebrew; every action also in the Command bar
 └─ cli.py         dai-pdf FILE; dai-pdf merge A B -o C; split; rotate; ocr; metadata --strip; info
```

- **Rendering:** `QPdfDocument` + `QPdfView` are available in Debian 13 (`python3-pyqt6.qtpdf` 6.9.0-2).
  Because the window must not parse the file, `QPdfView` is not used directly on the file: the helper renders
  pages to PNG at the zoom's DPI, and the window shows them in a scroll view with its own selection overlay.
  Text positions for search and copy come from the helper (`QPdfDocument.getAllText`, `getSelection`).
- **Editing:** `pikepdf` 9.5 (MPL-2.0, on qpdf 12, Apache-2.0): pages, forms (AcroForm), annotations, metadata
  (XMP and Info), encryption, flattening (through qpdf), overlays for stamps and signatures.
- **OCR:** `ocrmypdf` 16.7 (MPL-2.0) with the Tesseract languages already in the image. It needs Ghostscript
  for some operations (AGPL, used as a separate program, which is fine for Apache-2.0 code).
- **Not used:** PyMuPDF (AGPL-3.0: it would change the license of D.Ai's code). Poppler's Qt6 Python binding
  (not in Debian 13).
- **Size added to the image:** roughly 15 MB (qt6-pdf, pikepdf, ocrmypdf and its Python dependencies;
  Ghostscript about 20 MB more; **requires a check** on the built image). qpdfview can then leave the image.

## 4. The window (stage 1 and 2)

- **Top:** the file bar, only when the file "wants" something: "This PDF contains JavaScript (not run)",
  "2 attachments", "a form that would send data to example.com (blocked)", "3 links to the internet".
- **Left (right in Hebrew):** thumbnails, outline, search results, annotations, attachments.
- **Center:** the pages. Continuous or single page; fit width, fit page, zoom 25–800%; rotate view;
  text selection with Hebrew (logical order, not visual order; a known hard case, see §8).
- **Tools (stage 2):** select, hand, highlight, underline, strike, note, text (Hebrew and RTL inside the box),
  draw, shapes, stamp, form fields, redact (stage 3), sign (stage 4).
- **Every action has a sentence** in the Command bar: "rotate page 3", "merge with report.pdf",
  "remove metadata", "make it searchable", "summarize this" (Diamond).
- **Themes:** D.Ai Night, Day and high contrast; the page itself is never recolored, but a "comfortable
  reading" switch dims it and the high-contrast theme can invert the page for reading (a view option, not an
  edit).
- **Keyboard:** everything reachable; page navigation, search (`Ctrl+F`), zoom, tools (single letters as in
  other editors), focus visible. **Screen reader:** the text of the current page is exposed as an accessible
  text; thumbnails and tools have names; the file bar is announced.
- **Lite profile:** no thumbnails until opened, lower render DPI, cache of two pages, Diamond off.

## 5. Decisions needed

1. **The name:** "D.Ai PDF" (recommended, descriptive) or a product name like the other apps (needs a trademark
   check before publishing).
2. **qpdfview:** remove it once stage 1 is the default viewer (saves space, one viewer to maintain), or keep
   both for a release.
3. **Digital signatures (stage 4):** pyHanko (the usual Python library) is **not in Debian 13**. Options:
   (a) verify only, through qpdf and OpenSSL, and sign later; (b) package pyHanko in D.Ai's own apt repo
   (**requires a check** of its dependency tree and license, MIT); (c) sign through LibreOffice, which is in
   the image. Recommendation: (a) now, decide (b) or (c) later.
4. **Diamond in PDFs:** on by default (when a model is installed), or only through an explicit sentence.
   Recommendation: only when asked, as everywhere else in D.Ai.

## 6. Security, privacy and accessibility checklist (per stage)

- Helper runs with: `--unshare-all`, `--ro-bind` the file only, `--tmpfs /tmp`, no `$HOME`, `--die-with-parent`,
  seccomp and `prlimit` (CPU 20 s per page, memory 1 GB), the same arguments as Diamond Chat's picture sandbox.
- No action from the file is ever executed; unit tests feed PDFs with JavaScript, Launch, URI, SubmitForm and
  embedded `.exe` and assert: listed, not run, not opened, not saved executable.
- No network code in the app; the VM check confirms the process has no sockets.
- Logs: file names only in the journal at debug level; never file contents.
- Raz accessibility audit in three themes before merge, like every D.Ai window.
- Screen reader, keyboard-only, zoom 200%, RTL: checked in the VM run with a Hebrew PDF (text, outline, form).

## 7. Tests and verification

- **Unit (offscreen Qt):** render a generated PDF (reportlab is not needed: pikepdf and a hand-written content
  stream make the fixtures); search finds Hebrew and English; copy returns logical-order Hebrew; page operations
  keep the page count and content; forms fill and flatten; metadata strip removes Info and XMP; redaction
  leaves no text under the box; OCR produces a text layer (skipped where Tesseract is absent).
- **Security fixtures:** JS, Launch, URI, SubmitForm, attachments, a 10 000-page file, a recursive object tree,
  an encrypted file with a wrong password.
- **VM check:** open a PDF from the file manager (the default handler), the window appears, the helper runs
  under bwrap, the file bar shows the right notice, `dai-pdf merge` and `dai-pdf ocr` work from the shell.
- **CI (lint job):** `python3-pyqt6.qtpdf python3-pikepdf ocrmypdf bubblewrap` installed; tests run with
  `QT_QPA_PLATFORM=offscreen`; bwrap tests skipped where user namespaces are off.
- **Measure:** the window's memory with a 300-page file on the weak profile (docs/HARDWARE.md).

## 8. Risks and known limits

- **Hebrew text order in PDFs:** many PDFs store Hebrew visually reversed; extraction then gives mirrored text.
  Stage 1 applies a heuristic (reverse runs of Hebrew letters when the file has no bidi marks and the run reads
  backwards against a dictionary of common words). It will not be perfect; the limit is written in the window's
  help and in the accessibility statement.
- **PDFium in Qt and JavaScript:** Qt builds PDFium without V8, so no JS runs even outside the sandbox.
  **Requires a check** against Debian's `qt6-pdf` build options.
- **ocrmypdf and Ghostscript:** Ghostscript has had security bugs; it runs only inside the same bubblewrap helper.
- **Fonts for new Hebrew text:** needs a Hebrew font embedded when adding text (Noto Sans Hebrew or DejaVu;
  **requires a check** of what the image ships).
- **Printing:** through Qt's print dialog and CUPS; the sandboxed helper renders, the window prints the images.
- **Large files:** rendering on demand, cache small, pages beyond the limit shown as "could not be drawn".
- **Legal:** nothing here claims compliance with any standard (PDF/A, signatures law). A signed PDF's legal
  weight **requires legal review** per country.

## 9. Order of work

Stage 1 → Raz and VM checks → screenshots and README row → stage 2 → stage 3 → stage 4. Each stage is a
separate commit series on `docs/os-plan`, with unit tests and the VM check, before the next begins.
