from __future__ import annotations

import argparse
import os
import re
import sys
import time
import platform
import ctypes
from tempfile import TemporaryDirectory
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests
from playwright.sync_api import (
    BrowserContext,
    TimeoutError as PlaywrightTimeoutError,
    Page,
    sync_playwright,
)

APP_NAME = "Assistente-contracheque"
APP_VERSION = "2.0.0"
PORTAL_URL = "https://www.portaldoservidor.mg.gov.br/"
BACKEND_URL = "https://gestao-de-carreira-backend-fijuvx-a73918-161-97-80-237.sslip.io"
UPLOAD_PATH = "/api/financeiro/importacao-temporaria/upload-lote"
DOWNLOAD_TIMEOUT_MS = 45_000


@dataclass(frozen=True)
class DocumentoInfo:
    texto_linha: str
    ano: Optional[int]
    mes: Optional[int]
    is_decimo_terceiro: bool


def caminho_curto_windows(path: str) -> str:
    if platform.system().lower() != "windows":
        return path

    try:
        GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
        GetShortPathNameW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        GetShortPathNameW.restype = ctypes.c_uint

        buf_len = 4096
        out = ctypes.create_unicode_buffer(buf_len)
        rv = GetShortPathNameW(path, out, buf_len)
        return out.value if rv and out.value else path
    except Exception:
        return path


def carregar_ambiente(args: argparse.Namespace) -> tuple[Path, str, str]:
    download_dir = Path(os.getenv("DOWNLOAD_DIR", "./downloads_contracheques")).resolve()
    backend_url = (args.backend_url or os.getenv("BACKEND_URL") or BACKEND_URL).rstrip("/")
    portal_url = args.portal_url or os.getenv("PORTAL_URL") or PORTAL_URL

    download_dir.mkdir(parents=True, exist_ok=True)
    return download_dir, backend_url, portal_url


def mascarar_arg(arg: str) -> str:
    if "token=" in arg.lower():
        return re.sub(r"(?i)(token=)[^&\s]+", r"\1[oculto]", arg)
    if len(arg) > 90:
        return f"{arg[:90]}..."
    return arg


def extrair_token_uri(uri: str) -> Optional[str]:
    try:
        parsed = urlparse(uri)
        if parsed.scheme.lower() != "gestaodecarreira":
            return None
        query = parse_qs(parsed.query)
        token = query.get("token", [None])[0]
        return token.strip() if token else None
    except Exception:
        return None


def token_parece_valido(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{20,}", token.strip()))


def ler_texto_clipboard_windows() -> Optional[str]:
    if platform.system().lower() != "windows":
        return None

    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_bool
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool

    if not user32.OpenClipboard(None):
        return None

    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None

        kernel32.GlobalLock.restype = ctypes.c_void_p
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None

        try:
            texto = ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)

        return texto.strip() if texto else None
    except Exception:
        return None
    finally:
        user32.CloseClipboard()


def extrair_token_clipboard() -> Optional[str]:
    texto = ler_texto_clipboard_windows()
    if not texto:
        return None

    token_uri = extrair_token_uri(texto)
    if token_uri:
        return token_uri

    texto = texto.strip()
    return texto if token_parece_valido(texto) else None


def resolver_token(args: argparse.Namespace) -> tuple[str, str]:
    print(f"[debug] argv_count={len(sys.argv)}", flush=True)
    for i, arg in enumerate(sys.argv):
        print(f"[debug] argv[{i}]={mascarar_arg(arg)}", flush=True)

    if args.token:
        print("[debug] origem_token=cli", flush=True)
        print("[debug] token_recebido=sim", flush=True)
        return args.token.strip(), "cli"

    candidatos = []
    if args.import_url:
        candidatos.append(args.import_url)
    if args.import_uri:
        candidatos.append(args.import_uri)
    candidatos.extend(sys.argv[1:])

    for valor in candidatos:
        token = extrair_token_uri(valor)
        if token:
            print("[debug] origem_token=protocolo", flush=True)
            print("[debug] token_recebido=sim", flush=True)
            return token, "protocolo"

    token_clipboard = extrair_token_clipboard()
    if token_clipboard:
        print("[debug] origem_token=clipboard", flush=True)
        print("[debug] token_recebido=sim", flush=True)
        return token_clipboard, "clipboard"

    print("[debug] origem_token=manual_fallback", flush=True)
    print("[debug] token_recebido=nao", flush=True)
    print("Nao consegui receber o token automaticamente do site.", flush=True)
    print("Isso indica falha no botao do site ou no protocolo gestaodecarreira://.", flush=True)
    time.sleep(8)
    raise RuntimeError("Token nao informado.")


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("import_uri", nargs="?", help="URI do protocolo gestaodecarreira://")
    parser.add_argument("--token", dest="token", help="Token temporario gerado pelo site")
    parser.add_argument("--import-url", dest="import_url", help="URI do protocolo com token")
    parser.add_argument("--backend-url", dest="backend_url", help="URL base do backend")
    parser.add_argument("--portal-url", dest="portal_url", help="URL do Portal do Servidor")
    parser.add_argument("--check-token", action="store_true", help="Valida token e encerra sem abrir navegador")
    return parser


def normalizar_nome_arquivo(texto: str) -> str:
    texto = re.sub(r"[^\w\s.-]", "", texto, flags=re.UNICODE)
    texto = re.sub(r"\s+", "_", texto.strip())
    return texto[:120] if texto else f"arquivo_{int(time.time())}"


def extrair_info_documento(texto: str) -> DocumentoInfo:
    texto_norm = " ".join(texto.split())
    texto_lower = texto_norm.lower()

    is_decimo = (
        "13" in texto_lower
        or "décimo" in texto_lower
        or "decimo" in texto_lower
        or "13º" in texto_lower
        or "13o" in texto_lower
    )

    ano = None
    mes = None

    match_mes_ano = re.search(r"\b(0?[1-9]|1[0-2])/(20\d{2})\b", texto_lower)
    if match_mes_ano:
        mes = int(match_mes_ano.group(1))
        ano = int(match_mes_ano.group(2))

    return DocumentoInfo(
        texto_linha=texto_norm,
        ano=ano,
        mes=mes,
        is_decimo_terceiro=is_decimo,
    )


def iniciar_contexto(playwright, download_dir: Path, user_data_dir: Path) -> BrowserContext:
    user_data_dir = caminho_curto_windows(str(user_data_dir.resolve()))
    downloads_path = caminho_curto_windows(str(download_dir))

    navegadores = [
        ("Google Chrome", {"channel": "chrome"}),
        ("Microsoft Edge", {"channel": "msedge"}),
        ("Chromium", {}),
    ]

    ultimo_erro: Exception | None = None
    for nome, opcoes in navegadores:
        try:
            print(f"Abrindo {nome}...", flush=True)
            contexto = playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                accept_downloads=True,
                downloads_path=downloads_path,
                viewport={"width": 1440, "height": 900},
                **opcoes,
            )
            print(f"Navegador aberto: {nome}", flush=True)
            return contexto
        except Exception as exc:
            ultimo_erro = exc
            print(f"Nao consegui abrir {nome}. Vou tentar o proximo navegador.", flush=True)

    raise RuntimeError(f"Nao consegui abrir nenhum navegador. Ultimo erro: {ultimo_erro}")


def goto_com_retry(
    page: Page,
    url: str,
    *,
    tentativas: int = 3,
    timeout_ms: int = 90_000,
    wait_until: str = "domcontentloaded",
) -> None:
    ultimo_erro: Exception | None = None
    for i in range(1, tentativas + 1):
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            return
        except Exception as exc:
            ultimo_erro = exc
            print(f"Falha ao abrir {url} (tentativa {i}/{tentativas}): {exc}")
            page.wait_for_timeout(1500)

    if ultimo_erro:
        raise ultimo_erro


def encontrar_pagina_portal(page: Page) -> Page:
    contexto = page.context
    for p in contexto.pages:
        try:
            if "portaldoservidor.mg.gov.br" in (p.url or "").lower():
                return p
        except Exception:
            continue
    return page


def encontrar_qualquer_pagina_viva(page: Page) -> Page:
    try:
        _ = page.url
        return page
    except Exception:
        pass

    ctx = page.context
    for p in ctx.pages:
        try:
            _ = p.url
            return p
        except Exception:
            continue
    return page


def fechar_avisos_se_existirem(page: Page) -> None:
    try:
        candidatos = [
            page.get_by_role("button", name=re.compile(r"^fechar$", re.I)),
            page.get_by_role("button", name=re.compile(r"^(ok|entendi|continuar|prosseguir)$", re.I)),
            page.get_by_role("button", name=re.compile(r"^(x|×)$", re.I)),
        ]

        for c in candidatos:
            try:
                if c.count() > 0 and c.first.is_visible():
                    c.first.click(timeout=2000)
                    page.wait_for_timeout(300)
                    return
            except Exception:
                continue

        zk_close = page.locator(".z-window .z-window-close, .z-window-modal .z-window-close")
        if zk_close.count() > 0 and zk_close.first.is_visible():
            zk_close.first.click(timeout=2000)
            page.wait_for_timeout(300)
    except Exception:
        pass


def encontrar_contexto_lista(page: Page):
    """
    Retorna o contexto real onde a tabela está:
    - a própria página, ou
    - um frame
    """
    seletores_linhas = [
        "tr.z-listitem",
        ".z-listbox-body tr",
        "table tbody tr",
    ]

    for sel in seletores_linhas:
        try:
            if page.locator(sel).count() > 0:
                return page
        except Exception:
            pass

    try:
        for fr in page.frames:
            for sel in seletores_linhas:
                try:
                    if fr.locator(sel).count() > 0:
                        return fr
                except Exception:
                    continue
    except Exception:
        pass

    return page


def localizar_linhas_documento(contexto):
    candidatos = [
        "tr.z-listitem",
        ".z-listbox-body tr",
        "table tbody tr",
    ]

    for sel in candidatos:
        try:
            loc = contexto.locator(sel)
            if loc.count() > 0:
                return loc
        except Exception:
            continue

    return contexto.locator("tr.z-listitem")


def esperar_lista_em_alguma_frame(page: Page, timeout_ms: int):
    deadline = time.time() + (timeout_ms / 1000)

    while time.time() < deadline:
        page = encontrar_qualquer_pagina_viva(page)

        try:
            fechar_avisos_se_existirem(page)
        except Exception:
            pass

        contexto = encontrar_contexto_lista(page)

        try:
            linhas = localizar_linhas_documento(contexto)
            if linhas.count() > 0:
                return contexto
        except Exception:
            pass

        page.wait_for_timeout(300)

    raise PlaywrightTimeoutError("Timeout aguardando a lista de contracheques.")


def encontrar_pagina_com_lista_flexivel(page: Page) -> Page:
    contexto = page.context
    seletores_linhas = [
        "tr.z-listitem",
        ".z-listbox-body tr",
        "table tbody tr",
    ]

    for p in contexto.pages:
        try:
            for sel in seletores_linhas:
                if p.locator(sel).count() > 0:
                    return p
        except Exception:
            continue
    return page


def url_parece_login(url: str) -> bool:
    u = (url or "").lower()
    return any(
        x in u
        for x in [
            "gov.br",
            "oidc/login",
            "broker2/oidc/login",
            "j_security_check",
            "ssc-idp",
            "login",
            "autentic",
        ]
    )


def esperar_sair_do_login(page: Page, timeout_ms: int) -> None:
    deadline = time.time() + (timeout_ms / 1000)
    last_print = 0.0

    while time.time() < deadline:
        page = encontrar_qualquer_pagina_viva(page)
        try:
            if not url_parece_login(page.url) and "portaldoservidor.mg.gov.br" in page.url.lower():
                return
        except Exception:
            pass

        agora = time.time()
        if agora - last_print > 10:
            try:
                print(f"Aguardando finalizar login/SSO... URL atual: {page.url}")
            except Exception:
                print("Aguardando finalizar login/SSO... (URL indisponível)")
            last_print = agora

        page.wait_for_timeout(300)

    raise PlaywrightTimeoutError("Timeout aguardando finalizar login/SSO.")


def abrir_portal_e_autenticar(page: Page, portal_url: str) -> None:
    page.set_default_navigation_timeout(90_000)

    goto_com_retry(page, portal_url, tentativas=3, timeout_ms=90_000, wait_until="domcontentloaded")

    print(
        "\nO navegador foi aberto.\n"
        "Faca login normalmente no Portal do Servidor.\n"
        "Depois entre na pagina de contracheques e deixe o resto comigo.\n",
        flush=True,
    )

    # espera você terminar o login e/ou abrir a lista
    deadline = time.time() + (15 * 60)  # 15 minutos

    while time.time() < deadline:
        page = encontrar_qualquer_pagina_viva(page)
        page = encontrar_pagina_portal(page)

        try:
            fechar_avisos_se_existirem(page)
        except Exception:
            pass

        # 1) se já estiver na lista, ótimo
        try:
            contexto = encontrar_contexto_lista(page)
            linhas = localizar_linhas_documento(contexto)
            if linhas.count() > 0:
                print("Encontrei sua lista de contracheques.", flush=True)
                return
        except Exception:
            pass

        # 2) se já voltou ao portal depois do gov, também ok
        try:
            url_atual = page.url.lower()
            if "portaldoservidor.mg.gov.br" in url_atual and not url_parece_login(url_atual):
                # ainda não força nada; só espera você terminar de navegar
                pass
        except Exception:
            pass

        page.wait_for_timeout(1000)

    raise RuntimeError(
        "Ainda nao encontrei sua lista de contracheques. "
        "Abra a pagina de contracheques no navegador e tente novamente."
    )


def ir_para_lista_de_contracheques(page: Page):
    inicio = time.time()
    prazo_segundos = 180

    while True:
        page = encontrar_qualquer_pagina_viva(page)
        page = encontrar_pagina_portal(page)

        try:
            fechar_avisos_se_existirem(page)
        except Exception:
            pass

        # Se a lista já estiver visível, retorna o contexto correto
        try:
            contexto = esperar_lista_em_alguma_frame(page, timeout_ms=2000)
            return contexto
        except Exception:
            pass

        # tenta clicar em Contracheque
        candidatos_contracheque = [
            page.get_by_role("link", name=re.compile(r"^contracheque$", re.I)),
            page.get_by_role("button", name=re.compile(r"^contracheque$", re.I)),
            page.get_by_role("link", name=re.compile(r"contracheque", re.I)),
            page.get_by_role("button", name=re.compile(r"contracheque", re.I)),
            page.get_by_text(re.compile(r"\bcontracheque\b", re.I)),
        ]

        for c in candidatos_contracheque:
            try:
                if c.count() > 0 and c.first.is_visible():
                    c.first.scroll_into_view_if_needed()
                    c.first.click(timeout=5000)
                    page.wait_for_timeout(1500)
                    break
            except Exception:
                continue

        # tenta clicar em Consultar
        candidatos_consultar = [
            page.locator('a[href="/contracheque--consultar"]'),
            page.get_by_role("link", name=re.compile(r"^consultar$", re.I)),
            page.get_by_role("button", name=re.compile(r"^consultar$", re.I)),
            page.get_by_text(re.compile(r"\bconsultar\b", re.I)),
        ]

        for c in candidatos_consultar:
            try:
                if c.count() > 0 and c.first.is_visible():
                    c.first.scroll_into_view_if_needed()
                    c.first.click(timeout=5000)
                    page.wait_for_timeout(2000)
                    break
            except Exception:
                continue

        try:
            contexto = esperar_lista_em_alguma_frame(page, timeout_ms=4000)
            return contexto
        except Exception:
            pass

        if time.time() - inicio > prazo_segundos:
            raise RuntimeError(
                "Ainda nao encontrei sua lista de contracheques."
            )

        page.wait_for_timeout(1000)

def clicar_baixar_na_linha(
    page: Page,
    linha,
    pasta_destino: Path,
    competencia: str,
    tipo: str,
) -> bool:
    try:
        nome_base = f"{competencia}_{tipo}".replace("/", "-").replace(" ", "_")
        nome_base = normalizar_nome_arquivo(nome_base)

        btn = linha.locator("button.btn-outline-primary2", has_text=re.compile(r"baixar", re.I))
        if btn.count() == 0:
            btn = linha.locator("button", has_text=re.compile(r"baixar", re.I))

        if btn.count() == 0:
            print(f"[download] {competencia} | {tipo}: botao Baixar nao encontrado; pulando.", flush=True)
            return False

        print(f"Baixando {competencia} - {tipo}...", flush=True)

        botao = btn.first
        botao.scroll_into_view_if_needed(timeout=5000)
        with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as download_info:
            botao.click(timeout=5000, force=True)

        download = download_info.value
        suggested = download.suggested_filename or f"{nome_base}.pdf"
        ext = Path(suggested).suffix or ".pdf"
        destino = pasta_destino / f"{nome_base}{ext}"
        download.save_as(str(destino))

        print(f"Download concluido: {destino.name}", flush=True)
        return True

    except PlaywrightTimeoutError:
        print(f"Tempo esgotado no download: {competencia} - {tipo}", flush=True)
        return False
    except Exception as exc:
        print(f"Nao consegui baixar {competencia} - {tipo}: {exc}", flush=True)
        return False


def processar_pagina(page: Page, pasta_mensais: Path, pasta_decimo: Path, vistos: set[str]) -> int:
    page.wait_for_timeout(1500)

    contexto = esperar_lista_em_alguma_frame(page, timeout_ms=20000)
    linhas = localizar_linhas_documento(contexto)
    total_baixados = 0

    print(f"Contracheques encontrados nesta pagina: {linhas.count()}", flush=True)

    for i in range(linhas.count()):
        linha = linhas.nth(i)

        try:
            colunas = linha.locator("td")
            if colunas.count() < 3:
                continue

            competencia = colunas.nth(0).inner_text(timeout=3000).strip()
            tipo = colunas.nth(1).inner_text(timeout=3000).strip()
        except Exception:
            continue

        if not competencia or not tipo:
            continue

        chave = f"{competencia}|{tipo}".lower()
        if chave in vistos:
            continue

        info = extrair_info_documento(f"{competencia} {tipo}")

        pasta_destino = pasta_mensais
        tipo_lower = tipo.lower()

        if info.is_decimo_terceiro or "13" in tipo_lower or "décimo" in tipo_lower or "decimo" in tipo_lower:
            pasta_destino = pasta_decimo
        elif "mensal" in tipo_lower:
            pasta_destino = pasta_mensais
        else:
            print(f"[download] {competencia} | {tipo}: tipo nao reconhecido; pulando.", flush=True)
            continue

        ok = clicar_baixar_na_linha(
            page=page,
            linha=linha,
            pasta_destino=pasta_destino,
            competencia=competencia,
            tipo=tipo,
        )

        if ok:
            vistos.add(chave)
            total_baixados += 1

    return total_baixados


def ir_para_proxima_pagina(page: Page) -> bool:
    try:
        contexto = encontrar_contexto_lista(page)

        proximo = contexto.locator('a.z-paging-next[name$="-next"]')
        if proximo.count() == 0:
            print("Botão de próxima página não encontrado.")
            return False

        botao = proximo.first

        if not botao.is_visible():
            print("Botão de próxima página não está visível.")
            return False

        linhas_antes = localizar_linhas_documento(contexto)
        primeira_linha_antes = ""

        if linhas_antes.count() > 0:
            try:
                primeira_linha_antes = linhas_antes.nth(0).inner_text(timeout=3000).strip()
            except Exception:
                primeira_linha_antes = ""

        botao.scroll_into_view_if_needed()
        botao.click(timeout=5000)

        page.wait_for_timeout(2000)

        for _ in range(12):
            page.wait_for_timeout(500)

            contexto_depois = encontrar_contexto_lista(page)
            linhas_depois = localizar_linhas_documento(contexto_depois)

            if linhas_depois.count() == 0:
                continue

            try:
                primeira_linha_depois = linhas_depois.nth(0).inner_text(timeout=3000).strip()
            except Exception:
                continue

            if primeira_linha_depois != primeira_linha_antes:
                print("Avançou para a próxima página.")
                return True

        print("Não detectei mudança de página; assumindo fim da paginação.")
        return False

    except Exception as exc:
        print(f"Não foi possível ir para a próxima página: {exc}")
        return False


def coletar_pdfs(download_dir: Path) -> list[Path]:
    return sorted(p for p in download_dir.rglob("*.pdf") if p.is_file())


def enviar_pdfs_ao_backend(pdfs: list[Path], token: str, backend_url: str) -> None:
    if not pdfs:
        print("Nenhum PDF foi baixado para enviar ao site.", flush=True)
        return

    url = f"{backend_url}{UPLOAD_PATH}"
    arquivos_abertos = []
    files = []

    try:
        for pdf in pdfs:
            handle = pdf.open("rb")
            arquivos_abertos.append(handle)
            files.append(("arquivos", (pdf.name, handle, "application/pdf")))

        print(f"Enviando {len(pdfs)} arquivo(s) para o site...", flush=True)
        resposta = requests.post(
            url,
            headers={"X-Import-Token": token},
            files=files,
            timeout=180,
        )
        resposta.raise_for_status()
        print("Envio concluido com sucesso.", flush=True)
    finally:
        for handle in arquivos_abertos:
            handle.close()


def main() -> int:
    print("Iniciando o Assistente-contracheque...", flush=True)
    print("Preparando sua importacao de contracheques...", flush=True)

    args = criar_parser().parse_args()
    try:
        token, origem_token = resolver_token(args)
        download_dir, backend_url, portal_url = carregar_ambiente(args)
    except Exception as erro_token:
        print(f"Nao foi possivel iniciar: {erro_token}", flush=True)
        print("Fechando assistente...", flush=True)
        time.sleep(5)
        return 1

    print("====================================", flush=True)
    print(APP_NAME, flush=True)
    print("====================================", flush=True)
    print(f"Versao: {APP_VERSION}", flush=True)
    print(f"Origem do token: {origem_token}", flush=True)
    print("Token recebido: sim", flush=True)
    print("====================================", flush=True)

    if args.check_token:
        print("Teste de token concluido. O navegador nao sera aberto.", flush=True)
        return 0

    pasta_mensais = download_dir / "mensais"
    pasta_decimo = download_dir / "decimo_terceiro"
    pasta_mensais.mkdir(parents=True, exist_ok=True)
    pasta_decimo.mkdir(parents=True, exist_ok=True)

    vistos: set[str] = set()

    with sync_playwright() as playwright:
        with TemporaryDirectory(prefix="portal_mg_profile_") as perfil_temporario:
            print("Abrindo navegador seguro para voce fazer login...", flush=True)
            context = iniciar_contexto(playwright, download_dir, Path(perfil_temporario))
            page = context.pages[0] if context.pages else context.new_page()

            try:
                print("Abrindo o Portal do Servidor para voce...", flush=True)
                abrir_portal_e_autenticar(page, portal_url)
                print("Estou procurando seus contracheques disponiveis...", flush=True)
                _ = ir_para_lista_de_contracheques(page)

                total = 0
                pagina = 1

                while True:
                    print(f"\nProcessando pagina {pagina}...", flush=True)
                    page = encontrar_pagina_com_lista_flexivel(page)
                    baixados_nesta_pagina = processar_pagina(page, pasta_mensais, pasta_decimo, vistos)
                    total += baixados_nesta_pagina

                    avancou = ir_para_proxima_pagina(page)
                    if not avancou:
                        break

                    pagina += 1

                pdfs = coletar_pdfs(download_dir)
                enviar_pdfs_ao_backend(pdfs, token, backend_url)

                print(f"\nConcluido. Total de arquivos baixados: {total}", flush=True)
                print(f"Mensais: {pasta_mensais}")
                print(f"13o: {pasta_decimo}")
                print(f"{len(pdfs)} contracheques enviados para o site.", flush=True)
                print("Fechando assistente...", flush=True)
                time.sleep(5)

            except Exception as e:
                print(f"\nOcorreu um erro: {e}", flush=True)
                try:
                    print(f"URL atual: {page.url}")
                except Exception:
                    pass
                print("Fechando assistente em alguns segundos.", flush=True)
                time.sleep(8)

            finally:
                context.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
