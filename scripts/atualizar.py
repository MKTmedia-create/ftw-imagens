#!/usr/bin/env python3
"""Processa as imagens novas colocadas em entrada/ e refaz o catalogo."""
import hashlib, json, time
from pathlib import Path
from banco import *

ENTRADA = RAIZ / 'entrada'
IGNORAR = {'.gitkeep', '.DS_Store', 'LEIA-ME.md', 'Thumbs.db', 'desktop.ini'}
TIPOS = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}


LIMITE_NOMES_S = 95 * 60


def sincronizar_nomes(cat, orig):
    """Deixa cada original na release com o nome EAN_Marca_Nome. Retoma de onde parou."""
    meta = ler_originais()
    inicio = time.time()
    feitos, falhas, pendentes = 0, {}, 0
    for g in cat['grupos']:
        for it in g['i']:
            chave = f"{g['p']}/{it['a'].rsplit('.', 1)[0]}"
            m = meta.get(chave)
            if not m or not m.get('asset'):
                continue
            novo = f"{it['dn']}.{m['asset'].rsplit('.', 1)[-1].lower()}"
            if m['asset'] == novo:
                continue
            if time.time() - inicio > LIMITE_NOMES_S:
                pendentes += 1
                continue
            try:
                orig.renomear(m['tag'], m['asset'], novo)
                m['asset'] = novo
                feitos += 1
                time.sleep(0.7)
            except Exception as e:
                falhas[chave] = str(e)[:200]
            if feitos % 100 == 0:
                salvar_originais(meta)
                print(f'{feitos} nomes atualizados', flush=True)
    salvar_originais(meta)
    print(f'nomes: {feitos} atualizados, {pendentes} pendentes, {len(falhas)} falhas', flush=True)
    return dict(renomeados=feitos, pendentes=pendentes, falhas=falhas)


def main():
    novos = [p for p in ENTRADA.rglob('*') if p.is_file() and p.name not in IGNORAR]
    erros, feitos = {}, []
    if novos:
        meta = ler_originais()
        orig = Originais()
        for p in novos:
            relp = p.relative_to(ENTRADA).as_posix()
            ext = p.suffix.lower()
            partes = relp.split('/')
            marca = marca_oficial(partes[0]) if len(partes) > 1 else None
            if ext not in TIPOS:
                erros[relp] = 'Formato nao aceito: use PNG ou JPG.'; continue
            if not marca:
                erros[relp] = 'Coloque a imagem dentro de uma pasta de marca: FTW, DiaboVerde, Delicious ou Acessorios.'; continue
            if len(partes) < 3:
                erros[relp] = 'Crie uma pasta com o nome do produto dentro da pasta da marca.'; continue
            limpo = limpar_caminho('/'.join(partes[1:]))
            rel = marca + '/' + limpo.rsplit('.', 1)[0]
            try:
                dados = p.read_bytes()
                c = converter(dados)
                ant = meta.get(rel)
                if ant and ant.get('asset', '').endswith(ext.replace('jpeg', 'jpg')):
                    tag, nome = ant['tag'], ant['asset']
                    orig.rel.setdefault(tag, orig._carregar(tag))
                else:
                    tag = orig.release_de(marca)
                    nome = nome_asset(rel, '.jpg' if ext == '.jpeg' else ext, meta, tag)
                orig.enviar(tag, nome, dados, TIPOS[ext])
                gravar_versoes(rel, c)
                meta[rel] = dict(tag=tag, asset=nome, bytes=len(dados), w=c['w'], h=c['h'], alpha=c['alpha'],
                                 sha=hashlib.sha256(dados).hexdigest()[:16], origem=(ant or {}).get('origem', ''))
                p.unlink()
                feitos.append(rel)
            except Exception as e:
                erros[relp] = str(e)[:200]
        salvar_originais(meta)
        for d in sorted((x for x in ENTRADA.rglob('*') if x.is_dir()), key=lambda x: -len(x.parts)):
            if not any(d.iterdir()):
                d.rmdir()
    cat = gerar_catalogo()
    nomes = sincronizar_nomes(cat, Originais())
    gerar_catalogo()
    (DADOS / 'ultima_atualizacao.json').write_text(json.dumps(dict(processadas=feitos, erros=erros, nomes=nomes), ensure_ascii=False, indent=1),
                                                  encoding='utf-8')
    print(f'{len(feitos)} imagens processadas, {len(erros)} com erro')
    for k, v in erros.items():
        print('ERRO', k, v)


if __name__ == '__main__':
    main()
