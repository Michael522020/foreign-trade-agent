"""按联系人语言写开发信。句子是该语言写的，数字只来自已批准事实。"""

from __future__ import annotations

from src.errors import ConfigError
from src.outreach.validate import ApprovedFact
from src.scoring.config import ScoringConfig

_SUPPORTED = frozenset({"en", "de", "pt"})


def approved_facts(config: ScoringConfig) -> list[ApprovedFact]:
    facts: list[ApprovedFact] = []
    for payload in config.facts.values():
        facts.append(
            ApprovedFact(
                value=str(payload["value"]),
                unit=str(payload["unit"]),
                src=str(payload.get("src") or "config/product.yaml"),
            )
        )
    return facts


def _fact(config: ScoringConfig, name: str) -> tuple[str, str]:
    payload = config.facts[name]
    return str(payload["value"]), str(payload["unit"])


def compose_subject(language: str, config: ScoringConfig) -> str:
    del config
    subjects = {
        "en": "Second source for furniture",
        "de": "Zweite Quelle fuer Moebel",
        "pt": "Segunda fonte de moveis",
    }
    return subjects[language]


def compose_body(language: str, config: ScoringConfig, contact_name: str) -> str:
    moq, moq_unit = _fact(config, "moq")
    lead, lead_unit = _fact(config, "lead_time")
    category = {
        "en": config.category_en,
        "de": config.category_de,
        "pt": config.category_pt,
    }[language]
    seller = config.seller_name
    name = contact_name.strip() or seller
    if language == "en":
        sentences = [
            f"Hello {name}, I am writing because your company imports {category} and the category still looks active.",
            "A second factory is worth a short look when one supplier already carries most of the volume.",
            f"We manufacture {category} for importers who already buy this category.",
            f"Our minimum order is {moq} {moq_unit}.",
            f"The usual production lead time is {lead} {lead_unit} after the deposit is received.",
            "I will not attach a catalog or a link in this first note.",
            "If you review new factories, reply with the points you care about, such as materials, packing, and inspection.",
            "If this note is not useful, reply no and I will stop.",
            seller,
        ]
    elif language == "de":
        sentences = [
            f"Guten Tag {name}, ich schreibe, weil Ihr Unternehmen {category} importiert und die Kategorie weiterhin aktiv wirkt.",
            "Eine zweite Fabrik lohnt einen kurzen Blick, wenn ein Lieferant bereits den groessten Teil des Volumens traegt.",
            f"Wir fertigen {category} fuer Importeure, die diese Kategorie bereits einkaufen.",
            f"Unsere Mindestbestellmenge betraegt {moq} {moq_unit}.",
            f"Die uebliche Produktionszeit betraegt {lead} {lead_unit} nach Eingang der Anzahlung.",
            "In dieser ersten Nachricht haenge ich keinen Katalog und keinen Link an.",
            "Wenn Sie neue Fabriken pruefen, antworten Sie bitte mit den Punkten, die Ihnen wichtig sind, etwa Material, Verpackung und Pruefung.",
            "Wenn diese Nachricht nicht nuetzlich ist, reply no und ich stoppe.",
            seller,
        ]
    else:
        sentences = [
            f"Ola {name}, escrevo porque a sua empresa importa {category} e a categoria continua ativa.",
            "Uma segunda fabrica merece um olhar curto quando um fornecedor ja leva a maior parte do volume.",
            f"Fabricamos {category} para importadores que ja compram esta categoria.",
            f"A quantidade minima e {moq} {moq_unit}.",
            f"O prazo habitual de producao e {lead} {lead_unit} depois do deposito.",
            "Nesta primeira mensagem nao envio catalogo nem link.",
            "Se voce avalia novas fabricas, responda com os pontos que importam, como material, embalagem e inspecao.",
            "Se esta mensagem nao for util, reply no e eu paro.",
            seller,
        ]
    return " ".join(sentences)


def resolve_language(language: str | None) -> str:
    if language is None or language == "":
        return "en"
    code = language.split("-", 1)[0].lower()
    if code not in _SUPPORTED:
        raise ConfigError(f"不支持的开发信语言：{language}")
    return code


def why_this_works_zh(language: str) -> str:
    return (
        f"用{language}写了一封首封纯文本，只引用了配置里已批准的起订量和交期，"
        "并要求收件人回复 no 即可停止。"
    )
