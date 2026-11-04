#!/usr/bin/env python3
"""Processa as imagens novas colocadas em entrada/ e refaz o catalogo."""
import hashlib, json
from pathlib import Path
from banco import *

ENTRADA = RAIZ / 'entrada'
IGNORAR = {'.gitkeep', '.DS_Store', 'LEIA-ME.md', 'Thumbs.db', 'desktop.ini'}
TIPOS = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}


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
    gerar_catalogo()
    (DADOS / 'ultima_atualizacao.json').write_text(json.dumps(dict(processadas=feitos, erros=erros), ensure_ascii=False, indent=1),
                                                  encoding='utf-8')
    print(f'{len(feitos)} imagens processadas, {len(erros)} com erro')
    for k, v in erros.items():
        print('ERRO', k, v)


if __name__ == '__main__':
    main()
