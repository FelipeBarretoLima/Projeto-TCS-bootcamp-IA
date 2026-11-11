"""Um caso por tipo de dado pessoal. Todos os dados são inventados."""

import pytest

from extrato import padroes
from extrato.anonimizacao import Classe, Revisar, anonimiza_texto, classifica, resolve_contraparte
from extrato.modelos import PESSOA_FISICA, Meio

TITULARES = padroes.regex_de_nomes(["Fulano de Tal Exemplo", "Beltrana Souza Teste"])


def limpo(texto):
    return anonimiza_texto(texto, TITULARES)


@pytest.mark.parametrize(
    "texto,esperado",
    [
        # CPF completo e mascarado
        ("PADARIA MODELO 123.456.789-09", "PADARIA MODELO"),
        ("PADARIA MODELO •••.456.789-••", "PADARIA MODELO"),
        ("PADARIA MODELO ***.456.789-**", "PADARIA MODELO"),
        # CNPJ
        ("MERCADO FICTICIO LTDA 12.345.678/0001-90", "MERCADO FICTICIO LTDA"),
        # agência e conta
        # (o código COMPE do banco, 4 dígitos, não é dado pessoal e fica)
        ("BANCO FICTICIO S.A. (0999) Agência: 1234 Conta: 56789-0", "BANCO FICTICIO S.A. (0999)"),
        ("BANCO FICTICIO S.A. Ag 1234 C/C 98765", "BANCO FICTICIO S.A"),
        # cartão completo, mascarado e só final
        ("LOJA TESTE 4111 1111 1111 1111", "LOJA TESTE"),
        ("LOJA TESTE 4111 **** **** 1234", "LOJA TESTE"),
        ("LOJA TESTE XXXX.XXXX.XXXX.1234", "LOJA TESTE"),
        ("LOJA TESTE CARTÃO FINAL 1234", "LOJA TESTE CARTÃO"),
        # chave PIX aleatória
        ("LOJA TESTE 1b4e28ba-2fa1-11d2-883f-0016d3cca427", "LOJA TESTE"),
        # e-mail (também chave PIX)
        ("LOJA TESTE contato@exemplo.com.br", "LOJA TESTE"),
        # telefone (também chave PIX)
        ("LOJA TESTE (11) 98765-4321", "LOJA TESTE"),
        ("LOJA TESTE +55 11 987654321", "LOJA TESTE"),
        # endereço e CEP
        ("LOJA TESTE RUA DAS FLORES, 123", "LOJA TESTE"),
        ("LOJA TESTE 01234-567", "LOJA TESTE"),
        # código de boleto (linha digitável)
        ("COBRANCA 23790.12345 60000.123456 78000.123456 1 98760000010000", "COBRANCA"),
        # número de documento / código longo
        ("LOJA TESTE DOC 1234567", "LOJA TESTE DOC"),
        # nome do titular e do portador (completo e parcial)
        ("TRANSF FULANO DE TAL EXEMPLO", "TRANSF"),
        ("TRANSF FULANO TAL", "TRANSF"),
        ("TRANSF BELTRANA SOUZA", "TRANSF"),
    ],
)
def test_remove_cada_tipo_de_dado_pessoal(texto, esperado):
    assert limpo(texto) == esperado
    assert padroes.encontra(limpo(texto), TITULARES) == []


def test_nome_do_titular_sem_acento_e_com_acento():
    rx = padroes.regex_de_nomes(["José Antônio Teste"])
    assert anonimiza_texto("PIX JOSE ANTONIO TESTE", rx) == "PIX"
    assert anonimiza_texto("PIX JOSÉ ANTÔNIO TESTE", rx) == "PIX"


def test_sobrenome_sozinho_nao_e_removido():
    # um token solto aparece em nomes de empresa; só pares/nomes completos contam
    assert limpo("SOUZA MATERIAIS LTDA") == "SOUZA MATERIAIS LTDA"


# --- contraparte ---

def test_pix_com_cpf_vira_pessoa_fisica():
    assert resolve_contraparte("CICLANO EXEMPLO", "•••.456.789-••", Meio.PIX, TITULARES) == PESSOA_FISICA


def test_ted_sem_documento_vira_pessoa_fisica():
    assert resolve_contraparte("CICLANO EXEMPLO", "", Meio.TED_DOC, TITULARES) == PESSOA_FISICA


def test_titular_como_contraparte_de_pix_vira_pessoa_fisica():
    assert resolve_contraparte("FULANO DE TAL EXEMPLO", "", Meio.PIX, TITULARES) == PESSOA_FISICA


def test_empresa_com_cnpj_mantem_nome_limpo():
    r = resolve_contraparte("Mercado Ficticio Ltda", "12.345.678/0001-90", Meio.PIX, TITULARES)
    assert r == "MERCADO FICTICIO LTDA"


def test_boleto_sem_documento_nem_marcador_vira_pessoa_fisica():
    assert resolve_contraparte("CICLANO EXEMPLO", "", Meio.BOLETO, TITULARES) == PESSOA_FISICA
    assert resolve_contraparte("COMPANHIA FICTICIA S.A.", "", Meio.BOLETO, TITULARES) == "COMPANHIA FICTICIA S.A"


def test_estabelecimento_de_cartao_mantem_nome():
    assert resolve_contraparte("PADARIA MODELO", "", Meio.CARTAO_DEBITO, TITULARES) == "PADARIA MODELO"


def test_codigo_numerico_em_loja_de_cartao_nao_e_mei():
    # no cartão o número é código da loja; a limpeza apaga o código
    assert resolve_contraparte("LOJAFICTICIA.COM 12345678 OSASCO", "", Meio.CARTAO_CREDITO, TITULARES) == (
        "LOJAFICTICIA.COM OSASCO")
    # mas o padrão de MEI no cartão (raiz do CNPJ + nome) continua indo para revisão
    assert isinstance(resolve_contraparte("12345678 JOAO EXEMPLO", "", Meio.CARTAO_CREDITO, TITULARES), Revisar)


@pytest.mark.parametrize("nome,esperado", [
    ("JIM.COM 12345678 CICLANOVENDEDOR", "JIM.COM"),  # InfinitePay sem '*'
    ("JIM.COM*CICLANO", "JIM.COM"),
    ("PAG*CICLANO EXEMPLO", "PAG"),
    ("MP CICLANO EXEMPLO", "MP"),
    ("PAGODE DO BAIRRO", "PAGODE DO BAIRRO"),  # começa com "PAG" mas não é o intermediário
])
def test_intermediario_de_maquininha_fica_so_com_o_proprio_nome(nome, esperado):
    assert resolve_contraparte(nome, "", Meio.CARTAO_CREDITO, TITULARES) == esperado


@pytest.mark.parametrize(
    "nome,doc",
    [
        ("JOAO EXEMPLO ME", ""),  # microempresa com nome de pessoa
        ("JOAO EXEMPLO MEI", "12.345.678/0001-90"),
        ("12.345.678 JOAO EXEMPLO", ""),  # padrão de MEI: raiz do CNPJ + nome
        ("12 345 678 JOAO EXEMPLO", ""),
        ("JOAO EXEMPLO 12345678909", "12.345.678/0001-90"),  # padrão de MEI: nome + CPF
        ("12345678909", "12.345.678/0001-90"),  # nome é só o CPF
        ("SERVICOS EXEMPLO LTDA", "123.456.789-09"),  # marcador de empresa com CPF
    ],
)
def test_casos_ambiguos_vao_para_revisao(nome, doc):
    r = resolve_contraparte(nome, doc, Meio.PIX, TITULARES)
    assert isinstance(r, Revisar) and r.motivo == "contraparte_ambigua"


def test_empresa_com_nome_do_titular_vai_para_revisao():
    r = resolve_contraparte("FULANO TAL LTDA", "12.345.678/0001-90", Meio.PIX, TITULARES)
    assert isinstance(r, Revisar)


def test_sem_contraparte_fica_vazio():
    assert resolve_contraparte("", "", Meio.TARIFA, TITULARES) == ""


def test_classificacao_por_documento_vence_meio():
    assert classifica("ALGUEM", "123.456.789-09", Meio.CARTAO_DEBITO) is Classe.PESSOA_FISICA
    assert classifica("ALGUMA COISA", "12.345.678/0001-90", Meio.PIX) is Classe.EMPRESA


def test_empresa_so_com_cnpj_fica_sem_nome():
    assert resolve_contraparte("", "12.345.678/0001-90", Meio.PIX, TITULARES) == ""


def test_pessoa_so_com_cpf_vira_pessoa_fisica():
    assert resolve_contraparte("", "***.456.789-**", Meio.PIX, TITULARES) == PESSOA_FISICA


def test_cnpj_com_espaco_no_lugar_da_barra():
    assert limpo("LOJA TESTE 12.345.678 0001-90") == "LOJA TESTE"


# --- PIX/TED para empresa sem CNPJ nem LTDA (razão social escrita por extenso) ---

@pytest.mark.parametrize("nome", [
    "BAR E RESTAURANTE VALENTINO",
    "CIENA COMERCIO DE VESTUARIO",
    "LEROY MERLIN COMPANHIA BRASILEIRA DE BRICOLAGEM",
    "UNIVERSIDADE ESTADUAL DE LONDRINA",
    "CHEERS",                  # uma palavra só, que não é primeiro nome
])
def test_pix_para_empresa_sem_cnpj_mantem_o_nome(nome):
    assert classifica(nome, "", Meio.PIX) is Classe.EMPRESA
    assert resolve_contraparte(nome, "", Meio.PIX, None) == nome


@pytest.mark.parametrize("nome", [
    "MARIA SILVA SANTOS",
    "JOAO BARBOSA",            # "BAR" dentro do sobrenome não é palavra de empresa
    "FREDERICO ALVES",         # "REDE" dentro do nome
    "JOAO SILVA LANCHES",      # MEI com o nome do dono: começa com primeiro nome -> continua protegido
    "ANA PAULA COMERCIO",
    "MARIA",                   # uma palavra só, mas é primeiro nome
    "JHONATAN",
])
def test_pix_para_pessoa_continua_pessoa_fisica(nome):
    assert resolve_contraparte(nome, "", Meio.PIX, None) == PESSOA_FISICA
