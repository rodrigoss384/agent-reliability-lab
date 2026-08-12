export interface ChatResponse {
  session_id: string;
  guardrail_state: "entregue" | "bloqueado" | "bloqueado-na-saida" | "falha-segura";
  pre_guardrail: string;
  post_guardrail: string;
  retrieved_count: number;
  blocked_count: number;
  used_count: number;
  total_ms: number;
  model: string;
  uma_resposta?: string;
  decision_trail: Array<{ step: number; action: string; detail: string }>;
  chunks: Array<{
    id: number;
    content: string;
    blocked: boolean;
    pii_detected: string[];
    source: string;
  }>;
}

export const emptyStateFixture = {
  id: "empty-state-fixture",
  stateId: "empty",
  retrieved_count: 0,
  chunks: [],
};

export const blockedInputFixture = {
  id: "blocked-input-fixture",
  stateId: "bloqueado",
  pre_guardrail: "active",
  guardrail_state: "blocked",
  retrieved_count: 3,
  blocked_count: 1,
  used_count: 2,
  decision_trail: [
    {
      step: 1,
      action: "query_received",
      detail: "Pergunta enviada ao pipeline RAG.",
    },
    {
      step: 2,
      action: "retrieval",
      detail: `Vector search (cosine < 0.5) retornou 3 chunks do índice "docs_financeiros".`,
    },
    {
      step: 3,
      action: "pre_guardrail_scan",
      detail:
        "Chunk #1: detectadas categorias [CPF, nome_completo, numero_conta]. Chunks #2 e #3: limpos.",
    },
    {
      step: 4,
      action: "blocked",
      detail:
        "Pré-guardrail bloqueou chunk #1 (PII detectada). Chunks #2 e #3 (limpos) foram utilizados pelo provider.",
    },
  ],
  chunks: [
    {
      id: 1,
      content:
        "João Silva, portador do CPF 123.456.789-00, possui conta corrente nº 98765-4 com saldo de R$ 15.432,10 em 10/08/2026.",
      blocked: true,
      pii_detected: ["CPF", "nome_completo", "numero_conta"],
      source: "sistema_bancario.csv",
    },
    {
      id: 2,
      content:
        "O setor de atendimento registrou 1.243 chamados no mês de julho, com tempo médio de resolução de 4h32min.",
      blocked: false,
      pii_detected: [],
      source: "relatorio_atendimento.pdf",
    },
    {
      id: 3,
      content:
        "Política de investimento: clientes com mais de 50 mil em aplicações recebem assessoria premium trimestral.",
      blocked: false,
      pii_detected: [],
      source: "politica_investimento.md",
    },
  ],
  response: "Envio ao provider interrompido — PII detectada na entrada.",
};

export const entregueFixture: ChatResponse = {
  session_id: "ses-entregue-abc",
  guardrail_state: "entregue",
  pre_guardrail: "passed",
  post_guardrail: "passed",
  retrieved_count: 3,
  blocked_count: 0,
  used_count: 3,
  total_ms: 742,
  model: "provider-default/v1",
  uma_resposta:
    "O setor de atendimento registrou 1.243 chamados em julho, com tempo médio de 4h32min. A política de investimento define assessoria premium para clientes acima de 50 mil.",
  decision_trail: [
    { step: 1, action: "query_received", detail: "Pergunta enviada ao pipeline RAG." },
    {
      step: 2,
      action: "retrieval",
      detail: `Vector search (cosine < 0.5) retornou 3 chunks do índice "docs_financeiros".`,
    },
    { step: 3, action: "pre_guardrail_scan", detail: "Nenhum chunk bloqueado. Todos os 3 chunks permitidos para o provider." },
    {
      step: 4,
      action: "generation",
      detail: `Provider "provider-default/v1" gerou resposta em 742ms usando 3 chunks.`,
    },
    { step: 5, action: "post_guardrail_scan", detail: "Pós-guardrail: resposta sem PII detectada. Judge: NÃO." },
    {
      step: 6,
      action: "delivered",
      detail: "Resposta entregue ao chat. Nenhum conteúdo bloqueado.",
    },
  ],
  chunks: [
    {
      id: 1,
      content: "O setor de atendimento registrou 1.243 chamados no mês de julho, com tempo médio de resolução de 4h32min.",
      blocked: false,
      pii_detected: [],
      source: "relatorio_atendimento.pdf",
    },
    {
      id: 2,
      content: "Política de investimento: clientes com mais de 50 mil em aplicações recebem assessoria premium trimestral.",
      blocked: false,
      pii_detected: [],
      source: "politica_investimento.md",
    },
    {
      id: 3,
      content: "Processo de onboarding: novos clientes devem agendar reunião com gerente dedicado em até 5 dias úteis.",
      blocked: false,
      pii_detected: [],
      source: "processo_onboarding.md",
    },
  ],
};

export const outputBlockedFixture: ChatResponse = {
  session_id: "ses-output-blocked-abc",
  guardrail_state: "bloqueado-na-saida",
  pre_guardrail: "passed",
  post_guardrail: "active",
  retrieved_count: 3,
  blocked_count: 1,
  used_count: 2,
  total_ms: 891,
  model: "provider-default/v1",
  decision_trail: [
    { step: 1, action: "query_received", detail: "Pergunta enviada ao pipeline RAG." },
    {
      step: 2,
      action: "retrieval",
      detail: `Vector search (cosine < 0.5) retornou 3 chunks do índice "docs_financeiros".`,
    },
    { step: 3, action: "pre_guardrail_scan", detail: "Chunk #1: detectado valor monetário (R$). Chunks #2 e #3: limpos. 2 chunks permitidos para o provider." },
    {
      step: 4,
      action: "generation",
      detail: `Provider "provider-default/v1" gerou resposta em 891ms usando 2 chunks.`,
    },
    {
      step: 5,
      action: "post_guardrail_scan",
      detail: "Pós-guardrail: resposta contém padrão de PII detectado por regex. Judge: SIM.",
    },
    {
      step: 6,
      action: "blocked_output",
      detail: "Resposta candidata substituída por mensagem segura. Nenhum conteúdo sensível exposto ao cliente.",
    },
  ],
  chunks: [
    {
      id: 1,
      content: "Relatório financeiro: a receita do Q2 atingiu R$ 2.340.000, superando a meta de R$ 2.100.000.",
      blocked: true,
      pii_detected: ["valor_monetario"],
      source: "relatorio_financeiro.pdf",
    },
    {
      id: 2,
      content: "O tempo médio de resposta do suporte técnico caiu de 8h para 3h15min após reestruturação da equipe.",
      blocked: false,
      pii_detected: [],
      source: "metricas_suporte.xlsx",
    },
    {
      id: 3,
      content: "Pesquisa de satisfação: 87% dos clientes avaliaram o atendimento como ótimo ou bom no último trimestre.",
      blocked: false,
      pii_detected: [],
      source: "pesquisa_nps.csv",
    },
  ],
};

export const safeFailureFixture: ChatResponse = {
  session_id: "ses-fail-abc",
  guardrail_state: "falha-segura",
  pre_guardrail: "error",
  post_guardrail: "not-reached",
  retrieved_count: 2,
  blocked_count: 0,
  used_count: 0,
  total_ms: 0,
  model: "",
  decision_trail: [
    { step: 1, action: "query_received", detail: "Pergunta enviada ao pipeline RAG." },
    {
      step: 2,
      action: "retrieval",
      detail: `Vector search retornou 2 chunks do índice "docs_financeiros".`,
    },
    {
      step: 3,
      action: "guardrail_error",
      detail: "Timeout excedido no pré-guardrail (5000ms). Nenhum chunk enviado ao provider.",
    },
  ],
  chunks: [
    {
      id: 1,
      content: "Dados operacionais do mês de agosto: 3.421 tickets abertos e 2.987 resolvidos.",
      blocked: false,
      pii_detected: [],
      source: "dashboard_operacional.csv",
    },
    {
      id: 2,
      content: "Meta de SLA para o próximo trimestre: 95% dos chamados resolvidos em até 4 horas.",
      blocked: false,
      pii_detected: [],
      source: "metas_sla.md",
    },
  ],
};

export const sessionHistoryFixture = {
  session_id: "ses-entregue-abc",
  turns: [
    {
      turn_id: 1,
      question: "Qual foi o volume de chamados em julho?",
      resposta: "O setor de atendimento registrou 1.243 chamados em julho, com tempo médio de 4h32min.",
      guardrail_state: "entregue",
      timestamp: "2026-08-11T18:00:00Z",
      model: "provider-default/v1",
      total_ms: 512,
    },
    {
      turn_id: 2,
      question: "Há política de investimento para clientes premium?",
      resposta: "Sim. A política de investimento define assessoria premium trimestral para clientes com mais de 50 mil em aplicações.",
      guardrail_state: "entregue",
      timestamp: "2026-08-11T18:05:00Z",
      model: "provider-default/v1",
      total_ms: 634,
    },
  ],
  ttl_seconds: 86400,
  created_at: "2026-08-11T18:00:00Z",
  last_activity: "2026-08-11T18:05:00Z",
};

export const emptyHistoryFixture = {
  session_id: "ses-empty-history",
  turns: [],
  ttl_seconds: 86400,
  created_at: "2026-08-11T19:00:00Z",
  last_activity: "2026-08-11T19:00:00Z",
};

export const expiredSessionFixture = {
  error: "session_not_found",
  detail: "Sessão expirada ou inexistente.",
};
