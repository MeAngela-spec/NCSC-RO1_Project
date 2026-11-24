"""Readable browser printing, using the supplied routing slip's letterhead.

Keep a fixed 10 pt body instead of squeezing an arbitrary number of columns
onto one page. Every continuation section repeats the document identifiers.
"""
from datetime import datetime
from html import escape
import re

CORE = ["Hard Copy Routed", "Ref. No.", "Subject", "Assigned to",
        "Requested Actions", "Action Taken", "MOV 1", "MOV 2", "Status"]
SERIALS = {"no", "rowno", "rownumber", "sourcerowno", "sourcerownumber",
           "serialno", "serialnumber", "sno"}


def is_serial(column):
    return re.sub(r"[^a-z0-9]", "", column.lower()) in SERIALS


def printed_cell(record, column, index):
    if column == "No.":
        for name in record["columns"]:
            value = str(record["cells"].get(name, "")).strip()
            if is_serial(name) and value:
                return value
        return str(index + 1)
    if column in ("MOV 1", "MOV 2"):
        return "\n".join(entry["name"] for entry in record.get("movs", {}).get(column, []))
    return str(record["cells"].get(column, ""))


def column_bands(columns):
    bands = [
        ("Routing details", ["No.", "Hard Copy Routed", "Ref. No.", "Subject",
                             "Assigned to", "Requested Actions"], [10, 26, 35, 78, 32, 96]),
        ("Action, supporting documents and status", ["No.", "Ref. No.", "Subject",
                             "Action Taken", "MOV 1", "MOV 2", "Status"], [10, 35, 70, 58, 39, 39, 26]),
    ]
    extras = [column for column in columns if column not in CORE and not is_serial(column)]
    for start in range(0, len(extras), 3):
        group = extras[start:start + 3]
        bands.append(("Additional imported fields", ["No.", "Ref. No.", "Subject", *group],
                      [10, 35, 70] + [162 / len(group)] * len(group)))
    return bands


def matrix_html(records, requested_columns=None):
    available = list(dict.fromkeys(column for record in records for column in record["columns"]))
    columns = requested_columns if isinstance(requested_columns, list) else available
    if any(not isinstance(column, str) or column not in ["No.", *available] for column in columns):
        raise ValueError("The matrix columns changed. Refresh the register before printing.")
    # Required tracking fields always print. Keep meaningful extra fields in their visible order.
    columns = list(dict.fromkeys([*CORE, *columns]))
    bands = column_bands(columns)
    generated = escape(datetime.now().astimezone().strftime("%d %B %Y, %I:%M %p"))
    sections = []
    for part, (title, fields, widths) in enumerate(bands, 1):
        heading = (
            '<tr class="letterhead-row"><td colspan="' + str(len(fields)) + '">'
            '<img class="letterhead" src="/assets/matrix-letterhead.png" '
            'alt="Republic of the Philippines — National Commission of Senior Citizens; official routing slip letterhead">'
            '<h1>DOCUMENT TRACKING MATRIX</h1>'
            '<div class="report-meta"><span>Regional Office I · ' + str(len(records)) + ' document(s)</span>'
            '<span>Generated ' + generated + '</span></div>'
            '<div class="section-label"><strong>' + escape(title) + '</strong>'
            '<span>Section ' + str(part) + ' of ' + str(len(bands)) + '</span></div></td></tr>'
        )
        rows = ''.join(
            '<tr>' + ''.join('<td' + (' class="serial"' if column == 'No.' else '') + '>' +
                escape(printed_cell(record, column, index)) + '</td>' for column in fields) + '</tr>'
            for index, record in enumerate(records)
        )
        sections.append('<section class="matrix-section"><table><colgroup>' +
                        ''.join('<col style="width:' + str(round(width, 4)) + 'mm">' for width in widths) +
                        '</colgroup><thead>' + heading + '<tr>' +
                        ''.join('<th scope="col">' + escape(column) + '</th>' for column in fields) +
                        '</tr></thead><tbody>' + rows + '</tbody></table></section>')
    return '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NCSC RO1 · Document Tracking Matrix</title>
<style>
@page { size: A4 landscape; margin: 10mm; }
* { box-sizing: border-box; }
body { margin: 0; color: #141414; background: #edf0f6; font-family: Arial, sans-serif; }
.print-toolbar { padding: 16px 24px; background: #14104f; color: white; display: flex; align-items: center; gap: 18px; font-size: 14px; }
.print-toolbar p { flex: 1; margin: 0; line-height: 1.5; }
.print-toolbar button { background: white; color: #213d94; font: bold 14px Arial,sans-serif; border: 0; border-radius: 6px; padding: 11px 16px; cursor: pointer; }
.print-toolbar a { color: white; }
main { padding: 24px; overflow-x: auto; }
.matrix-section { width: 277mm; margin: 0 auto 24px; background: white; padding: 0; }
table { width: 277mm; border-collapse: collapse; table-layout: fixed; }
thead { display: table-header-group; }
tr { break-inside: avoid; page-break-inside: avoid; }
th, td { border: .25mm solid #555; padding: 2.2mm 2mm; font: 10pt/1.35 Arial,sans-serif; text-align: left; vertical-align: top; white-space: pre-wrap; overflow-wrap: anywhere; word-wrap: break-word; }
th { background: #f0f2f7; font-weight: bold; vertical-align: middle; }
.serial { text-align: center; }
.letterhead-row td { border: 0; padding: 0 0 3mm; white-space: normal; }
.letterhead { display: block; width: 186mm; height: auto; margin: 0 auto 3mm; }
h1 { font: bold 14pt/1.3 Arial,sans-serif; text-align: center; margin: 0 0 3mm; }
.report-meta, .section-label { display: flex; justify-content: space-between; gap: 6mm; font: 10pt/1.35 Arial,sans-serif; }
.report-meta { margin-bottom: 2mm; }
.section-label { border-top: .5mm solid #213d94; padding-top: 2mm; }
@media print {
 body { background: white; }
 .print-toolbar { display: none; }
 main { padding: 0; overflow: visible; }
 .matrix-section { margin: 0; break-before: page; page-break-before: always; }
 .matrix-section:first-child { break-before: auto; page-break-before: auto; }
}
</style><script src="/assets/matrix-print.js" defer></script></head><body>
<header class="print-toolbar"><p><strong>NCSC RO1 · Print matrix</strong><br>
A4 landscape · Routing and follow-up details use separate sections with matching reference numbers.</p>
<button type="button" id="printMatrixAgain">Open print dialog</button>
<a href="/?page=documents">Back to register</a></header><main>''' + ''.join(sections) + '</main></body></html>'
