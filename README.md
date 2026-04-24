## Português##

# Baixar Contracheques MG

Automação em Python para acessar o Portal do Servidor de Minas Gerais, localizar a lista de contracheques e baixar os arquivos de forma organizada.

Este projeto foi feito para uso local. Eu sou servidora pública e precisava reunir meus próprios contracheques dos últimos 5 anos, então montei uma automação simples para fazer isso sem ficar abrindo e baixando tudo na mão.

### O que a aplicação faz

- Abre o portal no navegador.
- Espera o login manual do usuário.
- Localiza a tela com a lista de contracheques.
- Baixa os documentos dos últimos 60 meses.
- Separa os arquivos em pastas diferentes para mensais e 13º.
- Evita baixar o mesmo item mais de uma vez na mesma execução.

### Como o projeto está distribuído

O repositório é enxuto de propósito:

- `baixar_contracheques_mg.py` - script principal com toda a automação.
- `.env` - arquivo local com as credenciais e o diretório de saída.
- `.env.example` - exemplo de configuração sem dados sensíveis.
- `.gitignore` - impede que segredos, cache do navegador e arquivos gerados sejam enviados.

Pastas que podem aparecer durante a execução:

- `downloads_contracheques/` - saída padrão dos PDFs.
- `playwright_state_portal_mg/` - pasta antiga de estado do navegador, que não deve ir para o Git.

### Requisitos

- Python 3.10 ou superior.
- Dependências:
  - `python-dotenv`
  - `playwright`
- Navegador do Playwright instalado na máquina.

### Configuração

Crie um arquivo `.env` na raiz do projeto:

```env
CPF=00000000000
SENHA=sua_senha_aqui
DOWNLOAD_DIR=./downloads_contracheques
```

Use o arquivo `.env.example` como referência. Não coloque esse arquivo no Git.

### Como executar

```bash
python baixar_contracheques_mg.py
```

Na execução, o navegador abre e o login é feito manualmente. Depois disso, o script percorre a listagem e salva os PDFs em pastas separadas.

### Sobre o Playwright

O projeto usa o Playwright porque ele lida bem com sites dinâmicos, páginas com `iframe`, downloads e seletores mais confiáveis.

Além deste caso, ele também serve para:

- automatizar formulários e fluxos de login;
- trabalhar com páginas dentro de `iframe`;
- baixar arquivos de forma controlada;
- tirar screenshots e gravar vídeos;
- gerar traces para depuração;
- criar testes de ponta a ponta;
- reutilizar estado autenticado quando fizer sentido.

Se eu fosse evoluir este projeto, os próximos passos naturais seriam:

- registrar logs melhores por etapa;
- salvar um relatório dos arquivos baixados;
- adicionar modo silencioso/headless;
- criar testes do fluxo principal;
- usar traces quando algo quebrar no portal.

### Observação de segurança

O script não deve conter segredos no código-fonte. Se houver troca de credenciais, o ideal é rotacionar a senha/chave no serviço e revisar o histórico do repositório.

## English##

This project was built for local, personal use. I am a public servant, and I needed a practical way to collect my own payslips from the last 5 years without going through the whole process by hand every single time. So I built a small Python automation to do exactly that on my machine.

### What the application does

- Opens the portal in a browser.
- Waits for the user to sign in manually.
- Finds the page that lists the payslips.
- Downloads the documents from the last 60 months.
- Organizes the files into separate folders for monthly payslips and the 13th salary.
- Avoids downloading the same item twice during the same run.

### Project layout

The repository is intentionally small:

- `baixar_contracheques_mg.py` - the main script with all the automation logic.
- `.env` - local configuration file with credentials and the output folder.
- `.env.example` - a safe example configuration without secrets.
- `.gitignore` - keeps secrets, browser cache, and generated files out of Git.

Folders that may appear during execution:

- `downloads_contracheques/` - default PDF output folder.
- `playwright_state_portal_mg/` - legacy browser state folder; it should not be committed.

### Requirements

- Python 3.10 or newer.
- Dependencies:
  - `python-dotenv`
  - `playwright`
- Playwright browsers installed on the machine.

### Setup

Create a `.env` file in the project root:

```env
CPF=00000000000
SENHA=your_password_here
DOWNLOAD_DIR=./downloads_contracheques
```

Use `.env.example` as the template. Do not commit the real `.env` file.

### How to run it

```bash
python baixar_contracheques_mg.py
```

When the script runs, the browser opens and the login is done manually. After that, the script walks through the payslip list and saves the PDFs into the proper folders.

### Why Playwright

Playwright is a good fit here because the portal behaves like a dynamic web app, and the script needs to deal with browser state, `iframe`s, downloads, and stable selectors.

Beyond this project, Playwright is also useful for:

- automating forms and login flows;
- working with pages inside `iframe`s;
- handling file downloads in a controlled way;
- taking screenshots and recording videos;
- generating traces for debugging;
- building end-to-end tests;
- reusing authenticated browser state when that is useful.

If this project grows later, the most natural improvements would be:

- better step-by-step logging;
- a download report;
- a headless mode;
- automated tests for the main flow;
- traces for troubleshooting whenever the portal changes.

### Security note

The script should not contain secrets in source code. If credentials change, the safest move is to rotate the password or key at the service level and review the repository history.
