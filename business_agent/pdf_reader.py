"""Leitura de PDF -> texto. Só extrai texto embutido; NÃO faz OCR."""
from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PyPdfError

MAX_BYTES = 10 * 1024 * 1024  # 10 MB


class PdfInvalido(ValueError):
    """Arquivo que não é um PDF legível (ou grande demais)."""


def extrair_texto(conteudo: bytes) -> str:
    """Devolve o texto do PDF. String vazia = provavelmente escaneado (sem camada de texto)."""
    if len(conteudo) > MAX_BYTES:
        raise PdfInvalido("Arquivo maior que 10 MB.")
    if not conteudo.startswith(b"%PDF"):  # confere a assinatura, não a extensão do nome
        raise PdfInvalido("O arquivo não é um PDF.")
    try:
        leitor = PdfReader(io.BytesIO(conteudo))
        return "\n".join((p.extract_text() or "") for p in leitor.pages).strip()
    except (PyPdfError, ValueError, KeyError) as e:
        raise PdfInvalido("Não foi possível ler o PDF.") from e
