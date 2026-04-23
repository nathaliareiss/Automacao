from __future__ import annotations

import os
import re
import time
import platform
import ctypes
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional
from uuid import uuid4

from dotenv import load_dotenv
from playwright.sync_api import (
    BrowserContext,
    Error,
    TimeoutError as PlaywrightTimeoutError,
    Page,
    sync_playwright,
)

PORTAL_URL = "https://www.portaldoservidor.mg.gov.br/"
CONTRACHEQUE_URL = "https://www.portaldoservidor.mg.gov.br/contracheque"
STATE_DIR = "playwright_state_portal_mg"


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


def carregar_ambiente() -> tuple[str, str, Path]:
    load_dotenv()

    cpf = os.getenv("CPF", "").strip()
    senha = os.getenv("SENHA", "").strip()
    download_dir = Path(os.getenv("DOWNLOAD_DIR", "./downloads_contracheques")).resolve()

    if not cpf or not senha:
        raise RuntimeError(
            "Defina CPF e SENHA no arquivo .env. "
            "Por segurança, não deixe credenciais no código."
        )

    download_dir.mkdir(parents=True, exist_ok=True)
    return cpf, senha, download_dir


def primeiros_dia_mes_ha_n_meses(n: int) -> date:
    hoje = date.today()
    total_meses = hoje.year * 12 + (hoje.month - 1)
    alvo = total_meses - n
    ano_alvo = alvo // 12
    mes_alvo = (alvo % 12) + 1
    return date(ano_alvo, mes_alvo, 1)


def dentro_dos_ultimos_60_meses(ano: Optional[int], mes: Optional[int]) -> bool:
    if ano is None or mes is None:
        return False

    doc = date(ano, mes, 1)
    limite = primeiros_dia_mes_ha_n_meses(59)
    hoje = date.today().replace(day=1)
    return limite <= doc <= hoje


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


def iniciar_contexto(playwright, download_dir: Path) -> BrowserContext:
    user_data_dir = str((Path(STATE_DIR) / f"profile_{uuid4().hex}").resolve())
    user_data_dir = caminho_curto_windows(user_data_dir)
    downloads_path = caminho_curto_windows(str(download_dir))

    return playwright.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=False,
        accept_downloads=True,
        downloads_path=downloads_path,
        viewport={"width": 1440, "height": 900},
    )


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


def abrir_portal_e_autenticar(page: Page, cpf: str, senha: str) -> None:
    page.set_default_navigation_timeout(90_000)

    goto_com_retry(page, PORTAL_URL, tentativas=3, timeout_ms=90_000, wait_until="domcontentloaded")

    print(
        "\nO navegador foi aberto.\n"
        "Faça o login MANUALMENTE no seu tempo.\n"
        "Depois do login, volte para o portal.\n"
        "De preferência, já deixe aberta a tela da LISTA de contracheques.\n"
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
                print("Lista de contracheques detectada.")
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
        "Tempo esgotado aguardando o login manual. "
        "Faça o login e deixe a lista de contracheques aberta antes de continuar."
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
                "Não consegui abrir a lista automaticamente. "
                "Deixe a tela da listagem aberta manualmente e rode de novo."
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

        btn = linha.locator("button:has-text('Baixar')")
        if btn.count() == 0:
            btn = linha.get_by_role("button", name=re.compile(r"^baixar$", re.I))

        if btn.count() == 0:
            print(f"Botão Baixar não encontrado para {competencia} - {tipo}")
            return False

        print(f"Tentando baixar: {competencia} - {tipo}")

        with page.expect_download(timeout=30000) as download_info:
            btn.first.click(timeout=5000)

        download = download_info.value
        suggested = download.suggested_filename or f"{nome_base}.pdf"
        ext = Path(suggested).suffix or ".pdf"
        destino = pasta_destino / f"{nome_base}{ext}"
        download.save_as(str(destino))

        print(f"Baixado: {destino.name}")
        return True

    except PlaywrightTimeoutError:
        print(f"Timeout no download: {competencia} - {tipo}")
        return False
    except Exception as exc:
        print(f"Erro ao baixar {competencia} - {tipo}: {exc}")
        return False


def processar_pagina(page: Page, pasta_mensais: Path, pasta_decimo: Path, vistos: set[str]) -> int:
    page.wait_for_timeout(1500)

    contexto = esperar_lista_em_alguma_frame(page, timeout_ms=20000)
    linhas = localizar_linhas_documento(contexto)
    total_baixados = 0

    print(f"Linhas encontradas nesta página: {linhas.count()}")

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

        deve_baixar = False
        pasta_destino = pasta_mensais
        tipo_lower = tipo.lower()

        if info.is_decimo_terceiro or "13" in tipo_lower or "décimo" in tipo_lower or "decimo" in tipo_lower:
            deve_baixar = True
            pasta_destino = pasta_decimo
        elif "mensal" in tipo_lower and dentro_dos_ultimos_60_meses(info.ano, info.mes):
            deve_baixar = True
            pasta_destino = pasta_mensais

        if not deve_baixar:
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


def main() -> int:
    cpf, senha, download_dir = carregar_ambiente()

    pasta_mensais = download_dir / "mensais_ultimos_60_meses"
    pasta_decimo = download_dir / "decimo_terceiro"
    pasta_mensais.mkdir(parents=True, exist_ok=True)
    pasta_decimo.mkdir(parents=True, exist_ok=True)

    vistos: set[str] = set()

    with sync_playwright() as playwright:
        print("Iniciando navegador...")
        context = iniciar_contexto(playwright, download_dir)
        page = context.pages[0] if context.pages else context.new_page()

        try:
            print("Abrindo portal...")
            abrir_portal_e_autenticar(page, cpf, senha)
            print("Verificando lista de contracheques...")
            _ = ir_para_lista_de_contracheques(page)

            total = 0
            pagina = 1

            while True:
                print(f"\nProcessando página {pagina}...")
                page = encontrar_pagina_com_lista_flexivel(page)
                baixados_nesta_pagina = processar_pagina(page, pasta_mensais, pasta_decimo, vistos)
                total += baixados_nesta_pagina

                avancou = ir_para_proxima_pagina(page)
                if not avancou:
                    break

                pagina += 1

            print(f"\nConcluído. Total de arquivos baixados: {total}")
            print(f"Mensais: {pasta_mensais}")
            print(f"13º: {pasta_decimo}")

        except Exception as e:
            print(f"\nERRO NO SCRIPT: {e}")
            try:
                print(f"URL atual: {page.url}")
            except Exception:
                pass
            try:
                input("O navegador ficará aberto. Pressione ENTER para fechar...")
            except Exception:
                pass

        finally:
            try:
                input("\nPressione ENTER para fechar o navegador...")
            except Exception:
                pass
            context.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())