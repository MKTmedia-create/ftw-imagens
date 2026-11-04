"""Funcoes do banco de imagens: nomes, conversao, GitHub Releases e catalogo."""
import csv, hashlib, io, json, os, re, shutil, subprocess, tempfile, threading, time, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import requests
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
RAIZ = Path(__file__).resolve().parent.parent
PRODUTOS = RAIZ / 'produtos'
MINIATURAS = RAIZ / 'miniaturas'
DADOS = RAIZ / 'dados'
ARQ_ORIGINAIS = DADOS / 'originais.json'
ARQ_CATALOGO = RAIZ / 'site' / 'catalogo.json'
REPO = os.environ.get('GITHUB_REPOSITORY', 'MKTmedia-create/ftw-imagens')
DONO, NOME_REPO = REPO.split('/')
BASE_SITE = f'https://{DONO.lower()}.github.io/{NOME_REPO}'
LADO_SITE, QUALIDADE_SITE = 1600, 85
LADO_MINI, QUALIDADE_MINI = 480, 78
MARCAS = {'ftw': 'FTW', 'diaboverde': 'DiaboVerde', 'delicious': 'Delicious', 'acessorios': 'Acessorios'}
ROTULO_MARCA = {'FTW': 'FTW Suplementos', 'DiaboVerde': 'Diabo Verde', 'Delicious': 'Delicious', 'Acessorios': 'Acessórios'}


# ---------- nomes ----------
def limpar_segmento(s):
    s = unicodedata.normalize('NFKD', unquote(s)).encode('ascii', 'ignore').decode()
    s = re.sub(r'\s*-\s+|\s+-\s*', '_', s)          # " - " vira _
    s = s.replace('_-_', '_')
    s = re.sub(r'[^A-Za-z0-9._-]+', '_', s)
    s = re.sub(r'(?<=[A-Za-z])20(?=[A-Za-z])', '_', s)  # resto de %20 (Peptide20Protein)
    s = re.sub(r'(?<![0-9])(100|35)25(?=_|$|[A-Za-z.])', r'\1', s)  # resto de %25 (Whey_10025 = Whey 100%)
    s = re.sub(r'_{2,}', '_', s)
    s = re.sub(r'_+(?=\.[A-Za-z0-9]+$)', '', s)  # "nome_(1)_.png" -> "nome_1.png"
    return s.strip('.') or 'sem_nome'


def limpar_caminho(p):
    return '/'.join(limpar_segmento(x) for x in p.split('/') if x)


def marca_oficial(seg):
    return MARCAS.get(re.sub(r'[^a-z]', '', limpar_segmento(seg).lower()))


# ---------- conversao ----------
def tem_transparencia(im):
    if im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info):
        return im.convert('RGBA').getextrema()[3][0] < 250
    return False


def png_leve(im):
    """PNG com transparencia, comprimido com pngquant quando disponivel."""
    with tempfile.TemporaryDirectory() as d:
        a = Path(d) / 'a.png'
        im.save(a, 'PNG', optimize=False)
        b = Path(d) / 'b.png'
        if shutil.which('pngquant'):
            r = subprocess.run(['pngquant', '--quality=65-95', '--speed', '3', '--force', '--output', str(b), str(a)],
                               capture_output=True)
            if r.returncode == 0 and b.exists():
                return b.read_bytes()
        o = io.BytesIO(); im.save(o, 'PNG', optimize=True)
        return o.getvalue()


def converter(dados):
    """Recebe bytes do original; devolve dict com versao site e miniatura."""
    im = Image.open(io.BytesIO(dados)); im.load()
    w, h = im.size
    alpha = tem_transparencia(im)
    base = im.convert('RGBA' if alpha else 'RGB')
    s = base.copy(); s.thumbnail((LADO_SITE, LADO_SITE), Image.LANCZOS)
    if alpha:
        web, ext = png_leve(s), 'png'
    else:
        o = io.BytesIO(); s.save(o, 'JPEG', quality=QUALIDADE_SITE, optimize=True, progressive=True, subsampling=0)
        web, ext = o.getvalue(), 'jpg'
    t = s.copy(); t.thumbnail((LADO_MINI, LADO_MINI), Image.LANCZOS)
    o = io.BytesIO(); t.save(o, 'WEBP', quality=QUALIDADE_MINI, method=5)
    return dict(web=web, ext=ext, mini=o.getvalue(), w=w, h=h, alpha=alpha, web_lado=max(s.size))


def gravar_versoes(rel, c):
    """rel = caminho sem extensao (FTW/linha/arquivo). Grava site e miniatura, apaga extensao antiga."""
    for velha in PRODUTOS.glob(rel.replace('[', '[[]') + '.*'):
        velha.unlink()
    alvo = PRODUTOS / f"{rel}.{c['ext']}"
    alvo.parent.mkdir(parents=True, exist_ok=True); alvo.write_bytes(c['web'])
    mini = MINIATURAS / f'{rel}.webp'
    mini.parent.mkdir(parents=True, exist_ok=True); mini.write_bytes(c['mini'])
    return alvo.name


# ---------- GitHub Releases (originais) ----------
class Originais:
    LIMITE = 990

    def __init__(self):
        tok = os.environ['GITHUB_TOKEN']
        self.s = requests.Session()
        self.s.headers.update({'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json',
                               'X-GitHub-Api-Version': '2022-11-28'})
        self.api = f'https://api.github.com/repos/{REPO}'
        self.lock = threading.Lock()
        self.rel = {}  # tag -> {id, assets:{nome:{id,size}}}

    def _pede(self, metodo, url, **kw):
        for t in range(10):
            try:
                r = self.s.request(metodo, url, timeout=600, **kw)
            except requests.RequestException as e:
                print('rede', e); time.sleep(20 * (t + 1)); continue
            if r.status_code in (403, 429) or r.status_code >= 500:
                espera = int(r.headers.get('Retry-After') or 0) or 60 * (t + 1)
                if 'not accessible' in r.text or 'Bad credentials' in r.text:
                    raise RuntimeError(f'sem permissao: {r.text[:200]}')
                print(f'{metodo} {r.status_code}: aguardando {espera}s', flush=True); time.sleep(espera); continue
            return r
        raise RuntimeError(f'falhou {metodo} {url}')

    def _carregar(self, tag):
        r = self._pede('GET', f'{self.api}/releases/tags/{tag}')
        if r.status_code == 404:
            return None
        d = r.json(); assets = {}
        pg = 1
        while True:
            x = self._pede('GET', f"{self.api}/releases/{d['id']}/assets", params=dict(per_page=100, page=pg)).json()
            for a in x:
                assets[a['name']] = dict(id=a['id'], size=a['size'])
            if len(x) < 100:
                break
            pg += 1
        return dict(id=d['id'], assets=assets)

    def _criar(self, tag, marca):
        rot = ROTULO_MARCA.get(marca, marca)
        corpo = (f'Arquivos originais em alta de {rot}. Criado e mantido automaticamente pelo banco de imagens. '
                 'Para encontrar uma imagem, use a pagina do banco de imagens.')
        r = self._pede('POST', f'{self.api}/releases', json=dict(tag_name=tag, name=f'Originais {rot}', body=corpo,
                                                                 make_latest='false'))
        if r.status_code not in (200, 201):
            raise RuntimeError(f'criar release {tag}: {r.status_code} {r.text[:300]}')
        return dict(id=r.json()['id'], assets={})

    def release_de(self, marca, ocupar=True):
        """Devolve a tag da marca com espaco livre (limite do GitHub: 1000 arquivos por release)."""
        n = 1
        with self.lock:
            while True:
                tag = f'originais-{marca.lower()}' + (f'-{n}' if n > 1 else '')
                if tag not in self.rel:
                    self.rel[tag] = self._carregar(tag) or self._criar(tag, marca)
                if len(self.rel[tag]['assets']) < self.LIMITE:
                    return tag
                n += 1

    def renomear(self, tag, velho, novo):
        """Muda o nome do arquivo na release. Pode ser repetido sem efeito colateral."""
        if tag not in self.rel:
            self.rel[tag] = self._carregar(tag)
        info = self.rel[tag]
        if velho not in info['assets'] and novo in info['assets']:
            return True
        if velho not in info['assets']:
            raise RuntimeError(f'arquivo nao encontrado: {velho}')
        r = self._pede('PATCH', f"{self.api}/releases/assets/{info['assets'][velho]['id']}", json=dict(name=novo))
        if r.status_code != 200:
            raise RuntimeError(f'renomear {velho}: {r.status_code} {r.text[:200]}')
        info['assets'][novo] = info['assets'].pop(velho)
        return True

    def enviar(self, tag, nome, dados, tipo):
        info = self.rel[tag]
        ex = info['assets'].get(nome)
        if ex and ex['size'] == len(dados):
            return
        if ex:
            self._pede('DELETE', f"{self.api}/releases/assets/{ex['id']}")
        with self.lock:
            info['assets'][nome] = dict(id=0, size=len(dados))
        url = f"https://uploads.github.com/repos/{REPO}/releases/{info['id']}/assets"
        r = self._pede('POST', url, params=dict(name=nome), data=dados, headers={'Content-Type': tipo})
        if r.status_code == 422:  # sobrou de envio interrompido
            atual = self._carregar(tag)
            if nome in atual['assets']:
                self._pede('DELETE', f"{self.api}/releases/assets/{atual['assets'][nome]['id']}")
            r = self._pede('POST', url, params=dict(name=nome), data=dados, headers={'Content-Type': tipo})
        if r.status_code not in (200, 201):
            raise RuntimeError(f'enviar {nome}: {r.status_code} {r.text[:300]}')
        with self.lock:
            info['assets'][nome] = dict(id=r.json()['id'], size=len(dados))


def ascii_seguro(t):
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode()
    t = re.sub(r'[^A-Za-z0-9.-]+', '_', t)
    return re.sub(r'_{2,}', '_', t).strip('_.')


def base_download(g):
    """EAN_Marca_Nome_do_Produto, sem repetir a marca no inicio do nome."""
    marca = ascii_seguro(ROTULO_MARCA[g['m']])
    nome = ascii_seguro(g['n'])
    if nome.lower().startswith(marca.lower() + '_'):
        nome = nome[len(marca) + 1:]
    partes = [g.get('ean', ''), marca, nome]
    if g['v'] == 'antigo':
        partes.append('Antigo')
    elif g['v']:
        partes.append(ascii_seguro(g['v']))
    return '_'.join(x for x in partes if x)


def definir_nomes_download(grupos):
    """Grava em cada imagem o nome usado no download: base + sequencia. Nunca repete nomes."""
    usados = set()
    for g in grupos:
        base = candidato = base_download(g)
        n = 2
        while candidato.lower() in usados:
            candidato = f'{base}_{n}'
            n += 1
        usados.add(candidato.lower())
        g['dz'] = candidato
        total = len(g['i'])
        for k, it in enumerate(g['i'], start=1):
            it['dn'] = f'{candidato}_{k:02d}' if total > 1 else candidato


def url_original(tag, nome):
    return f'https://github.com/{REPO}/releases/download/{tag}/{nome}'


def nome_asset(rel, ext, meta, tag):
    """Usa o nome do arquivo; se ja existir outro igual na mesma release, usa o caminho."""
    base = rel.split('/')[-1] + ext
    for k, v in meta.items():
        if k != rel and v.get('tag') == tag and v.get('asset') == base:
            return '__'.join(rel.split('/')[1:]) + ext
    return base


def ler_originais():
    return json.loads(ARQ_ORIGINAIS.read_text(encoding='utf-8')) if ARQ_ORIGINAIS.exists() else {}


def salvar_originais(m):
    ARQ_ORIGINAIS.write_text(json.dumps(m, ensure_ascii=False, indent=0, sort_keys=True), encoding='utf-8')


# ---------- nomes de exibicao ----------
ACENTOS = {
    'algodao': 'Algodão', 'limao': 'Limão', 'acai': 'Açaí', 'guarana': 'Guaraná', 'maca': 'Maçã', 'cafeina': 'Cafeína',
    'calcio': 'Cálcio', 'colageno': 'Colágeno', 'magnesio': 'Magnésio', 'curcuma': 'Cúrcuma', 'omega': 'Ômega',
    'pacoca': 'Paçoca', 'gratis': 'Grátis', 'unitaria': 'Unitária', 'pre': 'Pré', 'mamao': 'Mamão', 'maracuja': 'Maracujá',
    'cha': 'Chá', 'cafe': 'Café', 'bone': 'Boné', 'bones': 'Bonés', 'capsulas': 'Cápsulas', 'acessorios': 'Acessórios',
    'coq': 'Coqueteleira', 'leging': 'Legging', 'sache': 'Sachê', 'unitario': 'Unitário', 'atomico': 'Atômico', 'energetico': 'Energético', 'radioativo': 'Radioativo', 'unid': 'unid',
}
SIGLAS = {'BCAA', 'ZMA', 'HMB', 'NAC', 'NTR', 'FTW', 'D3', 'Q10', 'MCT', 'PA', 'ML', 'T2', 'B12', 'C', 'D'}
PASTAS_TECNICAS = {'antigo', 'atualizacao_abril_2026', 'vistas', '_vistas'}


def pretty_token(t):
    if not t:
        return ''
    if t.upper() in SIGLAS and t.upper() != 'C' and t.upper() != 'D':
        return t.upper()
    if re.fullmatch(r'\d+(?:[.,]\d+)?[A-Za-z]{1,3}', t):
        return t.lower().replace('ml', 'ml')
    a = ACENTOS.get(t.lower())
    if a:
        return a
    if t.lower() in ('de', 'do', 'da', 'com', 'e'):
        return t.lower()
    if t.isupper() or t.islower():
        return t.capitalize()
    return t


def bonito_tokens(toks):
    txt = ' '.join(pretty_token(x) for x in toks)
    txt = re.sub(r'\bWhey 100\b', 'Whey 100%', txt)
    txt = re.sub(r'\bWhey 35\b', 'Whey 35%', txt)
    txt = re.sub(r'\bDiaboVerde\b', 'Diabo Verde', txt)
    for sem, com in ACENTOS.items():  # palavras compostas: Banana-Acai
        txt = re.sub(rf'(?<=-){sem}\b|\b{sem}(?=-)', com, txt, flags=re.I)
    return txt


def tokens(seg):
    seg = re.sub(r'^\d+_(?=[A-Za-z])', '', seg.strip('_'))
    return [x for x in re.split(r'[_\s]+', seg) if x]


def bonito(seg):
    return bonito_tokens(tokens(seg))


def nome_grupo(partes):
    """partes = pastas depois da marca. Junta os niveis sem repetir palavras."""
    uteis = [p for p in partes if p.lower() not in PASTAS_TECNICAS] or partes or ['Geral']
    vistos, saida = set(), []
    for p in uteis:
        for t in tokens(p):
            if t.lower() not in vistos:
                vistos.add(t.lower()); saida.append(t)
    return bonito_tokens(saida)


def selo_versao(partes):
    low = [p.lower() for p in partes]
    if 'antigo' in low:
        return 'antigo'
    for p in low:
        m = re.match(r'atualizacao_([a-z]+)_(\d{4})', p)
        if m:
            return f'{m.group(1).capitalize()}/{m.group(2)}'
    return ''


# ---------- catalogo ----------
def ler_produtos():
    """dados/produtos.csv: PA, EAN e dados de cadastro por pasta. Sem precos, custos ou margens."""
    arq = DADOS / 'produtos.csv'
    if not arq.exists():
        return {}
    with open(arq, encoding='utf-8-sig', newline='') as f:
        return {r['pasta']: r for r in csv.DictReader(f, delimiter=';')}


def gerar_catalogo():
    meta = ler_originais()
    produtos = ler_produtos()
    grupos = {}
    for arq in sorted(PRODUTOS.rglob('*')):
        if not arq.is_file() or arq.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
            continue
        rel = arq.relative_to(PRODUTOS)
        if len(rel.parts) < 2:
            continue  # arquivo solto em produtos/ nao entra
        if rel.parts[0] not in ROTULO_MARCA:
            continue
        chave = rel.with_suffix('').as_posix()
        pasta = rel.parent.as_posix()
        m = meta.get(chave, {})
        g = grupos.setdefault(pasta, dict(p=pasta, m=rel.parts[0], l=bonito(rel.parts[1]) if len(rel.parts) > 2 else 'Geral',
                                          n=nome_grupo(list(rel.parts[1:-1])) or ROTULO_MARCA[rel.parts[0]],
                                          v=selo_versao(list(rel.parts[1:-1])), i=[]))
        item = dict(a=arq.name, b=arq.stat().st_size, w=m.get('w'), h=m.get('h'))
        if m.get('asset'):
            item.update(o=url_original(m['tag'], m['asset']), ob=m.get('bytes'), of=m['asset'].rsplit('.', 1)[-1].lower())
        g['i'].append(item)
    # remove miniaturas orfas
    if MINIATURAS.exists():
        for mini in MINIATURAS.rglob('*.webp'):
            chave = mini.relative_to(MINIATURAS).with_suffix('').as_posix()
            if not any((PRODUTOS / f'{chave}{x}').exists() for x in ('.jpg', '.png')):
                mini.unlink()
    for g in grupos.values():
        c = produtos.get(g['p'])
        if not c:
            continue
        dados = dict(pa=c['pa'], ean=c['ean'], dun=c.get('dun'), ds=c['descricao'], ct=c['categoria'], cx=c['caixa_embarque'],
                     qc=c.get('qtd_por_caixa'), ncm=c['ncm'], tb=c['na_tabela_jul2026'], st=c['status'])
        g.update({k: v for k, v in dados.items() if v})

    def ordem(t):
        return unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode().lower()
    # nomes iguais em pastas diferentes: deixa claro qual e qual
    iguais = {}
    for g in grupos.values():
        iguais.setdefault((g['m'], g['n'], g['v']), []).append(g)
    for lst in iguais.values():
        if len(lst) < 2:
            continue
        for g in lst:
            if re.search(r'(^|/)_?VISTAS(/|$)', g['p']):
                g['n'] += ' Vistas'
        resto = {}
        for g in lst:
            resto.setdefault(g['n'], []).append(g)
        for r in resto.values():
            for k, g in enumerate(sorted(r, key=lambda x: x['p'])[1:], start=2):
                g['n'] += f' ({k})'
    lista = sorted(grupos.values(), key=lambda g: (list(ROTULO_MARCA).index(g['m']), ordem(g['l']), ordem(g['n']), g['v'] == 'antigo'))
    definir_nomes_download(lista)
    cat = dict(gerado=datetime.now(timezone.utc).isoformat(timespec='seconds'), rotulos=ROTULO_MARCA,
               total=sum(len(g['i']) for g in lista), grupos=lista)
    ARQ_CATALOGO.parent.mkdir(exist_ok=True)
    ARQ_CATALOGO.write_text(json.dumps(cat, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    # planilha de-para para o time de e-commerce
    with open(DADOS / 'links_novos.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['marca', 'produto', 'pa', 'ean', 'dun', 'qtd_por_caixa', 'descricao', 'versao', 'arquivo', 'nome_download', 'link_site', 'link_original', 'miniatura', 'link_antigo'])
        for g in lista:
            for it in g['i']:
                chave = f"{g['p']}/{it['a'].rsplit('.', 1)[0]}"
                w.writerow([ROTULO_MARCA[g['m']], g['n'], g.get('pa', ''), g.get('ean', ''), g.get('dun', ''), g.get('qc', ''), g.get('ds', ''), g['v'], it['a'], it['dn'], f"{BASE_SITE}/produtos/{g['p']}/{it['a']}",
                            it.get('o', ''), f"{BASE_SITE}/miniaturas/{chave}.webp", meta.get(chave, {}).get('origem', '')])
    shutil.copy(DADOS / 'links_novos.csv', ARQ_CATALOGO.parent / 'links_novos.csv')
    return cat
