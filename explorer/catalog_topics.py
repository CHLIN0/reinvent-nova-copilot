"""Evidence-based topic suggestions; never changes attendee preferences.

Rules read only official titles, abstracts and tags. Topic membership is not a
priority recommendation or a reservation instruction. Repeated sessions retain
their distinct session IDs.
"""
import re
import json
from functools import lru_cache

CLASSIFICATION_VERSION = '2026-10-09.1'
TAXONOMY = [
    {'id': 'genai', 'label': '生成式 AI', 'description': '大型語言模型、基礎模型、多模態與生成式 AI；作為主要探索入口。', 'order': 10, 'group': 'ai'},
    {'id': 'training', 'label': '模型訓練／微調', 'description': '模型訓練、微調、強化學習與模型客製化。Coding Agent 的執行環境不等於模型訓練。', 'order': 20, 'group': 'ai'},
    {'id': 'inference', 'label': '推論／模型服務', 'description': '推論端點、模型服務、token 成本與延遲／吞吐最佳化。', 'order': 30, 'group': 'ai'},
    {'id': 'applications', 'label': 'AI 應用開發', 'description': '將 AI 接入應用、工作流程、助理及產品的實作。', 'order': 40, 'group': 'ai'},
    {'id': 'agents', 'label': 'Agent／Coding Agent', 'description': 'Agentic AI、AgentCore、Coding Agent、工具協作與 MCP。', 'order': 50, 'group': 'ai'},
    {'id': 'rag', 'label': 'RAG／AI 資料與記憶', 'description': '檢索增強生成、向量搜尋、知識庫與 Agent 記憶。', 'order': 60, 'group': 'ai'},
    {'id': 'ai_evaluation', 'label': 'AI 評估／可觀測性', 'description': '模型與 Agent 評估、品質、基準測試、追蹤及監控。', 'order': 70, 'group': 'ai'},
    {'id': 'ai_security', 'label': 'AI 安全／治理', 'description': 'AI 權限、安全、護欄、隱私與負責任 AI。', 'order': 80, 'group': 'ai'},
    {'id': 'ai_infra', 'label': 'AI 雲端基礎設施', 'description': 'GPU、Trainium、Inferentia、HyperPod 與 AI 運算／部署架構。', 'order': 90, 'group': 'ai'},
    {'id': 'ai_ml', 'label': '其他 AI／機器學習', 'description': '較廣的 AI／ML 主題；尚未出現明確生成式 AI 證據時放在這裡。', 'order': 100, 'group': 'ai'},
    {'id': 'data_platform', 'label': 'Data／資料平台', 'description': '資料庫、分析、資料湖、串流與資料工程；包含非 AI 的補充議程。', 'order': 110, 'group': 'support'},
    {'id': 'cloud_foundation', 'label': '雲端架構／平台', 'description': '架構、容器、無伺服器、運算與雲端營運；包含非 AI 的補充議程。', 'order': 120, 'group': 'support'},
]
for _definition in TAXONOMY:
    _definition['domain'] = ('data' if _definition['id'] == 'data_platform'
                             else 'cloud' if _definition['id'] == 'cloud_foundation' else 'ai')

GENAI = r'\b(?:generative\s+(?:ai|models?|agents?|applications?)|gen[ -]?ai|llms?|large\s+language\s+models?|foundation\s+models?|bedrock|agentcore|agentic|coding\s+agents?|claude|codex|kiro|nemotron|multimodal|diffusion\s+models?|graph[ -]?rag|rag|rlvr|ai[ -]generated|llama|qwen|deepseek|mistral|amazon\s+nova|gpt[ -]?\d[.\d]*)\b'
AI = r'\b(?:ai|artificial\s+intelligence|machine\s+learning|ml|sagemaker|deep\s+learning|neural\s+networks?|trainium|inferentia|pytorch|world\s+models?)\b'
TRAINING = r'\b(?:fine[ -]?tun\w*|pre[ -]?train\w*|reinforcement\s+learning|rlvr|supervised\s+fine[ -]?tuning|lora|qlora|distributed\s+training|model\s+(?:training|customization)|train(?:ing)?\s+(?:a\s+|your\s+|the\s+)?(?:foundation\s+|language\s+|world\s+)?models?|training\s+(?:jobs?|workloads?|cluster|data)|sft)\b'
INFERENCE = r'\b(?:inference|model\s+serving|serv(?:ing|e)\s+(?:ai\s+|llm\s+)?models?|prefill|decode|quantization|token\s+economics|tokenomics|tokens?\s+per\s+second|time\s+to\s+first\s+token|ttft|tpot|kv[ -]cache|vllm|sglang|tensorrt[ -]llm)\b'
AGENTS = r'\b(?:agentic|agentcore|ai\s+agents?|coding\s+agents?|autonomous\s+agents?|multi[ -]?agents?|agent\s+(?:harness|memory|runtime|orchestration)|mcp|model\s+context\s+protocol|claude\s+code|codex|kiro)\b'
RAG = r'\b(?:rag|graph[ -]?rag|retrieval[ -]augmented|vector\s+(?:search|database|indexes?|store)|s3\s+vectors|knowledge\s+bases?|agent\s+memory|embeddings?|semantic\s+search)\b'
APP = r'\b(?:ai[ -]powered|ai\s+(?:applications?|apps?|assistants?|workflows?|products?)|(?:build|building|develop|developing|deploy|deploying)\s+(?:an?\s+|your\s+)?(?:ai\s+|agentic\s+)?(?:agents?|assistants?|chatbots?)|chatbots?|copilots?|prompt\s+engineering|tool\s+(?:use|calling)|function\s+calling|text[ -]to[ -](?:sql|image|video)|natural\s+language)\b'
EVAL = r'\b(?:evaluat\w*|benchmark\w*|llm[ -]as[ -]a[ -]judge|observability|tracing|hallucinations?|model\s+(?:quality|monitoring)|agent\s+(?:quality|monitoring))\b'
SECURITY = r'\b(?:secur\w*|guardrails?|responsible\s+ai|governance|permissions?|authorization|privacy|prompt\s+injection|safety|cedar)\b'
INFRA = r'\b(?:gpus?|trainium|inferentia|hyperpod|aws\s+neuron|distributed\s+training|model\s+serving|inference\s+(?:platform|compute|cluster)|ai\s+(?:infrastructure|compute)|microvms?)\b'
DATA = r'\b(?:databases?|analytics|data\s+(?:engineering|pipelines?|lakes?|warehouse|platform|mesh|governance)|lakehouse|iceberg|etl|opensearch|redshift|dynamodb|aurora|neptune|kinesis|apache\s+(?:spark|kafka|flink)|s3\s+tables)\b'
CLOUD = r'\b(?:cloud\s+(?:architecture|operations|infrastructure|platform)|kubernetes|containers?|serverless|amazon\s+eks|amazon\s+ecs|aws\s+lambda|amazon\s+ec2|well[ -]architected|cloudwatch|infrastructure\s+as\s+code)\b'


def _fields(item):
    # The caller supplies the strict public catalog projection. Never inspect
    # nested upstream fields, custom labels, private notes, or attendee state.
    result = {}
    for key in ('title', 'abstract', 'tags'):
        value = item.get(key, '' if key != 'tags' else [])
        if key == 'tags':
            value = ' | '.join(str(tag) for tag in value) if isinstance(value, list) else ''
        result[key] = str(value or '')
    return result


def _matches(fields, pattern, exact_tags=()):
    evidence = []
    # Prefer descriptive content over a broad vendor label.
    for field in ('title', 'abstract'):
        hit = re.search(pattern, fields[field], re.I)
        if hit:
            left, right = max(0, hit.start() - 55), min(len(fields[field]), hit.end() + 95)
            evidence.append({'field': field, 'match': hit.group(), 'excerpt': fields[field][left:right]})
    tags = [tag.strip().casefold() for tag in fields['tags'].split('|')]
    for tag in exact_tags:
        if tag.casefold() in tags:
            evidence.append({'field': 'tags', 'match': tag, 'excerpt': tag})
    return evidence[:3]


def _classify_fields(fields):
    genai = _matches(fields, GENAI, ('Generative AI', 'Agentic AI', 'Amazon Bedrock'))
    ai = genai or _matches(fields, AI, ('Artificial Intelligence', 'Machine Learning', 'Amazon SageMaker'))
    # Vendor labels may be broad. They can suggest a topic, but never turn an
    # otherwise generic security/data talk into an AI specialisation.
    core_genai = _matches(fields, GENAI)
    core_ai = core_genai or _matches(fields, AI)
    results = []

    def add(topic_id, evidence, reason):
        if evidence:
            definition = next(d for d in TAXONOMY if d['id'] == topic_id)
            relevance = ('title' if any(e['field'] == 'title' for e in evidence)
                         else 'abstract' if any(e['field'] == 'abstract' for e in evidence) else 'official_tag')
            if relevance == 'official_tag':
                reason += '目前只有官方標籤證據，需閱讀摘要確認主題深度。'
            results.append({'id': topic_id, 'label': definition['label'], 'reason': reason,
                            'relevance': relevance, 'evidence': evidence})

    add('genai', genai, '官方題目、摘要或主題標籤出現生成式 AI、模型或 Agent 技術。')
    if core_ai:
        add('training', _matches(fields, TRAINING), '內容提到模型訓練、微調或強化學習，適合研究模型客製化。')
        add('inference', _matches(fields, INFERENCE), '內容提到模型推論或服務，可比較部署、效能與成本做法。')
        agents = _matches(fields, AGENTS, ('Agentic AI',))
        apps = _matches(fields, APP)
        add('applications', apps, '內容提到 AI 應用、助理或工作流程的建置／整合。')
        add('agents', agents, '內容提到 Agent、AgentCore、Coding Agent 或工具協作。')
        add('rag', _matches(fields, RAG), '內容提到檢索、向量搜尋、知識庫或 Agent 記憶。')
        add('ai_evaluation', _matches(fields, EVAL), 'AI 內容包含評估、基準、品質或可觀測性；請再閱讀具體評估對象。')
        add('ai_security', _matches(fields, SECURITY), 'AI 內容同時討論安全、權限、護欄或治理。')
        add('ai_infra', _matches(fields, INFRA), 'AI 內容包含運算硬體、叢集、模型服務或隔離執行環境。')
        if not core_genai:
            add('ai_ml', _matches(fields, AI, ('Artificial Intelligence', 'Machine Learning', 'Amazon SageMaker')), '官方內容屬 AI／ML，但目前規則未找到明確生成式 AI 證據。')
    else:
        # Retain tag-only suggestions for explicit review outside the core view.
        if genai:
            add('agents', _matches(fields, AGENTS, ('Agentic AI',)), '官方標籤提供 Agent 主題線索。')
        elif ai:
            add('ai_ml', ai, '官方標籤提供 AI／ML 主題線索。')
    add('data_platform', _matches(fields, DATA, ('Databases', 'Analytics', 'Data Engineering')), '資料平台補充議程；此分類本身不表示它是生成式 AI。')
    add('cloud_foundation', _matches(fields, CLOUD, ('Architecture', 'Cloud Operations', 'Compute', 'Containers', 'Serverless')), '雲端平台補充議程；此分類本身不表示它是生成式 AI。')
    return results


@lru_cache(maxsize=4096)
def _cached_classification(title, abstract, tags):
    """Immutable cache value, keyed solely by official public content."""
    fields = {'title': title, 'abstract': abstract, 'tags': tags}
    reasons = _classify_fields(fields)
    core_evidence = _matches(fields, GENAI) + _matches(fields, AI)
    broad_ai = any(d['domain'] == 'ai' and any(r['id'] == d['id'] for r in reasons) for d in TAXONOMY)
    data = {'reasons': reasons, 'ai_recommended': bool(core_evidence),
            'ai_tag_only': broad_ai and not core_evidence,
            'ai_relevance': ('title' if any(e['field'] == 'title' for e in core_evidence)
                            else 'abstract' if core_evidence else 'official_tag' if broad_ai else 'none')}
    # Serialised values cannot be mutated through a caller's enriched state.
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))


def _classification_data(item):
    fields = _fields(item)
    return json.loads(_cached_classification(fields['title'], fields['abstract'], fields['tags']))


def classify(item):
    """Return fresh ordered, explainable topic suggestions for one session."""
    return _classification_data(item)['reasons']



COMPANY_MATCH_VERSION = '2026-10-26.1'
COMPANIES = ('NVIDIA', 'OpenAI', 'Anthropic')
COMPANY_FIELDS = ('title', 'abstract', 'tags', 'speakers')


def company_matches(item):
    """Explain explicit public company-name mentions, with no presence claims.

    Product names such as Claude and Codex do not imply a company mention.
    Keep at most one excerpt per company and public field (12 records total).
    A speaker-string mention is text evidence, never an employer assertion.
    """
    results = []
    for company in COMPANIES:
        pattern = re.compile(r'(?<!\w)' + re.escape(company) + r'(?!\w)', re.I)
        for field in COMPANY_FIELDS:
            value = item.get(field)
            texts = value if isinstance(value, list) else [value]
            for text in texts:
                if not isinstance(text, str):
                    continue
                hit = pattern.search(text)
                if hit:
                    left, right = max(0, hit.start() - 55), min(len(text), hit.end() + 95)
                    results.append({'company': company, 'field': field,
                                    'match': hit.group(), 'excerpt': text[left:right],
                                    'rule_version': COMPANY_MATCH_VERSION})
                    break
    return results
