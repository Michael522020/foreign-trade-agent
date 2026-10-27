"""领域枚举。贸易术语 11 个都在枚举里，默认只启用 6 个。"""

from __future__ import annotations

from enum import Enum


class BuyerType(str, Enum):
    IMPORTER = "IMPORTER"
    DISTRIBUTOR = "DISTRIBUTOR"
    BRAND = "BRAND"
    TRADER = "TRADER"
    END_USER = "END_USER"
    UNKNOWN = "UNKNOWN"


class ContactRole(str, Enum):
    PURCHASING_MANAGER = "PURCHASING_MANAGER"
    SOURCING_SPECIALIST = "SOURCING_SPECIALIST"
    PRODUCT_MANAGER = "PRODUCT_MANAGER"
    OWNER_FOUNDER = "OWNER_FOUNDER"
    ENGINEER = "ENGINEER"
    UNKNOWN = "UNKNOWN"


class EmailStatus(str, Enum):
    VERIFIED = "verified"
    RISKY = "risky"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class Incoterm(str, Enum):
    EXW = "EXW"
    FCA = "FCA"
    FAS = "FAS"
    FOB = "FOB"
    CPT = "CPT"
    CFR = "CFR"
    CIF = "CIF"
    CIP = "CIP"
    DAP = "DAP"
    DPU = "DPU"
    DDP = "DDP"


ENABLED_INCOTERMS: frozenset[Incoterm] = frozenset(
    {
        Incoterm.EXW,
        Incoterm.FOB,
        Incoterm.CFR,
        Incoterm.CIF,
        Incoterm.DAP,
        Incoterm.DDP,
    }
)

PORT_REQUIRED: frozenset[Incoterm] = frozenset(
    {Incoterm.CFR, Incoterm.CIF, Incoterm.DAP, Incoterm.DDP}
)
PORT_FORBIDDEN: frozenset[Incoterm] = frozenset({Incoterm.EXW, Incoterm.FOB})


class PaymentTerms(str, Enum):
    TT_100_ADVANCE = "TT_100_ADVANCE"
    TT_30_70_BL_COPY = "TT_30_70_BL_COPY"
    LC_AT_SIGHT = "LC_AT_SIGHT"
    LC_USANCE = "LC_USANCE"
    DP = "DP"
    DA = "DA"
    OA = "OA"


HIGH_RISK_PAYMENT_TERMS: frozenset[PaymentTerms] = frozenset(
    {PaymentTerms.DP, PaymentTerms.DA, PaymentTerms.OA}
)


class LeadStage(str, Enum):
    RAW = "RAW"
    ENRICHED = "ENRICHED"
    SCORED = "SCORED"
    QUEUED = "QUEUED"
    CONTACTED = "CONTACTED"
    REPLIED = "REPLIED"
    BOUNCED = "BOUNCED"
    NOT_INTERESTED = "NOT_INTERESTED"
    NURTURE = "NURTURE"
    INQUIRY = "INQUIRY"
    QUOTING = "QUOTING"
    SAMPLE = "SAMPLE"
    NEGOTIATING = "NEGOTIATING"
    WON = "WON"
    LOST = "LOST"
    SUPPRESSED = "SUPPRESSED"


LEAD_TERMINALS: frozenset[LeadStage] = frozenset(
    {LeadStage.SUPPRESSED, LeadStage.WON, LeadStage.LOST}
)


class InquiryStatus(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    NEEDS_INFO = "NEEDS_INFO"
    ARCHIVED = "ARCHIVED"
    QUOTED = "QUOTED"
    SAMPLE_SENT = "SAMPLE_SENT"
    ORDER_CONFIRMED = "ORDER_CONFIRMED"
    CLOSED = "CLOSED"


INQUIRY_TERMINALS: frozenset[InquiryStatus] = frozenset(
    {InquiryStatus.CLOSED, InquiryStatus.ARCHIVED}
)


class InquiryType(str, Enum):
    REAL_RFQ = "REAL_RFQ"
    PRICE_PROBE = "PRICE_PROBE"
    COMPETITOR_PROBE = "COMPETITOR_PROBE"
    SPAM_BLAST = "SPAM_BLAST"
    SAMPLE_REQUEST = "SAMPLE_REQUEST"
    EXISTING_CUSTOMER = "EXISTING_CUSTOMER"


class Urgency(str, Enum):
    """业务已确认：询盘紧急度只用这三档。"""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class EmployeeBand(str, Enum):
    """员工人数，沿用采购侧常用的人数分段。"""

    UNKNOWN = "UNKNOWN"
    BAND_1_10 = "1-10"
    BAND_11_50 = "11-50"
    BAND_51_200 = "51-200"
    BAND_201_500 = "201-500"
    BAND_501_1000 = "501-1000"
    BAND_1001_5000 = "1001-5000"
    BAND_5001_10000 = "5001-10000"
    BAND_10001_PLUS = "10001+"


class AnnualRevenueBand(str, Enum):
    """年营收，人民币口径。

    UNDER_1M_CNY 是 100 万以下，1M_10M_CNY 是 100 万至 1000 万，
    10M_50M_CNY 是 1000 万至 5000 万，50M_200M_CNY 是 5000 万至 2 亿，
    200M_1B_CNY 是 2 亿至 10 亿，OVER_1B_CNY 是 10 亿以上。
    """

    UNKNOWN = "UNKNOWN"
    UNDER_1M_CNY = "UNDER_1M_CNY"
    FROM_1M_TO_10M_CNY = "1M_10M_CNY"
    FROM_10M_TO_50M_CNY = "10M_50M_CNY"
    FROM_50M_TO_200M_CNY = "50M_200M_CNY"
    FROM_200M_TO_1B_CNY = "200M_1B_CNY"
    OVER_1B_CNY = "OVER_1B_CNY"


class InteractionOutcome(str, Enum):
    """一次跟进的结果，沿用外贸 CRM 的常用结案。"""

    NO_REPLY = "NO_REPLY"
    REPLIED = "REPLIED"
    POSITIVE = "POSITIVE"
    OBJECTION = "OBJECTION"
    MEETING_SET = "MEETING_SET"
    NOT_INTERESTED = "NOT_INTERESTED"
    NURTURE = "NURTURE"
    BOUNCED = "BOUNCED"
    UNSUBSCRIBED = "UNSUBSCRIBED"
    WRONG_CONTACT = "WRONG_CONTACT"


class QuotationStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"


QUOTATION_TERMINALS: frozenset[QuotationStatus] = frozenset(
    {QuotationStatus.REJECTED, QuotationStatus.EXPIRED}
)


class CertificationType(str, Enum):
    CE = "CE"
    FDA = "FDA"
    ROHS = "RoHS"
    REACH = "REACH"
    UL = "UL"
    ISO9001 = "ISO9001"
    BSCI = "BSCI"
    FSC = "FSC"
    CARB = "CARB"
    CUL = "cUL"
    FCC = "FCC"
    SASO = "SASO"
    GCC = "GCC"
    PSE = "PSE"
    JIS = "JIS"
    RCM = "RCM"
    CFIA = "CFIA"


class CertificationStatus(str, Enum):
    VALID = "valid"
    EXPIRED = "expired"
    PENDING = "pending"


class Channel(str, Enum):
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    LINKEDIN = "LINKEDIN"
    EXHIBITION = "EXHIBITION"
    WEBSITE = "WEBSITE"
    CUSTOMS_DATA = "CUSTOMS_DATA"
    PLATFORM_INBOX = "PLATFORM_INBOX"
    OTHER = "OTHER"


class ContactChannel(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    PERSONAL_MEETING = "PERSONAL_MEETING"
    PLATFORM_INBOX = "PLATFORM_INBOX"
    RECORD_ONLY = "RECORD_ONLY"


class DataUsageScope(str, Enum):
    INTERNAL_USE_ONLY = "INTERNAL_USE_ONLY"


class Direction(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class SuppressionReason(str, Enum):
    UNSUBSCRIBED = "unsubscribed"
    COMPLAINED = "complained"
    HARD_BOUNCE = "hard_bounce"
    MANUAL = "manual"
    LEGAL_REQUEST = "legal_request"


class SuppressionScope(str, Enum):
    GLOBAL = "global"
    CAMPAIGN = "campaign"
    CHANNEL = "channel"


class ComplianceDecision(str, Enum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
