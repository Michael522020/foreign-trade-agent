"""导入本包即注册表和入库监听器。"""

from src.ingest.tables import (
    CustomsShipment,
    IngestDrop,
    IngestLedger,
    MergeCandidate,
    QuarantineItem,
)
from src.logging_config import configure_logging
from src.models.base import Base
from src.models.catalog import Certification, Product
from src.models.commercial import Inquiry, Quotation
from src.models.compliance import ComplianceAudit, Interaction, Suppression
from src.models.expiry import expire_due_quotations
from src.models.listeners import register_listeners
from src.models.parties import Company, Contact, Lead
from src.models.state_machine import (
    InquiryEvent,
    LeadEvent,
    QuotationEvent,
    transition,
)

configure_logging()
register_listeners()

__all__ = [
    "Base",
    "Certification",
    "Company",
    "ComplianceAudit",
    "Contact",
    "CustomsShipment",
    "IngestDrop",
    "IngestLedger",
    "MergeCandidate",
    "QuarantineItem",
    "Inquiry",
    "InquiryEvent",
    "Interaction",
    "Lead",
    "LeadEvent",
    "Product",
    "Quotation",
    "QuotationEvent",
    "Suppression",
    "expire_due_quotations",
    "transition",
]
