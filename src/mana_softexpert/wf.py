"""Cliente de ESCRITA no SoftExpert Workflow (wf_ws.php) — SDK Maná Camada 2A.

Extraído do agente-comercio-revendas (feature Endossos, validada em produção
2026-07-10: processo CRE-001 real criado com formulário + campo arquivo + anexos).
Padrões consolidados de 4 agentes: agente-nf, agente-cpr, agente-comite-credito,
agente-km. Referência canônica dos métodos: skill `softexpert-wf-ws`.

Regras de ouro embutidas:
  - SESSÃO HTTP PERSISTENTE (requests.Session): sem ela, cada consumo re-negocia
    TLS e N chamadas (ex: 5 anexos) demoram demais. 1 arquivo por chamada de
    anexo; N chamadas na MESMA sessão.
  - Campo tipo ARQUIVO do formulário: mesma estrutura do editEntityRecord, mas
    o atributo vai na EntityAttributeFileList com FileName + FileContent(base64).
  - FAILURE do SE → SoftExpertError com code/detail (nunca engole erro).
  - Zero credencial no código: base_url/api_key vêm do consumidor (env vars).

Uso:
    from mana_softexpert import SoftExpertWF
    se = SoftExpertWF(base_url=os.environ["SE_URL"],
                      api_key=os.environ["SE_API_KEY"],
                      user_id=os.environ.get("SE_USER_ID", ""))
    idp = se.new_workflow("SM.CV.PR.NE.CRE-001", "ENDOSSO - CLIENTE X")
    se.edit_form(idp, "scred", {"nomeclientenovo": "JOÃO", "uf": "GO"})
    se.edit_form_arquivo(idp, "scred", "termoanuencia", "termo.pdf", pdf_bytes)
    se.anexar(idp, "ATV-01", "cpr.pdf", pdf_bytes, summary="CPR endossada")
    se.cancel_workflow(idp, "cancelado pelo painel")
"""
from __future__ import annotations

import base64
import logging
import threading
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import requests

log = logging.getLogger("mana-softexpert.wf")

WF_WS_PATH = "/apigateway/se/ws/wf_ws.php"


class SoftExpertError(RuntimeError):
    """FAILURE retornado pelo SE (ou resposta sem os campos esperados)."""

    def __init__(self, metodo: str, code: str | None, detail: str | None):
        self.metodo = metodo
        self.code = code
        self.detail = detail
        super().__init__(f"{metodo} FAILURE: code={code} detail={detail}")


class SoftExpertWF:
    """Cliente wf_ws com sessão persistente. Thread-safe na criação da sessão."""

    def __init__(self, base_url: str, api_key: str, user_id: str = "",
                 timeout: int = 60, verify_ssl: bool = False):
        if not base_url or not api_key:
            raise ValueError("base_url e api_key são obrigatórios")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.user_id = user_id
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self._session: requests.Session | None = None
        self._lock = threading.Lock()

    # ── infra ────────────────────────────────────────────────────────

    def _sess(self) -> requests.Session:
        if self._session is None:
            with self._lock:
                if self._session is None:
                    s = requests.Session()
                    s.headers.update({"Authorization": self.api_key})
                    adapter = requests.adapters.HTTPAdapter(pool_connections=2, pool_maxsize=4)
                    s.mount("https://", adapter)
                    s.mount("http://", adapter)
                    self._session = s
        return self._session

    def _post(self, action: str, body_xml: str, timeout: int | None = None) -> ET.Element:
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:urn="urn:workflow">'
            "<soapenv:Header/><soapenv:Body>" + body_xml + "</soapenv:Body></soapenv:Envelope>"
        )
        resp = self._sess().post(
            self.base_url + WF_WS_PATH,
            data=envelope.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=UTF-8", "SOAPAction": action},
            timeout=timeout or self.timeout,
            verify=self.verify_ssl,
        )
        resp.raise_for_status()
        return ET.fromstring(resp.content)  # .content: ET respeita o encoding declarado

    @staticmethod
    def _retorno(root: ET.Element) -> dict:
        out: dict = {}
        for el in root.iter():
            tag = el.tag.split("}")[-1]
            if tag in ("Status", "Code", "Detail", "RecordKey", "RecordID") and el.text:
                out[tag] = el.text.strip()
        return out

    def _exige_sucesso(self, metodo: str, root: ET.Element) -> dict:
        r = self._retorno(root)
        if r.get("Status") != "SUCCESS":
            raise SoftExpertError(metodo, r.get("Code"), r.get("Detail"))
        return r

    def _user_xml(self, user_id: str | None) -> str:
        uid = user_id if user_id is not None else self.user_id
        return f"<urn:UserID>{escape(uid)}</urn:UserID>" if uid else ""

    # ── métodos ──────────────────────────────────────────────────────

    def new_workflow(self, process_id: str, titulo: str, user_id: str | None = None) -> str:
        """Instancia um processo. Retorna o WorkflowID/idprocess (RecordID).

        Gotcha -5 "processo não encontrado": ou o ProcessID está errado, ou o
        usuário executor NÃO tem permissão de INSTANCIAR o processo no SE
        (a lista de processos do newWorkflow é escopada por permissão)."""
        body = (
            "<urn:newWorkflow>"
            f"<urn:ProcessID>{escape(process_id)}</urn:ProcessID>"
            f"<urn:WorkflowTitle>{escape(titulo[:120])}</urn:WorkflowTitle>"
            f"{self._user_xml(user_id)}"
            "</urn:newWorkflow>"
        )
        r = self._exige_sucesso("newWorkflow", self._post("newWorkflow", body))
        idprocess = r.get("RecordID") or r.get("RecordKey")
        if not idprocess:
            raise SoftExpertError("newWorkflow", r.get("Code"), "SUCCESS sem RecordID")
        log.info("[SE] workflow criado: %s (%s)", idprocess, process_id)
        return idprocess

    def edit_form(self, workflow_id: str, entity_id: str, campos: dict) -> None:
        """Preenche campos TEXTO/opção do formulário — todos numa chamada.
        Valores None/"" são filtrados. Formatos: data YYYY-MM-DD, decimal com
        ponto, booleano 0/1 (ver skill softexpert-wf-ws)."""
        attrs = "".join(
            "<urn:EntityAttribute>"
            f"<urn:EntityAttributeID>{escape(str(k))}</urn:EntityAttributeID>"
            f"<urn:EntityAttributeValue>{escape(str(v))}</urn:EntityAttributeValue>"
            "</urn:EntityAttribute>"
            for k, v in campos.items() if v not in (None, "")
        )
        body = (
            "<urn:editEntityRecord>"
            f"<urn:WorkflowID>{escape(workflow_id)}</urn:WorkflowID>"
            f"<urn:EntityID>{escape(entity_id)}</urn:EntityID>"
            f"<urn:EntityAttributeList>{attrs}</urn:EntityAttributeList>"
            "</urn:editEntityRecord>"
        )
        self._exige_sucesso("editEntityRecord", self._post("editEntityRecord", body))
        log.info("[SE] form %s preenchido em %s (%d campos)", entity_id, workflow_id, len(campos))

    def edit_form_arquivo(self, workflow_id: str, entity_id: str, campo: str,
                          filename: str, conteudo: bytes) -> None:
        """Preenche um campo TIPO ARQUIVO do formulário (EntityAttributeFileList).
        FileContent = base64 do binário (não base64 de string base64)."""
        b64 = base64.b64encode(conteudo).decode("ascii")
        body = (
            "<urn:editEntityRecord>"
            f"<urn:WorkflowID>{escape(workflow_id)}</urn:WorkflowID>"
            f"<urn:EntityID>{escape(entity_id)}</urn:EntityID>"
            "<urn:EntityAttributeFileList>"
            "<urn:EntityAttributeFile>"
            f"<urn:EntityAttributeID>{escape(campo)}</urn:EntityAttributeID>"
            f"<urn:FileName>{escape(filename)}</urn:FileName>"
            f"<urn:FileContent>{b64}</urn:FileContent>"
            "</urn:EntityAttributeFile>"
            "</urn:EntityAttributeFileList>"
            "</urn:editEntityRecord>"
        )
        self._exige_sucesso("editEntityRecord",
                            self._post("editEntityRecord", body, timeout=120))
        log.info("[SE] campo arquivo %s.%s preenchido em %s: %s (%d bytes)",
                 entity_id, campo, workflow_id, filename, len(conteudo))

    def anexar(self, workflow_id: str, activity_id: str, filename: str, conteudo: bytes,
               attachment_name: str | None = None, summary: str = "",
               user_id: str | None = None) -> None:
        """Anexa 1 arquivo a uma ATIVIDADE (newAttachment). A atividade precisa
        estar HABILITADA. 1 arquivo por chamada; para N arquivos, chame N vezes
        (a sessão persistente torna isso barato)."""
        b64 = base64.b64encode(conteudo).decode("ascii")
        body = (
            "<urn:newAttachment>"
            f"<urn:WorkflowID>{escape(workflow_id)}</urn:WorkflowID>"
            f"<urn:ActivityID>{escape(activity_id)}</urn:ActivityID>"
            f"<urn:FileName>{escape(filename)}</urn:FileName>"
            f"<urn:FileContent>{b64}</urn:FileContent>"
            f"{self._user_xml(user_id)}"
            f"<urn:AttachmentName>{escape((attachment_name or filename)[:100])}</urn:AttachmentName>"
            f"<urn:Summary>{escape(summary[:250])}</urn:Summary>"
            "</urn:newAttachment>"
        )
        self._exige_sucesso("newAttachment", self._post("newAttachment", body, timeout=120))
        log.info("[SE] anexado em %s/%s: %s (%d bytes)",
                 workflow_id, activity_id, filename, len(conteudo))

    def cancel_workflow(self, workflow_id: str, motivo: str = "",
                        user_id: str | None = None) -> None:
        """Cancela a instância (o WS não exclui — cancela; fica auditável no SE)."""
        body = (
            "<urn:cancelWorkflow>"
            f"<urn:WorkflowID>{escape(workflow_id)}</urn:WorkflowID>"
            f"<urn:Explanation>{escape((motivo or 'Cancelado via SDK mana-softexpert')[:250])}</urn:Explanation>"
            f"{self._user_xml(user_id)}"
            "</urn:cancelWorkflow>"
        )
        self._exige_sucesso("cancelWorkflow", self._post("cancelWorkflow", body))
        log.info("[SE] workflow CANCELADO: %s", workflow_id)
