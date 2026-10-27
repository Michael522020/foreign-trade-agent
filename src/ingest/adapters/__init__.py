"""来源适配器注册表。"""

from src.ingest.adapters.customs import CustomsAdapter
from src.ingest.adapters.directory import ExhibitionAdapter, ManualAdapter, PlatformAdapter, WebsiteAdapter

ADAPTERS = {
    CustomsAdapter.source_name: CustomsAdapter(),
    ExhibitionAdapter.source_name: ExhibitionAdapter(),
    PlatformAdapter.source_name: PlatformAdapter(),
    WebsiteAdapter.source_name: WebsiteAdapter(),
    ManualAdapter.source_name: ManualAdapter(),
}
