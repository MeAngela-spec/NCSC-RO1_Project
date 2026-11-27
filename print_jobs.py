"""Short-lived, owner-bound rendered template pages for the native browser print dialog."""
import re
import secrets
import tempfile
import threading
import time
from pathlib import Path

_JOBS={}
_LOCK=threading.RLock()
_TTL=15*60

def _cleanup():
    for token,job in list(_JOBS.items()):
        if job['expires']<time.time():
            job['folder'].cleanup()
            del _JOBS[token]

def create(pdf_bytes, owner, record_ids=None):
    import pypdfium2 as pdfium
    with _LOCK:
        _cleanup()
        folder=tempfile.TemporaryDirectory(prefix='ncsc-native-print-')
        pages=[]
        try:
            with pdfium.PdfDocument(pdf_bytes) as pdf:
                if len(pdf)>200:
                    raise ValueError('This print job exceeds 200 pages. Select fewer documents.')
                for index in range(len(pdf)):
                    page=pdf[index]
                    try:
                        width,height=page.get_size()
                        bitmap=page.render(scale=3)
                        try:
                            bitmap.to_pil().save(Path(folder.name)/f'{index}.png',format='PNG')
                        finally:
                            bitmap.close()
                        pages.append({'index':index,'width_mm':round(width*25.4/72,3),'height_mm':round(height*25.4/72,3)})
                    finally:
                        page.close()
            token=secrets.token_hex(24)
            _JOBS[token]={'owner':owner,'expires':time.time()+_TTL,'folder':folder,'count':len(pages),'records':list(record_ids or [])}
            for page in pages:
                page['url']=f"/api/print-page/{token}/{page['index']}.png"
            return {'pages':pages,'expires_in':_TTL}
        except Exception:
            folder.cleanup()
            raise

def page(token, index, owner, authorize=None):
    with _LOCK:
        _cleanup()
        job=_JOBS.get(token) if re.fullmatch(r'[0-9a-f]{48}',token) else None
        if not job:
            raise ValueError('This print session has expired. Return to the register and choose Print slip again.')
        if job['owner']!=owner:
            raise PermissionError('This print session belongs to another account.')
        if authorize and not authorize(job['records']):
            raise PermissionError('Document access changed. Reopen the register and select accessible documents.')
        if index<0 or index>=job['count']:
            raise ValueError('Print page not found.')
        return (Path(job['folder'].name)/f'{index}.png').read_bytes()
