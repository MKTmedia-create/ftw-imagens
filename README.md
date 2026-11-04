# Banco de imagens FTW Suplementos

Página para o time: https://mktmedia-create.github.io/ftw-imagens/

## Onde fica cada coisa

| Pasta ou local | O que tem |
| --- | --- |
| `produtos/` | Versão para site (1600 px). É o link que o e-commerce usa. |
| `miniaturas/` | Miniaturas da página de busca. |
| Releases do GitHub | Arquivos originais em alta. |
| `entrada/` | Onde entram imagens novas ou atualizadas. |
| `dados/links_novos.csv` | Planilha com todos os links, novos e antigos, com PA e EAN. |
| `dados/produtos.csv` | PA, EAN e dados de cadastro de cada pasta. Pode ser editada. |

## Atualizar uma imagem

1. Coloque o original em `entrada/MARCA/PRODUTO/arquivo.png`.
2. Envie ao GitHub.
3. Em poucos minutos a página e os links estão atualizados.

Mesmo caminho e mesmo nome de uma imagem existente: substitui e mantém o link.

## Remover uma imagem

Apague o arquivo em `produtos/` e envie ao GitHub. Ele sai da página na próxima publicação.

## Embalagem antiga

Qualquer imagem dentro de uma pasta chamada `Antigo` fica marcada como antiga e escondida por padrão na página.

## Corrigir PA ou EAN

Edite `dados/produtos.csv`, coloque o código certo e, em `status`, escreva `ok`. Depois envie ao GitHub.

Este repositório é público: nunca inclua preço, custo, margem ou dados de tabela comercial.
