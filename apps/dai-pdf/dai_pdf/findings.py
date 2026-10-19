# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""What a PDF wants to do (docs/PDF.md §0, point 2): found, listed, never done.

Runs inside the sandbox (the helper imports it) over pikepdf's view of the file. Everything here is a count or
a name: no action is ever followed, no script evaluated, no embedded file opened.

  javascript     document-level or annotation JavaScript (never run: Qt's PDFium has no script engine, and the
                 helper does not either)
  launch         Launch actions (run a program)
  remote         GoToR actions (open another file)
  submit         SubmitForm actions (send the form's data to an address)
  links          URI actions (the internet): shown and asked about, one by one, in the window
  attachments    embedded files: name and size; saved only where the person chooses, never executable
  xfa            an XFA form: Qt's PDFium does not render it, the static page is shown instead
  encrypted      the file is encrypted (a password was needed or an owner password restricts it)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

MAX_WALK = 50_000  # objects looked at before giving up: a recursive or enormous file does not hang the helper


@dataclass
class Findings:
    javascript: int = 0
    launch: int = 0
    remote: int = 0
    submit: int = 0
    links: int = 0
    attachments: list[dict] = field(default_factory=list)  # {"name": ..., "size": ...}
    xfa: bool = False
    encrypted: bool = False
    truncated: bool = False  # the file was too large to look at completely

    def active(self) -> bool:
        """Anything that would act on its own, or reach outside the page, when opened elsewhere."""
        return bool(self.javascript or self.launch or self.remote or self.submit or self.attachments or self.xfa)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Findings":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def _name(value) -> str:
    try:
        return str(value)
    except Exception:  # noqa: BLE001 - a broken object is not a finding, just not a name
        return ""


def _count_action(action, found: Findings) -> None:
    kind = _name(action.get("/S")) if hasattr(action, "get") else ""
    if kind == "/JavaScript":
        found.javascript += 1
    elif kind == "/Launch":
        found.launch += 1
    elif kind == "/GoToR":
        found.remote += 1
    elif kind == "/SubmitForm":
        found.submit += 1
    elif kind == "/URI":
        found.links += 1
    nxt = action.get("/Next") if hasattr(action, "get") else None
    if nxt is not None:
        for item in (nxt if isinstance(nxt, list) or type(nxt).__name__ == "Array" else [nxt]):
            _count_action(item, found)


def scan(pdf) -> Findings:
    """`pdf` is an open pikepdf.Pdf. Looks at the catalog, the name trees, every page's annotations and the
    form fields, counting what would act."""
    import pikepdf

    found = Findings(encrypted=bool(pdf.is_encrypted))
    root = pdf.Root
    looked = 0

    open_action = root.get("/OpenAction")
    if isinstance(open_action, pikepdf.Dictionary):
        _count_action(open_action, found)
    aa = root.get("/AA")
    if isinstance(aa, pikepdf.Dictionary):
        for item in aa.values():
            if isinstance(item, pikepdf.Dictionary):
                _count_action(item, found)

    names = root.get("/Names")
    if isinstance(names, pikepdf.Dictionary):
        if "/JavaScript" in names:
            try:
                found.javascript += max(1, len(pikepdf.NameTree(names["/JavaScript"]).keys()))
            except Exception:  # noqa: BLE001 - a malformed tree still means "there is JavaScript here"
                found.javascript += 1
    try:
        for name, spec in pdf.attachments.items():
            size = 0
            try:
                size = len(spec.get_file().read_bytes())
            except Exception:  # noqa: BLE001 - size unknown is still an attachment
                size = -1
            found.attachments.append({"name": str(name)[:200], "size": size})
            looked += 1
            if looked > 500:
                found.truncated = True
                break
    except Exception:  # noqa: BLE001 - no usable attachment tree
        pass

    form = root.get("/AcroForm")
    if isinstance(form, pikepdf.Dictionary):
        if "/XFA" in form:
            found.xfa = True
        fields = form.get("/Fields")
        if isinstance(fields, pikepdf.Array):
            stack = list(fields)
            while stack and looked < MAX_WALK:
                looked += 1
                item = stack.pop()
                if not isinstance(item, pikepdf.Dictionary):
                    continue
                for key in ("/A", "/AA"):
                    act = item.get(key)
                    if isinstance(act, pikepdf.Dictionary):
                        if key == "/AA":
                            for sub in act.values():
                                if isinstance(sub, pikepdf.Dictionary):
                                    _count_action(sub, found)
                        else:
                            _count_action(act, found)
                kids = item.get("/Kids")
                if isinstance(kids, pikepdf.Array):
                    stack.extend(kids)
            if stack:
                found.truncated = True

    for page in pdf.pages:
        looked += 1
        if looked > MAX_WALK:
            found.truncated = True
            break
        annots = page.obj.get("/Annots")
        if not isinstance(annots, pikepdf.Array):
            continue
        for annot in annots:
            looked += 1
            if not isinstance(annot, pikepdf.Dictionary):
                continue
            act = annot.get("/A")
            if isinstance(act, pikepdf.Dictionary):
                _count_action(act, found)
            aa = annot.get("/AA")
            if isinstance(aa, pikepdf.Dictionary):
                for sub in aa.values():
                    if isinstance(sub, pikepdf.Dictionary):
                        _count_action(sub, found)
            if _name(annot.get("/Subtype")) == "/FileAttachment":
                fs = annot.get("/FS")
                name = _name(fs.get("/UF") or fs.get("/F")) if isinstance(fs, pikepdf.Dictionary) else ""
                found.attachments.append({"name": name[:200] or "attachment", "size": -1})
    return found
