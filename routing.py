"""Fill NCSC routing sheets with consistent document text and compact batch rows."""
import copy
import io
import math
import textwrap
from datetime import datetime
from zipfile import ZipFile
from lxml import etree

NS = {"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{"+NS["w"]+"}"
FONT = "Arial"
FONT_SIZE = "20"  # OOXML half points: 10 pt for every filled field.
ROW_BUDGET = 330  # Leave room for the original letterhead, table headings and complete action legend.

def printed_date(value):
    text = str(value or "")
    for format in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, format).strftime("%d %b\n%Y")
        except ValueError:
            pass
    return text


def put_cell(cell, value, bold=False, align=None):
    """Replace cell content, retaining cell geometry and setting a common font."""
    paragraphs = cell.findall("w:p", NS)
    paragraph = paragraphs[0] if paragraphs else etree.SubElement(cell, W+"p")
    prior = cell.find(".//w:rPr", NS)
    props = copy.deepcopy(prior) if prior is not None else etree.Element(W+"rPr")
    for other in paragraphs[1:]:
        cell.remove(other)
    for child in list(paragraph):
        if child.tag != W+"pPr":
            paragraph.remove(child)
    pprops = paragraph.find("w:pPr", NS)
    if pprops is None:
        pprops = etree.Element(W+"pPr")
        paragraph.insert(0, pprops)
    spacing = pprops.find("w:spacing", NS)
    if spacing is None:
        spacing = etree.SubElement(pprops, W+"spacing")
    for key, val in {"before":"0", "after":"0", "line":"240", "lineRule":"auto"}.items():
        spacing.set(W+key, val)
    snap = pprops.find("w:snapToGrid",NS)
    if snap is None:
        snap=etree.SubElement(pprops,W+"snapToGrid")
    snap.set(W+"val","0")
    if align:
        justify = pprops.find("w:jc", NS)
        if justify is None:
            justify = etree.SubElement(pprops, W+"jc")
        justify.set(W+"val", align)
    for key in ("rFonts", "sz", "szCs", "b", "bCs", "color"):
        for old in props.findall("w:"+key, NS):
            props.remove(old)
    fonts = etree.SubElement(props, W+"rFonts")
    for key in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(W+key, FONT)
    for key in ("sz", "szCs"):
        etree.SubElement(props, W+key).set(W+"val", FONT_SIZE)
    for key in ("b", "bCs"):
        etree.SubElement(props, W+key).set(W+"val", "1" if bold else "0")
    etree.SubElement(props, W+"color").set(W+"val", "000000")
    run = etree.SubElement(paragraph, W+"r")
    run.append(props)
    for index, line in enumerate(str(value or "").split("\n")):
        if index:
            etree.SubElement(run, W+"br")
        text = etree.SubElement(run, W+"t")
        text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text.text = line


def _height(values, widths):
    # Use the same 10 pt font on every row; paginate instead of shrinking text.
    lines = max(sum(max(1, math.ceil(len(line)/max(4, (width-10)/5.5))) for line in value.split("\n"))
                for value, width in zip(values, widths))
    return max(48, lines*13+12)

def _row_parts(values, widths):
    """Continue long entries on another sheet rather than reduce the common font."""
    wrapped = [[part for line in value.split("\n") for part in
                (textwrap.wrap(line,width=max(4,int((width-10)/5.5)),replace_whitespace=False,
                               drop_whitespace=False) or [""])] for value,width in zip(values,widths)]
    for offset in range(0,max(map(len,wrapped)),24):
        yield ["\n".join(lines[offset:offset+24]) if len(lines)>24 else values[index] if index!=5 or offset==0 else ""
               for index,lines in enumerate(wrapped)]

def format_row(row, values, widths):
    props = row.find("w:trPr",NS)
    if props is None:
        props=etree.Element(W+"trPr");row.insert(0,props)
    height = props.find("w:trHeight",NS)
    if height is None:
        height=etree.SubElement(props,W+"trHeight")
    height.set(W+"val",str(int(_height(values,widths)*20)))
    height.set(W+"hRule","atLeast")
    if props.find("w:cantSplit",NS) is None:
        etree.SubElement(props,W+"cantSplit")
    for cell,text in zip(row.findall("w:tc",NS),values):
        put_cell(cell,text,align="center")
        cell_props=cell.find("w:tcPr",NS)
        valign=cell_props.find("w:vAlign",NS)
        if valign is None:
            valign=etree.SubElement(cell_props,W+"vAlign")
        valign.set(W+"val","center")
        margins=cell_props.find("w:tcMar",NS)
        if margins is None:
            margins=etree.SubElement(cell_props,W+"tcMar")
        for side in ("top","bottom","left","right"):
            item=margins.find("w:"+side,NS)
            if item is None:
                item=etree.SubElement(margins,W+side)
            item.set(W+"w","80");item.set(W+"type","dxa")


def combined_sheet(template, rows, subject="SELECTED DOCUMENTS", reference=None):
    """One selected document per row, sharing each original NCSC sheet."""
    with ZipFile(template) as source:
        root = etree.fromstring(source.read("word/document.xml"))
        body = root.find("w:body", NS)
        original = [copy.deepcopy(child) for child in body if child.tag != W+"sectPr"]
        section = body.find("w:sectPr", NS)
        table = [child for child in original if child.tag == W+"tbl"][1]
        model = table.findall("w:tr", NS)[2]
        widths = [int(cell.find("w:tcPr/w:tcW", NS).get(W+"w"))/20 for cell in model.findall("w:tc", NS)]
        pages, current, used = [], [], 0
        for row in rows:
            values = [row.get(key, "") for key in ("from", "sign", "to", "date", "time", "note", "received")]
            for fields in _row_parts(values,widths):
                height = _height(fields, widths)
                if current and (used+height > ROW_BUDGET or len(current) >= 6):
                    pages.append(current)
                    current, used = [], 0
                current.append(fields)
                used += height
        if current:
            pages.append(current)
        for child in list(body):
            if child is not section:
                body.remove(child)
        for index, values in enumerate(pages):
            if index:
                paragraph = etree.Element(W+"p")
                etree.SubElement(etree.SubElement(paragraph, W+"r"), W+"br").set(W+"type", "page")
                body.insert(body.index(section), paragraph)
            page = [copy.deepcopy(child) for child in original]
            tables = [child for child in page if child.tag == W+"tbl"]
            heads = tables[0].findall("w:tr", NS)[1].findall("w:tc", NS)
            put_cell(heads[0], "SUBJECT  : "+subject, bold=True)
            put_cell(heads[1], "DRN  : "+reference if reference is not None else f"BATCH  : {index+1} / {len(pages)}", bold=True)
            data_table = tables[1]
            existing = data_table.findall("w:tr", NS)
            for header in existing[:2]:
                props = header.find("w:trPr", NS)
                if props is None:
                    props = etree.Element(W+"trPr")
                    header.insert(0, props)
                if props.find("w:tblHeader", NS) is None:
                    etree.SubElement(props, W+"tblHeader")
            for old in existing[2:]:
                data_table.remove(old)
            for fields in values:
                new = copy.deepcopy(model)
                format_row(new,fields,widths)
                data_table.append(new)
            if reference is not None:
                used=sum(_height(fields,widths) for fields in values)
                while used+48<=ROW_BUDGET:
                    blank=copy.deepcopy(model)
                    format_row(blank,[""]*7,widths)
                    data_table.append(blank);used+=48
            for child in page:
                body.insert(body.index(section), child)
        output = io.BytesIO()
        with ZipFile(output, "w") as destination:
            for info in source.infolist():
                destination.writestr(info, etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                                    if info.filename == "word/document.xml" else source.read(info.filename))
        return output.getvalue()
