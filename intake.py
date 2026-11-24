"""Local document intake. Nothing connects to an email provider or sends messages."""
import io
import re
from pathlib import Path
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser

MAX_TEXT = 60000

class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'):
            self.skip += 1
        if tag in ('p','br','div','tr','li','h1','h2') and not self.skip:
            self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script','style','head'):
            self.skip = max(0, self.skip - 1)
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

def plain_html(text):
    parser = PlainHTML()
    parser.feed(text[:500000])
    return re.sub(r'\n[ \t]*\n+', '\n\n', ''.join(parser.parts)).strip()[:MAX_TEXT]

def safe_name(value):
    return str(value or 'attachment').replace('\\','/').split('/')[-1][:240] or 'attachment'

def read_eml(raw):
    message = BytesParser(policy=policy.default).parsebytes(raw)
    info = {k:str(message.get(header, '')).strip()[:2000] for k,header in
            [('subject','Subject'),('sender','From'),('to','To'),('sent','Date')]}
    body = message.get_body(preferencelist=('plain','html'))
    try:
        text = body.get_content() if body else ''
        if not isinstance(text, str):
            text = ''
        info['body'] = plain_html(text) if body and body.get_content_subtype() == 'html' else text[:MAX_TEXT]
    except (LookupError, UnicodeError, KeyError):
        info['body'] = ''
    attachments = []
    for part in message.walk():
        if part is message or (not part.get_filename() and part.get_content_disposition() != 'attachment'):
            continue
        data = part.get_payload(decode=True)
        if data is None and part.get_content_type() == 'message/rfc822':
            data = b'\n'.join(p.as_bytes() for p in part.get_payload() if hasattr(p,'as_bytes'))
        if data is not None:
            attachments.append({'name':safe_name(part.get_filename() or 'attachment'), 'data':data})
    return info, attachments

def read_msg(raw):
    """Read common Unicode/ANSI Outlook .msg streams, retaining the original too."""
    import olefile
    try:
        ole = olefile.OleFileIO(io.BytesIO(raw))
    except (OSError, IOError) as exc:
        raise ValueError('This is not a readable Outlook .msg file. Export it as .eml or attach the original file instead.') from exc
    def text(code, base=()):
        for suffix,encoding in [('001F','utf-16-le'),('001E','cp1252')]:
            path = list(base) + ['__substg1.0_'+code+suffix]
            if ole.exists(path):
                return ole.openstream(path).read().decode(encoding,errors='replace').rstrip('\x00')[:MAX_TEXT]
        return ''
    try:
        headers = text('007D')
        parsed = BytesParser(policy=policy.default).parsebytes(headers.encode('utf-8')+b'\r\n\r\n')
        info = {'subject':text('0037'), 'sender':str(parsed.get('From','')) or text('5D01') or text('0C1F') or text('0C1A'),
                'to':str(parsed.get('To','')) or text('0E04'), 'sent':str(parsed.get('Date','')), 'body':text('1000')}
        if not info['body'] and ole.exists('__substg1.0_10130102'):
            info['body'] = plain_html(ole.openstream('__substg1.0_10130102').read().decode('utf-8',errors='replace'))
        attachments=[]
        bases=sorted({path[0] for path in ole.listdir() if path[0].startswith('__attach_version1.0_')})
        skipped=0
        for base in bases:
            path=[base,'__substg1.0_37010102']
            if ole.exists(path):
                attachments.append({'name':safe_name(text('3707',(base,)) or text('3704',(base,)) or 'attachment'),
                                    'data':ole.openstream(path).read()})
            else:
                skipped+=1
        if skipped:
            info['attachment_warning'] = f'{skipped} embedded Outlook items remain inside the original .msg file; open that file in Outlook to view them.'
        return info, attachments
    finally:
        ole.close()

def guessed_subject(text, filename, title=''):
    match=re.search(r'(?im)^\s*(?:subject|re)\s*[:\-]\s*(.+)$', text)
    if match:
        return match.group(1).strip()[:1000]
    if title and title.lower() not in ('untitled','document','microsoft word'):
        return title.strip()[:1000]
    # Unstructured documents use the filename instead of treating the agency letterhead as a subject.
    return Path(filename).stem.replace('_',' ').strip()[:1000]

def intake(filename, raw, parse_table, canonical):
    filename=safe_name(filename)
    suffix=Path(filename).suffix.lower()
    info={'filename':filename, 'type':'Document', 'sender':'', 'to':'', 'sent':'', 'body':''}
    warnings=[]
    attachments=[]
    candidates=[]
    if suffix in ('.eml','.msg'):
        email,attachments=(read_eml if suffix=='.eml' else read_msg)(raw)
        info.update(email)
        info['type']='Email'
        subject=email.get('subject','').strip() or Path(filename).stem
        candidates=[{'label':subject,'cells':{'Subject':subject},'source_reference':''}]
        if email.get('attachment_warning'):
            warnings.append(email['attachment_warning'])
        if not email.get('subject'):
            warnings.append('No email subject was found. The filename is used; review it before saving.')
    elif suffix in ('.xlsx','.csv'):
        info['type']='Spreadsheet'
        parsed=parse_table(filename, raw)
        warnings.extend(parsed.get('warnings',[]))
        for dataset in parsed['datasets']:
            for index,row in enumerate(dataset['rows'],1):
                cells=dict(zip(dataset['columns'],row))
                source_reference=cells.get('Ref. No.','')
                cells={k:v for k,v in cells.items() if k not in ('Ref. No.','Action Taken','MOV 1','MOV 2') and
                       re.sub('[^a-z0-9]','',k.lower()) not in ('no','rowno','rownumber','sourcerowno','sourcerownumber','serialno','serialnumber','sno')}
                candidates.append({'label':f"{dataset['name']} · Row {index} · {cells.get('Subject',Path(filename).stem)}",
                                   'sheet':dataset['name'], 'row':index, 'cells':cells, 'source_reference':source_reference})
        if len(candidates)>1:
            warnings.append('Choose one source row for this document. Use Import file in the register to add a complete tracking matrix.')
        if not candidates:
            raise ValueError('No data rows were found. Use another file or enter the details manually.')
    else:
        text,title='',''
        if suffix=='.pdf':
            import pdfplumber
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                title=str((pdf.metadata or {}).get('Title','') or '')
                text='\n'.join((page.extract_text() or '') for page in pdf.pages[:10])[:MAX_TEXT]
                if len(pdf.pages)>10:
                    warnings.append('Text was read from the first 10 pages. The complete PDF is retained.')
            if not text.strip():
                warnings.append('This PDF appears to be scanned. Review the original and fill in the details; OCR is not included.')
        elif suffix=='.docx':
            from docx import Document
            document=Document(io.BytesIO(raw))
            title=document.core_properties.title or ''
            text='\n'.join([p.text for p in document.paragraphs]+[' | '.join(c.text for c in row.cells) for table in document.tables for row in table.rows])[:MAX_TEXT]
        elif suffix in ('.txt','.log'):
            text=raw.decode('utf-8-sig',errors='replace')[:MAX_TEXT]
        else:
            warnings.append('The original file will be attached. Its filename is used as the subject; enter any remaining details.')
        info['body']=text
        subject=guessed_subject(text,filename,title)
        candidates=[{'label':subject,'cells':{'Subject':subject},'source_reference':''}]
    total=0
    kept=[]
    for attachment in attachments:
        total+=len(attachment['data'])
        if len(kept)>=100 or total>25*1024*1024:
            warnings.append('Some attachments remain inside the original email because of the 100-file / 25 MB extraction limit.')
            break
        kept.append(attachment)
    info.pop('subject',None)
    info.pop('attachment_warning',None)
    info['attachments']=[{'name':a['name'],'size':len(a['data'])} for a in kept]
    # Return only canonical additional headers; never duplicate the core or generate a reference here.
    for candidate in candidates:
        candidate['cells']={canonical(k):str(v)[:20000] for k,v in candidate['cells'].items()}
        candidate['cells'].setdefault('Status','For Routing')
    return {'info':info, 'candidates':candidates, 'warnings':list(dict.fromkeys(warnings)), 'attachments':kept}
