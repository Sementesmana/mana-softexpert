"""Testes do SoftExpertWF — sessão fake, zero rede."""
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from mana_softexpert import SoftExpertError, SoftExpertWF  # noqa: E402


class FakeResp:
    status_code = 200

    def __init__(self, body: str):
        self.content = body.encode()

    def raise_for_status(self):
        pass


class FakeSession:
    headers: dict = {}

    def __init__(self):
        self.chamadas = []
        self.resposta = '<e><Status>SUCCESS</Status><Code>1</Code></e>'

    def post(self, url, data=None, headers=None, timeout=None, verify=None):
        self.chamadas.append({"url": url, "body": data.decode(),
                              "action": headers.get("SOAPAction"), "timeout": timeout})
        return FakeResp(self.resposta)


@pytest.fixture
def se():
    cli = SoftExpertWF(base_url="https://se.example.com/", api_key="chave", user_id="0042")
    cli._session = FakeSession()
    return cli


def test_construtor_valida():
    with pytest.raises(ValueError):
        SoftExpertWF(base_url="", api_key="x")
    with pytest.raises(ValueError):
        SoftExpertWF(base_url="https://x", api_key="")


def test_new_workflow_sucesso_e_escape(se):
    se._session.resposta = '<e><Status>SUCCESS</Status><RecordID>CRE-0010042</RecordID></e>'
    idp = se.new_workflow("SM.CV.PR.NE.CRE-001", "ENDOSSO - JOÃO & FILHOS <t> - GARCIA")
    assert idp == "CRE-0010042"
    c = se._session.chamadas[0]
    assert c["action"] == "newWorkflow"
    assert c["url"].endswith("/apigateway/se/ws/wf_ws.php")
    assert "SM.CV.PR.NE.CRE-001" in c["body"]
    assert "JOÃO &amp; FILHOS &lt;t&gt;" in c["body"]        # escape XML
    assert "<urn:UserID>0042</urn:UserID>" in c["body"]      # user default do cliente


def test_new_workflow_failure_levanta(se):
    se._session.resposta = ('<e><Status>FAILURE</Status><Code>-5</Code>'
                            '<Detail>Não foi encontrado um processo</Detail></e>')
    with pytest.raises(SoftExpertError) as exc:
        se.new_workflow("X", "T")
    assert exc.value.code == "-5"


def test_new_workflow_sucesso_sem_recordid_levanta(se):
    se._session.resposta = '<e><Status>SUCCESS</Status></e>'
    with pytest.raises(SoftExpertError):
        se.new_workflow("P", "T")


def test_edit_form_filtra_vazios(se):
    se.edit_form("CRE-0010042", "scred",
                 {"nomeclientenovo": "JOÃO", "email": "", "uf": None, "municipio": "Rio Verde"})
    b = se._session.chamadas[0]["body"]
    assert b.count("<urn:EntityAttribute>") == 2
    assert "<urn:EntityID>scred</urn:EntityID>" in b
    assert "email" not in b and "uf" not in b


def test_edit_form_arquivo_estrutura(se):
    se.edit_form_arquivo("CRE-0010042", "scred", "termoanuencia", "termo.pdf", b"%PDF-fake")
    b = se._session.chamadas[0]["body"]
    assert "<urn:EntityAttributeFileList>" in b
    assert "<urn:EntityAttributeID>termoanuencia</urn:EntityAttributeID>" in b
    assert "<urn:FileName>termo.pdf</urn:FileName>" in b
    assert "<urn:FileContent>JVBERi1mYWtl</urn:FileContent>" in b   # base64 de %PDF-fake
    assert se._session.chamadas[0]["timeout"] == 120


def test_anexar_estrutura(se):
    se.anexar("CRE-0010042", "ATV-01", "cpr.pdf", b"abc",
              summary="CPR endossada", user_id="9999")
    b = se._session.chamadas[0]["body"]
    assert se._session.chamadas[0]["action"] == "newAttachment"
    assert "<urn:ActivityID>ATV-01</urn:ActivityID>" in b
    assert "<urn:UserID>9999</urn:UserID>" in b               # override do user
    assert "<urn:AttachmentName>cpr.pdf</urn:AttachmentName>" in b


def test_cancel_workflow(se):
    se.cancel_workflow("CRE-0010042", "teste")
    b = se._session.chamadas[0]["body"]
    assert se._session.chamadas[0]["action"] == "cancelWorkflow"
    assert "<urn:Explanation>teste</urn:Explanation>" in b


def test_sessao_reusada(se):
    """N chamadas usam a MESMA sessão (regra da sessão persistente)."""
    se.edit_form("W", "scred", {"a": "1"})
    se.anexar("W", "ATV-01", "f.pdf", b"x")
    se.cancel_workflow("W")
    assert len(se._session.chamadas) == 3   # tudo na mesma FakeSession


def test_user_ausente_omite_tag():
    cli = SoftExpertWF(base_url="https://x", api_key="k")   # sem user_id
    cli._session = FakeSession()
    cli._session.resposta = '<e><Status>SUCCESS</Status><RecordID>W1</RecordID></e>'
    cli.new_workflow("P", "T")
    assert "<urn:UserID>" not in cli._session.chamadas[0]["body"]
