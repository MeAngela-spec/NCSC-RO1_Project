"""NCSC-branded tracking reports. Uses the application's offline Python packages."""
import io
import math
import textwrap
from datetime import datetime

NAVY = "152467"
RED = "D91D35"
CORE = ["Hard Copy Routed", "Ref. No.", "Subject", "Assigned to", "Requested Actions",
        "Action Taken", "MOV 1", "MOV 2", "Status"]
NUMBER_NAMES = {"no", "rowno", "rownumber", "sourcerowno", "sourcerownumber", "serialno", "serialnumber", "sno"}

def is_number_column(name):
    return "".join(char for char in name.lower() if char.isalnum()) in NUMBER_NAMES

def number_records(records):
    return [{**record, "_row_number":next((str(record["cells"].get(h)) for h in record["columns"]
             if is_number_column(h) and record["cells"].get(h)), str(index))}
            for index, record in enumerate(records, 1)]


def columns_for(records):
    extras = list(dict.fromkeys(h for r in records for h in r["columns"] if h not in CORE and not is_number_column(h)))
    return ["No."] + CORE + (extras if len({r["collection_id"] for r in records}) == 1 else sorted(extras,key=str.casefold))


def cell_value(record, column):
    if column == "No.":
        return record.get("_row_number", "")
    if column in ("MOV 1", "MOV 2"):
        return "\n".join(e["name"] + (" [" + e["url"] + "]" if e["type"] == "link" and e["url"] not in e["name"] else "")
                         for e in record.get("movs", {}).get(column, []))
    return str(record["cells"].get(column, ""))


def excel_report(records, title, logo):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.page import PageMargins

    records = number_records(records)
    headers = columns_for(records)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "NCSC Tracking Matrix"
    sheet.sheet_view.showGridLines = False
    last = len(headers)
    for row, text, size, color, bold in [
        (1, "Republic of the Philippines", 10, "555B70", False),
        (2, "NATIONAL COMMISSION OF SENIOR CITIZENS", 16, NAVY, True),
        (3, "Regional Office I", 11, NAVY, True),
        (4, "DOCUMENT TRACKING MATRIX", 13, NAVY, True),
        (5, title, 11, "444B5F", False),
        (6, f"{len(records)} document(s)     Exported {datetime.now():%d %B %Y %I:%M %p}", 10, "626B80", False),
    ]:
        sheet.merge_cells(start_row=row, start_column=2, end_row=row, end_column=last)
        cell = sheet.cell(row, 2, text)
        cell.data_type = "s"
        cell.font = Font(name="Arial", size=size, color=color, bold=bold)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        sheet.row_dimensions[row].height = 24 if row in (2, 4) else 21
    image = Image(str(logo))
    image.width = image.height = 84
    sheet.add_image(image, "A1")
    sheet.row_dimensions[7].height = 8
    header_row = 8
    edge = Side(style="thin", color="DCE2EF")
    for col, heading in enumerate(headers, 1):
        cell = sheet.cell(header_row, col, heading)
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = Border(bottom=Side(style="medium", color=RED))
    sheet.row_dimensions[header_row].height = 36
    widths = {"No.":12, "Hard Copy Routed":19, "Ref. No.":25, "Subject":52, "Assigned to":22,
              "Requested Actions":43, "Action Taken":43, "MOV 1":40, "MOV 2":40, "Status":20}
    for index, heading in enumerate(headers, 1):
        sheet.column_dimensions[get_column_letter(index)].width = widths.get(heading, 32)
    for index, record in enumerate(records, header_row+1):
        lines = 2
        for col, heading in enumerate(headers, 1):
            value = cell_value(record, heading)
            cell = sheet.cell(index, col, value)
            # Imported text that starts with '=' stays text, never a formula.
            cell.data_type = "s"
            if heading == "No." and value.isdigit() and not (len(value)>1 and value.startswith("0")):
                cell.value = int(value)
            cell.font = Font(name="Arial", size=11, color="27314A")
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = Border(bottom=edge)
            if index % 2:
                cell.fill = PatternFill("solid", fgColor="F4F6FC")
            width = widths.get(heading, 32)
            lines = max(lines, sum(max(1, math.ceil(len(line)/max(10, width-3))) for line in value.splitlines()))
        sheet.row_dimensions[index].height = min(409, max(44, lines*15+8))
    sheet.freeze_panes = "D9"
    sheet.auto_filter.ref = f"A8:{get_column_letter(last)}{max(8, sheet.max_row)}"
    sheet.print_title_rows = "1:8"
    sheet.print_options.horizontalCentered = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_margins = PageMargins(left=.25, right=.25, top=.35, bottom=.35, header=.1, footer=.15)
    sheet.oddFooter.left.text = "NCSC Regional Office I"
    sheet.oddFooter.right.text = "Page &P of &N"
    sheet.print_area = f"A1:{get_column_letter(last)}{sheet.max_row}"
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def word_report(records, title, logo, paper="compact"):
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Mm, Pt, RGBColor

    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Mm(297), Mm(210)
    section.top_margin, section.bottom_margin = Mm(29), Mm(16)
    section.left_margin = section.right_margin = Mm(10)
    section.header_distance = Mm(7)
    section.footer_distance = Mm(7)
    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10)
    normal.paragraph_format.space_after = Pt(4)
    for name in ("Title", "Heading 1", "Heading 2"):
        document.styles[name].font.name = "Arial"
        document.styles[name].font.color.rgb = RGBColor.from_string(NAVY)
    head = section.header.add_table(rows=1, cols=2, width=Mm(277))
    head.autofit = False
    head.columns[0].width, head.columns[1].width = Mm(22), Mm(255)
    head.cell(0,0).width, head.cell(0,1).width = Mm(22), Mm(255)
    head.cell(0, 0).paragraphs[0].add_run().add_picture(str(logo), width=Mm(17))
    p = head.cell(0, 1).paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    p.add_run("Republic of the Philippines\n").font.size = Pt(9)
    name = p.add_run("NATIONAL COMMISSION OF SENIOR CITIZENS\n")
    name.bold = True
    name.font.size = Pt(12)
    name.font.color.rgb = RGBColor.from_string(NAVY)
    p.add_run("Regional Office I").font.size = Pt(10)
    # A compact rule separates the repeating agency header from report data.
    props = p._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for key, value in {"val":"single", "sz":"12", "color":RED, "space":"6"}.items():
        bottom.set(qn("w:"+key), value)
    borders.append(bottom)
    props.append(borders)
    section.header.paragraphs[0].paragraph_format.space_after = Pt(0)
    section.header.paragraphs[0].paragraph_format.line_spacing = Pt(1)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer.add_run("NCSC RO1   |   Page ").font.size = Pt(8)
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    records = number_records(records)
    headers = columns_for(records)
    blocks = [headers[:10]] + [["No.", "Ref. No.", "Subject"]+headers[i:i+6] for i in range(10, len(headers), 6)]
    weights = {"No.":.7, "Subject":2.3, "Requested Actions":1.8, "Action Taken":1.8, "MOV 1":1.5, "MOV 2":1.5, "Ref. No.":1.3}
    heights = []
    for headings in blocks:
        total = sum(weights.get(h,1) for h in headings)
        widths = [277*weights.get(h,1)/total*72/25.4-11 for h in headings]
        row_points = 0
        for record in records:
            line_counts = []
            for heading, width in zip(headings, widths):
                chars = max(2,int(width/5.5))
                line_counts.append(sum(max(1,len(textwrap.wrap(line,chars)))
                                       for line in cell_value(record,heading).split("\n")))
            row_points += max(18,max(line_counts)*13+6)
        heights.append(95+row_points*25.4/72)
    shared_height = heights[0] + sum(height-75 for height in heights[1:])
    inline_panels = len(records) <= 4 and shared_height <= 200
    if paper == "compact":
        target = shared_height if inline_panels else max(heights)
        section.page_height = Mm(min(210,max(110,math.ceil(target/5)*5)))
    for block_number, headings in enumerate(blocks):
        if block_number and inline_panels:
            subheading = document.add_paragraph()
            subheading.paragraph_format.space_before = Pt(12)
            subheading.paragraph_format.keep_with_next = True
            run = subheading.add_run("ADDITIONAL FIELDS")
            run.bold = True
            run.font.size = Pt(10)
        else:
            if block_number:
                document.add_page_break()
            title_p = document.add_paragraph()
            title_p.paragraph_format.keep_with_next = True
            run = title_p.add_run("DOCUMENT TRACKING MATRIX" + ("   Additional fields" if block_number else ""))
            run.bold = True
            run.font.size = Pt(13)
            meta = document.add_paragraph(title)
            meta.paragraph_format.keep_with_next = True
            meta.paragraph_format.space_after = Pt(3)
            info = document.add_paragraph(f"{len(records)} document(s)     Exported {datetime.now():%d %B %Y %I:%M %p}")
            info.paragraph_format.keep_with_next = True
            for run in info.runs:
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor.from_string("59637B")
        table = document.add_table(rows=1, cols=len(headings))
        table.autofit = False
        table.style = "Table Grid"
        total = sum(weights.get(h, 1) for h in headings)
        widths = [Mm(277*weights.get(h, 1)/total) for h in headings]
        for col, width in zip(table.columns, widths):
            col.width = width
        repeat = OxmlElement("w:tblHeader")
        table.rows[0]._tr.get_or_add_trPr().append(repeat)
        for index, heading in enumerate(headings):
            cell = table.rows[0].cells[index]
            cell.width = widths[index]
            shade = OxmlElement("w:shd")
            shade.set(qn("w:fill"), NAVY)
            cell._tc.get_or_add_tcPr().append(shade)
            run = cell.paragraphs[0].add_run(heading)
            run.bold = True
            run.font.color.rgb = RGBColor(255, 255, 255)
            run.font.size = Pt(10)
        for row_index, record in enumerate(records):
            cells = table.add_row().cells
            for index, heading in enumerate(headings):
                cell = cells[index]
                cell.width = widths[index]
                # Spaces after slash let long evidence URLs wrap in Word/PDF.
                text = cell_value(record, heading)
                cell.text = text
                for p in cell.paragraphs:
                    p.paragraph_format.space_after = Pt(3)
                    p.paragraph_format.keep_together = False
                    for run in p.runs:
                        run.font.size = Pt(10)
                if row_index % 2 == 0:
                    shade = OxmlElement("w:shd")
                    shade.set(qn("w:fill"), "F2F5FB")
                    cell._tc.get_or_add_tcPr().append(shade)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def make_export(records, title, format, root, convert, paper="compact"):
    if format == "xlsx":
        return excel_report(records, title, root/"assets/seal.png"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if format == "docx":
        return word_report(records, title, root/"assets/seal.png", paper), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if format == "pdf":
        return convert(word_report(records, title, root/"assets/seal.png", paper)), "application/pdf"
    raise ValueError("Choose Excel, PDF or Word export.")
