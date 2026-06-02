"""Safe network diagnostics API routes (#950)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from igris.core.network_diag_gateway import NetworkDiagGateway

router = APIRouter(prefix="/api/network", tags=["network"])
gateway = NetworkDiagGateway()


def _csv_to_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


class ProvisioningProposalRequest(BaseModel):
    target: str
    hook: str
    approval: bool = False
    dry_run: bool = True
    allowed_hosts: Optional[str] = None
    allowed_domains: Optional[str] = None


@router.get("/dns")
async def dns_lookup(
    host: str,
    allowed_hosts: Optional[str] = Query(default=None),
    allowed_domains: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    return gateway.dns_lookup(host, allowed_hosts=_csv_to_list(allowed_hosts), allowed_domains=_csv_to_list(allowed_domains))


@router.get("/tcp")
async def tcp_connect(
    host: str,
    port: int,
    timeout: float = 5.0,
    allowed_hosts: Optional[str] = Query(default=None),
    allowed_domains: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    return gateway.tcp_connect(host, port, timeout=timeout, allowed_hosts=_csv_to_list(allowed_hosts), allowed_domains=_csv_to_list(allowed_domains))


@router.get("/http-latency")
async def http_latency(
    url: str,
    timeout: float = 5.0,
    allowed_hosts: Optional[str] = Query(default=None),
    allowed_domains: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    return gateway.http_latency(url, timeout=timeout, allowed_hosts=_csv_to_list(allowed_hosts), allowed_domains=_csv_to_list(allowed_domains))


@router.get("/port-check")
async def port_check(
    host: str,
    port: int,
    timeout: float = 5.0,
    allowed_hosts: Optional[str] = Query(default=None),
    allowed_domains: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    return gateway.port_check(host, port, timeout=timeout, allowed_hosts=_csv_to_list(allowed_hosts), allowed_domains=_csv_to_list(allowed_domains))


@router.get("/traceroute")
async def traceroute(
    host: str,
    max_hops: int = 12,
    timeout: float = 10.0,
    allowed_hosts: Optional[str] = Query(default=None),
    allowed_domains: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    return gateway.traceroute(host, max_hops=max_hops, timeout=timeout, allowed_hosts=_csv_to_list(allowed_hosts), allowed_domains=_csv_to_list(allowed_domains))


@router.get("/diagnose")
async def diagnose(
    host: str,
    port: Optional[int] = None,
    url: Optional[str] = None,
    allowed_hosts: Optional[str] = Query(default=None),
    allowed_domains: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    return gateway.diagnose(host, port=port, url=url, allowed_hosts=_csv_to_list(allowed_hosts), allowed_domains=_csv_to_list(allowed_domains))


@router.get("/inventory")
async def inventory(
    host: str,
    port: Optional[int] = None,
    url: Optional[str] = None,
    allowed_hosts: Optional[str] = Query(default=None),
    allowed_domains: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    return gateway.inventory(host, port=port, url=url, allowed_hosts=_csv_to_list(allowed_hosts), allowed_domains=_csv_to_list(allowed_domains))


@router.post("/proposals/provisioning")
async def propose_provisioning(
    req: ProvisioningProposalRequest,
) -> Dict[str, Any]:
    return gateway.propose_provisioning_hook(
        req.target,
        req.hook,
        approval=req.approval,
        dry_run=req.dry_run,
        allowed_hosts=_csv_to_list(req.allowed_hosts),
        allowed_domains=_csv_to_list(req.allowed_domains),
    )


@router.get("/audit-log")
async def audit_log() -> Dict[str, Any]:
    return {"audit_log": gateway.get_audit_log()}
