# Assistente-contracheque

Helper Windows para baixar contracheques do Portal do Servidor MG e enviar os PDFs para o site Gestao de Carreira.

## Arquivos

- `baixar_contracheques_mg.py`: script principal. Resolve token, abre navegador, aguarda login manual, detecta a lista, baixa os PDFs e envia ao backend.
- `requirements.txt`: dependencias Python usadas no build.
- `Assistente-contracheque.spec`: configuracao do PyInstaller para gerar `Assistente-contracheque.exe`.
- `version_info.txt`: metadados de versao do executavel Windows.
- `build_helper.ps1`: build local do exe e do setup.
- `installer/Assistente-contracheque.iss`: script Inno Setup. Registra o protocolo `gestaodecarreira://`.
- `.env.example`: variaveis opcionais para teste local.

## Fluxo

1. O site abre `gestaodecarreira://importar?token=TOKEN`.
2. O Windows chama `Assistente-contracheque.exe "%1"`.
3. O helper extrai o token automaticamente.
4. O helper abre Chrome, depois Edge, depois Chromium se precisar.
5. A pessoa faz login manual no Portal do Servidor.
6. A pessoa abre a pagina de contracheques.
7. O helper encontra a tabela, clica apenas em `Baixar`, baixa todos os PDFs e separa:
   - `mensais`
   - `decimo_terceiro`
8. O helper envia os PDFs ao backend com `X-Import-Token`.

## Teste local

```powershell
cd helper-novo\python
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe baixar_contracheques_mg.py "gestaodecarreira://importar?token=TESTE123"
```

Tambem aceita:

```powershell
.\.venv\Scripts\python.exe baixar_contracheques_mg.py --token TESTE123
```

Para testar somente o token, sem abrir navegador:

```powershell
.\.venv\Scripts\python.exe baixar_contracheques_mg.py "gestaodecarreira://importar?token=TESTE123" --check-token
```

Se o token automatico nao chegar, o helper mostra diagnostico e pede token manual apenas como ultimo recurso.

## Build

```powershell
cd helper-novo\python
.\build_helper.ps1 -InstallDependencies -Installer
```

Saidas:

- `dist\Assistente-contracheque\Assistente-contracheque.exe`
- `dist\installer\Assistente-contracheque-Setup.exe`
- `backend\static\downloads\Assistente-contracheque-Setup.exe`
- `backend\static\downloads\GestaoDeCarreira-Setup-latest.exe` apenas como compatibilidade.
