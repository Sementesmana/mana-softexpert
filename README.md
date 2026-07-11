# mana-softexpert

> **SDK Camada 2A (Maná Builder) — ESCRITA no SoftExpert Workflow** via `wf_ws.php`:
> instanciar processo, preencher formulário (texto **e campo tipo arquivo**), anexar
> em atividade e cancelar instância — com **sessão SOAP persistente**.
> Par de escrita da leitura [`mana-habilidade-se-dataset-reader`](https://github.com/Sementesmana/mana-habilidade-se-dataset-reader).
> Documentação canônica dos métodos: skill `softexpert-wf-ws` (cockpit Maná Builder).

## Por que existe

Todo agente Maná que escreve no SE copiava o mesmo bloco SOAP (agente-nf, agente-cpr,
agente-comite-credito, agente-km...). Este SDK consolida o padrão, extraído da feature
Endossos do `agente-comercio-revendas` — **validada em produção em 2026-07-10**
(processo CRE-001 real criado com formulário + campo arquivo + anexos na ATV-01).

## Instalação

Distribuição por **git tag** (padrão Maná Builder):

```
pip install "git+https://github.com/Sementesmana/mana-softexpert.git@v0.1.0"
```

Dependência única: `requests>=2.31`.

## Uso típico

```python
import os
from mana_softexpert import SoftExpertWF, SoftExpertError

se = SoftExpertWF(
    base_url=os.environ["SE_URL"],          # ex: https://empresa.softexpert.app
    api_key=os.environ["SE_API_KEY"],       # header Authorization
    user_id=os.environ.get("SE_USER_ID"),   # matrícula do executor (opcional)
)

# 1. Instanciar processo → retorna o idprocess (WorkflowID)
idp = se.new_workflow("SM.CV.PR.NE.CRE-001", "ENDOSSO - CLIENTE X - REVENDA Y")

# 2. Preencher o formulário (todos os campos texto/opção numa chamada)
se.edit_form(idp, "scred", {
    "nomeclientenovo": "JOÃO DA SILVA",
    "tipocliente": "Pessoa Física",
    "uf": "GO",
})

# 3. Campo TIPO ARQUIVO do formulário (EntityAttributeFileList)
se.edit_form_arquivo(idp, "scred", "termoanuencia", "termo.pdf", pdf_bytes)

# 4. Anexos da ATIVIDADE (1 arquivo por chamada; sessão persistente barateia N chamadas)
for nome, conteudo in documentos:
    se.anexar(idp, "ATV-01", nome, conteudo, summary="Documentação do endosso")

# 5. Cancelar (o WS não exclui — cancela, auditável)
se.cancel_workflow(idp, "Cancelado pelo painel")
```

Erro `FAILURE` do SE levanta `SoftExpertError` com `.code` e `.detail`.

## Regras de ouro embutidas

| Regra | Por quê |
|---|---|
| **Sessão HTTP persistente** (`requests.Session` no cliente) | Sem ela cada consumo re-negocia TLS; 5 anexos viram 30s+ |
| **1 arquivo por chamada de anexo** | Contrato do `newAttachment`; N chamadas na mesma sessão |
| Campo arquivo = `EntityAttributeFileList` com `FileName`+`FileContent`(base64 do binário) | Estrutura do editEntityRecord pra campos tipo arquivo |
| `FAILURE` → exceção com code/detail | Nunca engolir erro do SE |
| Zero credencial no código | `base_url`/`api_key` vêm de env vars do consumidor |

## Gotchas de produção (aprendidos na marra)

- **`-5` "processo não encontrado" no newWorkflow:** ou o ProcessID está errado, ou o
  usuário do token **não tem permissão de INSTANCIAR** o processo (a lista é escopada
  por permissão). Confira também **vírgula/espaço colado no valor da env** (aconteceu).
- **A atividade do `anexar` precisa estar HABILITADA** (ex: primeira atividade recém-criada).
- Anexo é **da atividade**, não da instância.
- Salve o `idprocess` retornado **imediatamente** — é o amarre app↔SE e o que torna o
  retry idempotente (não re-instancia).

## API pública

| Símbolo | Descrição |
|---|---|
| `SoftExpertWF(base_url, api_key, user_id="", timeout=60, verify_ssl=False)` | Construtor (fail-fast sem base_url/api_key) |
| `.new_workflow(process_id, titulo, user_id=None)` → `str` | Instancia; retorna idprocess |
| `.edit_form(workflow_id, entity_id, campos: dict)` | Preenche campos texto/opção (filtra vazios) |
| `.edit_form_arquivo(workflow_id, entity_id, campo, filename, bytes)` | Campo tipo arquivo do form |
| `.anexar(workflow_id, activity_id, filename, bytes, attachment_name=None, summary="", user_id=None)` | Anexo na atividade |
| `.cancel_workflow(workflow_id, motivo="", user_id=None)` | Cancela a instância |
| `SoftExpertError` | `.metodo`, `.code`, `.detail` |

## LGPD

O SDK **transporta** dados de formulário e documentos direto app→SE. Nada passa por
LLM. Credenciais sempre via env var do consumidor (nunca hardcode).

## Estado

**v0.1.0** (2026-07-10) — primeira release, extraída de consumidor real em produção.

- ✅ Testes pytest (sessão fake, zero rede)
- ✅ Sessão persistente + thread-safe
- ⏳ **`alpha`** — pendente migração do `agente-comercio-revendas` (1º consumidor) pro gate beta

**Roadmap:** migrar comercio-revendas → `beta` · 2º consumidor (agente-nf ou agente-cpr)
→ `producao` · módulos futuros: `fm_ws` (leitura form), `dc_ws` (documentos), `tmc_ws` (Plano de Ação).

## Dono

Xayer (@xayer-mana, Sementes Maná LTDA). Mudanças via PR (semver: PATCH=fix,
MINOR=compatível, MAJOR=breaking + ADR).
