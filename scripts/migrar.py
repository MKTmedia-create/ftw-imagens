#!/usr/bin/env python3
"""Migracao inicial: baixa os 2.077 links da planilha, gera versoes e envia originais. Pode ser retomada."""
import csv, hashlib, json, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote, urlsplit
import requests
from banco import *

INICIO = time.time()
LIMITE_S = 5 * 3600
BLOCO = 150
ARQ_ERROS = DADOS / 'erros_migracao.json'
sess = requests.Session(); sess.headers['User-Agent'] = 'ftw-imagens-migracao'
trava = threading.Lock()


def plano():
    linhas = list(csv.DictReader(open(DADOS / 'links_origem.csv', encoding='utf-8')))
    usados, saida = set(), []
    for r in linhas:
        p = limpar_caminho(urlsplit(r['url']).path)
        ext = '.' + p.rsplit('.', 1)[-1].lower()
        rel = p.rsplit('.', 1)[0]
        base, n = rel, 2
        while rel.lower() in usados:
            rel = f'{base}_{n}'; n += 1
        usados.add(rel.lower())
        saida.append(dict(url=r['url'], rel=rel, ext=ext, marca=rel.split('/')[0]))
    return saida


def baixar(url):
    for t in range(5):
        try:
            r = sess.get(url, timeout=300)
            if r.status_code == 200:
                cl = r.headers.get('Content-Length')
                if cl and int(cl) != len(r.content):
                    raise IOError('download incompleto')
                return r.content
            err = f'HTTP {r.status_code}'
        except Exception as e:
            err = str(e)[:150]
        time.sleep(5 * (t + 1))
    raise IOError(err)


def git_salvar(msg):
    subprocess.run(['git', 'add', 'produtos', 'miniaturas', 'dados'], check=True, cwd=RAIZ)
    if subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=RAIZ).returncode == 0:
        return
    subprocess.run(['git', 'commit', '-qm', msg + ' [skip ci]'], check=True, cwd=RAIZ)
    for t in range(6):
        subprocess.run(['git', 'pull', '-q', '--rebase', 'origin', 'migracao'], cwd=RAIZ)
        if subprocess.run(['git', 'push', '-q', 'origin', 'HEAD:migracao'], cwd=RAIZ).returncode == 0:
            return
        time.sleep(15)
    raise RuntimeError('nao consegui enviar ao GitHub')


def main():
    PRODUTOS.mkdir(exist_ok=True); MINIATURAS.mkdir(exist_ok=True)
    itens = plano()
    meta = ler_originais()
    pend = [x for x in itens if x['rel'] not in meta]
    print(f'{len(itens)} no plano, {len(pend)} pendentes', flush=True)
    orig = Originais()
    erros = {}

    def trabalhar(x):
        dados = baixar(x['url'])
        c = converter(dados)
        tag = orig.release_de(x['marca'])
        with trava:
            nome = nome_asset(x['rel'], x['ext'], meta, tag)
            meta[x['rel']] = dict(tag=tag, asset=nome, reservado=True)
        tipo = 'image/png' if x['ext'] == '.png' else 'image/jpeg'
        orig.enviar(tag, nome, dados, tipo)
        with trava:
            gravar_versoes(x['rel'], c)
            meta[x['rel']] = dict(tag=tag, asset=nome, bytes=len(dados), w=c['w'], h=c['h'], alpha=c['alpha'],
                                  sha=hashlib.sha256(dados).hexdigest()[:16], origem=x['url'])

    feitos = 0
    with ThreadPoolExecutor(5) as ex:
        i = 0
        while i < len(pend) and time.time() - INICIO < LIMITE_S:
            lote = pend[i:i + BLOCO]; i += BLOCO
            fs = {ex.submit(trabalhar, x): x for x in lote}
            for f in as_completed(fs):
                x = fs[f]
                try:
                    f.result(); feitos += 1
                except Exception as e:
                    erros[x['url']] = str(e)[:200]
                    meta.pop(x['rel'], None)
                    print('ERRO', x['url'], e, flush=True)
            salvar_originais(meta)
            ARQ_ERROS.write_text(json.dumps(erros, ensure_ascii=False, indent=1), encoding='utf-8')
            git_salvar(f'Migracao: {len(meta)}/{len(itens)} imagens')
            print(f'{len(meta)}/{len(itens)} em {int(time.time()-INICIO)}s', flush=True)

    falta = [x for x in itens if x['rel'] not in meta]
    pesos = sum(p.stat().st_size for d in (PRODUTOS, MINIATURAS) for p in d.rglob('*') if p.is_file())
    dup = {}
    for k, v in meta.items():
        dup.setdefault(v.get('sha'), []).append(k)
    relatorio = dict(no_plano=len(itens), migradas=len(meta), faltando=len(falta), erros=len(erros),
                     bytes_originais=sum(v.get('bytes', 0) for v in meta.values()),
                     mb_versoes_site_e_miniaturas=round(pesos / 1e6), segundos=int(time.time() - INICIO),
                     identicos=[v for v in dup.values() if len(v) > 1])
    (DADOS / 'relatorio_migracao.json').write_text(json.dumps(relatorio, ensure_ascii=False, indent=1), encoding='utf-8')
    if not falta:
        gerar_catalogo()
        subprocess.run(['git', 'add', 'site'], cwd=RAIZ)
    git_salvar(f'Migracao concluida: {len(meta)}/{len(itens)}' if not falta else f'Migracao parcial: {len(meta)}/{len(itens)}')
    print({k: v for k, v in relatorio.items() if k != 'identicos'})


if __name__ == '__main__':
    main()
