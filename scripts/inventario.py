#!/usr/bin/env python3
"""Mede tamanho e disponibilidade de todos os links da planilha (nao baixa tudo)."""
import csv, io, json, statistics, sys, time
from concurrent.futures import ThreadPoolExecutor
import requests
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
rows = list(csv.DictReader(open('dados/links_origem.csv', encoding='utf-8')))
S = requests.Session()
S.headers['User-Agent'] = 'ftw-imagens-inventario'

def medir(r):
    u = r['url']
    for t in range(3):
        try:
            x = S.head(u, timeout=40, allow_redirects=True)
            size = x.headers.get('Content-Length')
            if x.status_code in (403, 405) or size is None:
                x = S.get(u, timeout=60, stream=True); size = x.headers.get('Content-Length'); x.close()
            return dict(url=u, aba=r['aba'], status=x.status_code, bytes=int(size or 0),
                        tipo=x.headers.get('Content-Type', ''), mod=x.headers.get('Last-Modified', ''))
        except Exception as e:
            err = str(e)[:120]; time.sleep(2 * (t + 1))
    return dict(url=u, aba=r['aba'], status=0, bytes=0, tipo='', mod='', erro=err)

with ThreadPoolExecutor(12) as ex:
    res = list(ex.map(medir, rows))

ok = [r for r in res if r['status'] == 200]
rel = dict(total=len(res), ok=len(ok), falhas=[r for r in res if r['status'] != 200][:200],
           total_gb=round(sum(r['bytes'] for r in ok) / 1e9, 2),
           sem_tamanho=sum(1 for r in ok if not r['bytes']),
           maior_mb=round(max([r['bytes'] for r in ok] or [0]) / 1e6, 1),
           mediana_mb=round(statistics.median([r['bytes'] for r in ok] or [0]) / 1e6, 2),
           acima_100mb=sum(1 for r in ok if r['bytes'] > 100e6),
           por_aba={a: dict(n=sum(1 for r in ok if r['aba'] == a),
                            gb=round(sum(r['bytes'] for r in ok if r['aba'] == a) / 1e9, 2))
                    for a in sorted({r['aba'] for r in res})})

# amostra: reencode para estimar tamanho das versoes web
step = max(1, len(ok) // 40)
am = []
for r in ok[::step]:
    try:
        b = S.get(r['url'], timeout=120).content
        im = Image.open(io.BytesIO(b)); im.load()
        info = dict(url=r['url'], mb=round(len(b) / 1e6, 2), dim=im.size, modo=im.mode)
        alpha = im.mode in ('RGBA', 'LA', 'P') and im.convert('RGBA').getextrema()[3][0] < 255
        info['alpha'] = bool(alpha)
        for lado in (2000, 1200):
            c = im.convert('RGBA' if alpha else 'RGB'); c.thumbnail((lado, lado), Image.LANCZOS)
            o = io.BytesIO(); c.save(o, 'WEBP', quality=88, method=4); info[f'webp{lado}_kb'] = len(o.getvalue()) // 1024
            o = io.BytesIO(); c.save(o, 'PNG', optimize=True); info[f'png{lado}_kb'] = len(o.getvalue()) // 1024
        am.append(info)
    except Exception as e:
        am.append(dict(url=r['url'], erro=str(e)[:150]))
rel['amostra'] = am
for k in ('webp2000_kb', 'png2000_kb', 'webp1200_kb', 'png1200_kb'):
    v = [a[k] for a in am if k in a]
    if v:
        rel[f'media_{k}'] = int(statistics.mean(v))
json.dump(rel, open('dados/inventario.json', 'w'), indent=1, ensure_ascii=False)
json.dump(res, open('dados/inventario_links.json', 'w'), ensure_ascii=False)
print({k: v for k, v in rel.items() if k not in ('amostra', 'falhas')})
