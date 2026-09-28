from django.contrib import admin
from .models import (
    AllocationRule,
    AllocationRuleDetail,
    Settlement,
    SettlementAllocation,
    SettlementAuditLog,
    SettlementEmail,
    SettlementSource,
    SettlementValidation,
    SettlementVendor,
    Vendor,
    VendorPrice,
    WasteLog,
)

admin.site.register([
    WasteLog,
    Vendor,
    VendorPrice,
    AllocationRule,
    AllocationRuleDetail,
    Settlement,
    SettlementSource,
    SettlementVendor,
    SettlementAllocation,
    SettlementValidation,
    SettlementAuditLog,
    SettlementEmail,
])
