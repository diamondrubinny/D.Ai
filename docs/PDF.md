# D.Ai PDF: a native reader and editor (plan for approval)

> Written on 2026-10-19 after "build a native PDF reader and editor feature". Nothing is built yet.
> The name "D.Ai PDF" is descriptive, like "D.Ai OCR": no new brand, nothing new to check for trademarks.

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
